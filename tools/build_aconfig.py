#!/usr/bin/env python3
"""Build the Android flag compiler offline from locked a2hlab source and crate trees."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
from bootstrap_sdk import ROOT, digest
from install_rust import verify_rust
from rebuild import verify_sources, verify_toolchains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists() or args.jobs < 1:
        parser.error('--out must be new and --jobs positive')
    sources = verify_sources(workspace, ROOT / 'framework-generator-dependencies.lock.json')
    sources += verify_sources(workspace, ROOT / 'aconfig-sources.lock.json')
    rust, rust_tree = verify_rust(workspace)
    toolchains = verify_toolchains(workspace, False)
    original = workspace / 'android-source/build-make/tools/aconfig'
    crates = workspace / 'android-source/aconfig-crates'
    source = output / 'source'
    shutil.copytree(original, source, symlinks=True)
    shutil.copy2(crates / 'Cargo.lock', source / 'Cargo.lock')
    cargo_home = output / 'cargo-home'
    cargo_home.mkdir()
    (cargo_home / 'config.toml').write_text('[source.crates-io]\nreplace-with = "vendored-sources"\n'
        '[source.vendored-sources]\ndirectory = ' + json.dumps(str(crates / 'vendor')) + '\n')
    sdk = workspace / 'toolchains/ohos-sdk/native/llvm/bin'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CARGO_', 'RUST', 'SCCACHE_'))}
    env.update(CARGO_HOME=str(cargo_home), CARGO_TARGET_DIR=str(output / 'target'),
               RUSTC=str(rust / 'bin/rustc'), PATH=str(rust / 'bin') + ':' + str(sdk) + ':/usr/bin:/bin',
               LC_ALL='C', TZ='UTC', SOURCE_DATE_EPOCH='1772755200',
               RUSTFLAGS='--remap-path-prefix=' + str(workspace) + '=/src --remap-path-prefix=' +
                         str(output) + '=/build/aconfig -C linker=' + str(sdk / 'clang'))
    command = [str(rust / 'bin/cargo'), 'build', '--manifest-path', str(source / 'Cargo.toml'),
               '--offline', '--locked', '--package', 'aconfig', '--release', '--jobs', str(args.jobs)]
    with (output / 'cargo.log').open('x') as log:
        subprocess.run(command, cwd=source, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    artifact = output / 'aconfig'
    shutil.copy2(output / 'target/release/aconfig', artifact)
    report = {'sources': sources, 'rust_tree_sha256': rust_tree, 'toolchains': toolchains,
              'cargo_lock_sha256': digest(crates / 'Cargo.lock'), 'command': command,
              'packages': tomllib.loads((crates / 'Cargo.lock').read_text())['package'],
              'inputs': {str(p.relative_to(workspace)): digest(p) for p in sorted(original.rglob('*'))
                         if p.is_file() and not p.is_symlink()},
              'artifacts': {'aconfig': {'sha256': digest(artifact), 'bytes': artifact.stat().st_size}},
              'scope': 'source host flag compiler; no device runtime acceptance'}
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('ACONFIG_SOURCE_PASS', digest(artifact))


if __name__ == '__main__':
    main()
