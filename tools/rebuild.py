#!/usr/bin/env python3
"""Verify pinned sources/toolchains, then run an isolated source build.

The full profile fails closed while any full-source contract remains open.
Native/apps/art builds are deliberately not advertised as complete Toutiao builds.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import sys
from bootstrap_sdk import ROOT, fingerprint
from fetch_sources import read_lock
from install_java import verify_java


def git(path, *command):
    # write-tree updates the index's cached tree. Independent build verifiers
    # must not contend on the checkout index or modify a caller's index.
    if command == ('write-tree',):
        index = Path(git(path, 'rev-parse', '--git-path', 'index').decode().strip())
        if not index.is_absolute():
            index = path / index
        with tempfile.TemporaryDirectory(prefix='a2hlab-verify-index-') as temporary:
            isolated = Path(temporary) / 'index'
            shutil.copyfile(index, isolated)
            return subprocess.check_output(['git', '-C', str(path), 'write-tree'],
                env=dict(os.environ, GIT_INDEX_FILE=str(isolated)), stderr=subprocess.STDOUT)
    return subprocess.check_output(['git', '-C', str(path), *command], stderr=subprocess.STDOUT)


def verify_sources(workspace, lock=None):
    resolved = []
    for entry in read_lock(lock or ROOT / 'sources.lock.json'):
        path = workspace / entry['path']
        revision = git(path, 'rev-parse', 'HEAD').decode().strip()
        if revision != entry['revision']:
            raise ValueError('Source revision differs from lock: ' + entry['path'])
        if git(path, 'ls-files', '--others', '--exclude-standard').strip():
            raise ValueError('Untracked source files: ' + entry['path'])
        if entry.get('patch'):
            patch = (ROOT / entry['patch']).read_bytes()
            if hashlib.sha256(patch).hexdigest() != entry['patch_sha256']:
                raise ValueError('Patch digest mismatch: ' + entry['path'])
            # Pin the resulting Git tree too: diff object abbreviations vary
            # with repository history and are not a stable content comparison.
            if git(path, 'diff', '--binary'):
                raise ValueError('Unstaged modifications: ' + entry['path'])
            actual = git(path, 'write-tree').decode().strip()
            if actual != entry['tree']:
                raise ValueError('Applied source patch differs: ' + entry['path'])
        elif git(path, 'status', '--porcelain').strip():
            raise ValueError('Source checkout is dirty: ' + entry['path'])
        resolved.append(dict(entry, tree=git(path, 'write-tree').decode().strip()))
    return resolved


def verify_toolchains(workspace, include_clang):
    lock = json.loads((ROOT / 'toolchains.lock.json').read_text())
    wanted = [('ohos-sdk', 'ohos-sdk')]
    if include_clang:
        wanted.append(('platform-clang', 'clang-15'))
    record = {}
    for key, folder in wanted:
        path = workspace / 'toolchains' / folder
        if not path.is_dir():
            raise ValueError('Missing bootstrapped toolchain: ' + str(path))
        actual = fingerprint(path)['sha256']
        if actual != lock[key]['tree_sha256']:
            raise ValueError('Toolchain content differs from lock: ' + str(path))
        record[key] = actual
        print('VERIFIED_TOOLCHAIN', key, actual, flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', choices=['native', 'native-support', 'apps', 'art', 'host-tools', 'core-java', 'full'], required=True)
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--native-build', type=Path,
                        help='Verified native-support output for source ICU JNI in the ART profile')
    args = parser.parse_args()
    if args.native_build and args.profile != 'art':
        parser.error('--native-build applies to the art profile')
    if args.profile == 'full':
        gaps = json.loads((ROOT / 'full-build-gaps.json').read_text())
        if not gaps['complete_source_build']:
            print('FULL_BUILD_NOT_READY: refusing historical binary fallback', file=sys.stderr)
            for gap in gaps['gaps']:
                print('- ' + gap, file=sys.stderr)
            return 2
        raise ValueError('Full source pipeline must be implemented before changing its readiness gate')
    workspace = args.workspace.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new (no stale-object reuse)')
    sources = verify_sources(workspace)
    if args.profile == 'core-java':
        sources += verify_sources(workspace, ROOT / 'core-sources.lock.json')
    if args.profile == 'native-support':
        for lock in ['native-sources.lock.json', 'framework-sources.lock.json', 'core-sources.lock.json']:
            sources += verify_sources(workspace, ROOT / lock)
    toolchains = verify_toolchains(workspace, args.profile != 'native')
    if args.profile == 'core-java':
        java_home, toolchains['jdk21'] = verify_java(workspace)
    output.mkdir(parents=True)
    report = {'profile': args.profile, 'sources': sources, 'toolchains': toolchains,
              'complete_toutiao_build': False, 'device_accepted': False, 'status': 'running'}
    env = dict(os.environ, SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')

    def run(name, *command, cwd=None):
        with (output / (name + '.log')).open('x') as log:
            subprocess.run([str(x) for x in command], check=True, stdout=log,
                           stderr=subprocess.STDOUT, env=env, cwd=cwd)

    try:
        if args.profile == 'native':
            run('native', sys.executable, workspace / 'westlake/tools/build_native.py',
                '--sdk', workspace / 'toolchains/ohos-sdk/native', '--out', output / 'native')
        elif args.profile == 'native-support':
            run('native-support', sys.executable, workspace / 'westlake/tools/build_android_native.py',
                '--workspace', workspace, '--out', output / 'native', '--jobs', args.jobs)
        elif args.profile == 'apps':
            run('restool', sys.executable, ROOT / 'tools/build_restool.py', '--workspace', workspace,
                '--out', output / 'restool', '--jobs', args.jobs)
            run('apps', sys.executable, workspace / 'westlake/tools/build_apps.py',
                '--sdk', workspace / 'toolchains/ohos-sdk', '--restool', output / 'restool/restool',
                '--out', output / 'apps')
        elif args.profile == 'art':
            run('objects', 'make', '-f', 'Makefile.ohos-arm64', '-j' + str(args.jobs),
                'WORKSPACE=' + str(workspace), 'BUILDDIR=' + str(output / 'objects'),
                'clean-runtime-objects', 'jni-stubs', cwd=workspace / 'art-build')
            run('link', sys.executable, workspace / 'art-build/tools/link_runtime.py',
                '--workspace', workspace, '--objects', output / 'objects', '--out', output / 'runtime',
                *(['--native-build', args.native_build.resolve()] if args.native_build else []))
            run('providers', sys.executable, ROOT / 'tools/audit_runtime_symbols.py',
                '--workspace', workspace, '--runtime', output / 'runtime',
                '--report', output / 'provider-audit.json', '--require-complete')
        elif args.profile == 'host-tools':
            run('host', sys.executable, workspace / 'art-build/tools/build_host.py',
                '--workspace', workspace, '--out', output / 'host', '--jobs', args.jobs)
        elif args.profile == 'core-java':
            run('java', sys.executable, ROOT / 'tools/build_core_java.py',
                '--source-root', workspace / 'android-source', '--java-home', java_home,
                '--out', output / 'java')
        report['status'] = 'source-build-pass'
    except Exception as error:
        report['status'] = 'fail'
        report['error'] = str(error)
        raise
    finally:
        (output / 'build.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print('SOURCE_BUILD_PASS', args.profile, output, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
