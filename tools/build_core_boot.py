#!/usr/bin/env python3
"""Generate an ARM64 core boot image from verified source-build outputs.

Optional source Java extensions join the image; the framework image is separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

NAMES = ['core-oj', 'core-libart', 'core-icu4j', 'okhttp']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_jars(core, extensions):
    jars, owners = {}, set()
    for directory in [core, *extensions]:
        report = json.loads((directory / 'artifacts.json').read_text())
        if not report.get('dex_class_ownership') or report.get('board_jar_inputs') != []:
            raise ValueError('Java build lacks source/class ownership verification: ' + str(directory))
        definitions = set(report['dex_class_ownership'])
        if owners & definitions:
            raise ValueError('Duplicate core/extension DEX definitions')
        owners.update(definitions)
        for name in set(report['dex_class_ownership'].values()):
            if name not in [*NAMES, 'conscrypt', 'bouncycastle', 'apache-xml'] or name in jars:
                raise ValueError('Unexpected/duplicate core library: ' + name)
            path = directory / (name + '.jar')
            if not path.resolve().is_relative_to(directory) or sha(path) != report['artifacts'][path.name]['sha256']:
                raise ValueError('JAR differs from source report: ' + str(path))
            jars[name] = path
    order = ['core-oj', 'core-libart', 'core-icu4j', 'conscrypt', 'okhttp', 'bouncycastle', 'apache-xml']
    if any(name not in jars for name in NAMES):
        raise ValueError('Missing source core JAR')
    return {name: jars[name] for name in order if name in jars}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-build', type=Path, required=True)
    parser.add_argument('--core-build', type=Path, required=True)
    parser.add_argument('--extension-build', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    host, core, output = args.host_build.resolve(), args.core_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    host_report = json.loads((host / 'artifacts.json').read_text())
    binary = host / host_report['artifact']['path']
    if not binary.resolve().is_relative_to(host) or sha(binary) != host_report['artifact']['sha256']:
        raise ValueError('Host dex2oat differs from its source-build report')
    jars = source_jars(core, [p.resolve() for p in args.extension_build])
    physical = list(jars.values())
    logical = ['/system/framework/' + path.name for path in physical]
    output.mkdir(parents=True)
    command = [str(binary), '--runtime-arg', '-Xbootclasspath:' + ':'.join(map(str, physical)),
               '--runtime-arg', '-Xbootclasspath-locations:' + ':'.join(logical)]
    for path, location in zip(physical, logical):
        command += ['--dex-file=' + str(path), '--dex-location=' + location]
    command += ['--instruction-set=arm64', '--compiler-filter=verify', '--base=0x70000000',
                '--image=' + str(output / 'boot.art'), '--oat-file=' + str(output / 'boot.oat'),
                '--oat-location=/system/framework/arm64/boot.oat', '--android-root=' + str(output),
                '--runtime-arg', '-Xms64m', '--runtime-arg', '-Xmx256m', '-j1']
    env = dict(os.environ, SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    with (output / 'build.log').open('x') as log:
        subprocess.run(command, check=True, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    artifacts = {}
    for stem in ['boot', *['boot-' + name for name in list(jars)[1:]]]:
        for suffix in ['.art', '.oat', '.vdex']:
            path = output / (stem + suffix)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Missing/empty core image artifact: ' + path.name)
            artifacts[path.name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    record = {'scope': 'ARM64 core image source build; not full framework or device acceptance',
              'command': command, 'dex2oat_sha256': sha(binary),
              'jars': {path.name: sha(path) for path in physical}, 'artifacts': artifacts,
              'classpath_order': list(jars),
              'complete_boot_classpath': False, 'device_accepted': False}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('CORE_BOOT_IMAGE_SOURCE_BUILD_PASS', len(artifacts))


if __name__ == '__main__':
    main()
