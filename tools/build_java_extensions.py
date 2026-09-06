#!/usr/bin/env python3
"""Build Bouncy Castle, Apache XML and Conscrypt using source core classes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from build_core_java import ROOT, D8_SHA256, sha, class_source, write_jar, dex_definitions
from install_java import verify_java
from rebuild import verify_sources
from rebuild import verify_toolchains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--core-build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--library', action='append', choices=['bouncycastle', 'apache-xml', 'conscrypt'])
    args = parser.parse_args()
    workspace, core, output = args.workspace.resolve(), args.core_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    locks = verify_sources(workspace, ROOT / 'core-sources.lock.json')
    locks += verify_sources(workspace, ROOT / 'java-extensions.lock.json')
    selected = args.library or ['bouncycastle', 'apache-xml', 'conscrypt']
    native_toolchains = {}
    if 'conscrypt' in selected:
        locks += verify_sources(workspace, ROOT / 'native-sources.lock.json')
        native_toolchains = verify_toolchains(workspace, False)
    java_home, jdk_hash = verify_java(workspace)
    report = json.loads((core / 'artifacts.json').read_text())
    header = core / report['compile_header']['path']
    if not header.resolve().is_relative_to(core) or sha(header) != report['compile_header']['sha256']:
        raise ValueError('Compile core classes differ from source report')
    if report.get('board_jar_inputs') != []:
        raise ValueError('Core lacks source-only input verification')
    source = workspace / 'android-source'
    d8, module = source / 'r8/r8.jar', source / 'libcore/luni/src/module/java/module-info.java'
    if sha(d8) != D8_SHA256:
        raise ValueError('D8 differs from locked compiler')
    inventory = json.loads((ROOT / 'sources/java-extensions.json').read_text())
    output.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ('JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH')}
    env.update(SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    record = {'scope': 'source Java extensions; not native crypto/framework/UX acceptance',
              'sources': locks, 'jdk_tree_sha256': jdk_hash, 'core_header_sha256': sha(header),
              'd8_sha256': sha(d8), 'inputs': {module.relative_to(source).as_posix(): sha(module)},
              'commands': [], 'artifacts': {}, 'dex_class_ownership': {}, 'board_jar_inputs': [],
              'device_accepted': False}
    record['native_toolchains'] = native_toolchains
    record['generated_sources'] = {}

    def run(name, command):
        record['commands'].append(list(map(str, command)))
        with (output / (name + '.log')).open('x') as log:
            subprocess.run(list(map(str, command)), check=True, env=env, stdout=log, stderr=subprocess.STDOUT)

    def checked(relative):
        path = source / relative
        if not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError('Missing/outside declared input: ' + relative)
        record['inputs'][relative] = sha(path)
        return path

    definitions = set(report['dex_class_ownership'])
    for name, spec in inventory.items():
        if name not in selected:
            continue
        paths = [checked(relative) for relative in spec['sources']]
        if spec.get('generator') == 'conscrypt-native-constants':
            generator = checked('conscrypt/constants/src/gen/cpp/generate_constants.cc')
            native = workspace / 'toolchains/ohos-sdk/native'
            tool = output / 'conscrypt_generate_constants'
            run('compile-constants', [native / 'llvm/bin/clang', '-x', 'c++', '-std=c++17',
                '-DBORINGSSL_NO_CXX', '-I' + str(source / 'boringssl/src/include'),
                '-O2', '-Werror=date-time', '-ffile-prefix-map=' + str(workspace) + '=/src',
                generator, '-o', tool])
            generated = output / 'generated/com/android/org/conscrypt/NativeConstants.java'
            generated.parent.mkdir(parents=True)
            command = [str(tool), 'com.android.org.conscrypt']
            record['commands'].append(command)
            generated.write_bytes(subprocess.check_output(command, env=env))
            record['generated_sources'][generated.relative_to(output).as_posix()] = sha(generated)
            record['constants_generator_sha256'] = sha(tool)
            paths.append(generated)
        owners = set()
        for path in paths:
            package = re.search(r'(?m)^\s*package\s+([\w.]+)\s*;', path.read_text())
            if not package:
                raise ValueError('Missing package: ' + str(path))
            identity = (package[1].replace('.', '/'), path.name)
            if identity in owners:
                raise ValueError('Duplicate source identity: ' + str(identity))
            owners.add(identity)
        rsp = output / (name + '.rsp')
        rsp.write_text('\n'.join('"' + str(p) + '"' for p in paths + [module]) + '\n')
        classes = output / (name + '-classes')
        run('javac-' + name, [java_home / 'bin/javac', '-J-Xmx2g', '-source', '17', '-target', '17',
            '--system', 'none', '--patch-module', 'java.base=' + str(header) + ':' + str(source / name),
            '-g:source', '-proc:none', '-XDstringConcat=inline', '-encoding', 'UTF-8',
            '-d', classes, '@' + str(rsp)])
        entries = {}
        for path in sorted(classes.rglob('*.class')):
            data = path.read_bytes()
            identity, filename = class_source(data)
            if identity == 'module-info':
                continue
            if (identity.rpartition('/')[0], filename) not in owners or identity + '.class' in entries:
                raise ValueError('Unowned or duplicate compiled class: ' + identity)
            entries[identity + '.class'] = data
        class_jar = output / (name + '.classes.jar')
        write_jar(class_jar, entries)
        dex = output / (name + '-dex')
        dex.mkdir()
        run('d8-' + name, [java_home / 'bin/java', '-Xmx2g',
            '-Dcom.android.tools.r8.emitRecordAnnotationsInDex', '-cp', d8, 'com.android.tools.r8.D8',
            '--android-platform-build', '--release', '--min-api', '35', '--lib', header,
            '--output', dex, class_jar])
        payload = {relative: checked(path).read_bytes() for path, relative in spec['resources'].items()}
        for path in sorted(dex.iterdir()):
            if path.suffix != '.dex':
                raise ValueError('Unexpected D8 artifact: ' + str(path))
            data = path.read_bytes()
            for descriptor in dex_definitions(data):
                if descriptor in definitions:
                    raise ValueError('Duplicate core/extension class: ' + descriptor)
                definitions.add(descriptor)
                record['dex_class_ownership'][descriptor] = name
            payload[path.name] = data
        runtime = output / (name + '.jar')
        write_jar(runtime, payload)
        for path in [runtime, class_jar]:
            record['artifacts'][path.name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('JAVA_EXTENSIONS_SOURCE_BUILD_PASS', len(record['dex_class_ownership']))


if __name__ == '__main__':
    main()
