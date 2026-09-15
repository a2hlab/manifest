#!/usr/bin/env python3
"""Compile the source Android framework graph and record class ownership.

This emits an unrelocated class JAR for subsequent runtime packaging. It is
neither a boot JAR nor evidence that the framework works on a device.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from bootstrap_sdk import ROOT, digest
from build_core_java import class_source, write_jar
from install_java import verify_java
from rebuild import verify_sources


def load_build(directory, record):
    directory = directory.resolve()
    path = directory / 'artifacts.json'
    report = json.loads(path.read_text())
    if report.get('errors'):
        raise ValueError('Failed prerequisite: ' + str(directory))
    artifacts = report.get('artifacts', report.get('generated', {}))
    for name, entry in artifacts.items():
        path = directory / (entry.get('path', name) if isinstance(entry, dict) else name)
        expected = entry['sha256'] if isinstance(entry, dict) else entry
        if not path.resolve().is_relative_to(directory) or digest(path) != expected:
            raise ValueError('Generated artifact differs: ' + str(path))
    record['prerequisites'][str(directory)] = digest(directory / 'artifacts.json')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'core-build', 'support-build', 'experimental-annotations-build',
                 'aidl-build', 'flags-build', 'module-build', 'hidl-build', 'misc-build',
                 'cronet-build', 'schema-build', 'resources-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--core-extension-build', type=Path, action='append', required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'framework-inputs.lock.json')
    java, java_tree = verify_java(workspace)
    root = workspace / 'android-source'
    record = {'sources': sources, 'jdk_tree_sha256': java_tree, 'prerequisites': {},
              'inputs': {}, 'transforms': {}, 'class_ownership': {}, 'resources': {},
              'excluded_sources': {}, 'duplicate_identical_sources': {}, 'commands': [],
              'scope': 'unrelocated source framework classes; runtime packaging and device acceptance pending',
              'board_jar_inputs': [], 'device_accepted': False}
    core = args.core_build.resolve()
    core_report = load_build(core, record)
    core_header = core / core_report['compile_header']['path']
    if digest(core_header) != core_report['compile_header']['sha256']:
        raise ValueError('Source core header differs')
    headers = [core_header]
    for directory in args.core_extension_build:
        report = load_build(directory, record)
        headers += [directory.resolve() / name for name in report['artifacts'] if name.endswith('.classes.jar')]
    support = args.support_build.resolve()
    load_build(support, record)
    headers += [support / n for n in ['annotations.jar', 'guava-android.jar', 'protobuf-lite.jar']]
    load_build(args.experimental_annotations_build, record)
    headers += [args.experimental_annotations_build.resolve() / 'annotation-experimental.jar']
    aidl = args.aidl_build.resolve()
    aidl_report = load_build(aidl, record)
    files = [(root / s, 'source') for s in aidl_report['sources'] if s.endswith('.java')]
    files += [(aidl / s, 'aidl') for s in aidl_report['generated'] if s.endswith('.java')]
    for kind in ['flags', 'module', 'hidl', 'misc', 'cronet', 'schema', 'resources']:
        directory = getattr(args, kind + '_build').resolve()
        report = load_build(directory, record)
        for name in report['artifacts']:
            if not name.endswith('.java'):
                continue
            if kind == 'schema' and not name.startswith('audio-schema/'):
                continue
            if kind == 'cronet' and not name.startswith('java/'):
                continue
            files.append((directory / name, kind))
    output.mkdir(parents=True)
    port_file = ROOT / 'framework-source-ports.json'
    source_ports = json.loads(port_file.read_text())['files']
    record['source_ports_sha256'] = digest(port_file)
    applied_ports = set()
    transformed = []
    for path, kind in files:
        original = path
        text = path.read_text()
        content = text
        record['inputs'][str(path)] = digest(path)
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else None
        if relative in source_ports:
            for before, after in source_ports[relative].items():
                if content.count(before) != 1:
                    raise ValueError('Framework source port changed: ' + relative + ': ' + before)
                content = content.replace(before, after)
            applied_ports.add(relative)
        if kind == 'cronet' or path.is_relative_to(root / 'external-cronet'):
            content = content.replace('com.google.protobuf', 'com.android.framework.protobuf')
        if kind == 'module':
            prefix = ('android.internal.framework.protobuf' if 'libaconfig_java_proto_nano' in path.parts
                      else 'com.android.framework.protobuf')
            content = content.replace('com.google.protobuf', prefix)
            if 'perfetto_trace_javastream_protos' in path.parts:
                content = content.replace('perfetto.protos', 'android.internal.perfetto.protos')
        if content != text:
            target = output / 'repacked-source' / digest(path) / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            record['transforms'][str(target.relative_to(output))] = {
                'source': str(path), 'source_sha256': digest(path), 'sha256': digest(target)}
            path = target
        transformed.append((path, original, kind))
    if applied_ports != set(source_ports):
        raise ValueError('Framework source ports not applied: ' + str(set(source_ports) - applied_ports))
    import sys
    sys.path.insert(0, str(workspace / 'westlake/tools'))
    from aosp_blueprint import Sources, index
    modules, errors = index(root)
    if errors:
        raise ValueError('Blueprint parse failures: ' + str(errors))
    groups = Sources(root, modules)
    for prefix in ['com.android.framework.protobuf.nano', 'android.internal.framework.protobuf.nano']:
        for original in groups.files('libprotobuf-java-nano'):
            if original.suffix != '.java' or original.name == 'package-info.java':
                continue
            path = output / 'protobuf-runtimes' / prefix / original.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(original.read_text().replace('com.google.protobuf.nano', prefix))
            record['inputs'][str(original)] = digest(original)
            record['transforms'][str(path.relative_to(output))] = {
                'source': str(original), 'source_sha256': digest(original), 'sha256': digest(path)}
            transformed.append((path, original, 'protobuf-runtime'))
    identities, origins = {}, {}
    for path, original, kind in sorted(set(transformed)):
        reason = None
        if original.is_relative_to(root / 'protobuf/java/core/src/main/java'):
            reason = 'libprotobuf-java-lite is owned by the separately source-built support JAR'
        if (original.name == 'GEN_JNI.java' and kind == 'cronet'
                and 'cronet_aml_components_cronet_android_cronet_jni_registration__java' not in original.parts):
            reason = 'upstream per-library remove-gen-jni-jarjar-rules; final registration owns implementation'
        if not path.read_text().strip():
            reason = 'declaration-only AIDL; implementation is a Java source'
        if reason:
            record['excluded_sources'][str(original)] = reason
            continue
        match = re.search(r'(?m)^\s*package\s+([\w.]+)\s*;', path.read_text())
        if not match:
            raise ValueError('Missing source package: ' + str(path))
        identity = match[1].replace('.', '/') + '/' + path.stem
        if identity in core_report['class_ownership']:
            relative = str(original.relative_to(root))
            if core_report['inputs'].get(relative) != digest(original):
                raise ValueError('Core/framework source ownership differs: ' + identity)
            record['excluded_sources'][str(original)] = 'identical source already owned by core boot JAR'
            continue
        if identity in identities:
            if identities[identity].read_bytes() != path.read_bytes():
                raise ValueError('Different source definitions: ' + identity)
            record['duplicate_identical_sources'].setdefault(identity, []).append(str(original))
            continue
        identities[identity] = path
        origins[identity] = {'source': str(original), 'kind': kind, 'compiled_sha256': digest(path)}
    module = root / 'libcore/luni/src/module/java/module-info.java'
    record['inputs'][str(module)] = digest(module)
    kept = sorted(identities.values()) + [module]
    patch_roots = [workspace, output] + [getattr(args, kind + '_build').resolve()
                   for kind in ['aidl', 'flags', 'module', 'hidl', 'misc', 'cronet', 'schema', 'resources']]
    flags = ['-source', '17', '-target', '17', '--system', 'none', '--patch-module',
             'java.base=' + ':'.join(map(str, headers + patch_roots)),
             '-encoding', 'UTF-8', '-g:source', '-processorpath',
             ':'.join(str(support / n) for n in ['safeparcel-processor.jar', 'guava-host.jar', 'annotations.jar']),
             '-processor', 'android.app.appsearch.safeparcel.SafeParcelProcessor',
             '-s', str(output / 'safeparcel-generated'), '-XDstringConcat=inline',
             '-Xmaxerrs', '1000', '-Xmaxwarns', '5', '-d', str(output / 'classes'), *map(str, kept)]
    response = output / 'javac.args'
    response.write_text('\n'.join(json.dumps(s) for s in flags) + '\n')
    command = [str(java / 'bin/javac'), '-J-Xmx7g', '@' + str(response)]
    record['commands'].append(command)
    env = {k: v for k, v in os.environ.items() if k not in
           ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH']}
    env.update(LC_ALL='C', TZ='UTC')
    with (output / 'javac.log').open('x') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Framework compilation failed; see ' + str(output / 'javac.log'))
    for path in sorted((output / 'safeparcel-generated').rglob('*.java')):
        match = re.search(r'(?m)^\s*package\s+([\w.]+)\s*;', path.read_text())
        identity = match[1].replace('.', '/') + '/' + path.stem
        if identity in origins:
            raise ValueError('SafeParcel source collision: ' + identity)
        origins[identity] = {'source': str(path.relative_to(output)), 'kind': 'safeparcel-generated',
                             'compiled_sha256': digest(path)}
    entries = {}
    for path in sorted((output / 'classes').rglob('*.class')):
        data = path.read_bytes()
        identity, source_file = class_source(data)
        if identity == 'module-info':
            continue
        source_identity = identity.rsplit('/', 1)[0] + '/' + source_file.removesuffix('.java')
        if source_identity not in origins:
            raise ValueError('Unowned framework class: ' + identity + ' from ' + source_file)
        if identity in core_report['class_ownership'] or identity in record['class_ownership']:
            raise ValueError('Duplicate runtime class ownership: ' + identity)
        record['class_ownership'][identity] = origins[source_identity]
        entries[identity + '.class'] = data
    # Keep source-owned Java resources (notably libphonenumber metadata).
    # Java and build metadata are never copied as runtime resources.
    for name in aidl_report['collected_modules']:
        if name not in modules:
            continue
        spec = groups.module(name)
        base = root / Path(spec['file']).parent
        if spec['fields'].get('java_resources'):
            raise ValueError('Unimplemented explicit Java resource list: ' + name)
        for relative in spec['fields'].get('java_resource_dirs', []):
            directory = base / relative
            for path in sorted(directory.rglob('*')):
                if not path.is_file() or path.suffix in {'.java', '.html', '.class', '.jar'}:
                    continue
                key = str(path.relative_to(directory))
                if key in entries and entries[key] != path.read_bytes():
                    raise ValueError('Different duplicate Java resource: ' + key)
                entries[key] = path.read_bytes()
                record['resources'][key] = {'source': str(path), 'sha256': digest(path)}
    jar = output / 'framework-unrelocated.classes.jar'
    write_jar(jar, entries)
    record['artifacts'] = {jar.name: {'sha256': digest(jar), 'bytes': jar.stat().st_size}}
    record['source_count'] = len(kept)
    record['safeparcel_source_count'] = sum(v['kind'] == 'safeparcel-generated' for v in origins.values())
    record['definitions'] = {p: digest(root / p) for p in sorted(groups.definitions)}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('FRAMEWORK_JAVA_SOURCE_PASS', len(kept), len(record['class_ownership']), digest(jar), flush=True)


if __name__ == '__main__':
    main()
