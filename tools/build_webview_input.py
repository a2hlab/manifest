#!/usr/bin/env python3
"""Rebuild the parity27 WebView device input byte for byte from public sources.

parity27-runtime-inputs.lock.json pins six device-captured WebView files, and probe_source_app.py
--webview-input accepts only those bytes. A launch with --bionic-shim-build stages that build's
libwebview_bionic_shim.so and libandroid.so instead of the captured ones, and reads the other four,
which this tool rebuilds:

  webview-t.apk                                     AOSP's prebuilt WebView 109.0.5414.123 with
                                                    Westlake's classes and hooks
  webview-t-lib/libwebviewchromium.so               that APK's engine, 11 imports renamed to the shim's
  webview-t-lib/libjnigraphics.so                   Westlake's AndroidBitmap shim
  webview-t-lib/libwebviewchromium_plat_support.so  AOSP's WebView platform support built for OH

Inputs: AOSP's APK (webview-t-recipe.json names the commit; the hash is checked), smali 2.5.2 and its
dependencies from Maven Central, the workspace's toolchains and pinned source trees, and Westlake's
framework/webview-shim/webview-t. Every output must match the lock; anything else fails.
Needs java and Info-ZIP zip 3.0 on PATH.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
LOCK_PREFIX = '/data/local/tmp/asx/'
OUTPUTS = ['webview-t.apk', 'webview-t-lib/libwebviewchromium.so',
           'webview-t-lib/libjnigraphics.so', 'webview-t-lib/libwebviewchromium_plat_support.so']


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            result.update(block)
    return result.hexdigest()


def run(command, **kwargs):
    subprocess.run([str(part) for part in command], check=True, **kwargs)


# --- unified diffs ------------------------------------------------------------------------------

def patch_sections(text):
    """{path without its a/ b/ prefix: [hunk, ...]}; a hunk is (old start, [(tag, line), ...])."""
    sections, current, lines, index = {}, None, text.split('\n'), 0
    while index < len(lines):
        line = lines[index]
        if line.startswith('--- ') and index + 1 < len(lines) and lines[index + 1].startswith('+++ '):
            path = lines[index + 1][4:].split('\t')[0]
            current = sections.setdefault(path[2:] if path.startswith('b/') else path, [])
            index += 2
            continue
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if match:
            old_count = int(match.group(2) if match.group(2) is not None else 1)
            new_count = int(match.group(4) if match.group(4) is not None else 1)
            body, index = [], index + 1
            while old_count or new_count:
                tag, content = lines[index][:1], lines[index][1:]
                if tag not in ' -+':
                    raise ValueError('Malformed patch line: ' + lines[index])
                body.append((tag, content))
                old_count -= tag in ' -'
                new_count -= tag in ' +'
                index += 1
            if index < len(lines) and lines[index].startswith('\\'):
                raise ValueError('Patches here end every file with a newline')
            current.append((int(match.group(1)), body))
            continue
        index += 1
    return sections


def apply_hunks(text, hunks):
    """Apply hunks exactly (no fuzz, no offsets beyond earlier hunks' size changes)."""
    if not text.endswith('\n'):
        raise ValueError('Patched files here end with a newline')
    lines = text.split('\n')[:-1]
    shift = 0
    for start, body in hunks:
        position = start - 1 + shift if start else 0
        old = [content for tag, content in body if tag in ' -']
        new = [content for tag, content in body if tag in ' +']
        if lines[position:position + len(old)] != old:
            raise ValueError('Patch context does not match at line %d' % start)
        lines[position:position + len(old)] = new
        shift += len(new) - len(old)
    return '\n'.join(lines) + '\n'


def apply_patch_tree(patch_text, tree):
    for path, hunks in patch_sections(patch_text).items():
        target = tree / path
        target.write_text(apply_hunks(target.read_text(), hunks))


# --- the engine ---------------------------------------------------------------------------------

def rename_imports(image, renames):
    """Rename whole .dynstr strings in place; each new name has the old name's length."""
    image = bytearray(image)
    if image[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected a little-endian ELF64 engine')
    shoff, = struct.unpack_from('<Q', image, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', image, 0x3a)

    def section(index):
        name, _, _, _, offset, size = struct.unpack_from('<IIQQQQ', image, shoff + index * shentsize)
        return name, offset, size

    _, names_offset, _ = section(shstrndx)
    dynstr = None
    for index in range(shnum):
        name, offset, size = section(index)
        if image[names_offset + name:names_offset + name + 8] == b'.dynstr\0':
            dynstr = (offset, offset + size)
    if dynstr is None:
        raise ValueError('Engine has no .dynstr')
    for old, new in sorted(renames.items()):
        if len(old) != len(new):
            raise ValueError('Rename changes length: ' + old)
        needle = b'\0' + old.encode() + b'\0'
        found = [match.start() + 1 for match in re.finditer(re.escape(needle), bytes(image[dynstr[0]:dynstr[1]]))]
        if len(found) != 1:
            raise ValueError('%s is %d strings in the engine .dynstr' % (old, len(found)))
        start = dynstr[0] + found[0]
        image[start:start + len(old)] = new.encode()
    return bytes(image)


# --- the dex ------------------------------------------------------------------------------------

LINE = re.compile(r'    \.line \d+$')
STATIC_VALUE = re.compile(r'^(\.field [^=]*?) = (.*)$')
DEFAULT_VALUES = {'false', 'null', '0x0', '0x0L', '0x0t', '0x0s', '0.0f', '0.0', "'\\u0000'"}


def normalize_smali(text):
    """The captured dex went through a tool that dropped .line entries after a method's last
    instruction and trailing default static values; these two rules redo that on baksmali's text."""
    out = []
    for line in text.split('\n'):
        if line == '.end method':
            while out and (LINE.match(out[-1]) or out[-1] == ''):
                out.pop()
        out.append(line)
    for index in reversed([i for i, line in enumerate(out) if line.startswith('.field ') and ' static ' in line]):
        match = STATIC_VALUE.match(out[index])
        if not match:
            continue
        if match.group(2) not in DEFAULT_VALUES:
            break
        out[index] = match.group(1)
    return '\n'.join(out)


def build_dex(aosp_dex, westlake, recipe, smali_tools, work):
    classpath = ':'.join(str(smali_tools / name) for name in sorted(recipe['smali_tools']))
    tree = work / 'smali'
    run(['java', '-Xmx4g', '-cp', classpath, 'org.jf.baksmali.Main', 'disassemble', aosp_dex, '-o', tree])
    for path in tree.rglob('*.smali'):
        path.write_text(normalize_smali(path.read_text()))
    apply_patch_tree((westlake / recipe['dex']['patch']).read_text(), tree)
    for directory in recipe['dex']['added_smali']:
        source = westlake / directory
        for path in sorted(source.rglob('*.smali')):
            target = tree / path.relative_to(source)
            if target.exists():
                raise ValueError('Added class already in the AOSP dex: ' + str(path.relative_to(source)))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    assembled = work / 'assembled.dex'
    # One job: smali's multi-threaded writer orders some interned tables by thread timing.
    run(['java', '-Xmx4g', '-cp', classpath, 'org.jf.smali.Main', 'assemble', '-j', '1', tree, '-o', assembled])
    order = json.loads((westlake / recipe['dex']['order']).read_text())
    dex = bytearray(assembled.read_bytes())
    if sha256(dex) != order['assembled_sha256']:
        raise ValueError('The assembled dex differs from the one the order file describes')
    for offset, hex_bytes in order['ranges']:
        data = bytes.fromhex(hex_bytes)
        dex[offset:offset + len(data)] = data
    if sha256(dex) != order['captured_sha256']:
        raise ValueError('The ordered dex differs from the captured one')
    return bytes(dex)


# --- the APK ------------------------------------------------------------------------------------

def central_records(raw):
    end = raw.rfind(b'PK\x05\x06')
    count, = struct.unpack_from('<H', raw, end + 10)
    offset, = struct.unpack_from('<I', raw, end + 16)
    records = []
    for _ in range(count):
        if raw[offset:offset + 4] != b'PK\x01\x02':
            raise ValueError('Bad central directory record')
        name_length, extra_length, comment_length = struct.unpack_from('<HHH', raw, offset + 28)
        size = 46 + name_length + extra_length + comment_length
        records.append(raw[offset:offset + size])
        offset += size
    return records


def infozip_deflate(data):
    """The captured dex entry came from Info-ZIP zip 3.0, whose deflate output differs from zlib's."""
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / 'classes.dex').write_bytes(data)
        run(['zip', '-q', '-X', '-6', 'entry.zip', 'classes.dex'], cwd=directory)
        raw = (Path(directory) / 'entry.zip').read_bytes()
    name_length, extra_length = struct.unpack_from('<HH', raw, 26)
    size, = struct.unpack_from('<I', raw, 18)
    return raw[30 + name_length + extra_length:30 + name_length + extra_length + size]


def build_apk(aosp_apk, dex, entry):
    """The captured APK is AOSP's with every deflated entry recompressed by zlib at level 6, the
    signing block dropped and classes.dex replaced as Info-ZIP's zip -u writes it."""
    raw = aosp_apk.read_bytes()
    when = datetime.datetime.fromisoformat(entry['dos_time'])
    dos_time = (when.hour << 11) | (when.minute << 5) | (when.second // 2)
    dos_date = ((when.year - 1980) << 9) | (when.month << 5) | when.day
    unix_owner = b'ux' + struct.pack('<HBBIBI', 11, 1, 4, entry['uid'], 4, entry['gid'])
    out, central = bytearray(), bytearray()
    records = central_records(raw)
    for record in records:
        record = bytearray(record)
        method, = struct.unpack_from('<H', record, 10)
        compressed_size, = struct.unpack_from('<I', record, 20)
        name_length, = struct.unpack_from('<H', record, 28)
        local_offset, = struct.unpack_from('<I', record, 42)
        name = bytes(record[46:46 + name_length])
        local_name_length, local_extra_length = struct.unpack_from('<HH', raw, local_offset + 26)
        header_size = 30 + local_name_length + local_extra_length
        local = bytearray(raw[local_offset:local_offset + header_size])
        data = raw[local_offset + header_size:local_offset + header_size + compressed_size]
        if name == b'classes.dex':
            data = infozip_deflate(dex)
            crc = zlib.crc32(dex)
            local_extra = (b'UT' + struct.pack('<HBII', 9, 3, entry['unix_time'], entry['unix_time'])
                           + unix_owner)
            local = bytearray(struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, 0, 8, dos_time, dos_date, crc,
                                          len(data), len(dex), len(name), len(local_extra))
                              + name + local_extra)
            central_extra = b'UT' + struct.pack('<HBI', 5, 3, entry['unix_time']) + unix_owner
            record = record[:46 + name_length] + central_extra
            struct.pack_into('<H', record, 4, 0x031e)
            struct.pack_into('<HHIII', record, 12, dos_time, dos_date, crc, len(data), len(dex))
            struct.pack_into('<H', record, 30, len(central_extra))
            struct.pack_into('<I', record, 38, 0o100644 << 16)
        elif method == 8:
            compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
            data = compressor.compress(zlib.decompress(data, -15)) + compressor.flush()
            struct.pack_into('<I', local, 18, len(data))
            struct.pack_into('<I', record, 20, len(data))
        elif method != 0:
            raise ValueError('Unexpected compression method in the AOSP APK')
        struct.pack_into('<I', record, 42, len(out))
        out += local + data
        central += record
    directory_offset = len(out)
    out += central + struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(records), len(records),
                                 len(central), directory_offset, 0)
    return bytes(out)


# --- the native libraries -----------------------------------------------------------------------

def stage(entries, workspace, westlake, westlake_patch_cache, root):
    """Lay out exactly the headers and sources the captured build read, from pinned trees."""
    for entry in entries:
        kind, relative = entry['from'].split(':', 1)
        source = (workspace if kind == 'workspace' else westlake) / relative
        text = source.read_bytes()
        if 'patch' in entry:
            kind, relative = entry['patch'].split(':', 1)
            if kind != 'westlake':
                raise ValueError('Patches come from Westlake: ' + entry['patch'])
            sections = westlake_patch_cache.setdefault(relative, patch_sections((westlake / relative).read_text()))
            matches = [path for path in sections if entry['stage'].endswith('/' + path)]
            if len(matches) != 1:
                raise ValueError('No single patch section for ' + entry['stage'])
            text = apply_hunks(text.decode(), sections[matches[0]]).encode()
        for old, new in entry.get('replace', []):
            if text.count(old.encode()) != 1:
                raise ValueError('Replacement does not match once in ' + entry['stage'])
            text = text.replace(old.encode(), new.encode())
        if sha256(text) != entry['sha256']:
            raise ValueError('Staged input differs from the captured build: ' + entry['stage'])
        target = root / entry['stage']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text)


def stub_library(clang, soname, symbols, work, tag):
    """A link-time stand-in exporting only what the captured link resolved against it."""
    if symbols and isinstance(symbols[0], str):
        # Linker-defined names: exporting them is all the captured link input did here.
        source = work / ('%s-%s.S' % (tag, soname))
        source.write_text(''.join('.globl %s\n.set %s, 0\n' % (name, name) for name in symbols))
    else:
        source = work / ('%s-%s.c' % (tag, soname))
        lines = []
        for name, kind, binding in symbols:
            weak = '__attribute__((weak)) ' if binding == 'weak' else ''
            if kind == 'object':
                lines.append('%schar s%d[1] __asm__("%s");' % (weak, len(lines), name))
            else:
                lines.append('%svoid f%d(void) __asm__("%s"); %svoid f%d(void) {}'
                             % (weak, len(lines), name, weak, len(lines)))
        source.write_text('\n'.join(lines) + '\n')
    library = work / ('%s-%s' % (tag, soname))
    run([clang, '--target=aarch64-linux-ohos', '-fuse-ld=lld', '-nostdlib', '-shared', '-w',
         '-Wl,-soname,' + soname, source, '-o', library])
    return library


def build_jnigraphics(toolchain, sysroot, staged, work):
    clangxx = toolchain / 'bin/clang++'
    obj = work / 'libjnigraphics_webview_shim.o'
    run([clangxx, '--target=aarch64-linux-ohos', '--sysroot=' + str(sysroot), '-fPIC', '-O2', '-std=c++17',
         '-fno-exceptions', '-fno-rtti', '-Wno-everything', '-D__OHOS__', '-DANDROID',
         '-I' + str(staged / 'ad-frameworks-native/include'), '-I' + str(staged / 'ad-libnativehelper/include_jni'),
         '-c', staged / 'webview-shim/libjnigraphics_webview_shim.cpp', '-o', obj])
    return obj


def build_plat_support(toolchain, sysroot, staged, work):
    clangxx = toolchain / 'bin/clang++'
    hwui = staged / 'aosp14/libs/hwui'
    skia = staged / 'skia-m133'
    a11, a15, nativehelper = staged / 'aosp11', staged / 'aosp15', staged / 'ad-libnativehelper'
    includes = [staged / 'plat-src', hwui, hwui.parent, hwui / 'jni', staged / 'hwui_stubinc',
                staged / 'skia_compat_headers', skia, skia / 'include', skia / 'include/core',
                skia / 'include/private', skia / 'src/core', skia / 'modules/skcms/src',
                a15 / 'system/core/libutils/include', a15 / 'system/core/libcutils/include',
                a15 / 'system/logging/liblog/include', a11 / 'frameworks/native/include',
                a11 / 'frameworks/native/libs/ui/include', a11 / 'frameworks/native/libs/nativebase/include',
                a11 / 'frameworks/native/libs/nativewindow/include', a11 / 'frameworks/native/libs/arect/include',
                a11 / 'frameworks/native/libs/math/include', nativehelper / 'include_jni', nativehelper / 'include',
                nativehelper / 'include_platform', nativehelper / 'include_platform_header_only',
                a11 / 'libnativehelper/include', a11 / 'libnativehelper/header_only_include',
                a15 / 'frameworks/base/libs/androidfw/include', a15 / 'frameworks/native/include',
                a15 / 'frameworks/native/libs/gui/include']
    flags = ['--target=aarch64-linux-ohos', '--sysroot=' + str(sysroot), '-fPIC', '-O2', '-std=c++17', '-fno-rtti',
             '-Wno-everything', '-D__OHOS__', '-D_GNU_SOURCE', '-DANDROID', '-D__ANDROID_API__=33',
             '-DENABLE_STRING8_OBSOLETE_METHODS', '-DSK_BUILD_FOR_ANDROID_FRAMEWORK=1', '-DSK_GANESH',
             '-DSKIA_OHOS', '-DSK_GL', '-DSKIA_DLL', '-DNDEBUG', '-D_LIBCPP_PROMOTE_H',
             '-include', staged / 'libcxx_compat_arm64.h',
             '-include', staged / 'skia_compat_headers/hwui_force_include.h',
             '-include', staged / 'hwui_stubinc/arm64_force_include.h']
    flags += ['-I' + str(path) for path in includes]
    sources = {name + '.o': staged / 'plat-src' / (name + '.cpp')
               for name in ['draw_functor', 'draw_gl_functor', 'functor_utils', 'jni_entry_point', 'graphics_utils']}
    sources['graphic_buffer_impl.o'] = staged / 'webview-shim/graphic_buffer_impl_oh.cpp'
    objects = []
    for name in sorted(sources):  # the captured link took obj/*.o in byte order
        run([clangxx, *flags, '-c', sources[name], '-o', work / name])
        objects.append(work / name)
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, required=True,
                        help='Workspace with toolchains/, android-source/, preserved/ and upstream/')
    parser.add_argument('--westlake-source', type=Path, required=True)
    parser.add_argument('--aosp-webview-apk', type=Path, required=True,
                        help="AOSP's prebuilt/arm64/webview.apk at the commit webview-t-recipe.json names")
    parser.add_argument('--smali-tools', type=Path, required=True,
                        help='Directory holding the smali 2.5.2 jars webview-t-recipe.json lists')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace, westlake = args.workspace.resolve(), args.westlake_source.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    recipe_path = ROOT / 'webview-t-recipe.json'
    lock_path = ROOT / 'parity27-runtime-inputs.lock.json'
    recipe = json.loads(recipe_path.read_text())
    lock = {entry['path'].removeprefix(LOCK_PREFIX): entry['sha256']
            for entry in json.loads(lock_path.read_text())['files'] if entry.get('category') == 'webview'}

    if file_sha256(args.aosp_webview_apk) != recipe['aosp_webview_apk']['sha256']:
        raise ValueError('Not the pinned AOSP WebView APK')
    for name, entry in recipe['smali_tools'].items():
        if file_sha256(args.smali_tools / name) != entry['sha256']:
            raise ValueError('Not the pinned ' + entry['maven'])
    toolchain = workspace / 'toolchains/clang-15'
    sysroot = workspace / 'toolchains/ohos-sdk/native/sysroot'
    version = subprocess.run([toolchain / 'bin/clang', '--version'], check=True, capture_output=True, text=True)
    if recipe['compiler_identity'] not in version.stdout:
        raise ValueError('Expected the pinned platform clang 15 in the workspace')
    if not subprocess.run(['zip', '-v'], check=True, capture_output=True, text=True).stdout.count('Zip 3.0'):
        raise ValueError('Expected Info-ZIP zip 3.0 on PATH')
    builtins = toolchain / 'lib/clang/15.0.4/lib/aarch64-linux-ohos/libclang_rt.builtins.a'
    libraries = sysroot / 'usr/lib/aarch64-linux-ohos'

    output.mkdir(parents=True)
    (output / 'webview-t-lib').mkdir()
    with tempfile.TemporaryDirectory(dir=output) as scratch:
        work = Path(scratch)
        with zipfile.ZipFile(args.aosp_webview_apk) as apk:
            engine = apk.read('lib/arm64-v8a/libwebviewchromium.so')
            (work / 'aosp.dex').write_bytes(apk.read('classes.dex'))
        (output / 'webview-t-lib/libwebviewchromium.so').write_bytes(
            rename_imports(engine, recipe['engine_import_renames']))

        dex = build_dex(work / 'aosp.dex', westlake, recipe, args.smali_tools.resolve(), work)
        (output / 'webview-t.apk').write_bytes(build_apk(args.aosp_webview_apk, dex, recipe['apk_dex_entry']))

        patches = {}
        staged = work / 'stage'
        stage(recipe['jnigraphics']['stage'], workspace, westlake, patches, staged)
        stage(recipe['plat_support']['stage'], workspace, westlake, patches, staged)
        clang, clangxx = toolchain / 'bin/clang', toolchain / 'bin/clang++'
        jnigraphics = build_jnigraphics(toolchain, sysroot, staged, work)
        libcxx = stub_library(clang, 'libc++_shared.so', recipe['jnigraphics']['libcxx_stub'], work, 'jnigraphics')
        run([clangxx, '--target=aarch64-linux-ohos', '--sysroot=' + str(sysroot), '-fuse-ld=lld', '-shared', '-fPIC',
             '-nostdlib++', '-Wl,-soname=libjnigraphics.so', '-Wl,--no-as-needed',
             '-o', output / 'webview-t-lib/libjnigraphics.so', jnigraphics, libcxx, '-lc'])

        objects = build_plat_support(toolchain, sysroot, staged, work)
        stubs = recipe['plat_support']['stubs']
        hwui = stub_library(clang, 'libhwui.so', stubs['libhwui.so'], work, 'plat')
        libcxx = stub_library(clang, 'libc++_shared.so', stubs['libc++_shared.so'], work, 'plat')
        run([clangxx, '--target=aarch64-linux-ohos', '--sysroot=' + str(sysroot), '-fuse-ld=lld', '-shared', '-fPIC',
             '-nostdlib++', '-B' + str(libraries), '-L' + str(libraries),
             '-Wl,-soname=libwebviewchromium_plat_support.so', '-Wl,--allow-shlib-undefined',
             '-Wl,--unresolved-symbols=ignore-all', '-o', output / 'webview-t-lib/libwebviewchromium_plat_support.so',
             *objects, hwui, libcxx, '-ldl', '-lc', '-lm', '-lpthread', builtins])

    artifacts, errors = {}, []
    for name in OUTPUTS:
        path = output / name
        artifacts[name] = {'sha256': file_sha256(path), 'bytes': path.stat().st_size}
        if artifacts[name]['sha256'] != lock[name]:
            errors.append('Differs from the parity27 lock: ' + name)
    report = {
        'schema': 'a2hlab-webview-t-input/v1',
        'recipe_sha256': file_sha256(recipe_path),
        'lock_sha256': file_sha256(lock_path),
        'aosp_webview_apk_sha256': recipe['aosp_webview_apk']['sha256'],
        'replaced_by_bionic_shim_build': ['webview-t-lib/libandroid.so', 'webview-t-lib/libwebview_bionic_shim.so'],
        'artifacts': artifacts,
        'errors': errors,
    }
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    if errors:
        raise SystemExit('\n'.join(errors))
    print('WEBVIEW_INPUT_REBUILT', len(artifacts), 'files match the parity27 lock', flush=True)


if __name__ == '__main__':
    main()
