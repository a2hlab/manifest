#!/usr/bin/env python3
"""Package a pinned Chromium WebView build as a provenance-checked probe input."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

from bootstrap_sdk import digest


IMPORT_REWRITES = {
    'connect': 'wl_conn',
    'freeaddrinfo': 'wl_freeai_oh',
    'getaddrinfo': 'wl_getai_oh',
    'getprogname': 'wl_progname',
    'longjmp': 'wl_ljmp',
    'pthread_sigmask': 'wl_pthread_mask',
    'setjmp': 'wl_sjp',
    'sigaction': 'wl_sigact',
    'sigaddset': 'wl_addset',
    'sigemptyset': 'wl_emptyset',
    'sigfillset': 'wl_fillset',
    'sigismember': 'wl_ismember',
}


def rewrite_elf_dynstr(path):
    """Rewrite exact, equal-length ELF64 .dynstr entries and return offsets."""
    image = bytearray(path.read_bytes())
    if image[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected a little-endian ELF64 WebView engine')
    section_offset = struct.unpack_from('<Q', image, 0x28)[0]
    section_size = struct.unpack_from('<H', image, 0x3a)[0]
    section_count = struct.unpack_from('<H', image, 0x3c)[0]
    names_index = struct.unpack_from('<H', image, 0x3e)[0]
    if section_size != 64 or names_index >= section_count:
        raise ValueError('Unexpected ELF64 section table')

    def section(index):
        start = section_offset + index * section_size
        if start + section_size > len(image):
            raise ValueError('ELF section table extends past end of file')
        name = struct.unpack_from('<I', image, start)[0]
        offset, size = struct.unpack_from('<QQ', image, start + 24)
        return name, offset, size

    _, names_offset, names_size = section(names_index)
    names = image[names_offset:names_offset + names_size]
    dynamic = None
    for index in range(section_count):
        name_offset, offset, size = section(index)
        end = names.find(b'\0', name_offset)
        if end >= 0 and names[name_offset:end] == b'.dynstr':
            dynamic = (offset, size)
            break
    if dynamic is None:
        raise ValueError('WebView engine has no .dynstr section')
    dynamic_offset, dynamic_size = dynamic
    if dynamic_offset + dynamic_size > len(image):
        raise ValueError('ELF .dynstr extends past end of file')
    rewritten = {}
    for old, new in sorted(IMPORT_REWRITES.items()):
        if len(old) != len(new):
            raise ValueError('ELF import rewrite changes string length: ' + old)
        needle = old.encode() + b'\0'
        replacement = new.encode() + b'\0'
        positions = []
        cursor = dynamic_offset
        end = dynamic_offset + dynamic_size
        while True:
            found = image.find(needle, cursor, end)
            if found < 0:
                break
            positions.append(found)
            cursor = found + len(needle)
        if len(positions) != 1:
            raise ValueError('%s appears %d times in WebView .dynstr' %
                             (old, len(positions)))
        image[positions[0]:positions[0] + len(replacement)] = replacement
        rewritten[old] = {'replacement': new, 'file_offset': positions[0]}
    path.write_bytes(image)
    return rewritten


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--westlake-source', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--framework-runtime', type=Path, required=True,
                        help='Accepted source runtime providing libhwui and liblog')
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    westlake = args.westlake_source.resolve()
    source = args.source_root.resolve()
    build = args.build_dir.resolve()
    framework_runtime = args.framework_runtime.resolve()
    lock_path = args.lock.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    if (not westlake.is_relative_to(workspace) or not source.is_relative_to(workspace)
            or not build.is_relative_to(source)
            or not framework_runtime.is_relative_to(workspace)
            or not lock_path.is_relative_to(workspace)):
        raise ValueError('WebView sources, runtimes, builds, and locks must remain inside the workspace')

    framework_runtime_report_path = framework_runtime / 'artifacts.json'
    framework_runtime_report = json.loads(framework_runtime_report_path.read_text())
    if framework_runtime_report.get('errors'):
        raise ValueError('Framework runtime report contains errors')
    for name in ['libhwui.so', 'liblog.so']:
        path = framework_runtime / name
        entry = framework_runtime_report.get('artifacts', {}).get(name, {})
        if (not path.is_file() or digest(path) != entry.get('sha256')
                or path.stat().st_size != entry.get('bytes')):
            raise ValueError('Changed framework runtime input: ' + name)

    lock = json.loads(lock_path.read_text())
    if lock.get('profile') != 'chromium109-webview-source' or len(lock.get('projects', [])) != 1:
        raise ValueError('Unexpected WebView source lock')
    project = lock['projects'][0]
    wanted_revision = project.get('upstream', {}).get('revision')
    revision = subprocess.check_output(
            ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(
            ['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'],
            text=True)
    if revision != wanted_revision or dirty:
        raise ValueError('Chromium checkout differs from the pinned clean upstream revision')

    args_gn = build / 'args.gn'
    apk = build / 'apks/SystemWebView64.apk'
    library = build / 'libwebviewchromium.so'
    ninja = source / 'third_party/ninja/ninja'
    aapt2 = source / 'third_party/android_sdk/public/build-tools/33.0.0/aapt2'
    for path in [args_gn, apk, library, ninja, aapt2]:
        if not path.is_file():
            raise ValueError('Missing Chromium build input: ' + str(path))
    gn = args_gn.read_text()
    required = {
        'target_os': '"android"',
        'target_cpu': '"arm64"',
        'system_webview_package_name': '"com.android.webview"',
        'webview_includes_weblayer': 'false',
    }
    for name, value in required.items():
        if not re.search(r'^\s*' + re.escape(name) + r'\s*=\s*' +
                         re.escape(value) + r'\s*$', gn, re.MULTILINE):
            raise ValueError('Required GN argument missing: ' + name)

    dry_run = subprocess.run(
            [str(ninja), '-C', str(build), '-n', 'apks/SystemWebView64.apk'],
            check=True, capture_output=True, text=True)
    if 'no work to do' not in dry_run.stdout:
        raise ValueError('Chromium source build is not up to date')
    badging = subprocess.check_output([str(aapt2), 'dump', 'badging', str(apk)], text=True)
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",
                        badging, re.MULTILINE)
    if (not package or package.group(1) != 'com.android.webview'
            or package.group(3) != project.get('release_tag')):
        raise ValueError('Unexpected WebView APK identity')

    with zipfile.ZipFile(apk) as archive:
        embedded = archive.read('lib/arm64-v8a/libwebviewchromium.so')
    raw_engine_sha256 = digest(library)
    if raw_engine_sha256 != hashlib.sha256(embedded).hexdigest():
        raise ValueError('Standalone and APK WebView libraries differ')

    sdk_candidates = [
        workspace / 'toolchains/ohos-sdk/native',
        workspace / 'workspace/toolchains/ohos-sdk/native',
        workspace / 'source-closure/workspace/toolchains/ohos-sdk/native',
    ]
    sdk_matches = {path.resolve() for path in sdk_candidates if path.is_dir()}
    if len(sdk_matches) != 1:
        raise ValueError('Expected exactly one OH SDK inside the workspace')
    sdk = sdk_matches.pop()
    compiler = sdk / 'llvm/bin/clang'
    compiler_cxx = sdk / 'llvm/bin/clang++'
    readelf = sdk / 'llvm/bin/llvm-readelf'
    compiler_rt = sdk / 'llvm/lib/clang/15.0.4/lib/aarch64-linux-ohos'
    shim_source = westlake / 'framework/webview-shim/webview_bionic_shim.c'
    setjmp_source = westlake / 'framework/webview-shim/webview_setjmp_arm64.S'
    version_script = westlake / 'framework/webview-shim/webview_bionic_shim.map'
    libandroid_source = westlake / 'framework/webview-shim/libandroid_webview_core_shim.c'
    jnigraphics_source = westlake / 'framework/webview-shim/libjnigraphics_webview_shim.cpp'
    platform_entry_source = westlake / 'framework/webview-shim/webview_platform_jni.cpp'
    platform_buffer_header = westlake / 'framework/webview-shim/webview_graphic_buffer_oh.h'
    platform_buffer_source = westlake / 'framework/webview-shim/graphic_buffer_impl_oh.cpp'
    imports = workspace / 'imports'
    frameworks_base = imports / 'frameworks-base'
    frameworks_native = imports / 'frameworks-native-android15'
    platform_source_root = frameworks_base / 'native/webview/plat_support'
    platform_upstream_sources = [
        platform_source_root / 'draw_functor.cpp',
        platform_source_root / 'draw_gl_functor.cpp',
        platform_source_root / 'functor_utils.cpp',
        platform_source_root / 'graphics_utils.cpp',
    ]
    skia = source / 'third_party/skia'
    android_headers = workspace / 'imports/frameworks-native-android15/include'
    jni_headers = workspace / 'imports/libnativehelper/include_jni'
    for path in [compiler, compiler_cxx, readelf, compiler_rt / 'clang_rt.crtbegin.o',
                 compiler_rt / 'libclang_rt.builtins.a', compiler_rt / 'clang_rt.crtend.o',
                 shim_source, setjmp_source, version_script, libandroid_source,
                 jnigraphics_source, platform_entry_source, platform_buffer_header,
                 platform_buffer_source, *platform_upstream_sources,
                 android_headers / 'android/bitmap.h', jni_headers / 'jni.h',
                 framework_runtime_report_path, framework_runtime / 'libhwui.so',
                 framework_runtime / 'liblog.so']:
        if not path.is_file():
            raise ValueError('Missing WebView boundary build input: ' + str(path))

    output.mkdir(parents=True)
    (output / 'webview-t-lib').mkdir()
    apk_target = output / 'webview-t.apk'
    engine_target = output / 'webview-t-lib/libwebviewchromium.so'
    shutil.copyfile(apk, apk_target)
    shutil.copyfile(library, engine_target)
    if digest(apk_target) != digest(apk) or digest(engine_target) != raw_engine_sha256:
        raise ValueError('Copied WebView source build differs')
    rewrites = rewrite_elf_dynstr(engine_target)

    shim_object = output / 'webview_bionic_shim.c.o'
    setjmp_object = output / 'webview_setjmp_arm64.S.o'
    shim_target = output / 'webview-t-lib/libwebview_bionic_shim.so'
    libandroid_target = output / 'webview-t-lib/libandroid.so'
    jnigraphics_target = output / 'webview-t-lib/libjnigraphics.so'
    platform_target = output / 'webview-t-lib/libwebviewchromium_plat_support.so'
    compile_commands = [
        [str(compiler), '--target=aarch64-linux-ohos',
         '--sysroot=' + str(sdk / 'sysroot'), '-fPIC', '-O2', '-Wall', '-Wextra',
         '-Werror', '-c', str(shim_source), '-o', str(shim_object)],
        [str(compiler), '--target=aarch64-linux-ohos',
         '--sysroot=' + str(sdk / 'sysroot'), '-fPIC', '-c', str(setjmp_source),
         '-o', str(setjmp_object)],
    ]
    for index, command in enumerate(compile_commands):
        with (output / ('boundary-compile-%d.log' % index)).open('x') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    link_command = [
        str(compiler), '--target=aarch64-linux-ohos',
        '--sysroot=' + str(sdk / 'sysroot'), '-fuse-ld=lld', '-nostdlib', '-shared',
        '-Wl,-z,defs', '-Wl,--build-id=sha1',
        '-Wl,-soname,libwebview_bionic_shim.so',
        '-Wl,--version-script=' + str(version_script),
        str(compiler_rt / 'clang_rt.crtbegin.o'), str(shim_object), str(setjmp_object),
        '-Wl,--as-needed', '-ldl', '-lc', str(compiler_rt / 'libclang_rt.builtins.a'),
        str(compiler_rt / 'clang_rt.crtend.o'), '-o', str(shim_target),
    ]
    with (output / 'boundary-link.log').open('x') as log:
        subprocess.run(link_command, check=True, stdout=log, stderr=subprocess.STDOUT)

    libandroid_command = [
        str(compiler), '--target=aarch64-linux-ohos',
        '--sysroot=' + str(sdk / 'sysroot'), '-fuse-ld=lld', '-fPIC', '-O2',
        '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,-z,defs',
        '-Wl,--build-id=sha1', '-Wl,-soname,libandroid.so', str(libandroid_source),
        '-ldl', '-o', str(libandroid_target),
    ]
    with (output / 'libandroid-build.log').open('x') as log:
        subprocess.run(libandroid_command, check=True, stdout=log, stderr=subprocess.STDOUT)
    jnigraphics_command = [
        str(compiler_cxx), '--target=aarch64-linux-ohos',
        '--sysroot=' + str(sdk / 'sysroot'), '-fuse-ld=lld', '-std=c++17', '-fPIC',
        '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,-z,defs',
        '-Wl,--build-id=sha1', '-Wl,-soname,libjnigraphics.so',
        '-I' + str(android_headers), '-I' + str(jni_headers),
        str(jnigraphics_source), '-o', str(jnigraphics_target),
    ]
    with (output / 'libjnigraphics-build.log').open('x') as log:
        subprocess.run(jnigraphics_command, check=True, stdout=log,
                       stderr=subprocess.STDOUT)

    platform_include_dirs = [
        platform_source_root,
        westlake / 'framework/webview-shim',
        imports / 'libnativehelper/include_jni',
        imports / 'libnativehelper/include_platform',
        imports / 'libnativehelper/include',
        imports / 'libnativehelper/header_only_include',
        frameworks_base / 'libs/hwui',
        frameworks_base / 'libs/hwui/jni',
        frameworks_base / 'libs/androidfw/include',
        imports / 'libbase/include',
        imports / 'fmtlib/include',
        imports / 'incremental-delivery/incfs/util/include',
        imports / 'system-core/libutils/include',
        imports / 'system-core/libcutils/include',
        imports / 'system-core/libsystem/include',
        imports / 'logging/liblog/include',
        imports / 'hardware-libhardware/include_all',
        frameworks_native / 'include',
        frameworks_native / 'libs/binder/include',
        frameworks_native / 'libs/nativewindow/include',
        frameworks_native / 'libs/ui/include',
        frameworks_native / 'libs/arect/include',
        frameworks_native / 'libs/nativebase/include',
        frameworks_native / 'libs/math/include',
        frameworks_native / 'libs/binder/ndk/include_cpp',
        frameworks_native / 'libs/binder/ndk/include_ndk',
        imports / 'oh61-vulkan-headers/include',
        skia,
        skia / 'modules/skcms',
        skia / 'client_utils/android',
    ]
    skia_public = skia / 'include'
    platform_include_dirs.extend(sorted(
        path for path in skia_public.rglob('*') if path.is_dir()))
    if any(not path.is_dir() for path in platform_include_dirs):
        raise ValueError('Missing WebView platform-support include directory')
    platform_command = [
        str(compiler_cxx), '--target=aarch64-linux-ohos',
        '--sysroot=' + str(sdk / 'sysroot'), '-fuse-ld=lld', '-std=gnu++20',
        '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
        '-include', str(platform_buffer_header), '-shared', '-Wl,-z,defs',
        '-Wl,--allow-shlib-undefined', '-Wl,--build-id=sha1',
        '-Wl,-soname,libwebviewchromium_plat_support.so',
        *['-I' + str(path) for path in platform_include_dirs],
        *[str(path) for path in platform_upstream_sources],
        str(platform_buffer_source), str(platform_entry_source),
        '-Wl,--no-as-needed', str(framework_runtime / 'libhwui.so'),
        str(framework_runtime / 'liblog.so'), '-o', str(platform_target),
    ]
    with (output / 'platform-support-build.log').open('x') as log:
        subprocess.run(platform_command, check=True, stdout=log,
                       stderr=subprocess.STDOUT)

    engine_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide', str(engine_target)], text=True)
    shim_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide', str(shim_target)], text=True)
    for old, new in IMPORT_REWRITES.items():
        if re.search(r'\b' + re.escape(old) + r'@LIBC\b', engine_symbols):
            raise ValueError('Original WebView import remains after rewrite: ' + old)
        if not re.search(r'\b' + re.escape(new) + r'@LIBC\b', engine_symbols):
            raise ValueError('Rewritten WebView import missing: ' + new)
        if not re.search(r'\b' + re.escape(new) + r'@@LIBC\b', shim_symbols):
            raise ValueError('Source WebView boundary export missing: ' + new)
    libandroid_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide', str(libandroid_target)], text=True)
    jnigraphics_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide', str(jnigraphics_target)], text=True)
    platform_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide', str(platform_target)], text=True)
    hwui_symbols = subprocess.check_output(
            [str(readelf), '--dyn-syms', '--wide',
             str(framework_runtime / 'libhwui.so')], text=True)
    for symbol in ['ALooper_acquire', 'ALooper_addFd', 'ALooper_forThread',
                   'ALooper_prepare', 'ALooper_release', 'ALooper_removeFd', 'ALooper_wake',
                   'ANativeWindow_acquire', 'ANativeWindow_fromSurface',
                   'ANativeWindow_getFormat', 'ANativeWindow_getHeight',
                   'ANativeWindow_getWidth', 'ANativeWindow_lock',
                   'ANativeWindow_release', 'ANativeWindow_setBuffersGeometry',
                   'ANativeWindow_unlockAndPost']:
        if not re.search(r'\b' + re.escape(symbol) + r'$', libandroid_symbols,
                         re.MULTILINE):
            raise ValueError('Source libandroid export missing: ' + symbol)
    for symbol in ['AndroidBitmap_getInfo', 'AndroidBitmap_lockPixels',
                   'AndroidBitmap_unlockPixels']:
        if not re.search(r'\b' + re.escape(symbol) + r'$', jnigraphics_symbols,
                         re.MULTILINE):
            raise ValueError('Source libjnigraphics export missing: ' + symbol)
    if not re.search(r'\bJNI_OnLoad$', platform_symbols, re.MULTILINE):
        raise ValueError('Source WebView platform-support JNI_OnLoad missing')
    for symbol in [
            '_ZN11GraphicsJNI15getNativeCanvasEP7_JNIEnvP8_jobject',
            '_ZN18SkCanvasStateUtils18ReleaseCanvasStateEP13SkCanvasState',
            '_ZN7android10uirenderer21WebViewFunctor_createEPvRKNS0_23WebViewFunctorCallbacksENS0_10RenderModeE',
            '_ZN7android10uirenderer22WebViewFunctor_releaseEi',
            '_ZN7android10uirenderer37WebViewFunctor_reportRenderingThreadsEiPKim',
            '_ZN7android10uirenderer38WebViewFunctor_queryPlatformRenderModeEv',
    ]:
        if not re.search(r'\b' + re.escape(symbol) + r'$', hwui_symbols,
                         re.MULTILINE):
            raise ValueError('Source libhwui platform-support export missing: ' + symbol)

    destinations = {
        'webview-t.apk': apk_target,
        'webview-t-lib/libandroid.so': libandroid_target,
        'webview-t-lib/libjnigraphics.so': jnigraphics_target,
        'webview-t-lib/libwebviewchromium.so': engine_target,
        'webview-t-lib/libwebview_bionic_shim.so': shim_target,
        'webview-t-lib/libwebviewchromium_plat_support.so': platform_target,
    }
    artifacts = {}
    for name, path in destinations.items():
        artifacts[name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    artifacts['webview-t-lib/libwebviewchromium.so'].update({
        'raw_source_build_sha256': raw_engine_sha256,
        'embedded_raw_source_build_sha256': hashlib.sha256(embedded).hexdigest(),
        'boundary_import_rewrites': rewrites,
    })
    report = {
        'schema': 'a2hlab-source-webview/v4',
        'scope': 'source-built Chromium WebView plus source OH boundary; device acceptance separate',
        'source_lock_sha256': digest(lock_path),
        'source_revision': revision,
        'source_tracked_clean': True,
        'build_directory': str(build),
        'args_gn_sha256': digest(args_gn),
        'ninja_dry_run': dry_run.stdout.strip(),
        'package': package.group(1),
        'version_code': int(package.group(2)),
        'version_name': package.group(3),
        'native_engine_source_build': True,
        'native_engine_boundary_transformed': True,
        'boundary_source_build': True,
        'platform_support_source_build': True,
        'boundary_sources': {
            str(shim_source.relative_to(westlake)): digest(shim_source),
            str(setjmp_source.relative_to(westlake)): digest(setjmp_source),
            str(version_script.relative_to(westlake)): digest(version_script),
            str(libandroid_source.relative_to(westlake)): digest(libandroid_source),
            str(jnigraphics_source.relative_to(westlake)): digest(jnigraphics_source),
            str(platform_entry_source.relative_to(westlake)): digest(platform_entry_source),
            str(platform_buffer_header.relative_to(westlake)): digest(platform_buffer_header),
            str(platform_buffer_source.relative_to(westlake)): digest(platform_buffer_source),
        },
        'platform_support_upstream_sources': {
            str(path.relative_to(workspace)): digest(path)
            for path in platform_upstream_sources
        },
        'framework_runtime_report_sha256': digest(framework_runtime_report_path),
        'framework_runtime_inputs': {
            name: framework_runtime_report['artifacts'][name]
            for name in ['libhwui.so', 'liblog.so']
        },
        'boundary_compiler_sha256': digest(compiler),
        'boundary_compiler_cxx_sha256': digest(compiler_cxx),
        'boundary_commands': compile_commands + [link_command, libandroid_command,
                                                  jnigraphics_command,
                                                  platform_command],
        # Chromium's checked-in Android Maven/prebuilt inputs have not yet been
        # closed to their own source projects. Keep this fail-closed even though
        # the APK and native engine were compiled locally from the pinned tree.
        'java_runtime_dependencies_source_complete': False,
        'complete_build_input_closure': False,
        'device_accepted': False,
        'artifacts': artifacts,
        'errors': [],
    }
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('SOURCE_WEBVIEW_PACKAGED', package.group(3), len(artifacts), flush=True)


if __name__ == '__main__':
    main()
