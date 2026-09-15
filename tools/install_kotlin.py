#!/usr/bin/env python3
"""Install content-locked Kotlin compilers offline from their a2hlab repository."""
import argparse
import json
from pathlib import Path
import tempfile
from bootstrap_sdk import ROOT, digest, extract_zip, fingerprint
from rebuild import verify_sources


def verify_kotlin(workspace):
    lock = json.loads((ROOT / 'kotlin-compiler.lock.json').read_text())
    path = workspace / 'toolchains/kotlin1822'
    if fingerprint(path)['sha256'] != lock['tree_sha256']:
        raise ValueError('Kotlin compiler tree differs from pinned input')
    return path / lock['home'], lock['tree_sha256']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    verify_sources(workspace, ROOT / 'kotlin-inputs.lock.json')
    lock = json.loads((ROOT / 'kotlin-compiler.lock.json').read_text())
    repository = workspace / lock['repository_path']
    if json.loads((repository / 'index.json').read_text()) != lock:
        raise ValueError('Compiler repository index differs from lock')
    archive = repository / lock['path']
    if digest(archive) != lock['sha256'] or archive.stat().st_size != lock['bytes']:
        raise ValueError('Compiler archive differs from lock')
    output = workspace / 'toolchains/kotlin1822'
    if output.exists():
        raise ValueError('Compiler output must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kotlin-compiler-', dir=output.parent) as directory:
        stage = Path(directory) / 'tree'
        stage.mkdir()
        extract_zip(archive, stage)
        tree = fingerprint(stage)
        if tree['sha256'] != lock['tree_sha256']:
            raise ValueError('Extracted compiler tree differs from lock')
        (stage / 'tree.json').write_text(json.dumps(tree, indent=2, sort_keys=True) + '\n')
        stage.rename(output)
    print('KOTLIN_COMPILER_READY', output)


if __name__ == '__main__':
    main()
