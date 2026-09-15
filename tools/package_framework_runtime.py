#!/usr/bin/env python3
"""Relocate and dex the source framework/adapter graph, with unique class ownership."""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile
from bootstrap_sdk import digest
from build_core_java import D8_SHA256, class_source, dex_definitions, write_jar
from build_framework_java import load_build
from install_java import verify_java


def rules_from(path):
    rules = []
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if fields[0] not in {'rule', 'zap'} or len(fields) != (3 if fields[0] == 'rule' else 2):
            raise ValueError('Unsupported relocation rule: ' + line)
        pattern = ''
        parts = re.split(r'(\*\*|\*)', fields[1])
        for index, token in enumerate(parts):
            # Android JarJar permits a trailing wildcard to match nothing.
            trailing = index == len(parts) - 2 and parts[-1] == ''
            pattern += (('(.*)' if trailing else '(.+?)') if token == '**' else
                        ('([^.]*)' if trailing else '([^.]+)') if token == '*' else re.escape(token))
        rules.append((fields[0], re.compile('^' + pattern + '$'), fields[2] if len(fields) == 3 else None))
    return rules


def relocated(identity, rules):
    name = identity.replace('/', '.')
    for kind, pattern, target in rules:
        match = pattern.fullmatch(name)
        if not match:
            continue
        if kind == 'zap':
            return None
        return re.sub(r'@([0-9]+)', lambda m: match[int(m[1])], target).replace('.', '/')
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'rules', 'core-build', 'framework-build', 'adapter-build',
                 'support-build', 'jarjar-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--core-extension-build', type=Path, action='append', required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    java, java_tree = verify_java(workspace)
    d8 = workspace / 'android-source/r8/r8.jar'
    if digest(d8) != D8_SHA256:
        raise ValueError('D8 differs from pinned compiler')
    record = {'prerequisites': {}, 'commands': [], 'artifacts': {}, 'class_ownership': {},
              'dex_class_ownership': {}, 'dex_synthetic_origins': {}, 'excluded_compile_only_classes': {},
              'jdk_tree_sha256': java_tree, 'd8_sha256': digest(d8),
              'jarjar_rules_sha256': digest(args.rules), 'board_jar_inputs': [],
              'scope': 'source process framework and adapters; full native and device acceptance pending',
              'device_accepted': False}
    core = load_build(args.core_build, record)
    framework = load_build(args.framework_build, record)
    adapter = load_build(args.adapter_build, record)
    load_build(args.support_build, record)
    load_build(args.jarjar_build, record)
    libraries = {}
    core_header = args.core_build.resolve() / core['compile_header']['path']
    if digest(core_header) != core['compile_header']['sha256']:
        raise ValueError('Core header differs')
    # Use only core-owned implementations as the D8 library input. Exclude the
    # temporary Conscrypt API prototype, then add the real extension classes.
    with zipfile.ZipFile(core_header) as archive:
        for name in archive.namelist():
            if core['class_ownership'].get(name.removesuffix('.class')) not in {None, 'compile-only'}:
                libraries[name] = archive.read(name)
    core_dex = set(core['dex_class_ownership'])
    for directory in args.core_extension_build:
        report = load_build(directory, record)
        core_dex.update(report['dex_class_ownership'])
        for name in report['artifacts']:
            if not name.endswith('.classes.jar'):
                continue
            with zipfile.ZipFile(directory / name) as archive:
                for entry in archive.namelist():
                    if entry in libraries:
                        raise ValueError('Duplicate core library class: ' + entry)
                    libraries[entry] = archive.read(entry)
    output.mkdir(parents=True)
    library = output / 'core-compile-only.jar'
    write_jar(library, libraries)
    rules = rules_from(args.rules)
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')

    def run(command, name):
        command = list(map(str, command))
        record['commands'].append(command)
        with (output / (name + '.log')).open('x') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(output / (name + '.log')))

    inputs = {
        'framework': [args.framework_build / 'framework-unrelocated.classes.jar',
                      args.support_build / 'guava-android.jar', args.support_build / 'protobuf-lite.jar'],
        'adapter-runtime-bcp': [args.adapter_build / 'westlake-unrelocated.classes.jar'],
    }
    compile_jars = []
    for group, jars in inputs.items():
        entries, expected = {}, {}
        for jar in jars:
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    data = archive.read(name)
                    if name.endswith('.class'):
                        identity, source_file = class_source(data)
                        if identity.startswith('com/google/protobuf/nano/'):
                            record['excluded_compile_only_classes'][identity] = 'explicit relocated nano runtimes own these classes'
                            continue
                        destination = relocated(identity, rules)
                        if destination is None:
                            record['excluded_compile_only_classes'][identity] = 'upstream annotation stripping rule'
                        else:
                            if destination in expected or destination in record['class_ownership']:
                                raise ValueError('Duplicate relocated class: ' + destination)
                            expected[destination] = {'original': identity, 'class_jar': str(jar),
                                                     'source_file': source_file, 'group': group}
                    if name in entries:
                        raise ValueError('Duplicate input JAR entry: ' + name)
                    entries[name] = data
        raw = output / (group + '.unrelocated.jar')
        write_jar(raw, entries)
        repacked = output / (group + '.jarjar-output.jar')
        run([java / 'bin/java', '-Xmx3g', '-jar', args.jarjar_build / 'jarjar.jar',
             'process', args.rules.resolve(), raw, repacked], 'jarjar-' + group)
        entries, actual = {}, set()
        with zipfile.ZipFile(repacked) as archive:
            for name in archive.namelist():
                if name.endswith('/'):
                    continue
                data = archive.read(name)
                if name.endswith('.class'):
                    identity, _ = class_source(data)
                    if identity in actual or name != identity + '.class':
                        raise ValueError('Invalid relocated class entry: ' + name)
                    actual.add(identity)
                entries[name] = data
        if actual != set(expected):
            raise ValueError('JarJar class inventory differs from rules: ' +
                             str({'missing': sorted(set(expected) - actual), 'extra': sorted(actual - set(expected))}))
        record['class_ownership'].update(expected)
        class_jar = output / (group + '.classes.jar')
        write_jar(class_jar, entries)
        dex = output / (group + '-dex')
        dex.mkdir()
        lib_flags = [value for path in [library] + compile_jars for value in ['--lib', path]]
        run([java / 'bin/java', '-Xmx7g', '-Dcom.android.tools.r8.emitRecordAnnotationsInDex',
             '-cp', d8, 'com.android.tools.r8.D8', '--android-platform-build', '--release', '--min-api', '35',
             *lib_flags, '--output', dex, class_jar], 'd8-' + group)
        payload = {n: d for n, d in entries.items() if not n.endswith('.class') and not n.startswith('META-INF/')}
        for path in sorted(dex.iterdir()):
            if path.suffix != '.dex':
                raise ValueError('Unexpected D8 artifact: ' + str(path))
            data = path.read_bytes()
            class_defs = struct.unpack_from('<I', data, 100)[0]
            for index, descriptor in enumerate(dex_definitions(data)):
                identity = descriptor[1:-1]
                if descriptor in core_dex or descriptor in record['dex_class_ownership']:
                    raise ValueError('Duplicate boot class: ' + descriptor)
                if identity not in expected:
                    access = struct.unpack_from('<I', data, class_defs + 32 * index + 4)[0]
                    origin = re.split(r'\$\$ExternalSynthetic|-IA$', identity)[0]
                    if not access & 0x1000 or origin not in expected:
                        raise ValueError('Unowned D8 class: ' + descriptor)
                    record['dex_synthetic_origins'][descriptor] = origin
                if identity.startswith(('com/google/common/', 'com/google/protobuf/', 'org/chromium/net/',
                                        'org/chromium/base/', 'org/jni_zero/', 'sun/misc/')):
                    raise ValueError('Private or compile-only class leaked into boot payload: ' + descriptor)
                record['dex_class_ownership'][descriptor] = group
            payload[path.name] = data
        runtime = output / (group + '.jar')
        write_jar(runtime, payload)
        for path in [runtime, class_jar]:
            record['artifacts'][path.name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
        compile_jars.append(class_jar)
        print('FRAMEWORK_RUNTIME_PACKAGED', group, len(expected), digest(runtime), flush=True)
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
