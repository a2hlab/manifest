#!/usr/bin/env python3
"""Stage verified source outputs and exercise Appspawn framework initialization."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid
from bootstrap_sdk import digest
from build_core_boot import source_jars


def remote_hashes(shell, paths, attempts=1, note=None):
    """The device's SHA-256 of each path, by sha256sum in batches of 32: {path: hash}.

    shell() already fails when a call does not finish (no exit-status marker), yet the final check
    failed with 'Device transfers differ from declared source artifacts' while every file was in
    place: finished calls answered some paths with no hash (2026-11-21, both OnePlus 6 phones, whose
    sha256sum is a wrapper running openssl per file; the next deployment passed). With attempts > 1
    the paths without a hash are asked again, alone, and note() gets what the device printed for
    them. A hash that differs is returned as read; a really missing file stays missing.
    """
    hashes = {}
    pending = list(paths)
    for attempt in range(max(1, attempts)):
        said = {}
        for start in range(0, len(pending), 32):
            batch = pending[start:start + 32]
            _, text = shell('sha256sum ' + ' '.join(map(shlex.quote, batch)))
            for line in text.splitlines():
                match = re.fullmatch(r'([0-9a-f]{64})\s+(.+)', line)
                if match:
                    hashes[match[2]] = match[1]
                else:
                    for path in batch:
                        if path in line:
                            said.setdefault(path, line.strip())
        pending = [path for path in pending if path not in hashes]
        if not pending:
            break
        if note and attempt + 1 < attempts:
            shown = '; '.join(said.get(path, path + ': (nothing printed)') for path in pending[:3])
            note('%d of %d paths without a hash, asking again: %s' % (len(pending), len(paths), shown))
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['appspawn-build', 'core-runtime', 'native-runtime', 'core-build',
                 'framework-build', 'boot-build', 'resources-build', 'firmware-abi', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--extension-build', type=Path, action='append', required=True)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--cache-report', type=Path)
    parser.add_argument('--data-build', type=Path)
    parser.add_argument('--uses-library-build', type=Path, action='append', default=[],
                        help='A jar for an Android shared library an app declares in '
                             '<uses-library>, staged as framework/<name>.jar. Not on the boot '
                             'class path: LoadedApk loads it per app that asks for it.')
    parser.add_argument('--contracts', action='store_true')
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    files, prerequisites = {}, {}

    def include(directory, prefix, select):
        directory = directory.resolve()
        report = json.loads((directory / 'artifacts.json').read_text())
        if report.get('errors') or report.get('deployable') is False:
            raise ValueError('Failed or link-only source build: ' + str(directory))
        prerequisites[str(directory)] = digest(directory / 'artifacts.json')
        for name, entry in report['artifacts'].items():
            if not select(name):
                continue
            path, dest = directory / name, prefix + name
            if not path.resolve().is_relative_to(directory) or digest(path) != entry['sha256']:
                raise ValueError('Changed source artifact: ' + str(path))
            if dest in files and digest(files[dest]) != digest(path):
                raise ValueError('Conflicting stage artifact: ' + dest)
            files[dest] = path
        return report

    for directory in [args.core_runtime, args.native_runtime]:
        include(directory, '', lambda name: name.endswith('.so'))
    ndk_graphics_contracts = args.contracts and 'libjnigraphics.so' in files
    include(args.appspawn_build, '', lambda name: name == 'appspawn-x')
    include(args.resources_build, '', lambda name: name == 'framework-res.apk')
    font_contracts = False
    if args.data_build:
        data_report = include(args.data_build, '', lambda name: True)
        font_contracts = args.contracts and data_report.get('font_count', 0) > 0
    include(args.framework_build, 'fw/', lambda name: name in ['framework.jar', 'adapter-runtime-bcp.jar'])
    for directory in args.uses_library_build:
        include(directory, 'framework/', lambda name: name.endswith('.jar'))
    jars = source_jars(args.core_build.resolve(), [p.resolve() for p in args.extension_build])
    for name, path in jars.items():
        files['fw/' + name + '.jar'] = path
    boot = include(args.boot_build, 'boot/', lambda name: name.endswith(('.art', '.oat', '.vdex')))
    staged_jars = {Path(n).name: digest(p) for n, p in files.items() if n.startswith('fw/')}
    if boot['jars'] != staged_jars:
        raise ValueError('Boot image and runtime JARs differ')
    if boot['classpath_order'] != [*jars, 'framework', 'adapter-runtime-bcp']:
        raise ValueError('Boot class path order differs')
    output.mkdir(parents=True)
    transport = [args.hdc, '-t', args.serial]

    def call(command, cwd=output, timeout=55):
        result = subprocess.run(transport + command, cwd=cwd, capture_output=True, timeout=timeout)
        text = (result.stdout + result.stderr).decode(errors='replace').replace('\r', '')
        if result.returncode or '[Fail]' in text:
            raise RuntimeError(text)
        return text

    def shell(command):
        text = call(['shell', 'sh -c ' + shlex.quote(command) +
                     '; a2h_rc=$?; printf "\\n__A2H_RC__%s\\n" "$a2h_rc"'])
        marker = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if not marker:
            raise RuntimeError('Missing device exit status: ' + text)
        return int(marker[1]), text[:marker.start()]

    if args.serial not in subprocess.check_output([args.hdc, 'list', 'targets'], text=True).split():
        raise ValueError('Device is not connected')
    code, identity = shell('uname -m')
    if code or identity.strip() != 'aarch64':
        raise ValueError('Unexpected device architecture: ' + identity)
    firmware = json.loads(args.firmware_abi.read_text())['firmware']
    expected = {e['path']: e['sha256'] for e in firmware.values()}
    code, hashes = shell('sha256sum ' + ' '.join(shlex.quote(p) for p in sorted(expected)))
    actual = {row.split(None, 1)[1].strip(): row.split()[0] for row in hashes.splitlines()
              if len(row.split(None, 1)) == 2 and len(row.split()[0]) == 64}
    if code or actual != expected:
        raise ValueError('Installed firmware differs from link declarations')
    cache = json.loads(args.cache_report.read_text()) if args.cache_report else {}
    stage = '/data/local/tmp/a2hlab-framework-' + uuid.uuid4().hex
    record = {'scope': 'source Appspawn framework initialization; not Toutiao UX acceptance',
              'stage': stage, 'prerequisites': prerequisites, 'firmware': actual,
              'files': {}, 'passed': False, 'full_stack_accepted': False}

    def save():
        (output / 'device-report.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')

    save()
    code, text = shell('mkdir -p ' + stage + '/fw ' + stage + '/boot ' +
                       stage + '/data/dalvik-cache/arm64 ' + stage + '/i18n/etc/icu ' + stage + '/tzdata')
    if code:
        raise RuntimeError(text)
    wanted = {name: digest(path) for name, path in files.items()}
    parents = sorted({str(Path(stage + '/' + name).parent) for name in files})
    code, text = shell('mkdir -p ' + ' '.join(map(shlex.quote, parents)))
    if code:
        raise RuntimeError(text)

    # Batch cache reads and copies, while still verifying every source and every
    # destination byte identity. Hundreds of fonts need not incur four transport
    # round trips per file. A missing or changed cache entry is sent from host.
    candidates = {}
    if re.fullmatch(r'/data/local/tmp/a2hlab-[a-z]+-[0-9a-f]{32}', cache.get('stage', '')):
        for name in files:
            old = cache.get('files', {}).get(name)
            previous_hash = old.get('sha256') if isinstance(old, dict) else old
            if previous_hash == wanted[name]:
                candidates[name] = cache['stage'] + '/' + name
    cached = remote_hashes(shell, list(candidates.values()))  # a missing cache entry is normal: ask once
    groups, copied = {}, set()
    for name, previous in candidates.items():
        if cached.get(previous) == wanted[name]:
            groups.setdefault(str(Path(stage + '/' + name).parent), []).append(previous)
            copied.add(name)
    for parent, paths in groups.items():
        for start in range(0, len(paths), 32):
            code, text = shell('cp ' + ' '.join(map(shlex.quote, paths[start:start + 32])) +
                               ' ' + shlex.quote(parent + '/'))
            if code:
                raise RuntimeError(text)
    for name, path in sorted(files.items()):
        if name not in copied:
            call(['file', 'send', path.name, stage + '/' + name], cwd=path.parent,
                 # sized from the file, as in probe_source_app: 55 s fails over wireless
                 timeout=max(55, path.stat().st_size // (512 * 1024) + 30))
    actual = remote_hashes(shell, [stage + '/' + name for name in files], attempts=3,
                           note=lambda text: print('probe_framework_vm: ' + text, file=sys.stderr, flush=True))
    if actual != {stage + '/' + name: value for name, value in wanted.items()}:
        raise ValueError('Device transfers differ from declared source artifacts')
    record['files'] = {name: {'sha256': wanted[name], 'bytes': path.stat().st_size}
                       for name, path in files.items()}
    record['cache_files_reused'] = len(copied)
    save()
    code, text = shell('chmod 755 ' + stage + '/appspawn-x')
    if code:
        raise RuntimeError(text)
    search = [stage, '/system/lib64', '/system/lib64/platformsdk', '/system/lib64/chipset-sdk',
              '/system/lib64/chipset-sdk-sp', '/system/lib64/ndk', '/vendor/lib64/chipsetsdk',
              '/vendor/lib64/hw', '/vendor/lib64']
    command = ('cd ' + stage + '; WESTLAKE_RUNTIME_ROOT=' + stage +
               ' LD_LIBRARY_PATH=' + ':'.join(search) + ' timeout 40 ' + stage +
               '/appspawn-x --preload-test --socket-name A2H-' + uuid.uuid4().hex[:12])
    if args.contracts:
        command = 'export WESTLAKE_SOURCE_CONTRACTS=1; ' + command
    if font_contracts:
        command = 'export WESTLAKE_SOURCE_FONT_CONTRACTS=1; ' + command
    if ndk_graphics_contracts:
        command = 'export WESTLAKE_SOURCE_NDK_GRAPHICS_CONTRACTS=1; ' + command
    code, text = shell(command)
    (output / 'device.log').write_text(text)
    record.update(device_command=command, exit_code=code, device_log_sha256=digest(output / 'device.log'),
                  passed=code == 0 and 'SOURCE_FRAMEWORK_PRELOAD_PASS' in text and (
                      not args.contracts or 'SOURCE_FRAMEWORK_CONTRACTS_PASS' in text) and (
                      not font_contracts or 'SOURCE_FONT_ISOLATION_PASS' in text) and (
                      not ndk_graphics_contracts or 'SOURCE_NDK_GRAPHICS_PASS' in text),
                  contracts_requested=args.contracts,
                  contracts_passed='SOURCE_FRAMEWORK_CONTRACTS_PASS' in text,
                  font_contracts_requested=font_contracts,
                  font_contracts_passed='SOURCE_FONT_ISOLATION_PASS' in text,
                  ndk_graphics_contracts_requested=ndk_graphics_contracts,
                  ndk_graphics_contracts_passed='SOURCE_NDK_GRAPHICS_PASS' in text,
                  class_initialization_failures=sorted(set(re.findall(r'failed initialization: (.+)', text))))
    save()
    print('SOURCE_FRAMEWORK_DEVICE_PRELOAD', record['passed'], stage, flush=True)
    print('\n'.join(text.splitlines()[-50:]), flush=True)
    if not record['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
