#!/usr/bin/env python3
"""Install content-locked Git LFS toolchains offline; never download a fallback."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from bootstrap_sdk import ROOT, digest, fingerprint, inside
from fetch_sources import read_lock

FOLDERS = {'ohos-sdk': 'ohos-sdk', 'platform-clang': 'clang-15'}


def extract_tar(archive, output):
    """Extract new files only, then create validated in-tree relative symlinks."""
    links = []
    names = set()
    with tarfile.open(archive, 'r:*') as source:
        for member in source:
            target = inside(output, member.name)
            if target == output or target in names:
                raise ValueError('Duplicate or root archive entry: ' + member.name)
            names.add(target)
            if target.exists() or target.is_symlink():
                if not (member.isdir() and target.is_dir() and not target.is_symlink()):
                    raise ValueError('Archive entry already exists: ' + member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.issym():
                link = Path(member.linkname)
                if link.is_absolute() or '\\' in member.linkname or not (target.parent / link).resolve().is_relative_to(output.resolve()):
                    raise ValueError('Unsafe archive symlink: ' + member.name)
                links.append((target, member.linkname))
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError('Unsupported archive entry: ' + member.name)
    # No extraction traverses a symlink. A symlink directory with file children
    # is rejected instead of silently following or replacing it.
    link_paths = {target for target, _ in links}
    for target in names:
        if any(parent in link_paths for parent in target.parents):
            raise ValueError('Archive member beneath a symlink: ' + str(target))
    for target, link in links:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(link)
    for target, _ in links:
        if not target.resolve().is_relative_to(output.resolve()):
            raise ValueError('Symlink chain escapes output: ' + str(target))


def install_package(archive, output, lock):
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be new: ' + str(output))
    if not archive.is_file() or archive.stat().st_size != lock['bytes'] or digest(archive) != lock['sha256']:
        raise ValueError('Missing/corrupt LFS archive (a pointer file is not an archive): ' + str(archive))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='a2hlab-install-', dir=output.parent) as scratch:
        stage = Path(scratch) / 'tree'
        stage.mkdir()
        extract_tar(archive, stage)
        tree = fingerprint(stage)
        if tree['sha256'] != lock['tree_sha256']:
            raise ValueError('Extracted toolchain tree differs from manifest lock')
        tree['archive_sha256'] = lock['sha256']
        (stage / 'tree.json').write_text(json.dumps(tree, sort_keys=True, indent=2) + '\n')
        stage.rename(output)
    print('TOOLCHAIN_READY', output, tree['sha256'], flush=True)


def install(workspace, keys, output=None):
    workspace = workspace.resolve()
    lock = json.loads((ROOT / 'toolchains.lock.json').read_text())
    repo = workspace / lock['repository_path']
    entry = next(e for e in read_lock(ROOT / 'sources.lock.json') if e['path'] == lock['repository_path'])
    revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != entry['revision']:
        raise ValueError('Toolchain repository revision differs from source lock')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']).strip():
        raise ValueError('Toolchain repository has local changes')
    index = json.loads((repo / 'index.json').read_text())['packages']
    for key in keys:
        for field in ('path', 'sha256', 'bytes', 'tree_sha256'):
            if index[key][field] != lock[key][field]:
                raise ValueError('Toolchain index differs from manifest: ' + key + '/' + field)
        archive = inside(repo, lock[key]['path'])
        install_package(archive, output or workspace / 'toolchains' / FOLDERS[key], lock[key])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--package', choices=FOLDERS, action='append')
    args = parser.parse_args()
    install(args.workspace, args.package or list(FOLDERS))


if __name__ == '__main__':
    main()
