#!/usr/bin/env python3
"""Fetch exact revisions plus hash-checked patches into new workspace directories."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read_lock(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if not path.is_relative_to(ROOT) or path in seen:
        raise ValueError('Lock outside manifest or recursive include: ' + str(path))
    seen.add(path)
    data = json.loads(path.read_text())
    entries = list(data['projects'])
    for include in data.get('includes', []):
        entries += read_lock(path.parent / include, seen)
    names = [entry['path'] for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate project path in lock')
    return entries


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1'))


def fetch(entry, workspace):
    relative = PurePosixPath(entry['path'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Invalid checkout path')
    if not re.fullmatch('[0-9a-f]{40}', entry['revision']):
        raise ValueError('A full 40-character source revision is required')
    if not re.fullmatch(r'https://github\.com/a2hlab/[A-Za-z0-9_.-]+\.git', entry['url']):
        raise ValueError('Active dependencies must be checked in under a2hlab')
    target = workspace.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(workspace.resolve()):
        raise ValueError('Checkout escapes workspace')
    if target.exists():
        raise ValueError('Refusing to overwrite existing source directory: ' + str(target))
    patch = None
    if entry.get('patch'):
        patch = (ROOT / entry['patch']).resolve()
        if not patch.is_relative_to(ROOT):
            raise ValueError('Patch outside manifest')
        if hashlib.sha256(patch.read_bytes()).hexdigest() != entry['patch_sha256']:
            raise ValueError('Patch digest mismatch: ' + str(patch))
    target.mkdir(parents=True)
    print('FETCH', entry['path'], entry['revision'], flush=True)
    run('git', 'init', '-q', str(target))
    run('git', 'remote', 'add', 'origin', entry['url'], cwd=target)
    sparse = entry.get('sparse_paths', [])
    for name in sparse:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('Invalid sparse source directory: ' + name)
    if sparse:
        run('git', 'sparse-checkout', 'init', '--cone', cwd=target)
        run('git', 'sparse-checkout', 'set', *sparse, cwd=target)
    run('git', 'fetch', '--depth=1', '--no-tags', *(['--filter=blob:none'] if sparse else []),
        'origin', entry['revision'], cwd=target)
    run('git', 'checkout', '-q', '--detach', entry['revision'], cwd=target)
    if entry.get('lfs'):
        run('git', 'lfs', 'install', '--local', cwd=target)
        run('git', 'lfs', 'pull', 'origin', cwd=target)
        run('git', 'lfs', 'fsck', cwd=target)
    if patch:
        run('git', 'apply', '--index', str(patch), cwd=target)
    record = dict(entry, tree=run('git', 'write-tree', cwd=target).decode().strip())
    if entry.get('tree') and record['tree'] != entry['tree']:
        raise ValueError('Patched checkout tree differs from lock: ' + entry['path'])
    (target / '.git/a2hlab-source.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    print('READY', entry['path'], record['tree'], flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    entries = read_lock(args.lock)
    workspace = args.workspace.absolute()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(lambda entry: fetch(entry, workspace), entries))
    (workspace / ('resolved-' + args.lock.name)).write_text(json.dumps(records, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
