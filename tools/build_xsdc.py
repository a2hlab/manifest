#!/usr/bin/env python3
"""Compile Android's XML schema compiler and Commons CLI from pinned sources."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from bootstrap_sdk import ROOT, digest
from build_core_java import write_jar
from install_java import verify_java
from rebuild import verify_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'framework-generator-dependencies.lock.json')
    java, java_tree = verify_java(workspace)
    roots = [workspace / 'android-source/system-tools-xsdc/src/main/java',
             workspace / 'android-source/external-commons-cli/src/java']
    files = sorted(p for root in roots for p in root.rglob('*.java'))
    output.mkdir(parents=True)
    response = output / 'javac.args'
    flags = ['--release', '17', '-proc:none', '-encoding', 'UTF-8',
             '-d', str(output / 'classes'), *map(str, files)]
    response.write_text('\n'.join(json.dumps(x) for x in flags) + '\n')
    env = dict(os.environ, LC_ALL='C', TZ='UTC')
    for name in ['JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH']:
        env.pop(name, None)
    command = [str(java / 'bin/javac'), '@' + str(response)]
    with (output / 'javac.log').open('x') as log:
        subprocess.run(command, check=True, env=env, stdout=log, stderr=subprocess.STDOUT)
    entries = {p.relative_to(output / 'classes').as_posix(): p.read_bytes()
               for p in sorted((output / 'classes').rglob('*.class'))}
    entries['META-INF/MANIFEST.MF'] = b'Manifest-Version: 1.0\r\nMain-Class: com.android.xsdc.Main\r\n\r\n'
    jar = output / 'xsdc.jar'
    write_jar(jar, entries)
    report = {'sources': sources, 'jdk_tree_sha256': java_tree, 'command': command,
              'inputs': {str(p.relative_to(workspace)): digest(p) for p in files},
              'artifacts': {'xsdc.jar': {'sha256': digest(jar), 'bytes': jar.stat().st_size}},
              'scope': 'source host XML schema compiler; no device runtime claim'}
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('XSDC_SOURCE_PASS', len(files), digest(jar))


if __name__ == '__main__':
    main()
