#!/usr/bin/env python3
"""Compile Android core Java sources without board JARs or an Android SDK JAR.

The combined source compile breaks libcore/ICU/OkHttp's bootstrap cycle. Class
SourceFile attributes partition its result back into explicitly owned JARs.
The generated Conscrypt API header is compile-only and is never packaged for
runtime. Full Conscrypt/framework/native integration remains a separate gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
D8_SHA256 = '4a84f75723c26d647025204560161bf9e02bdf05700f4014d377393c349f22dc'
JAR_TIME = (2026, 3, 6, 0, 0, 0)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def class_source(data):
    """Read only the JVM class identity and SourceFile attribute; no JVM load."""
    cursor = 0

    def take(count):
        nonlocal cursor
        result = data[cursor:cursor + count]
        cursor += count
        if len(result) != count:
            raise ValueError('Truncated class file')
        return result

    def u2():
        return struct.unpack('>H', take(2))[0]

    def u4():
        return struct.unpack('>I', take(4))[0]

    if u4() != 0xcafebabe:
        raise ValueError('Not a class file')
    take(4)
    pool = [None] * u2()
    index = 1
    while index < len(pool):
        tag = take(1)[0]
        if tag == 1:
            pool[index] = take(u2()).decode('utf-8', errors='replace')
        elif tag in (7, 8, 16, 19, 20):
            pool[index] = u2()
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            take(4)
        elif tag in (5, 6):
            take(8)
            index += 1
        elif tag == 15:
            take(3)
        else:
            raise ValueError('Unknown constant-pool tag: ' + str(tag))
        index += 1
    u2()
    name = pool[pool[u2()]]
    u2()
    take(2 * u2())

    def attributes():
        result = {}
        for _ in range(u2()):
            key = pool[u2()]
            result[key] = take(u4())
        return result

    for _ in range(2):  # fields, methods
        for _ in range(u2()):
            take(6)
            attributes()
    attrs = attributes()
    if name == 'module-info':
        return name, None
    if 'SourceFile' not in attrs:
        raise ValueError('Missing class ownership metadata: ' + name)
    source = pool[struct.unpack('>H', attrs['SourceFile'])[0]]
    return name, source


def write_jar(path, entries):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, JAR_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def dex_definitions(data):
    if not data.startswith(b'dex\n') or len(data) < 112:
        raise ValueError('Expected a standard DEX file')
    def word(offset):
        return struct.unpack_from('<I', data, offset)[0]
    strings, types, count, classes = word(60), word(68), word(96), word(100)
    result = []
    for i in range(count):
        string_index = word(types + 4 * word(classes + i * 32))
        offset = word(strings + 4 * string_index)
        for _ in range(5):
            byte = data[offset]
            offset += 1
            if not byte & 128:
                break
        else:
            raise ValueError('Invalid DEX string length')
        result.append(data[offset:data.index(0, offset)].decode('utf-8'))
    return result


def generate_headers(source, output):
    # This is the exact API subset needed to bootstrap OkHttp. Restrict the
    # signature grammar and fail if upstream changes beyond that grammar.
    signatures = source / 'conscrypt/api/public/current.txt'
    body = re.search(r'  public class SSLSockets \{(.*?)\n  \}', signatures.read_text(), re.S)
    if not body:
        raise ValueError('Missing upstream SSLSockets API signature')
    methods = []
    for line in body[1].splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith('method '):
            raise ValueError('Unsupported header member: ' + line)
        line = re.sub(r'@(Nullable|NonNull)\s+', '', line[7:])
        match = re.fullmatch(r'(.+?)\((.*?)\)(.*);', line)
        if not match or any(token in line for token in ['<', '>', '@']):
            raise ValueError('Unsupported header signature: ' + line)
        parameters = match[2].split(', ') if match[2] else []
        signature = match[1] + '(' + ', '.join(
            parameter + ' p' + str(i) for i, parameter in enumerate(parameters)) + ')' + match[3]
        methods.append('    ' + signature + ' { throw new AssertionError("compile-only API header"); }')
    header = output / 'headers/android/net/ssl/SSLSockets.java'
    header.parent.mkdir(parents=True)
    header.write_text('package android.net.ssl;\npublic class SSLSockets {\n' + '\n'.join(methods) + '\n}\n')

    # ICU uses these flag names only in source-retention API annotations. This
    # generates identifiers, not an invented flag-value implementation.
    declarations = source / 'icu/icu.aconfig'
    text = declarations.read_text()
    package = re.search(r'package:\s*"([\w.]+)"', text)[1]
    flags = re.findall(r'\bname:\s*"(\w+)"', text)
    generated = output / 'generated/com/android/icu/Flags.java'
    generated.parent.mkdir(parents=True)
    generated.write_text('package ' + package + ';\npublic final class Flags {\n' + ''.join(
        ' public static final String FLAG_' + flag.upper() + ' = "' + package + '.' + flag + '";\n'
        for flag in flags) + '}\n')
    return [header, generated], {str(p.relative_to(source)): sha(p)
                                 for p in [signatures, declarations]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    compiler = str(args.java_home.resolve() / 'bin/javac')
    java = str(args.java_home.resolve() / 'bin/java')
    if not Path(compiler).is_file() or not Path(java).is_file():
        parser.error('JDK 21 is required')
    d8 = source / 'r8/r8.jar'
    if sha(d8) != D8_SHA256:
        raise ValueError('D8 differs from the pinned Android 15 compiler')
    inventory = json.loads((ROOT / 'sources/core-java.json').read_text())['sources']
    owners, inputs = {}, {}
    for relative, owner in inventory.items():
        path = source / relative
        if not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError('Missing/outside Java source: ' + relative)
        package = re.search(r'(?m)^package\s+([\w.]+)\s*;', path.read_text())
        if not package:
            raise ValueError('Missing package declaration: ' + relative)
        identity = (package[1].replace('.', '/'), path.name)
        if identity in owners:
            raise ValueError('Duplicate Java class ownership: ' + str(identity))
        owners[identity] = owner
        inputs[relative] = sha(path)
    output.mkdir(parents=True)
    generated, generator_inputs = generate_headers(source, output)
    owners[('android/net/ssl', 'SSLSockets.java')] = 'compile-only'
    owners[('com/android/icu', 'Flags.java')] = 'compile-only'
    env = {k: v for k, v in os.environ.items()
           if k not in ('JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH')}
    env.update(SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    commands = []

    def run(name, command):
        commands.append(list(map(str, command)))
        with (output / (name + '.log')).open('x') as log:
            subprocess.run(command, check=True, env=env, stdout=log, stderr=subprocess.STDOUT)

    sources = [source / name for name in sorted(inventory)] + generated
    module = source / 'libcore/luni/src/module/java/module-info.java'
    inputs[module.relative_to(source).as_posix()] = sha(module)
    sources += [module]
    response = output / 'sources.rsp'
    response.write_text('\n'.join('"' + str(path) + '"' for path in sources) + '\n')
    classes = output / 'classes'
    run('javac', [compiler, '-J-Xmx4g', '-source', '17', '-target', '17', '--system', 'none',
        '--patch-module', 'java.base=' + str(source / 'libcore'), '-encoding', 'UTF-8',
        '-g:source', '-proc:none', '-XDstringConcat=inline', '-d', classes, '@' + str(response)])
    partitions = {owner: {} for owner in sorted(set(inventory.values()))}
    headers, ownership = {}, {}
    for path in sorted(classes.rglob('*.class')):
        data = path.read_bytes()
        name, filename = class_source(data)
        if name == 'module-info':
            continue
        identity = (name.rpartition('/')[0], filename)
        if identity not in owners:
            raise ValueError('Unowned compiled class: ' + name)
        owner = owners[identity]
        if name in ownership:
            raise ValueError('Duplicate compiled class: ' + name)
        ownership[name] = owner
        headers[name + '.class'] = data
        if owner != 'compile-only':
            partitions[owner][name + '.class'] = data
    header_jar = output / 'core-all-compile-only.jar'
    write_jar(header_jar, headers)
    resources = {owner: {} for owner in partitions}
    for relative in ['luni/src/main/java/java/util/logging/logging.properties',
                     'luni/src/main/java/java/security/security.properties']:
        resources['core-oj'][relative.removeprefix('luni/src/main/java/')] = (source / 'libcore' / relative).read_bytes()
    for owner, relative in [('core-oj', 'libcore/ojluni/src/main/resources'),
                            ('core-icu4j', 'icu/android_icu4j/resources')]:
        directory = source / relative
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                resources[owner][path.relative_to(directory).as_posix()] = path.read_bytes()
                inputs[path.relative_to(source).as_posix()] = sha(path)
    artifacts, dex_ownership = {}, {}
    for owner, entries in partitions.items():
        class_jar = output / (owner + '.classes.jar')
        write_jar(class_jar, entries)
        dex = output / (owner + '-dex')
        dex.mkdir()
        # Android 15 build/soong/java/config/config.go sets this property:
        # its D8 version still otherwise desugars/removes java.lang.Record.
        run('d8-' + owner, [java, '-Xmx2g', '-Dcom.android.tools.r8.emitRecordAnnotationsInDex',
            '-cp', str(d8), 'com.android.tools.r8.D8',
            '--android-platform-build', '--release', '--min-api', '35', '--lib', str(header_jar),
            '--output', str(dex), str(class_jar)])
        payload = dict(resources[owner])
        for path in sorted(dex.iterdir()):
            if path.suffix != '.dex':
                raise ValueError('Unexpected D8 output: ' + str(path))
            data = path.read_bytes()
            for descriptor in dex_definitions(data):
                if descriptor in dex_ownership:
                    raise ValueError('Duplicate runtime DEX class: ' + descriptor)
                if descriptor in ('Landroid/net/ssl/SSLSockets;', 'Lcom/android/icu/Flags;'):
                    raise ValueError('Compile-only header leaked into runtime: ' + descriptor)
                dex_ownership[descriptor] = owner
            payload[path.name] = data
        runtime = output / (owner + '.jar')
        write_jar(runtime, payload)
        artifacts[runtime.name] = {'sha256': sha(runtime), 'bytes': runtime.stat().st_size,
                                   'source_classes': len(entries)}
    for descriptor in ['Ljava/lang/Object;', 'Ljava/lang/Class;', 'Ljava/lang/Record;',
                       'Ldalvik/system/VMRuntime;']:
        if descriptor not in dex_ownership:
            raise ValueError('Required ART class removed by D8: ' + descriptor)
    report = {'scope': 'source-built core Java; full stack and device acceptance remain open',
              'inputs': inputs, 'generator_inputs': generator_inputs, 'commands': commands,
              'compiler': subprocess.check_output([compiler, '-version'], text=True, env=env).strip(),
              'd8_sha256': sha(d8), 'class_ownership': ownership, 'artifacts': artifacts,
              'dex_class_ownership': dex_ownership,
              'compile_header': {'path': header_jar.name, 'sha256': sha(header_jar)},
              'board_jar_inputs': [], 'device_accepted': False}
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('CORE_JAVA_SOURCE_BUILD_PASS', json.dumps(artifacts, sort_keys=True))


if __name__ == '__main__':
    main()
