#!/usr/bin/env python3
"""Load verified source native libraries in an isolated OH device directory."""
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid
from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'westlake-source', 'runtime', 'core-runtime', 'firmware-abi', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--graphics-buffers', action='store_true')
    parser.add_argument('--legacy-cpp', action='store_true')
    parser.add_argument('--renderer-build', type=Path)
    parser.add_argument('--graphics-buffer-format', choices=['1', '4', 'all'], default='all')
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    if sum([bool(args.renderer_build), args.graphics_buffers, args.legacy_cpp]) > 1:
        parser.error('Select one native contract')
    files, prerequisites = {}, {}
    for directory in [args.runtime.resolve(), args.core_runtime.resolve()]:
        report = json.loads((directory / 'artifacts.json').read_text())
        if report.get('errors') or report.get('deployable') is False:
            raise ValueError('Failed or link-only prerequisite: ' + str(directory))
        prerequisites[str(directory)] = digest(directory / 'artifacts.json')
        for name, entry in report['artifacts'].items():
            path = directory / name
            if not path.resolve().is_relative_to(directory) or digest(path) != entry['sha256']:
                raise ValueError('Changed source artifact: ' + str(path))
            if name.endswith('.so'):
                if name in files and digest(files[name]) != digest(path):
                    raise ValueError('Conflicting source libraries: ' + name)
                files[name] = path
    output.mkdir(parents=True)
    transport = [args.hdc, '-t', args.serial]

    def call(command, cwd=output):
        result = subprocess.run(transport + command, cwd=cwd, capture_output=True, timeout=50)
        text = (result.stdout + result.stderr).decode(errors='replace').replace('\r', '')
        if result.returncode or '[Fail]' in text:
            raise RuntimeError(text)
        return text

    def shell(command):
        text = call(['shell', 'sh -c ' + shlex.quote(command) +
                     '; a2h_rc=$?; printf "\\n__A2H_RC__%s\\n" "$a2h_rc"'])
        marker = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if not marker:
            raise RuntimeError('Missing device exit status: ' + text)
        return int(marker[1]), text[:marker.start()]

    if args.serial not in subprocess.check_output([args.hdc, 'list', 'targets'], text=True).split():
        raise ValueError('Device is not connected')
    code, identity = shell('uname -m')
    if code or identity.strip() != 'aarch64':
        raise ValueError('Unexpected device architecture: ' + identity)
    firmware = json.loads(args.firmware_abi.read_text())['firmware']
    expected = {e['path']: e['sha256'] for e in firmware.values()}
    code, hashes = shell('sha256sum ' + ' '.join(shlex.quote(p) for p in sorted(expected)))
    actual = {row.split(None, 1)[1].strip(): row.split()[0] for row in hashes.splitlines()
              if len(row.split(None, 1)) == 2 and len(row.split()[0]) == 64}
    if code or actual != expected:
        raise ValueError('Installed firmware differs from link declarations')
    source = args.westlake_source.resolve() / 'native' / (
        'legacy_cpp_probe.c' if args.legacy_cpp else
        'platform_graphics_probe.c' if args.graphics_buffers else 'platform_load_probe.c')
    probe = output / 'platform_load_probe'
    sdk = workspace / 'toolchains/ohos-sdk/native'
    command = [str(sdk / 'llvm/bin/clang'), '--target=aarch64-linux-ohos',
               '--sysroot=' + str(sdk / 'sysroot'), '-O2', '-Werror', str(source), '-ldl', '-o', str(probe)]
    if args.graphics_buffers:
        command += ['-I' + str(workspace / 'android-source/frameworks-native/libs/nativewindow/include'),
                    '-I' + str(workspace / 'android-source/frameworks-native/libs/arect/include'),
                    '-D__INTRODUCED_IN(x)=', '-D__INTRODUCED_IN_32(x)=',
                    '-D__INTRODUCED_IN_64(x)=', '-D__INTRODUCED_IN_FUTURE=']
    if args.renderer_build:
        directory = args.renderer_build.resolve()
        report = json.loads((directory / 'artifacts.json').read_text())
        if report.get('errors') or report.get('deployable') is False:
            raise ValueError('Failed renderer probe build')
        original = directory / probe.name
        if digest(original) != report['artifacts'][probe.name]['sha256']:
            raise ValueError('Changed renderer probe')
        if report['prerequisites']['runtime'] != digest(args.runtime / 'artifacts.json'):
            raise ValueError('Renderer probe was linked against another runtime')
        prerequisites[str(directory)] = digest(directory / 'artifacts.json')
        shutil.copyfile(original, probe)
        command = report['command']
        source = args.westlake_source.resolve() / 'native/skia_gpu_probe.cpp'
    else:
        subprocess.run(command, check=True)
    files[probe.name] = probe
    stage = '/data/local/tmp/a2hlab-native-' + uuid.uuid4().hex
    record = {'scope': ('original Android legacy C++ ABI guards, allocation and logging' if args.legacy_cpp else
                        'source Ganesh GPU draw and readback' if args.renderer_build else
                        'source Android/OH buffer descriptors and CPU round trips' if args.graphics_buffers
                         else 'native relocation and constructors; not Java or Toutiao UX acceptance'),
              'stage': stage, 'prerequisites': prerequisites, 'firmware': actual,
              'probe_source_sha256': digest(source), 'command': command, 'files': {}, 'passed': False}
    code, text = shell('mkdir ' + stage)
    if code:
        raise RuntimeError(text)
    for name, path in sorted(files.items()):
        remote = stage + '/' + name
        call(['file', 'send', path.name, remote], cwd=path.parent)
        code, text = shell('sha256sum ' + shlex.quote(remote))
        if code or text.split()[0] != digest(path):
            raise ValueError('Device transfer differs: ' + name)
        record['files'][name] = digest(path)
        (output / 'device-report.json').write_text(json.dumps(record, indent=2) + '\n')
    shell('chmod 755 ' + stage + '/platform_load_probe')
    libraries = sorted(name for name in files if name.endswith('.so'))
    search = [stage, '/system/lib64', '/system/lib64/platformsdk', '/system/lib64/chipset-sdk',
              '/system/lib64/chipset-sdk-sp', '/system/lib64/ndk', '/vendor/lib64/chipsetsdk',
              '/vendor/lib64/hw', '/vendor/lib64']
    command = 'LD_LIBRARY_PATH=' + ':'.join(search) + ' timeout 30 ' + stage + '/platform_load_probe ' + ' '.join(libraries)
    if args.graphics_buffers and args.graphics_buffer_format != 'all':
        command = 'A2H_BUFFER_FORMAT=' + args.graphics_buffer_format + ' ' + command
    record['graphics_buffer_format'] = args.graphics_buffer_format if args.graphics_buffers else None
    code, text = shell(command)
    (output / 'device.log').write_text(text)
    marker = ('SOURCE_LEGACY_CPP_PASS' if args.legacy_cpp else
              'SOURCE_GPU_RENDER_PASS' if args.renderer_build else
              'SOURCE_GRAPHICS_BUFFERS_PASS' if args.graphics_buffers else 'SOURCE_NATIVE_LOAD_PASS')
    record.update(device_command=command, exit_code=code, passed=code == 0 and marker in text)
    (output / 'device-report.json').write_text(json.dumps(record, indent=2) + '\n')
    print('SOURCE_NATIVE_DEVICE_LOAD', record['passed'], stage, flush=True)
    if not record['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
