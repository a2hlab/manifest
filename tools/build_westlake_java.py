#!/usr/bin/env python3
"""Compile the Westlake Java adapters against the source Android framework."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from bootstrap_sdk import digest
from build_core_java import class_source, write_jar
from build_framework_java import load_build
from install_java import verify_java


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'westlake-source', 'core-build', 'framework-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--core-extension-build', type=Path, action='append', required=True)
    args = parser.parse_args()
    workspace, westlake, output = args.workspace.resolve(), args.westlake_source.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    java, java_tree = verify_java(workspace)
    record = {'jdk_tree_sha256': java_tree, 'inputs': {}, 'prerequisites': {}, 'commands': [],
              'class_ownership': {}, 'artifacts': {}, 'board_jar_inputs': [], 'device_accepted': False,
              'scope': 'source Westlake adapter classes; runtime packaging and device acceptance pending'}
    core = load_build(args.core_build, record)
    header = args.core_build.resolve() / core['compile_header']['path']
    if digest(header) != core['compile_header']['sha256']:
        raise ValueError('Core header differs')
    headers = [header]
    framework = load_build(args.framework_build, record)
    headers += [args.framework_build.resolve() / 'framework-unrelocated.classes.jar']
    for directory in args.core_extension_build:
        report = load_build(directory, record)
        headers += [directory.resolve() / n for n in report['artifacts'] if n.endswith('.classes.jar')]
    files = []
    for component in ['core', 'activity', 'window', 'package-manager', 'contentprovider', 'broadcast', 'appspawn-x']:
        files += sorted((westlake / 'framework' / component / 'java').rglob('*.java'))
    identities = {}
    for path in files:
        match = re.search(r'(?m)^\s*package\s+([\w.]+)\s*;', path.read_text())
        if not match:
            raise ValueError('Missing Java package: ' + str(path))
        identity = match[1].replace('.', '/') + '/' + path.stem
        if identity in identities:
            raise ValueError('Duplicate Java source: ' + identity)
        identities[identity] = path
        record['inputs'][str(path.relative_to(westlake))] = digest(path)
    output.mkdir(parents=True)
    module = workspace / 'android-source/libcore/luni/src/module/java/module-info.java'
    flags = ['-source', '17', '-target', '17', '--system', 'none', '--patch-module',
             'java.base=' + ':'.join(map(str, headers + [westlake, workspace])),
             '-g:source', '-proc:none', '-XDstringConcat=inline', '-encoding', 'UTF-8',
             '-Xmaxerrs', '1000', '-Xmaxwarns', '5', '-d', str(output / 'classes'), *map(str, files + [module])]
    response = output / 'javac.args'
    response.write_text('\n'.join(json.dumps(s) for s in flags) + '\n')
    command = [str(java / 'bin/javac'), '-J-Xmx2g', '@' + str(response)]
    record['commands'].append(command)
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')
    with (output / 'javac.log').open('x') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Westlake Java compilation failed; see ' + str(output / 'javac.log'))
    entries = {}
    for path in sorted((output / 'classes').rglob('*.class')):
        data = path.read_bytes()
        identity, source_file = class_source(data)
        if identity == 'module-info':
            continue
        source_identity = identity.rsplit('/', 1)[0] + '/' + source_file.removesuffix('.java')
        if source_identity not in identities:
            raise ValueError('Unowned adapter class: ' + identity)
        if identity in core['class_ownership'] or identity in framework['class_ownership']:
            raise ValueError('Adapter would override source framework class: ' + identity)
        record['class_ownership'][identity] = str(identities[source_identity].relative_to(westlake))
        entries[identity + '.class'] = data
    jar = output / 'westlake-unrelocated.classes.jar'
    write_jar(jar, entries)
    record['artifacts'][jar.name] = {'sha256': digest(jar), 'bytes': jar.stat().st_size}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('WESTLAKE_JAVA_SOURCE_PASS', len(files), len(entries), digest(jar), flush=True)


if __name__ == '__main__':
    main()
