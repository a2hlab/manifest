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
from build_core_boot import source_jars
from build_core_java import write_jar, D8_SHA256
from install_java import verify_java

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
    parser.add_argument('--extension-build', type=Path, action='append', default=[])
    parser.add_argument('--native-build', type=Path)
    parser.add_argument('--compatibility', action='store_true')
    args = parser.parse_args()
    workspace, runtime, core, boot = [getattr(args, x).resolve() for x in ['workspace', 'runtime', 'core', 'boot']]
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    reports = {name: json.loads((path / 'artifacts.json').read_text())
               for name, path in [('runtime', runtime), ('core', core), ('boot', boot)]}
    if reports['core'].get('board_jar_inputs') != [] or not reports['core'].get('dex_class_ownership'):
        raise ValueError('Core report lacks source-only DEX verification')
    jars = source_jars(core, [p.resolve() for p in args.extension_build])
    files = [(path, 'core/' + path.name) for path in jars.values()]
    for directory, name in [(runtime, 'runtime'), (boot, 'boot')]:
        entries = reports[name]['artifacts']
        selected = sorted(entries)
        for relative in selected:
            path = directory / relative
            if not path.resolve().is_relative_to(directory) or sha(path) != entries[relative]['sha256']:
                raise ValueError('Artifact differs from source report: ' + str(path))
            destination = relative if name == 'runtime' else name + '/' + relative
            files.append((path, destination))
    if set(reports['boot']['jars']) != {name + '.jar' for name in jars}:
        raise ValueError('Boot image has a different source classpath')
    for name, path in jars.items():
        jar = name + '.jar'
        if reports['boot']['jars'][jar] != sha(path):
            raise ValueError('Core image was generated from different JARs: ' + jar)
    libcxx = workspace / 'toolchains/clang-15/lib/aarch64-linux-ohos/libc++.so'
    if sha(libcxx) != reports['runtime']['platform_providers']['libc++.so']['sha256']:
        raise ValueError('Platform libc++ differs from runtime link input')
    files.append((libcxx, 'libc++.so'))
    if args.native_build:
        native = args.native_build.resolve()
        native_report = json.loads((native / 'artifacts.json').read_text())
        if native_report['target'] != 'ohos' or native_report['compiler_runtimes']['libc++.so'] != sha(libcxx):
            raise ValueError('Native support target/C++ provider mismatch')
        for name, entry in native_report['artifacts'].items():
            path = native / entry['path']
            if not path.resolve().is_relative_to(native) or sha(path) != entry['sha256']:
                raise ValueError('Changed native support artifact: ' + name)
            if name.endswith('.so'):
                files.append((path, name))
    output.mkdir(parents=True)
    sdk = workspace / 'toolchains/ohos-sdk/native'
    java_probe_record = {}
    if args.compatibility:
        if not args.native_build or any(name not in jars for name in ['conscrypt', 'bouncycastle', 'apache-xml']):
            raise ValueError('Compatibility probe requires native support and all three Java extensions')
        java_home, java_probe_record['jdk_tree_sha256'] = verify_java(workspace)
        java_source = workspace / 'art-build/tests/CoreCompatibilityProbe.java'
        header = core / reports['core']['compile_header']['path']
        if sha(header) != reports['core']['compile_header']['sha256']:
            raise ValueError('Changed core compile header')
        headers = [header]
        for path in jars.values():
            if path.parent == core:
                continue
            extension_report = json.loads((path.parent / 'artifacts.json').read_text())
            classes = path.with_suffix('.classes.jar')
            if sha(classes) != extension_report['artifacts'][classes.name]['sha256']:
                raise ValueError('Changed extension compile classes')
            headers.append(classes)
        module = workspace / 'android-source/libcore/luni/src/module/java/module-info.java'
        classes = output / 'probe-classes'
        commands = [[str(java_home / 'bin/javac'), '-source', '17', '-target', '17', '--system', 'none',
                     '--patch-module', 'java.base=' + ':'.join(map(str, headers)) + ':' + str(java_source.parent),
                     '-proc:none', '-XDstringConcat=inline', '-encoding', 'UTF-8', '-d', str(classes),
                     str(module), str(java_source)]]
        with (output / 'javac-probe.log').open('x') as log:
            subprocess.run(commands[0], stdout=log, stderr=subprocess.STDOUT, check=True)
        class_jar = output / 'probe.classes.jar'
        write_jar(class_jar, {p.relative_to(classes).as_posix(): p.read_bytes()
                            for p in sorted(classes.rglob('*.class')) if p.name != 'module-info.class'})
        dex = output / 'probe-dex'
        dex.mkdir()
        d8 = workspace / 'android-source/r8/r8.jar'
        if sha(d8) != D8_SHA256:
            raise ValueError('D8 compiler differs from lock')
        commands.append([str(java_home / 'bin/java'), '-cp', str(d8), 'com.android.tools.r8.D8',
                         '--release', '--min-api', '35', '--output', str(dex), str(class_jar)])
        with (output / 'd8-probe.log').open('x') as log:
            subprocess.run(commands[-1], stdout=log, stderr=subprocess.STDOUT, check=True)
        probe_jar = output / 'probe.jar'
        write_jar(probe_jar, {p.name: p.read_bytes() for p in sorted(dex.glob('*.dex'))})
        files.append((probe_jar, probe_jar.name))
        java_probe_record.update(source_sha256=sha(java_source), commands=commands)
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
    record['java_probe'] = java_probe_record
    unique_files = {}
    for path, relative in files:
        if relative in unique_files and sha(unique_files[relative]) != sha(path):
            raise ValueError('Conflicting runtime stage inputs: ' + relative)
        unique_files[relative] = path
    files = [(path, relative) for relative, path in unique_files.items()]
    for path, relative in files:
        remote = stage + '/' + relative
        call(['file', 'send', path.name, remote], cwd=path.parent)
        actual = shell('sha256sum ' + shlex.quote(remote)).split()[0]
        if actual != sha(path):
            raise ValueError('Device transfer hash mismatch: ' + relative)
        record['files'][relative] = {'sha256': actual, 'bytes': path.stat().st_size}
    shell('chmod 755 ' + stage + '/core_vm_probe')
    classpath = ':'.join(stage + '/core/' + n + '.jar' for n in jars)
    logical = ':'.join('/system/framework/' + n + '.jar' for n in jars)
    command = (f'cd {stage}; LD_LIBRARY_PATH={stage} ANDROID_DATA={stage}/data '
               f'ANDROID_ROOT={stage} timeout 30 {stage}/core_vm_probe {classpath} {stage}/boot/boot.art {logical}')
    if args.compatibility:
        command += ' ' + stage + '/probe.jar'
    try:
        result = shell(command)
        record['passed'] = 'CORE_VM_PASS record=resolved nanotime=monotonic properties=os iovmax=os systemloader=resolved' in result
        if args.compatibility:
            record['passed'] &= 'CORE_COMPATIBILITY_PASS' in result
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
