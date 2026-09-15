#!/usr/bin/env python3
"""Build the Android JarJar command line tool and ASM from locked sources."""
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
    for name in ['workspace', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'framework-java-compiler-tools.lock.json')
    java, java_tree = verify_java(workspace)
    root = workspace / 'android-source'
    jarjar = root / 'external-jarjar'
    # These integrations are not reachable from the CLI. Compiling them would
    # unnecessarily require the upstream prebuilt Ant and Maven plugin JARs.
    integrations = {
        'src/main/com/tonicsystems/jarjar/util/AntJarProcessor.java',
        'src/main/com/tonicsystems/jarjar/JarJarMojo.java',
        'src/main/com/tonicsystems/jarjar/JarJarTask.java',
    }
    files = [p for folder in ['src/android', 'src/main']
             for p in (jarjar / folder).rglob('*.java')
             if str(p.relative_to(jarjar)) not in integrations]
    for module in ['asm', 'asm-tree', 'asm-commons']:
        files += list((root / 'external-ow2-asm' / module / 'src/main').rglob('*.java'))
    files = sorted(files)
    output.mkdir(parents=True)
    flags = ['-source', '17', '-target', '17', '-proc:none', '-g:source',
             '-encoding', 'UTF-8', '-d', str(output / 'classes'), *map(str, files)]
    response = output / 'javac.args'
    response.write_text('\n'.join(json.dumps(s) for s in flags) + '\n')
    command = [str(java / 'bin/javac'), '@' + str(response)]
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')
    with (output / 'javac.log').open('x') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('JarJar source compilation failed; see ' + str(output / 'javac.log'))
    entries = {str(p.relative_to(output / 'classes')): p.read_bytes()
               for p in sorted((output / 'classes').rglob('*.class'))}
    resources = list((jarjar / 'res').rglob('*'))
    resources = [p for p in resources if p.is_file()]
    for path in resources:
        entries[str(path.relative_to(jarjar / 'res'))] = path.read_bytes()
    entries['META-INF/MANIFEST.MF'] = b'Manifest-Version: 1.0\n' + (jarjar / 'manifest.txt').read_bytes() + b'\n'
    result_jar = output / 'jarjar.jar'
    write_jar(result_jar, entries)
    record = {'sources': sources, 'jdk_tree_sha256': java_tree, 'commands': [command],
              'inputs': {str(p): digest(p) for p in files + resources + [jarjar / 'manifest.txt']},
              'excluded_unused_integrations': sorted(integrations),
              'artifacts': {result_jar.name: {'sha256': digest(result_jar), 'bytes': result_jar.stat().st_size}},
              'scope': 'source host CLI; no Ant or Maven integration and no runtime deployment'}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('JARJAR_SOURCE_PASS', len(files), digest(result_jar), flush=True)


if __name__ == '__main__':
    main()
