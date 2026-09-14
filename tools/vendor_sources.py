#!/usr/bin/env python3
"""One-time publisher of exact public dependency trees into private a2hlab repos.

Upstream history is not rewritten or pushed. Each dependency gets an initial
snapshot commit with the exact original Git tree and original licenses. The
original URL/revision are retained in the manifest. Local patches remain separate.
"""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from pathlib import Path
import subprocess
import tarfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, GIT_AUTHOR_DATE='2026-09-05T12:00:00Z',
           GIT_COMMITTER_DATE='2026-09-05T12:00:00Z', GIT_TERMINAL_PROMPT='0')


def run(*command, cwd=None):
    return subprocess.check_output([str(x) for x in command], cwd=cwd, env=ENV, stderr=subprocess.STDOUT)


@contextmanager
def exact_archive_attributes(source):
    # git archive otherwise honors export-ignore and eol conversions, silently
    # omitting files or changing bytes in embedded third-party source trees.
    path = Path(run('git', 'rev-parse', '--git-path', 'info/attributes', cwd=source).decode().strip())
    if not path.is_absolute():
        path = source / path
    saved = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((saved or b'') + b'\n* -export-ignore -export-subst -text\n')
    try:
        yield
    finally:
        if saved is None:
            path.unlink()
        else:
            path.write_bytes(saved)


def publish(entry, workspace, destination):
    source = workspace / entry['path']
    if run('git', 'rev-parse', 'HEAD', cwd=source).decode().strip() != entry['revision']:
        raise ValueError('Original checkout revision differs: ' + entry['path'])
    name = 'dep-' + entry['path'].removeprefix('upstream/').replace('aosp-11', 'aosp11').replace('/', '-')
    name = re.sub(r'[^A-Za-z0-9_.-]+', '-', name)
    target = destination / name
    record = destination / (name + '.json')
    if record.is_file():
        saved = json.loads(record.read_text())
        remote = run('git', 'ls-remote', saved['url'], 'refs/heads/main').decode().split()[0]
        if remote != saved['revision'] or saved['upstream']['revision'] != entry['revision']:
            raise ValueError('Previously published snapshot drift: ' + name)
        print('VERIFIED_EXISTING_SNAPSHOT', name, flush=True)
        return saved
    if target.exists():
        raise ValueError('Refusing to overwrite local snapshot: ' + str(target))
    existing = subprocess.run(['gh', 'api', 'repos/a2hlab/' + name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if existing.returncode == 0:
        raise ValueError('Refusing to change existing org repository: ' + name)
    listing = run('git', 'ls-tree', '-r', '-l', 'HEAD', cwd=source).decode()
    gitlinks = {}
    for row in listing.splitlines():
        parts = row.split(None, 4)
        if parts[0] == '160000':
            relative = parts[4]
            if entry.get('unmaterialized_gitlinks', {}).get(relative) != parts[2]:
                raise ValueError('Nested gitlink needs explicit vendoring: ' + row)
            path = source / relative
            if path.is_dir() and any(path.iterdir()):
                raise ValueError('Declared unmaterialized gitlink contains files: ' + relative)
            gitlinks[relative] = parts[2]
        if (parts[2] != '-' and parts[3].isdigit() and int(parts[3]) >= 100 * 1024 * 1024
                and parts[4] not in entry.get('lfs_paths', [])):
            raise ValueError('Oversized source blob needs LFS review: ' + row)
    target.mkdir(parents=True)
    # Preserve cross-project test symlinks as Git symlink blobs. Do not follow
    # or read their targets, and create them only after regular file extraction.
    links = []
    with exact_archive_attributes(source):
        archive = subprocess.Popen(['git', '-C', str(source), 'archive', '--format=tar', 'HEAD'], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode='r|') as packed:
            for member in packed:
                relative = Path(member.name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe source path: ' + member.name)
                if member.issym():
                    if Path(member.linkname).is_absolute():
                        raise ValueError('Absolute source symlink needs review: ' + member.name)
                    links.append((target / relative, member.linkname))
                else:
                    packed.extract(member, target, filter='data')
        archive.stdout.close()
        if archive.wait() != 0:
            raise ValueError('Source export failed')
    for path, link in links:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(link)
    run('git', 'init', '-q', '-b', 'main', cwd=target)
    run('git', 'config', 'user.name', 'ymote', cwd=target)
    run('git', 'config', 'user.email', '151983+ymote@users.noreply.github.com', cwd=target)
    # Preserve upstream blob bytes even when a project has eol=lf attributes
    # for CRLF files already committed upstream.
    (target / '.git/info/attributes').write_text('* -text\n')
    run('git', 'add', '-f', '--', '.', cwd=target)
    for relative, revision in gitlinks.items():
        run('git', 'update-index', '--add', '--cacheinfo', '160000,' + revision + ',' + relative, cwd=target)
    tree = run('git', 'write-tree', cwd=target).decode().strip()
    if tree != run('git', 'rev-parse', 'HEAD^{tree}', cwd=source).decode().strip():
        raise ValueError('Snapshot changed original source tree: ' + name)
    lfs_records = {}
    if entry.get('lfs_paths'):
        run('git', 'lfs', 'install', '--local', cwd=target)
        for relative in entry['lfs_paths']:
            path = target / relative
            if not path.resolve().is_relative_to(target.resolve()) or not path.is_file():
                raise ValueError('Missing/outside explicit LFS input: ' + relative)
            with path.open('rb') as stream:
                lfs_records[relative] = {'sha256': hashlib.file_digest(stream, 'sha256').hexdigest(),
                                         'bytes': path.stat().st_size}
            run('git', 'lfs', 'track', '--filename', relative, cwd=target)
        run('git', 'add', '-f', '.gitattributes', cwd=target)
        run('git', 'add', '--renormalize', '.', cwd=target)
    message = ('Vendor dependency snapshot for repository-only Westlake rebuild\n\n'
               'Upstream: ' + entry['url'] + '\nRevision: ' + entry['revision'] + '\nTree: ' + tree)
    run('git', 'commit', '-q', '-m', message, cwd=target)
    revision = run('git', 'rev-parse', 'HEAD', cwd=target).decode().strip()
    run('gh', 'repo', 'create', 'a2hlab/' + name, '--private', '--description',
        'Pinned dependency source snapshot for Westlake; original licenses and provenance retained')
    url = 'https://github.com/a2hlab/' + name + '.git'
    run('git', 'remote', 'add', 'origin', url, cwd=target)
    run('git', 'push', '-u', 'origin', 'main', cwd=target)
    result = dict(entry, url=url, revision=revision,
                  upstream={'url': entry['url'], 'revision': entry['revision'], 'tree': tree})
    if lfs_records:
        result.update(lfs=True, lfs_files=lfs_records,
                      snapshot_tree=run('git', 'rev-parse', 'HEAD^{tree}', cwd=target).decode().strip())
    record.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('PUBLISHED', name, revision, 'original-tree=' + tree, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    destination = args.out.absolute()
    destination.mkdir(parents=True, exist_ok=True)
    original = {name: json.loads((ROOT / name).read_text()) for name in ['upstream.lock.json', 'packaging.lock.json']}
    entries = [entry for data in original.values() for entry in data['projects']
               if not entry['url'].startswith('https://github.com/a2hlab/')]
    if not entries:
        print('All active dependencies are already vendored; provenance preserved.')
        return
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda entry: publish(entry, args.workspace.resolve(), destination), entries))
    by_path = {entry['path']: entry for entry in results}
    for name, data in original.items():
        data['projects'] = [by_path.get(entry['path'], entry) for entry in data['projects']]
        (ROOT / name).write_text(json.dumps(data, indent=2) + '\n')
    (ROOT / 'dependency-source-provenance.json').write_text(json.dumps(results, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
