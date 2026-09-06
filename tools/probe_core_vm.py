#!/usr/bin/env python3
"""Stage verified source core outputs and test JNI VM creation on an OHOS device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import uuid

NAMES = ['core-oj', 'core-libart', 'core-icu4j', 'okhttp']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'runtime', 'core', 'boot', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    workspace, runtime, core, boot = [getattr(args, x).resolve() for x in ['workspace', 'runtime', 'core', 'boot']]
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    reports = {name: json.loads((path / 'artifacts.json').read_text())
               for name, path in [('runtime', runtime), ('core', core), ('boot', boot)]}
    if reports['core'].get('board_jar_inputs') != [] or not reports['core'].get('dex_class_ownership'):
        raise ValueError('Core report lacks source-only DEX verification')
    files = []
    for directory, name in [(runtime, 'runtime'), (core, 'core'), (boot, 'boot')]:
        entries = reports[name]['artifacts']
        selected = [n + '.jar' for n in NAMES] if name == 'core' else sorted(entries)
        for relative in selected:
            path = directory / relative
            if not path.resolve().is_relative_to(directory) or sha(path) != entries[relative]['sha256']:
                raise ValueError('Artifact differs from source report: ' + str(path))
            destination = relative if name == 'runtime' else name + '/' + relative
            files.append((path, destination))
    for name in NAMES:
        jar = name + '.jar'
        if reports['boot']['jars'][jar] != sha(core / jar):
            raise ValueError('Core image was generated from different JARs: ' + jar)
    libcxx = workspace / 'toolchains/clang-15/lib/aarch64-linux-ohos/libc++.so'
    if sha(libcxx) != reports['runtime']['platform_providers']['libc++.so']['sha256']:
        raise ValueError('Platform libc++ differs from runtime link input')
    files.append((libcxx, 'libc++.so'))
    output.mkdir(parents=True)
    sdk = workspace / 'toolchains/ohos-sdk/native'
    source = workspace / 'art-build/tests/core_vm_probe.c'
    probe = output / 'core_vm_probe'
    command = [str(sdk / 'llvm/bin/clang'), '--target=aarch64-linux-ohos',
               '--sysroot=' + str(sdk / 'sysroot'), '-O2', '-Werror=date-time',
               '-ffile-prefix-map=' + str(workspace) + '=/src',
               '-I' + str(workspace / 'upstream/aosp-11/libnativehelper/include_jni'),
               str(source), '-ldl', '-o', str(probe)]
    subprocess.run(command, check=True)
    files.append((probe, probe.name))
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

    stage = '/data/local/tmp/a2hlab-core-' + uuid.uuid4().hex
    shell('mkdir ' + stage)
    shell('mkdir -p ' + stage + '/core ' + stage + '/boot ' + stage + '/data/dalvik-cache/arm64')
    record = {'scope': 'source core VM startup; not framework/Toutiao acceptance',
              'stage': stage, 'source_sha256': sha(source), 'build_command': command,
              'files': {}, 'passed': False, 'full_stack_accepted': False}
    for path, relative in files:
        remote = stage + '/' + relative
        call(['file', 'send', path.name, remote], cwd=path.parent)
        actual = shell('sha256sum ' + shlex.quote(remote)).split()[0]
        if actual != sha(path):
            raise ValueError('Device transfer hash mismatch: ' + relative)
        record['files'][relative] = {'sha256': actual, 'bytes': path.stat().st_size}
    shell('chmod 755 ' + stage + '/core_vm_probe')
    classpath = ':'.join(stage + '/core/' + n + '.jar' for n in NAMES)
    command = (f'cd {stage}; LD_LIBRARY_PATH={stage} ANDROID_DATA={stage}/data '
               f'ANDROID_ROOT={stage} timeout 20 {stage}/core_vm_probe {classpath} {stage}/boot/boot.art')
    try:
        result = shell(command)
        record['passed'] = 'CORE_VM_PASS record=resolved nanotime=monotonic properties=os iovmax=os systemloader=resolved' in result
    except RuntimeError as error:
        result = str(error)
    (output / 'device.log').write_text(result)
    record['device_log_sha256'] = sha(output / 'device.log')
    # These legacy boundary registrations are still compatibility gaps even if
    # the tested startup/OS-query path succeeds. Preserve their diagnostics.
    record['native_registration_diagnostics'] = sorted({line.split('] ', 1)[-1]
        for line in result.splitlines() if 'Failed to register' in line})
    (output / 'device-probe.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('CORE_VM_DEVICE_PASS' if record['passed'] else 'CORE_VM_DEVICE_FAIL', stage)
    raise SystemExit(0 if record['passed'] else 1)


if __name__ == '__main__':
    main()
