#!/usr/bin/env python3
"""Compile the original AndroidX experimental annotations with pinned Kotlin."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from bootstrap_sdk import ROOT, digest
from build_core_java import write_jar
from install_java import verify_java
from install_kotlin import verify_kotlin
from rebuild import verify_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'core-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'annotation-experimental-sources.lock.json')
    kotlin, kotlin_tree = verify_kotlin(workspace)
    java, java_tree = verify_java(workspace)
    core = args.core_build.resolve()
    report = json.loads((core / 'artifacts.json').read_text())
    header = core / report['compile_header']['path']
    if digest(header) != report['compile_header']['sha256']:
        raise ValueError('Source core header differs from build report')
    files = sorted((workspace / 'android-source/androidx-annotation-experimental').rglob('*.kt'))
    output.mkdir(parents=True)
    command = [str(java / 'bin/java'), '-Xmx2g', '-cp', str(kotlin / 'lib/*'),
               'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-kotlin-home', str(kotlin),
               '-jvm-target', '1.8', '-no-jdk', '-no-stdlib', '-no-reflect',
               '-classpath', str(header) + ':' + str(kotlin / 'lib/kotlin-stdlib.jar'),
               '-module-name', 'androidx-annotation-experimental', '-d', str(output / 'classes'), *map(str, files)]
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')
    with (output / 'kotlinc.log').open('x') as log:
        subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    entries = {str(p.relative_to(output / 'classes')): p.read_bytes()
               for p in sorted((output / 'classes').rglob('*.class'))}
    if not entries or any(not n.startswith('androidx/annotation/') for n in entries):
        raise ValueError('Unexpected or empty experimental annotation class ownership')
    jar = output / 'annotation-experimental.jar'
    write_jar(jar, entries)
    record = {'sources': sources, 'kotlin_tree_sha256': kotlin_tree, 'jdk_tree_sha256': java_tree,
              'core_header_sha256': digest(header), 'command': command,
              'inputs': {str(p): digest(p) for p in files},
              'artifacts': {jar.name: {'sha256': digest(jar), 'bytes': jar.stat().st_size}},
              'classes': sorted(entries), 'scope': 'source Kotlin annotations; compiler libraries are not deployed'}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('EXPERIMENTAL_ANNOTATIONS_SOURCE_PASS', len(entries), digest(jar))


if __name__ == '__main__':
    main()
