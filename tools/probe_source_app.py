#!/usr/bin/env python3
"""Launch the pinned original APK with verified source outputs and fresh data.

The installed OH window host is a recorded platform prerequisite. A successful
spawn is diagnostic progress, not acceptance of the app's UI or source closure.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import tarfile
import time
import uuid
from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'westlake-source', 'framework-report', 'app-input', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--host', default='org.westlake.imehost')
    parser.add_argument('--host-build', type=Path, help='Verified signed source host build')
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists() or not re.fullmatch(r'[a-zA-Z0-9_.]+', args.host):
        parser.error('Use a new output and a valid host package')
    framework = json.loads(args.framework_report.read_text())
    app = json.loads((args.app_input / 'app-input.json').read_text())
    lock = json.loads((Path(__file__).resolve().parents[1] / 'app-inputs.lock.json').read_text())
    if (not framework['passed'] or app['apk_modified'] or
            app['application'] != lock['applications']['toutiao']):
        raise ValueError('Expected accepted framework probe and pinned original APK')
    package = app['application']['package']
    if not re.fullmatch(r'[a-zA-Z0-9_.]+', package):
        raise ValueError('Invalid application package')
    app_files = {'toutiao.apk': {'sha256': app['apk_sha256']}, **app['native_libraries']}
    for name, entry in app_files.items():
        path = args.app_input.resolve() / name
        if not path.resolve().is_relative_to(args.app_input.resolve()) or digest(path) != entry['sha256']:
            raise ValueError('Changed original APK input: ' + name)
    output.mkdir(parents=True)
    state = {'scope': 'isolated source stack application startup probe', 'source_ui_accepted': False,
             'full_source_closure': False, 'framework_report_sha256': digest(args.framework_report),
             'app_input_sha256': digest(args.app_input / 'app-input.json'), 'parent': None, 'child': None}

    def save():
        (output / 'device-report.json').write_text(json.dumps(state, indent=2) + '\n')

    transport = [args.hdc, '-t', args.serial]

    def call(command, cwd=output):
        result = subprocess.run(transport + command, cwd=cwd, capture_output=True, timeout=55)
        text = (result.stdout + result.stderr).decode(errors='replace').replace('\r', '')
        if result.returncode or '[Fail]' in text:
            raise RuntimeError(text)
        return text

    def shell(command):
        text = call(['shell', 'sh -c ' + shlex.quote(command) +
                     '; a2h_rc=$?; printf "\\n__A2H_RC__%s\\n" "$a2h_rc"'])
        with (output / 'commands.jsonl').open('a') as journal:
            journal.write(json.dumps({'command': command, 'output': text}) + '\n')
        match = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if not match or int(match[1]):
            raise RuntimeError(text)
        return text[:match.start()]

    def send(path, remote):
        call(['file', 'send', path.name, remote], cwd=path.parent)
        if shell('sha256sum ' + shlex.quote(remote)).split()[0] != digest(path):
            raise ValueError('Changed transfer: ' + remote)

    def hashes(paths):
        result = {}
        for start in range(0, len(paths), 24):
            text = shell('sha256sum ' + ' '.join(map(shlex.quote, paths[start:start + 24])))
            for line in text.splitlines():
                value, name = line.split(None, 1)
                result[name.strip()] = value
        return result

    if args.serial not in subprocess.check_output([args.hdc, 'list', 'targets'], text=True).split():
        raise ValueError('Device is not connected')
    if shell('uname -m').strip() != 'aarch64':
        raise ValueError('Unexpected device architecture')
    if hashes(sorted(framework['firmware'])) != framework['firmware']:
        raise ValueError('Host firmware differs from accepted source framework probe')
    previous = framework['stage']
    expected = {previous + '/' + n: e['sha256'] for n, e in framework['files'].items()}
    if hashes(sorted(expected)) != expected:
        raise ValueError('Previously staged source outputs changed')
    raw = shell('bm dump -n ' + args.host)
    host = json.loads(raw[raw.index('{'):])['applicationInfo']
    uid = host['uid']
    if uid < 20000000:
        raise ValueError('Expected an installed OH application host')
    if args.host_build:
        host_report = json.loads((args.host_build / 'artifacts.json').read_text())
        local_hap = args.host_build / 'source-host.hap'
        wanted = host_report['artifacts'][local_hap.name]['sha256']
        installed_hap = '/data/app/el1/bundle/public/' + args.host + '/entry.hap'
        if (host_report.get('errors') or not host_report.get('program_and_resources_match_source') or
                digest(local_hap) != wanted or hashes([installed_hap]) != {installed_hap: wanted}):
            raise ValueError('Installed host differs from the signed source payload')
        state['source_host_build_sha256'] = digest(args.host_build / 'artifacts.json')
        state['source_host_hap_sha256'] = wanted
    shell('power-shell wakeup')
    result = shell('aa start -b ' + args.host + ' -a EntryAbility')
    if 'start ability successfully' not in result:
        raise RuntimeError(result)
    host_pid = None
    window = None
    for _ in range(60):
        try:
            host_pid = int(shell('pidof ' + args.host).strip())
            host_state = json.loads(shell(f'cat /proc/{host_pid}/root/data/storage/el2/base/haps/entry/files/window-state.json'))
            window = int(host_state['details'].get('window', host_state['details'])['id'])
            if window > 0:
                break
        except (RuntimeError, ValueError, KeyError):
            pass
        time.sleep(0.25)
    if not window or window <= 0:
        raise ValueError('Missing host window')
    state.update(host_pid=host_pid, window=window)
    suffix = uuid.uuid4().hex
    runtime = '/data/app/el2/100/base/' + args.host + '/files/a2hlab-source-' + suffix
    stage = '/data/local/tmp/a2hlab-app-' + suffix
    logical = '/data/local/tmp/asx'
    socket_name = 'A2HSource' + suffix[:20]
    socket = '/dev/unix/socket/' + socket_name
    state.update(stage=stage, runtime=runtime, uid=uid, host=host, socket=socket,
                 source_files=framework['files'], apk_sha256=app['apk_sha256'])
    save()
    sdk = args.workspace.resolve() / 'toolchains/ohos-sdk/native'
    helpers = {}
    for source_name in ['source_app_namespace.c', 'host_spawn.c', 'touchfwd.c']:
        source = args.westlake_source.resolve() / 'native' / source_name
        target = output / source_name.removesuffix('.c')
        command = [str(sdk / 'llvm/bin/clang'), '--target=aarch64-linux-ohos',
                   '--sysroot=' + str(sdk / 'sysroot'), '-O2', '-Wall', '-Werror',
                   str(source), '-o', str(target)]
        subprocess.run(command, check=True)
        helpers[target.name] = {'source_sha256': digest(source), 'sha256': digest(target), 'command': command}
    state['helpers'] = helpers
    save()
    shell('mkdir ' + stage + ' ' + runtime)
    shell('cp -a ' + previous + '/. ' + runtime + '/')
    copied = {runtime + '/' + n: e['sha256'] for n, e in framework['files'].items()}
    if hashes(sorted(copied)) != copied:
        raise ValueError('Candidate source copy changed')
    archive = output / 'original-app.tar'
    with tarfile.open(archive, 'w') as tar:
        for name in sorted(app_files):
            tar.add(args.app_input / name, arcname=name, recursive=False)
    send(archive, stage + '/' + archive.name)
    shell('tar -xf ' + stage + '/original-app.tar -C ' + runtime)
    expected_app = {runtime + '/' + n: e['sha256'] for n, e in app_files.items()}
    if hashes(sorted(expected_app)) != expected_app:
        raise ValueError('Candidate original APK files changed')
    shell('mkdir -p ' + runtime + '/private-tmp/asx ' + runtime + '/data/dalvik-cache/arm64 ' +
          runtime + '/app-data/' + package + '/code_cache/art-volatile ' +
          runtime + '/app-data/' + package + '/app_webview ' + runtime + '/app-data/' + args.host +
          ' && chown -R ' + str(uid) + ':' + str(uid) + ' ' + runtime +
          ' && chmod 755 ' + runtime + '/appspawn-x')
    for name in helpers:
        send(output / name, stage + '/' + name)
    shell('chmod 755 ' + stage + '/source_app_namespace ' + stage + '/host_spawn')
    def tlv(kind, value):
        value += bytes((-len(value)) % 4)
        return struct.pack('<HH', len(value) + 4, kind) + value

    body = tlv(0, struct.pack('<I', 0) + args.host.encode() + b'\0')
    body += tlv(2, struct.pack('<III64I64s', uid, uid, 1, 3099, *([0] * 63), b'imehost'))
    body += tlv(5, struct.pack('<Q', host['accessTokenIdEx']))
    body += tlv(3, struct.pack('<I', 0) + b'normal\0')
    request = output / 'request.bin'
    request.write_bytes(struct.pack('<5I256s', 0xef201234, 0, 276 + len(body), 0x41324801, 4,
                                    args.host.encode()) + body)
    send(request, stage + '/request.bin')
    search = [logical, '/system/lib64', '/system/lib64/platformsdk', '/system/lib64/chipset-sdk',
              '/system/lib64/chipset-sdk-sp', '/system/lib64/ndk', '/vendor/lib64/chipsetsdk',
              '/vendor/lib64/hw', '/vendor/lib64', logical + '/lib/arm64-v8a']
    env = {'WESTLAKE_RUNTIME_ROOT': logical, 'LD_LIBRARY_PATH': ':'.join(search),
           'WESTLAKE_SOURCE_LOG_STDERR': '1',
           'WESTLAKE_SOURCE_PACKAGE': '1',
           'WESTLAKE_TRACE_NATIVE_LOADER': '1',
           'ASX_RUNTIME_OWNER_UID': str(uid), 'ASX_LAUNCH_PKG': package,
           'ASX_NATIVE_LIB_DIR': logical + '/lib/arm64-v8a',
           'ASX_APK_PATH': logical + '/toutiao.apk', 'ASX_LAUNCH_ACTIVITY': package + '.activity.MainActivity',
           'ASX_DIRECT_LAUNCH': '1', 'ASX_KEEP_THEME': '1', 'ASX_DIAG_THROWABLE': '1',
           'ASX_WEBVIEW_DATA_DIR': '/data/data/' + package + '/app_webview',
           'WL_PARENT_ID': str(window), 'WL_SUB_WINDOW': '1', 'WL_FOCUSABLE': '1',
           'WL_SESSION_BUNDLE': args.host, 'WL_ABILITY_OWNED_WINDOWS': '1', 'WL_MMI': '1',
           'WESTLAKE_OH_JIT_ANON_FALLBACK': '1',
           # WESTLAKE §812 (openharmony art-fixes): this standalone ARM64 port has no
           # qualified optimizing-JIT reference pipeline. Toutiao hits a generated-code
           # fault with a corrupt non-null heap reference -- it surfaces as method
           # resolution for descriptors that exist in no JAR (e.g.
           # ClientTransaction.obtain(IApplicationThread, IBinder)) and ART then aborts
           # with "Throwing new exception ... with unexpected pending exception" on the
           # first activity transition after a tap. Keep real JIT execution but constrain
           # it to ART's baseline compiler through the appspawn §791 gate, which adds
           # -Xcompiler-option --baseline. Upstream §812 hardcodes the same option in
           # Runtime::CreateJit(); this reaches it without rebuilding libart.
           'APPSPAWNX_JIT_BASELINE': '1',
           'WESTLAKE_OH_JIT_FILE_CACHE_DIR': '/data/data/' + package + '/code_cache/art-volatile'}
    if 'liboh_permission_queries.so' in framework['files']:
        env['WESTLAKE_PERMISSION_HELPER_PATH'] = logical + '/liboh_permission_queries.so'
    if 'liboh_account_state.so' in framework['files']:
        env['WESTLAKE_ACCOUNT_HELPER_PATH'] = logical + '/liboh_account_state.so'
    script = output / 'run.sh'
    script.write_text('#!/system/bin/sh\nset -eu\ncd ' + logical + '\n' +
                      ''.join('export ' + k + '=' + shlex.quote(v) + '\n' for k, v in env.items()) +
                      'exec ' + logical + '/appspawn-x --socket-name ' + socket_name + '\n')
    send(script, runtime + '/run.sh')
    shell('chown ' + str(uid) + ':' + str(uid) + ' ' + runtime + '/run.sh')
    command = ('nohup ' + stage + '/source_app_namespace ' + runtime + ' ' + str(uid) +
               ' /system/bin/sh ' + logical + '/run.sh >' + stage + '/parent.log 2>&1 </dev/null & echo $!')
    state['parent'] = int(shell(command).strip())
    save()
    for _ in range(60):
        if 'READY' in shell('if [ -S ' + socket + ' ]; then echo READY; fi'):
            break
        time.sleep(0.5)
    else:
        log = shell('tail -n 500 ' + stage + '/parent.log')
        (output / 'parent.log').write_text(log)
        raise RuntimeError('Source parent did not listen; see ' + str(output / 'parent.log'))
    response = shell(stage + '/host_spawn ' + socket + ' ' + stage + '/request.bin')
    match = re.search(r'HOST_SPAWN result=0 pid=(\d+)', response)
    if not match:
        raise RuntimeError(response)
    state['child'] = int(match[1])
    save()
    # WESTLAKE: a physical touch never reaches this app through OH MMI. Its windows are
    # bridge-created sub-windows that InputWindowsManager never registered, and
    # subscribeMmi is disabled in the child, so OH delivers pointer events to SceneBoard
    # and the panel feels dead (PointerEvent/dispatchTouch counts stay at 0 in every
    # capture). touchfwd reads the digitizer's evdev node directly and re-emits each
    # gesture into the bridge's in-process injection channel, which IS delivered.
    #
    # Two details are load-bearing:
    #   * the child runs in a private mount namespace (source_app_namespace), so the
    #     global channel symlink must resolve through /proc/<pid>/root -- otherwise the
    #     forwarder writes into a file the child never reads;
    #   * the bridge only ever opens the mailbox for reading, so it must be created here
    #     and owned by the app uid.
    # event2 is this board's real digitizer (gsl680_tp, ABS 0..1200 x 0..1920); event5 is
    # the virtual node and is NOT what a finger drives.
    touch_device = '/dev/input/event2'
    child_pid = state['child']
    box = '/proc/%d/root/data/local/tmp/noice_tap.%d' % (child_pid, child_pid)
    shell('chmod 755 ' + stage + '/touchfwd')
    shell(': > ' + box + '; chown ' + str(uid) + ':' + str(uid) + ' ' + box +
          '; chmod 666 ' + box + '; ln -sf ' + box + ' /data/local/tmp/noice_tap')
    shell('P=$(pidof touchfwd 2>/dev/null); [ -n "$P" ] && kill $P 2>/dev/null; exit 0')
    shell('setsid env WL_TOUCH_STREAM=1 WL_TOUCH_STREAM_CLICK=1 WL_TOUCH_COORD_GAIN=1 ' +
          stage + '/touchfwd ' + touch_device + ' </dev/null >' + stage +
          '/touchfwd.log 2>&1 & exit 0')
    time.sleep(1)
    state['touch'] = {'device': touch_device, 'channel': box,
                      'forwarder_pid': shell('pidof touchfwd; exit 0').strip()}
    save()
    print('SOURCE_APP_SPAWNED', json.dumps({k: state[k] for k in ['parent', 'child', 'stage', 'runtime']}), flush=True)


if __name__ == '__main__':
    main()
