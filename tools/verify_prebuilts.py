#!/usr/bin/env python3
"""Verify every checked-in prebuilt against its sources.lock.json entry.

A recorded hash that nothing compares against is decoration. This is the
comparison: it is called from rebuild.py before any profile runs, so a prebuilt
that has been swapped, truncated or silently regenerated stops the build instead
of reaching a device.

Prebuilts live in a separate top-level `prebuilts` array rather than in
`projects`, because `projects` entries are Git checkouts: fetch_sources.py
requires each one to carry an a2hlab clone URL and a 40-character revision, and
a jar has neither. Keeping them apart also keeps the two ideas apart -- a
project is fetched and can be re-derived from history, a prebuilt is a build
output someone produced once and has to be reproduced through its recipe.

Every entry names that recipe. The point of the pairing is that "where did this
binary come from" has an answer in the tree, not in someone's shell history.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def inside(relative):
    """Resolve a lock-relative path, refusing anything that leaves the tree.

    Both sides are resolved before comparing. Resolving only the target and
    comparing against a raw ROOT rejects every path whenever the checkout sits
    behind a symlink -- on macOS /var is a link to /private/var, so a tree under
    /var/folders fails the containment test against its own root.
    """
    root = Path(ROOT).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Prebuilt path escapes the manifest: ' + relative)
    return target


def verify(lock=None):
    """Check every prebuilt. Returns the records; raises on the first mismatch."""
    lock = lock or (ROOT / 'sources.lock.json')
    entries = json.loads(lock.read_text()).get('prebuilts', [])
    verified = []
    for entry in entries:
        path = inside(entry['path'])
        if not path.is_file():
            raise ValueError('Missing prebuilt: ' + entry['path'])

        size = path.stat().st_size
        if size != entry['bytes']:
            raise ValueError('Prebuilt size differs from lock: %s (%d, expected %d)'
                             % (entry['path'], size, entry['bytes']))

        actual = digest(path)
        if actual != entry['sha256']:
            raise ValueError('Prebuilt content differs from lock: %s (%s)'
                             % (entry['path'], actual))

        # A prebuilt whose recipe is absent is exactly the thing this file
        # exists to prevent: a binary nobody can regenerate.
        recipe = inside(entry['recipe'])
        if not recipe.is_file():
            raise ValueError('Prebuilt %s names a recipe that is not in the tree: %s'
                             % (entry['path'], entry['recipe']))

        print('VERIFIED_PREBUILT', entry['path'], actual, flush=True)
        verified.append(dict(entry, verified_sha256=actual))
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    args = parser.parse_args()
    records = verify(args.lock)
    if not records:
        print('no prebuilts declared', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
