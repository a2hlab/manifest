#!/usr/bin/env python3
"""Extract the locked legacy OH platform compiler; never use a workstation prebuilt."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
from bootstrap_sdk import ROOT, digest, fingerprint, inside


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be a new directory')
    lock = json.loads((ROOT / 'toolchains.lock.json').read_text())['platform-clang']
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='a2hlab-clang-', dir=output.parent) as scratch:
        scratch = Path(scratch)
        archive = args.archive or scratch / 'clang.tar.gz'
        if not args.archive:
            with urllib.request.urlopen(lock['url']) as src, archive.open('xb') as dst:
                shutil.copyfileobj(src, dst)
        if archive.stat().st_size != lock['bytes'] or digest(archive) != lock['sha256']:
            raise ValueError('Compiler archive digest mismatch')
        stage = scratch / 'unpacked'
        stage.mkdir()
        with tarfile.open(archive, 'r:gz') as source:
            # Python data_filter rejects devices, absolute/escaping links and
            # paths. Explicitly validate names too and never extract over live files.
            for member in source:
                inside(stage, member.name)
                source.extract(member, stage, filter='data')
        compiler = stage / lock['root']
        if not (compiler / 'bin/clang').is_file():
            raise ValueError('Missing compiler after extraction')
        current = compiler / 'lib/clang/current'
        if not current.exists():
            current.symlink_to('15.0.4')
        tree = fingerprint(compiler)
        tree['archive_sha256'] = lock['sha256']
        (compiler / 'tree.json').write_text(json.dumps(tree, sort_keys=True, indent=2) + '\n')
        compiler.rename(output)
    print('CLANG_TREE_SHA256', tree['sha256'], flush=True)
    print('CLANG_READY', output, flush=True)


if __name__ == '__main__':
    main()
