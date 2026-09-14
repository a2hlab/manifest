#!/usr/bin/env python3
"""Package pinned Android ICU and optional complete default font assets."""
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from bootstrap_sdk import ROOT, digest
from rebuild import verify_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fonts', action='store_true')
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'core-sources.lock.json')
    source = workspace / 'android-source/icu/icu4c/source/stubdata/icudt75l.dat'
    destination = 'i18n/etc/icu/' + source.name
    target = output / destination
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    report = {'scope': 'pinned ICU data asset; packaged without recompilation',
              'sources': sources, 'inputs': {str(source.relative_to(workspace)): digest(source)},
              'artifacts': {destination: {'sha256': digest(target), 'bytes': target.stat().st_size}}}
    if args.fonts:
        report['sources'] += verify_sources(workspace, ROOT / 'framework-sources.lock.json')
        report['sources'] += verify_sources(workspace, ROOT / 'framework-fonts.lock.json')
        inventory = ROOT / 'framework-font-assets.json'
        spec = json.loads(inventory.read_text())
        report['font_inventory_sha256'] = digest(inventory)
        report['scope'] = 'pinned ICU and Android 15 default font assets; packaged without recompilation'

        def install(relative, destination):
            source = workspace / relative
            if Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError('Outside font source: ' + relative)
            target = output / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            report['inputs'][relative] = digest(source)
            report['artifacts'][destination] = {'sha256': digest(target), 'bytes': target.stat().st_size}

        wanted = set()
        for name, relative in spec['configs'].items():
            wanted.update(node.text.strip() for node in ET.parse(workspace / relative).iter('font'))
            install(relative, 'etc/' + name)
        if not wanted.issubset(spec['fonts']):
            raise ValueError('Font configuration has unowned assets: ' + str(wanted - spec['fonts'].keys()))
        for name, entry in spec['fonts'].items():
            if Path(name).name != name:
                raise ValueError('Invalid installed font filename: ' + name)
            install(entry['source'], 'fonts/' + name)
            blueprint = workspace / entry['blueprint']
            report['inputs'][entry['blueprint']] = digest(blueprint)
        # Materialize the upstream compatibility aliases as identical files so
        # staging does not depend on filesystem symlink behavior.
        for name, original in spec['aliases'].items():
            if Path(name).name != name or original not in spec['fonts']:
                raise ValueError('Invalid font alias: ' + name)
            install(spec['fonts'][original]['source'], 'fonts/' + name)
        report['font_count'] = len(spec['fonts'])
        report['font_aliases'] = spec['aliases']
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('SOURCE_RUNTIME_DATA_PACKAGED', len(report['artifacts']), 'assets', flush=True)


if __name__ == '__main__':
    main()
