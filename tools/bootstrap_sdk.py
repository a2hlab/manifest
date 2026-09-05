#!/usr/bin/env python3
"""SDK archive helpers and compatibility entry point for repository-only installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
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
    from install_toolchains import install
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    install(args.workspace, ['ohos-sdk'], args.out)


if __name__ == '__main__':
    main()
