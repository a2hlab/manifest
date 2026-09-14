#!/usr/bin/env python3
"""Compose verified source DSOs, with explicit version replacements recorded."""
import argparse
import json
from pathlib import Path
import shutil
from bootstrap_sdk import digest


def compose(builds, replacements, output):
    if output.exists():
        raise ValueError('Output already exists')
    files, used, changes, prerequisites = {}, set(), {}, {}
    for directory in builds:
        directory = directory.resolve()
        report = json.loads((directory / 'artifacts.json').read_text())
        if report.get('errors') or report.get('deployable') is False:
            raise ValueError('Failed or link-only build: ' + str(directory))
        prerequisites[str(directory)] = digest(directory / 'artifacts.json')
        for name, entry in report['artifacts'].items():
            if not name.endswith('.so'):
                continue
            path = directory / name
            if Path(name).name != name or not path.resolve().is_relative_to(directory):
                raise ValueError('Outside runtime artifact: ' + name)
            if digest(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
                raise ValueError('Changed runtime artifact: ' + str(path))
            if name in files and files[name][1]['sha256'] != entry['sha256']:
                if name not in replacements or name in used:
                    raise ValueError('Undeclared or repeated replacement: ' + name)
                used.add(name)
                changes[name] = {'from': str(files[name][0]), 'from_sha256': files[name][1]['sha256'],
                                 'to': str(path), 'to_sha256': entry['sha256']}
            files[name] = (path, entry)
    if used != replacements or not files:
        raise ValueError('Unused replacement or empty runtime')
    output.mkdir(parents=True)
    record = {'scope': 'source runtime composition; device acceptance pending', 'prerequisites': prerequisites,
              'replacements': changes, 'artifacts': {}, 'origins': {}, 'errors': []}
    for name, (path, entry) in sorted(files.items()):
        target = output / name
        shutil.copyfile(path, target)
        if digest(target) != entry['sha256']:
            raise ValueError('Copied runtime artifact differs: ' + name)
        record['artifacts'][name] = entry
        record['origins'][name] = str(path)
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, action='append', required=True)
    p.add_argument('--replace', action='append', default=[])
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    report = compose(args.build, set(args.replace), args.out.absolute())
    print('NATIVE_RUNTIME_COMPOSED', len(report['artifacts']))


if __name__ == '__main__':
    main()
