#!/usr/bin/env python3
"""Rehash two isolated builds and require identical complete artifact inventories."""
import argparse
import json
from pathlib import Path, PurePosixPath
from bootstrap_sdk import digest


def inventory(root):
    root = root.resolve()
    data = json.loads((root / 'artifacts.json').read_text())
    declared = data.get('artifacts', data)
    if not declared:
        raise ValueError('Empty artifact inventory')
    actual = {}
    for name, entry in declared.items():
        part = PurePosixPath(name)
        if part.is_absolute() or '..' in part.parts:
            raise ValueError('Unsafe artifact path: ' + name)
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError('Artifact symlink escapes build root')
        actual[name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
        if any(actual[name][key] != entry[key] for key in ['sha256', 'bytes']):
            raise ValueError('Recorded artifact no longer matches: ' + str(path))
    return actual


def compare(first, second):
    left, right = inventory(first), inventory(second)
    if left != right:
        changed = sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))
        raise ValueError('Artifact reproduction mismatch: ' + ', '.join(changed))
    return {'result': 'byte-identical', 'artifacts': left,
            'scope': 'Source artifact reproduction only; not device acceptance or performance parity'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = compare(args.first, args.second)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x') as stream:
            stream.write(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
