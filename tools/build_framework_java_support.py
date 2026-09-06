#!/usr/bin/env python3
"""Build framework annotations, Guava, SafeParcel and protobuf from pinned sources."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from bootstrap_sdk import ROOT, digest
from build_core_java import write_jar, class_source
from install_java import verify_java
from rebuild import verify_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'core-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = []
    for name in ['annotation-sources', 'errorprone-annotation-sources', 'framework-java-support-sources',
                 'framework-java-dependencies', 'framework-mainline-sources', 'framework-tools-sources']:
        sources += verify_sources(workspace, ROOT / (name + '.lock.json'))
    java, java_tree = verify_java(workspace)
    root = workspace / 'android-source'
    sys.path.insert(0, str(workspace / 'westlake/tools'))
    from aosp_blueprint import Sources, index
    modules, errors = index(root)
    if errors:
        raise ValueError('Blueprint parse failures: ' + str(errors))
    groups = Sources(root, modules)
    core = args.core_build.resolve()
    core_report = json.loads((core / 'artifacts.json').read_text())
    header = core / core_report['compile_header']['path']
    if digest(header) != core_report['compile_header']['sha256']:
        raise ValueError('Source core compile header differs')
    output.mkdir(parents=True)
    record = {'sources': sources, 'jdk_tree_sha256': java_tree, 'core_header_sha256': digest(header),
              'inputs': {}, 'commands': [], 'artifacts': {}, 'excluded_compile_only_classes': {},
              'scope': 'source framework dependencies and annotation processor; no framework acceptance'}
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')

    def compile_jar(name, paths, classpath=(), resources=(), android=False, allowed_prefix=None):
        paths = sorted(set(paths))
        for path in paths:
            record['inputs'][str(path)] = digest(path)
        flags = ['-source', '17', '-target', '17', '-g:source', '-proc:none', '-encoding', 'UTF-8',
                 '-XDstringConcat=inline', '-d', str(output / (name + '-classes'))]
        if android:
            paths.append(root / 'libcore/luni/src/module/java/module-info.java')
            flags += ['--system', 'none', '--patch-module', 'java.base=' + str(header) + ':' + str(output)]
        elif classpath:
            flags += ['-classpath', ':'.join(map(str, classpath))]
        response = output / (name + '.args')
        response.write_text('\n'.join(json.dumps(str(v)) for v in flags + paths) + '\n')
        command = [str(java / 'bin/javac'), '-J-Xmx3g', '@' + str(response)]
        record['commands'].append(command)
        with (output / (name + '.log')).open('x') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('Source compilation failed: ' + name + '; see ' + str(output / (name + '.log')))
        entries = {}
        excluded = []
        for path in sorted((output / (name + '-classes')).rglob('*.class')):
            data = path.read_bytes()
            identity, _ = class_source(data)
            if identity == 'module-info' or (allowed_prefix and not identity.startswith(allowed_prefix)):
                excluded.append(identity)
                continue
            entries[identity + '.class'] = data
        for directory in resources:
            for path in sorted(directory.rglob('*')):
                if not path.is_file() or path.suffix == '.java':
                    continue
                relative = str(path.relative_to(directory))
                if relative in entries:
                    raise ValueError('Duplicate Java resource: ' + relative)
                record['inputs'][str(path)] = digest(path)
                entries[relative] = path.read_bytes()
        jar = output / (name + '.jar')
        write_jar(jar, entries)
        record['artifacts'][jar.name] = {'sha256': digest(jar), 'bytes': jar.stat().st_size}
        record['excluded_compile_only_classes'][name] = excluded
        print('JAVA_SUPPORT_BUILT', name, len(entries), digest(jar), flush=True)
        return jar

    annotations = []
    for relative in ['androidx-annotation/androidx/annotation', 'errorprone-annotations/com/google/errorprone/annotations',
                     'external-jsr305/ri/src/main/java', 'external-guava/android-annotation-stubs/src']:
        annotations += list((root / relative).rglob('*.java'))
    annotation_jar = compile_jar('annotations', annotations)
    common = groups.files('guava-both')
    android_jar = compile_jar('guava-android', groups.files('guava-android-host') + common, [annotation_jar])
    host_jar = compile_jar('guava-host', groups.files('guava-jre') + common, [annotation_jar])
    compile_jar('safeparcel-processor', groups.files('safeparcel-annotation-processor-lib') + groups.files('jsilver'),
                [annotation_jar, host_jar], [root / 'external-jsilver/src', root / 'modules-appsearch/safeparcel-processor/resources'])
    relocated = []
    for path in groups.files('libprotobuf-java-lite'):
        if path.suffix != '.java':
            continue
        record['inputs'][str(path)] = digest(path)
        target = output / 'protobuf-lite-source' / path.name
        target.parent.mkdir(exist_ok=True)
        target.write_text(path.read_text().replace('com.google.protobuf', 'com.android.framework.protobuf'))
        relocated.append(target)
    # Match libprotobuf's upstream compile-only libcore_private.stubs dependency.
    # The runtime JAR includes only protobuf classes, never this Unsafe header.
    relocated += list((root / 'protobuf/java/core/src/stubs').rglob('*.java'))
    compile_jar('protobuf-lite', relocated, android=True, allowed_prefix='com/android/framework/protobuf/')
    record['definitions'] = {p: digest(root / p) for p in sorted(groups.definitions)}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('FRAMEWORK_JAVA_SUPPORT_PASS', flush=True)


if __name__ == '__main__':
    main()
