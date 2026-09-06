#!/usr/bin/env python3
"""Generate an ARM64 core boot image from verified source-build outputs.

This is the four-JAR core image, not the complete Westlake framework image.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-build', type=Path, required=True)
    parser.add_argument('--core-build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    host, core, output = args.host_build.resolve(), args.core_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    host_report = json.loads((host / 'artifacts.json').read_text())
    core_report = json.loads((core / 'artifacts.json').read_text())
    binary = host / host_report['artifact']['path']
    if not binary.resolve().is_relative_to(host) or sha(binary) != host_report['artifact']['sha256']:
        raise ValueError('Host dex2oat differs from its source-build report')
    physical = [core / (name + '.jar') for name in NAMES]
    logical = ['/system/framework/' + path.name for path in physical]
    for path in physical:
        if sha(path) != core_report['artifacts'][path.name]['sha256']:
            raise ValueError('Core JAR differs from its source-build report: ' + path.name)
    if not core_report.get('dex_class_ownership') or core_report.get('board_jar_inputs') != []:
        raise ValueError('Core build lacks runtime-class/source-input verification')
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
    for stem in ['boot', 'boot-core-libart', 'boot-core-icu4j', 'boot-okhttp']:
        for suffix in ['.art', '.oat', '.vdex']:
            path = output / (stem + suffix)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Missing/empty core image artifact: ' + path.name)
            artifacts[path.name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    record = {'scope': 'ARM64 core image source build; not full framework or device acceptance',
              'command': command, 'dex2oat_sha256': sha(binary),
              'jars': {path.name: sha(path) for path in physical}, 'artifacts': artifacts,
              'complete_boot_classpath': False, 'device_accepted': False}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('CORE_BOOT_IMAGE_SOURCE_BUILD_PASS', len(artifacts))


if __name__ == '__main__':
    main()
