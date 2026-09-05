#!/usr/bin/env python3
"""Verify a content-locked official SDK archive and unpack selected components.

An existing archive can be supplied with --archive; it is always re-hashed.
No dependency on the original author's workstation or installed SDK exists.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def inside(root, relative):
    part = PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or '\\' in relative:
        raise ValueError('Unsafe archive path: ' + relative)
    target = root.joinpath(*part.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Archive path escapes output: ' + relative)
    return target


def extract_zip(archive, output):
    links = []
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = inside(output, member.filename)
            mode = member.external_attr >> 16
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() or target.is_symlink():
                raise ValueError('Duplicate archive entry: ' + member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                links.append((target, source.read(member).decode('utf-8')))
            elif stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError('Unsupported archive entry: ' + member.filename)
            else:
                with source.open(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if mode & 0o111 else 0o644)
    for target, link in links:
        if Path(link).is_absolute() or not (target.parent / link).resolve().is_relative_to(output.resolve()):
            raise ValueError('Unsafe archive symlink: ' + str(target))
        target.symlink_to(link)
    for target, _ in links:
        if not target.resolve().is_relative_to(output.resolve()):
            raise ValueError('Symlink chain escapes output: ' + str(target))


def fingerprint(root):
    entries = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if name == 'tree.json':
            continue
        if path.is_symlink():
            entries[name] = {'link': os.readlink(path)}
        elif path.is_file():
            entries[name] = {'sha256': digest(path), 'executable': bool(path.stat().st_mode & 0o111)}
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    return {'sha256': hashlib.sha256(encoded).hexdigest(), 'files': entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Previously downloaded official tar.gz (always verified)')
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    parser.add_argument('--components', nargs='+', choices=['native', 'ets', 'toolchains'], default=['native', 'ets', 'toolchains'])
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must not already exist')
    lock = json.loads((ROOT / 'toolchains.lock.json').read_text())['ohos-sdk']
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='a2hlab-sdk-', dir=output.parent) as scratch:
        scratch = Path(scratch)
        archive = args.archive or scratch / 'sdk.tar.gz'
        if not args.archive:
            print('Downloading', lock['url'], flush=True)
            with urllib.request.urlopen(lock['url']) as src, archive.open('xb') as dst:
                shutil.copyfileobj(src, dst)
        if archive.stat().st_size != lock['bytes'] or digest(archive) != lock['sha256']:
            raise ValueError('SDK archive does not match the content lock; nothing extracted')
        print('Verified archive', lock['sha256'], flush=True)
        stage = scratch / 'sdk'
        stage.mkdir()
        wanted = {lock['members'][c] for c in args.components}
        with tarfile.open(archive, 'r|gz') as source:
            for member in source:
                if member.name not in wanted:
                    continue
                if not member.isfile():
                    raise ValueError('Expected regular SDK zip: ' + member.name)
                packed = scratch / Path(member.name).name
                with source.extractfile(member) as src, packed.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                extract_zip(packed, stage)
                wanted.remove(member.name)
                print('Extracted', member.name, flush=True)
                if not wanted:
                    break
        if wanted:
            raise ValueError('SDK archive missing components: ' + repr(wanted))
        for component in args.components:
            meta = json.loads((stage / component / 'oh-uni-package.json').read_text())
            if meta['version'] != lock['version']:
                raise ValueError('Unexpected component version: ' + component)
        tree = fingerprint(stage)
        tree['archive_sha256'] = lock['sha256']
        tree['components'] = sorted(set(args.components))
        (stage / 'tree.json').write_text(json.dumps(tree, sort_keys=True, indent=2) + '\n')
        stage.rename(output)
    print('SDK_TREE_SHA256', tree['sha256'], flush=True)
    print('SDK_READY', output, flush=True)


if __name__ == '__main__':
    main()
