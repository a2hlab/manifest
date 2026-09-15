#!/usr/bin/env python3
"""Generate the declared Westlake process boot image from source-built Java JARs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from build_core_boot import sha, source_jars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['host-build', 'core-build', 'framework-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--extension-build', type=Path, action='append', required=True)
    args = parser.parse_args()
    host, output = args.host_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    host_report = json.loads((host / 'artifacts.json').read_text())
    binary = host / host_report['artifact']['path']
    if not binary.resolve().is_relative_to(host) or sha(binary) != host_report['artifact']['sha256']:
        raise ValueError('dex2oat differs from source build')
    jars = source_jars(args.core_build.resolve(), [p.resolve() for p in args.extension_build])
    if len(jars) != 7:
        raise ValueError('The framework profile requires all seven core runtime libraries')
    owners = set()
    for directory in [args.core_build, *args.extension_build]:
        owners.update(json.loads((directory / 'artifacts.json').read_text())['dex_class_ownership'])
    framework = args.framework_build.resolve()
    report = json.loads((framework / 'artifacts.json').read_text())
    if report['board_jar_inputs'] != [] or set(report['dex_class_ownership'].values()) != {'framework', 'adapter-runtime-bcp'}:
        raise ValueError('Unexpected process framework ownership')
    if owners.intersection(report['dex_class_ownership']):
        raise ValueError('Duplicate core/framework boot classes')
    for name in ['framework', 'adapter-runtime-bcp']:
        path = framework / (name + '.jar')
        if sha(path) != report['artifacts'][path.name]['sha256']:
            raise ValueError('Framework JAR differs from source report: ' + name)
        jars[name] = path
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
                '--runtime-arg', '-Xms64m', '--runtime-arg', '-Xmx768m', '-j4']
    env = dict(os.environ, SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    with (output / 'build.log').open('x') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode:
        raise RuntimeError('Framework image generation failed; see ' + str(output / 'build.log'))
    artifacts = {}
    for stem in ['boot', *['boot-' + name for name in list(jars)[1:]]]:
        for suffix in ['.art', '.oat', '.vdex']:
            path = output / (stem + suffix)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Missing/empty image artifact: ' + path.name)
            artifacts[path.name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    record = {'scope': 'source boot image for declared Westlake process profile; native/device acceptance pending',
              'command': command, 'dex2oat_sha256': sha(binary), 'artifacts': artifacts,
              'jars': {path.name: sha(path) for path in physical}, 'classpath_order': list(jars),
              'device_accepted': False}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('FRAMEWORK_BOOT_IMAGE_SOURCE_PASS', len(jars), len(artifacts), flush=True)


if __name__ == '__main__':
    main()
