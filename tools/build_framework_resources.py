#!/usr/bin/env python3
"""Compile Android framework resources from locked sources using pinned AAPT2."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
from bootstrap_sdk import ROOT, digest
from rebuild import verify_sources
from install_android_compilers import verify_android_compilers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--flag-build', type=Path, required=True,
                        help='Source framework flag generation report for the same release')
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'framework-sources.lock.json')
    compiler, compiler_tree = verify_android_compilers(workspace)
    aapt2 = compiler / 'aapt2'
    base = workspace / 'android-source/frameworks-base/core/res'
    output.mkdir(parents=True)
    generated = output / 'generated-res'
    (generated / 'raw').mkdir(parents=True)
    (generated / 'values').mkdir()
    record = {'scope': 'source framework resources; not Java framework or UI acceptance',
              'sources': sources, 'compiler_tree_sha256': compiler_tree,
              'aapt2_sha256': digest(aapt2), 'inputs': {}, 'commands': [], 'artifacts': {},
              'board_apk_inputs': [], 'device_accepted': False}
    env = dict(os.environ, SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    def checked(path):
        if not path.is_file() or not path.resolve().is_relative_to(base):
            raise ValueError('Missing/outside resource input: ' + str(path))
        record['inputs'][path.relative_to(base).as_posix()] = digest(path)
        return path
    def run(name, command):
        command = list(map(str, command))
        record['commands'].append(command)
        with (output / (name + '.log')).open('x') as log:
            subprocess.run(command, check=True, env=env, stdout=log, stderr=subprocess.STDOUT)
    for path in sorted((base / 'res').rglob('*')):
        if path.is_file():
            checked(path)
    remote = output / 'remote-colors'
    remote.mkdir()
    for name in ['public', 'colors']:
        run('compile-remote-' + name, [aapt2, 'compile', checked(base / 'remote_color_resources_res/values' / (name + '.xml')), '-o', remote])
    run('link-remote', [aapt2, 'link', '-o', remote / 'remote-color-resources.apk',
        '--manifest', checked(base / 'RemoteThemeColorsAndroidManifest.xml'),
        remote / 'values_public.arsc.flat', remote / 'values_colors.arsc.flat'])
    with zipfile.ZipFile(remote / 'remote-color-resources.apk') as packed:
        (generated / 'raw/remote_views_color_resources.arsc').write_bytes(packed.read('resources.arsc'))
    (generated / 'values/symbols.xml').write_bytes(checked(base / 'remote_color_resources_res/symbols.xml').read_bytes())
    run('compile-framework', [aapt2, 'compile', '--dir', base / 'res', '--pseudo-localize', '-o', output / 'compiled-res.zip'])
    run('compile-generated', [aapt2, 'compile', '--dir', generated, '-o', output / 'generated-res.zip'])
    manifest = checked(base / 'AndroidManifest.xml')
    # Resources and Java consume exactly the same pinned release flag values.
    flag_names = sorted({name.removeprefix('!') for name in
                         re.findall(r'android:featureFlag="([^"\n]+)"', manifest.read_text())})
    flag_report_path = args.flag_build.resolve() / 'artifacts.json'
    flag_report = json.loads(flag_report_path.read_text())
    for name, entry in flag_report['artifacts'].items():
        path = args.flag_build.resolve() / name
        if not path.resolve().is_relative_to(args.flag_build.resolve()) or digest(path) != entry['sha256']:
            raise ValueError('Source flag artifact differs: ' + name)
    flags = {name: flag_report['flags'][name] for name in flag_names}
    if not all(type(value) is bool for value in flags.values()):
        raise ValueError('Resource feature flags must be booleans')
    record['aconfig_report_sha256'] = digest(flag_report_path)
    record['release'] = flag_report['release']
    record['manifest_feature_flags'] = flags
    run('link-framework', [aapt2, 'link', '-o', output / 'framework-res.apk',
        '--manifest', manifest,
        '--private-symbols', 'com.android.internal',
        '--no-auto-version', '--auto-add-overlay', '--enable-sparse-encoding',
        '--min-sdk-version', '35', '--target-sdk-version', '35',
        '--version-code', '35', '--version-name', '15', '--product', 'default',
        '--feature-flags', ','.join(name + '=' + str(flags[name]).lower() for name in flag_names),
        '--java', output / 'java', '--output-text-symbols', output / 'R.txt',
        '-R', output / 'compiled-res.zip', '-R', output / 'generated-res.zip'])
    apk = output / 'framework-res.apk'
    with zipfile.ZipFile(apk) as packed:
        if 'resources.arsc' not in packed.namelist() or any(n.endswith('.dex') for n in packed.namelist()):
            raise ValueError('Invalid framework resource-only APK')
    required = ['framework-res.apk', 'R.txt', 'java/android/R.java',
                'java/android/Manifest.java', 'java/com/android/internal/R.java']
    for name in required:
        path = output / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing framework resource output: ' + name)
        record['artifacts'][name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    run('dump-resources', [aapt2, 'dump', 'resources', apk])
    (output / 'artifacts.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    print('FRAMEWORK_RESOURCES_SOURCE_BUILD_PASS', len(record['inputs']), digest(apk))


if __name__ == '__main__':
    main()
