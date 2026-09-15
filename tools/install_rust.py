#!/usr/bin/env python3
"""Install pinned Rust compiler components from a2hlab archives without installer scripts."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from bootstrap_sdk import ROOT, digest, fingerprint
from install_toolchains import extract_tar
from rebuild import verify_sources


def assemble(repository, output, index):
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='rust-components-', dir=output.parent) as scratch:
        for component in index['components']:
            archive = repository / component['archive']
            if digest(archive) != component['sha256'] or archive.stat().st_size != component['bytes']:
                raise ValueError('Rust compiler archive differs: ' + component['name'])
            stage = Path(scratch) / component['name']
            stage.mkdir()
            extract_tar(archive, stage)
            distribution = stage / component['archive'].removesuffix('.tar.xz')
            names = (distribution / 'components').read_text().splitlines()
            if len(names) != 1:
                raise ValueError('Unexpected Rust component layout')
            tree = distribution / names[0]
            for path in sorted(tree.rglob('*')):
                if path.name == 'manifest.in':
                    continue
                target = output / path.relative_to(tree)
                if path.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(path.readlink())
                elif path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif path.is_file():
                    if target.exists():
                        raise ValueError('Conflicting Rust distribution file: ' + str(target))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            licenses = output / 'share/licenses' / component['name']
            licenses.mkdir(parents=True)
            for path in distribution.glob('LICENSE*'):
                shutil.copy2(path, licenses / path.name)
    return fingerprint(output)


def verify_rust(workspace):
    lock = json.loads((ROOT / 'rust-compiler.lock.json').read_text())
    path = workspace / 'toolchains/rust194'
    if fingerprint(path)['sha256'] != lock['tree_sha256']:
        raise ValueError('Rust compiler tree differs from lock')
    return path, lock['tree_sha256']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    verify_sources(workspace, ROOT / 'rust-inputs.lock.json')
    lock = json.loads((ROOT / 'rust-compiler.lock.json').read_text())
    repository = workspace / lock['repository_path']
    if json.loads((repository / 'index.json').read_text()) != lock['index']:
        raise ValueError('Rust compiler index differs from lock')
    output = workspace / 'toolchains/rust194'
    if output.exists():
        raise ValueError('Rust compiler destination must be new')
    tree = assemble(repository, output, lock['index'])
    if tree['sha256'] != lock['tree_sha256']:
        raise ValueError('Installed Rust compiler fingerprint mismatch')
    (output / 'tree.json').write_text(json.dumps(tree, indent=2, sort_keys=True) + '\n')
    print('RUST_COMPILER_READY', tree['sha256'])


if __name__ == '__main__':
    main()
