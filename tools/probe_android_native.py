#!/usr/bin/env python3
"""Compile and run behavioral native-support checks in an isolated OHOS device stage."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import uuid
import zipfile
import zlib
from build_core_java import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'native-build', 'apk', 'out']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    workspace, native, output = args.workspace.resolve(), args.native_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    build = json.loads((native / 'artifacts.json').read_text())
    if build['target'] != 'ohos':
        raise ValueError('An OHOS source build is required')
    inventory = workspace / 'westlake/native/libraries.json'
    if sha(inventory) != build['inventory_sha256']:
        raise ValueError('Build inventory differs from source report')
    apk_lock = json.loads((Path(__file__).resolve().parents[1] / 'app-inputs.lock.json').read_text())
    # The lock is a single original APK input, independent of runtime builds.
    expected = apk_lock['applications']['toutiao']
    if sha(args.apk) != expected['sha256'] or args.apk.stat().st_size != expected['bytes']:
        raise ValueError('APK differs from the original application lock')
    files = [(args.apk.resolve(), 'toutiao.apk')]
    for name, entry in build['artifacts'].items():
        path = native / entry['path']
        if not path.resolve().is_relative_to(native) or sha(path) != entry['sha256']:
            raise ValueError('Changed native artifact: ' + name)
        if name.endswith('.so'):
            files.append((path, 'lib/' + name))
    platform = workspace / 'toolchains/clang-15'
    libcxx = platform / 'lib/aarch64-linux-ohos/libc++.so'
    if sha(libcxx) != build['compiler_runtimes']['libc++.so']:
        raise ValueError('Platform libc++ differs from native build')
    files.append((libcxx, 'lib/libc++.so'))
    output.mkdir(parents=True)
    with zipfile.ZipFile(output / 'fixture.zip', 'x', compression=zipfile.ZIP_DEFLATED) as packed:
        item = zipfile.ZipInfo('hello.txt', date_time=(2026, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        packed.writestr(item, '你好 Android'.encode())
    (output / 'malformed.zip').write_bytes((output / 'fixture.zip').read_bytes()[:20])
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = bytes([0,255,0,0,255,0,255,0,255,0,0,0,255,255,255,255,255,255])
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
    (output / 'fixture.png').write_bytes(png + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
    font = workspace / 'android-source/frameworks-base/data/fonts/DroidSansFallback.ttf'
    files.append((font, 'font.ttf'))
    for name in ['fixture.zip', 'malformed.zip', 'fixture.png']:
        files.append((output / name, name))
    sdk = workspace / 'toolchains/ohos-sdk/native'
    spec = json.loads(inventory.read_text())
    includes = set(spec['includes'])
    for library in spec['libraries'].values():
        includes.update(library.get('includes', []))
    source = workspace / 'westlake/native/tests/support_probe.cpp'
    command = [sdk / 'llvm/bin/clang++', '--target=aarch64-linux-ohos', '--sysroot=' + str(sdk / 'sysroot'),
               '-std=gnu++20', '-O2', '-D_GNU_SOURCE', '-D_POSIX_C_SOURCE=200809L',
               '-include', workspace / 'westlake/native/include/ohos_port.h',
               '-nostdinc++', '-isystem', platform / 'include/libcxx-ohos/include/c++/v1',
               '-ffile-prefix-map=' + str(workspace) + '=/src',
               *['-I' + str(workspace / p) for p in sorted(includes)], source,
               '-nostdlib++', '-Wl,-z,defs',
               *[native / entry['path'] for name, entry in build['artifacts'].items() if name.endswith('.so')],
               libcxx, '-ldl', '-lpthread', '-o', output / 'support_probe']
    with (output / 'compile.log').open('x') as log:
        subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT, check=True)
    files.append((output / 'support_probe', 'support_probe'))
    transport = [args.hdc, '-t', args.serial]
    def call(command, cwd=output):
        result = subprocess.run(transport + command, cwd=cwd, capture_output=True, timeout=120)
        text = (result.stdout + result.stderr).decode(errors='replace').replace('\r', '')
        if result.returncode or '[Fail]' in text:
            raise RuntimeError(text)
        return text
    def shell(command):
        text = call(['shell', 'sh -c ' + shlex.quote(command) +
                     '; a2h_rc=$?; printf "\\n__A2H_RC__%s\\n" "$a2h_rc"'])
        match = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if not match or int(match[1]):
            raise RuntimeError(text)
        return text[:match.start()]
    stage = '/data/local/tmp/a2hlab-native-' + uuid.uuid4().hex
    shell('mkdir ' + stage + ' && mkdir ' + stage + '/lib')
    record = {'scope': 'source native support behavior; not a Toutiao UI launch',
              'stage': stage, 'files': {}, 'source_sha256': sha(source),
              'build_report_sha256': sha(native / 'artifacts.json'),
              'command': list(map(str, command)), 'passed': False, 'full_stack_accepted': False}
    for path, relative in files:
        remote = stage + '/' + relative
        call(['file', 'send', path.name, remote], cwd=path.parent)
        actual = shell('sha256sum ' + shlex.quote(remote)).split()[0]
        if actual != sha(path):
            raise ValueError('Device transfer mismatch: ' + relative)
        record['files'][relative] = {'sha256': actual, 'bytes': path.stat().st_size}
    shell('chmod 755 ' + stage + '/support_probe')
    command = f'cd {stage}; LD_LIBRARY_PATH={stage}/lib timeout 30 ./support_probe fixture.zip fixture.png font.ttf toutiao.apk malformed.zip'
    try:
        result = shell(command)
        record['passed'] = 'ANDROID_SUPPORT_PASS' in result
    except RuntimeError as error:
        result = str(error)
    (output / 'device.log').write_text(result)
    record['device_log_sha256'] = sha(output / 'device.log')
    (output / 'device-probe.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('ANDROID_SUPPORT_DEVICE_PASS' if record['passed'] else 'ANDROID_SUPPORT_DEVICE_FAIL', stage)
    raise SystemExit(0 if record['passed'] else 1)


if __name__ == '__main__':
    main()
