#!/usr/bin/env python3
"""Install the pinned JDK offline from its a2hlab Git LFS repository."""
import argparse
import json
from pathlib import Path
import subprocess
from bootstrap_sdk import ROOT, fingerprint
from fetch_sources import read_lock
from install_toolchains import install_package


def verify_java(workspace):
    lock = json.loads((ROOT / 'java-compiler.lock.json').read_text())
    path = workspace / 'toolchains/jdk21'
    if fingerprint(path)['sha256'] != lock['tree_sha256']:
        raise ValueError('JDK tree differs from pinned compiler input')
    return path / lock['home'], lock['tree_sha256']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    lock = json.loads((ROOT / 'java-compiler.lock.json').read_text())
    repo = workspace / lock['repository_path']
    source = next(e for e in read_lock(ROOT / 'core-sources.lock.json') if e['path'] == lock['repository_path'])
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != source['revision'] or subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']).strip():
        raise ValueError('JDK input checkout differs from source lock')
    if json.loads((repo / 'index.json').read_text()) != lock:
        raise ValueError('JDK archive index differs from compiler lock')
    install_package(repo / lock['path'], workspace / 'toolchains/jdk21', lock)


if __name__ == '__main__':
    main()
