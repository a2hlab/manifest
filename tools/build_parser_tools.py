#!/usr/bin/env python3
"""Build the M4, Bison and Flex host generators from pinned release sources."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from bootstrap_sdk import ROOT, digest
from rebuild import verify_sources, verify_toolchains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    sources = verify_sources(workspace, ROOT / 'parser-sources.lock.json')
    toolchains = verify_toolchains(workspace, False)
    sdk = workspace / 'toolchains/ohos-sdk/native/llvm/bin'
    output.mkdir(parents=True)
    prefix = '/opt/a2hlab-parser-tools'
    installed = output / 'dest' / prefix.lstrip('/')
    env = dict(os.environ, LC_ALL='C', TZ='UTC', SOURCE_DATE_EPOCH='1725148800',
               PATH=str(installed / 'bin') + ':' + str(sdk) + ':/usr/bin:/bin',
               CC=str(sdk / 'clang'), CXX=str(sdk / 'clang++'), AR=str(sdk / 'llvm-ar'),
               RANLIB=str(sdk / 'llvm-ranlib'),
               CFLAGS='-O2 -g0 -ffile-prefix-map=' + str(workspace) + '=/src -ffile-prefix-map=' +
                      str(output) + '=/build/parser-tools',
               CONFIG_SHELL='/bin/bash')
    for name in ['CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CPATH', 'LIBRARY_PATH',
                 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'CONFIG_SITE']:
        env.pop(name, None)
    commands = []
    for name in ['m4', 'bison', 'flex']:
        build = output / name
        build.mkdir()
        source = output / 'sources' / name
        shutil.copytree(workspace / 'android-source/parser-tools' / name, source)
        # Git does not preserve release timestamps. Equalize the copied inputs
        # so make uses the checked-in release configure/parser files instead of
        # attempting to regenerate them with undeclared host autotools.
        for path in source.rglob('*'):
            if path.is_file():
                os.utime(path, (1725148800, 1725148800))
        if name != 'm4':
            env['M4'] = str(installed / 'bin/m4')
        if name == 'flex':
            env['BISON_PKGDATADIR'] = str(installed / 'share/bison')
        steps = [[str(source / 'configure'), '--prefix=' + prefix, '--disable-nls'],
                 ['make', '-j' + str(args.jobs)], ['make', 'install', 'DESTDIR=' + str(output / 'dest')]]
        for number, command in enumerate(steps):
            commands.append(command)
            with (build / (str(number) + '.log')).open('x') as log:
                subprocess.run(command, cwd=build, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        print('BUILT_SOURCE_GENERATOR', name, flush=True)
    artifacts = {str(p.relative_to(output)): {'sha256': digest(p), 'bytes': p.stat().st_size}
                 for p in sorted(installed.rglob('*')) if p.is_file()}
    report = {'sources': sources, 'toolchains': toolchains, 'commands': commands,
              'install_root': str(installed.relative_to(output)), 'artifacts': artifacts,
              'scope': 'source host parser generators; no device runtime artifacts'}
    (output / 'artifacts.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('PARSER_TOOLS_SOURCE_PASS', len(artifacts), flush=True)


if __name__ == '__main__':
    main()
