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
    parser.add_argument('--webview-input', type=Path,
                        help='Hash-locked device-captured WebView payload root')
    parser.add_argument('--bionic-shim-build', type=Path,
                        help='Source-built libwebview_bionic_shim.so replacing the device-captured '
                             'copy in --webview-input (the captured copy predates the loader refusals)')
    parser.add_argument('--source-webview-build', type=Path,
                        help='Verified source WebView build overriding its APK and engine DSO')
    parser.add_argument('--runtime-env', action='append', default=[], metavar='KEY=VALUE',
                        help='extra environment for the spawned child, e.g. APPSPAWNX_VERBOSE_CLASS=1 '
                             "to trace class loading. Repeatable; it cannot replace a key the launcher sets")
    parser.add_argument('--touch-mode', choices=['stream', 'tap'], default='stream',
                        help="how the forwarder replays a physical gesture: 'stream' sends the "
                             "motion stream plus a hit-tested click for a stationary tap (drags "
                             "scroll, and a row whose click is stranded behind the main-queue "
                             "barrier still fires); 'tap' sends one press/release per gesture, "
                             "which is what views that ignore the synthesised click need")
    parser.add_argument('--android-native-target', action='append', default=[],
                        help='APK DSO basename to route through the isolated Android ABI namespace')
    parser.add_argument('--android-native-net-target', action='append', default=[],
                        help='Android DSO basename requiring Bionic network-structure translation')
    parser.add_argument('--trace-runtime-lock', type=Path,
                        help='Exact harness runtime lock for opt-in ART JNI registration tracing')
    parser.add_argument('--trace-run-id', help='Unique structured trace run identity')
    parser.add_argument('--trace-scenario', default='cold-launch')
    parser.add_argument('--app', default='toutiao', help='application key in app-inputs.lock.json')
    parser.add_argument('--launch-activity',
                        help='fully qualified launch activity; defaults to the pinned entry, '
                             'then to <package>.activity.MainActivity')
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists() or not re.fullmatch(r'[a-zA-Z0-9_.]+', args.host):
        parser.error('Use a new output and a valid host package')
    framework = json.loads(args.framework_report.read_text())
    app = json.loads((args.app_input / 'app-input.json').read_text())
    lock = json.loads((Path(__file__).resolve().parents[1] / 'app-inputs.lock.json').read_text())
    if args.app not in lock['applications']:
        raise ValueError('Unknown application: ' + args.app)
    if (not framework['passed'] or app['apk_modified'] or
            app['application'] != lock['applications'][args.app]):
        raise ValueError('Expected accepted framework probe and pinned original APK')
    package = app['application']['package']
    if not re.fullmatch(r'[a-zA-Z0-9_.]+', package):
        raise ValueError('Invalid application package')
    base_apk = args.app + '.apk'
    launch_activity = (args.launch_activity
                       or app['application'].get('launch_activity')
                       or package + '.activity.MainActivity')
    if not re.fullmatch(r'[a-zA-Z0-9_.$]+', launch_activity):
        raise ValueError('Invalid launch activity: ' + launch_activity)
    # Split APKs carry no code, but the density and language splits own the
    # resources: McDonald's keeps 886 drawables and its own resources.arsc in
    # split_config.xxxhdpi.apk. Every split must reach the asset manager or the
    # app comes up unable to resolve most of its own resources.
    split_apks = {item['staged']: {'sha256': item['sha256']}
                  for item in (app.get('splits') or {}).values()}
    app_files = {base_apk: {'sha256': app['apk_sha256']}, **split_apks, **app['native_libraries']}
    for name, entry in app_files.items():
        path = args.app_input.resolve() / name
        if not path.resolve().is_relative_to(args.app_input.resolve()) or digest(path) != entry['sha256']:
            raise ValueError('Changed original APK input: ' + name)
    trace = None
    if args.trace_runtime_lock:
        trace = json.loads(args.trace_runtime_lock.read_text())
        if (not args.trace_run_id or not re.fullmatch(r'[a-zA-Z0-9_.-]+', args.trace_run_id)
                or not re.fullmatch(r'[a-zA-Z0-9_.-]+', args.trace_scenario)
                or trace.get('target_abi') != 'arm64-v8a'
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', trace.get('runtime_lock_id', ''))):
            raise ValueError('Trace needs an explicit valid run and ARM64 runtime lock')
        staged_jars = {entry['name']: entry['sha256'] for entry in trace['boot_classpath']}
        expected_jars = {
            name.removeprefix('fw/'): entry['sha256']
            for name, entry in framework['files'].items()
            if name.startswith('fw/') and name.endswith('.jar')
        }
        staged_bridges = {entry['name']: entry['sha256'] for entry in trace['bridge_libraries']}
        expected_bridges = {
            name: entry['sha256'] for name, entry in framework['files'].items()
            if name.endswith('.so')
        }
        if (len(staged_jars) != len(trace['boot_classpath']) or staged_jars != expected_jars
                or len(staged_bridges) != len(trace['bridge_libraries'])
                or staged_bridges != expected_bridges or 'libart.so' not in staged_bridges):
            raise ValueError('Trace runtime lock does not match staged source JARs and DSOs')
    elif args.trace_run_id:
        raise ValueError('Trace run identity requires a verified runtime lock')
    native_targets = sorted(set(args.android_native_target))
    native_net_targets = sorted(set(args.android_native_net_target))
    available_native_basenames = {
        Path(name).name for name in app['native_libraries'] if name.endswith('.so')
    }
    if any(not re.fullmatch(r'lib[a-zA-Z0-9_.+-]+\.so', name)
           or name not in available_native_basenames for name in native_targets):
        raise ValueError('Android namespace target is not a pinned APK DSO')
    webview_files = {}
    webview_paths = {}
    webview_lock_path = Path(__file__).resolve().parents[1] / 'parity27-runtime-inputs.lock.json'
    if args.webview_input:
        webview_lock = json.loads(webview_lock_path.read_text())
        prefix = '/data/local/tmp/asx/'
        webview_files = {
            entry['path'].removeprefix(prefix): {
                'sha256': entry['sha256'],
                'provenance': 'device-captured',
            }
            for entry in webview_lock['files']
            if entry.get('category') == 'webview' and entry['path'].startswith(prefix)
        }
        required = {
            'webview-t.apk',
            'webview-t-lib/libandroid.so',
            'webview-t-lib/libjnigraphics.so',
            'webview-t-lib/libwebview_bionic_shim.so',
            'webview-t-lib/libwebviewchromium.so',
            'webview-t-lib/libwebviewchromium_plat_support.so',
        }
        if (set(webview_files) != required
                or webview_lock.get('complete_build_input_closure') is not False):
            raise ValueError('Unexpected WebView device-input lock')
        webview_root = args.webview_input.resolve()
        for name, entry in webview_files.items():
            path = webview_root / name
            if (not path.resolve().is_relative_to(webview_root)
                    or digest(path) != entry['sha256']):
                raise ValueError('Changed device-captured WebView input: ' + name)
            webview_paths[name] = path
    if args.bionic_shim_build:
        # The WebView input's bionic shim is also the ABI boundary preloaded for the APK's own
        # native libraries. The device-captured copy predates the refusal of self-trapping
        # libraries (Akamai's libakamaibmp.so raises an uncatchable SIGILL on load), so a
        # source-built shim replaces it, hash-checked like every other input.
        if not webview_files:
            raise ValueError('A bionic shim build replaces the WebView input shim: pass --webview-input')
        shim_root = args.bionic_shim_build.resolve()
        shim_report = json.loads((shim_root / 'artifacts.json').read_text())
        shim_entry = shim_report['artifacts']['libwebview_bionic_shim.so']
        shim_path = shim_root / 'libwebview_bionic_shim.so'
        if shim_report.get('errors') or digest(shim_path) != shim_entry['sha256']:
            raise ValueError('Changed or failed bionic shim build')
        webview_files['webview-t-lib/libwebview_bionic_shim.so'] = {
            'sha256': shim_entry['sha256'], 'provenance': 'source-built'}
        webview_paths['webview-t-lib/libwebview_bionic_shim.so'] = shim_path
    source_webview_report = None
    if args.source_webview_build:
        if not webview_files:
            raise ValueError('Source WebView candidate requires the locked device input as a control')
        source_webview_root = args.source_webview_build.resolve()
        source_webview_report_path = source_webview_root / 'artifacts.json'
        source_webview_report = json.loads(source_webview_report_path.read_text())
        source_names = {
            'webview-t.apk',
            'webview-t-lib/libandroid.so',
            'webview-t-lib/libjnigraphics.so',
            'webview-t-lib/libwebviewchromium.so',
            'webview-t-lib/libwebview_bionic_shim.so',
            'webview-t-lib/libwebviewchromium_plat_support.so',
        }
        if (source_webview_report.get('errors')
                or source_webview_report.get('schema') != 'a2hlab-source-webview/v4'
                or source_webview_report.get('package') != 'com.android.webview'
                or source_webview_report.get('version_name') != '109.0.5414.123'
                or source_webview_report.get('native_engine_source_build') is not True
                or source_webview_report.get('native_engine_boundary_transformed') is not True
                or source_webview_report.get('boundary_source_build') is not True
                or source_webview_report.get('platform_support_source_build') is not True
                or set(source_webview_report.get('artifacts', {})) != source_names):
            raise ValueError('Unexpected source WebView build report')
        for name in source_names:
            path = source_webview_root / name
            entry = source_webview_report['artifacts'][name]
            if (not path.resolve().is_relative_to(source_webview_root)
                    or digest(path) != entry['sha256'] or path.stat().st_size != entry['bytes']):
                raise ValueError('Changed source WebView artifact: ' + name)
            webview_paths[name] = path
            webview_files[name] = {
                'sha256': entry['sha256'],
                'provenance': 'source-built',
                'source_build_report_sha256': digest(source_webview_report_path),
            }
    available_net_basenames = available_native_basenames | {
        Path(name).name for name in webview_files if name.endswith('.so')
    }
    if any(not re.fullmatch(r'lib[a-zA-Z0-9_.+-]+\.so', name)
           or name not in available_net_basenames for name in native_net_targets):
        raise ValueError('Android network ABI target is not a pinned staged DSO')
    output.mkdir(parents=True)
    state = {'scope': 'isolated source stack application startup probe', 'source_ui_accepted': False,
             'full_source_closure': False, 'framework_report_sha256': digest(args.framework_report),
             'app_input_sha256': digest(args.app_input / 'app-input.json'), 'parent': None, 'child': None}
    if trace:
        state['jni_registration_trace'] = {
            'enabled': True,
            'run_id': args.trace_run_id,
            'scenario': args.trace_scenario,
            'apk_sha256': app['apk_sha256'],
            'runtime_lock_id': trace['runtime_lock_id'],
            'runtime_lock_sha256': digest(args.trace_runtime_lock),
            'libart_sha256': staged_bridges['libart.so'],
            'source': 'ClassLinker::RegisterNative after effective entrypoint installation',
        }
    if webview_files:
        state['webview_payload'] = {
            'complete_build_input_closure': False,
            'files': webview_files,
        }
        device_files = {name: entry for name, entry in webview_files.items()
                        if entry['provenance'] == 'device-captured'}
        if device_files:
            state['webview_device_input'] = {
                'provenance': 'device-captured',
                'complete_build_input_closure': False,
                'lock_sha256': digest(webview_lock_path),
                'files': device_files,
            }
        if source_webview_report is not None:
            state['webview_source_build'] = {
                'report_sha256': digest(source_webview_report_path),
                'native_engine_source_build': True,
                'native_engine_boundary_transformed': True,
                'boundary_source_build': True,
                'java_runtime_dependencies_source_complete':
                    source_webview_report['java_runtime_dependencies_source_complete'],
                'complete_build_input_closure':
                    source_webview_report['complete_build_input_closure'],
                'files': {name: entry for name, entry in webview_files.items()
                          if entry['provenance'] == 'source-built'},
            }
    if native_targets:
        if not webview_files:
            raise ValueError('Android ABI namespace currently requires the locked bionic boundary input')
        state['android_native_namespace'] = {
            'selection': 'explicit APK DSO basenames',
            'targets': native_targets,
            'bionic_boundary': 'webview-t-lib/libwebview_bionic_shim.so',
            'bionic_boundary_provenance':
                webview_files['webview-t-lib/libwebview_bionic_shim.so']['provenance'],
        }
    if native_net_targets:
        if 'libandroid_native_network_compat.so' not in framework.get('files', {}):
            raise ValueError('Android network ABI targets require the source translator')
        state['android_native_network_boundary'] = {
            'selection': 'explicit Android DSO basenames',
            'targets': native_net_targets,
            'translator': 'libandroid_native_network_compat.so',
            'translator_provenance': 'source-built',
        }

    def save():
        (output / 'device-report.json').write_text(json.dumps(state, indent=2) + '\n')

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
        with (output / 'commands.jsonl').open('a') as journal:
            journal.write(json.dumps({'command': command, 'output': text}) + '\n')
        match = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if not match or int(match[1]):
            raise RuntimeError(text)
        return text[:match.start()]

    def send(path, remote):
        # A flat 55 s held over USB and failed over wireless debugging: the ~200 MB launch archive
        # moves at roughly 2 MB/s there, so the same send timed out for one app and scraped through
        # for another. Size the limit from the file instead, assuming no better than 512 KiB/s.
        seconds = max(55, path.stat().st_size // (512 * 1024) + 30)
        call(['file', 'send', path.name, remote], cwd=path.parent, timeout=seconds)
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
    archive = output / 'launch-inputs.tar'
    with tarfile.open(archive, 'w') as tar:
        for name in sorted(app_files):
            tar.add(args.app_input / name, arcname=name, recursive=False)
        if webview_files:
            for name in sorted(webview_files):
                tar.add(webview_paths[name], arcname=name, recursive=False)
    send(archive, stage + '/' + archive.name)
    shell('tar -xf ' + stage + '/' + archive.name + ' -C ' + runtime)
    expected_app = {runtime + '/' + n: e['sha256'] for n, e in app_files.items()}
    if hashes(sorted(expected_app)) != expected_app:
        raise ValueError('Candidate original APK files changed')
    if webview_files:
        expected_webview = {runtime + '/' + n: e['sha256'] for n, e in webview_files.items()}
        if hashes(sorted(expected_webview)) != expected_webview:
            raise ValueError('Candidate WebView files changed')
    shell('mkdir -p ' + runtime + '/private-tmp/asx ' + runtime + '/data/dalvik-cache/arm64 ' +
          runtime + '/app-data/' + package + '/code_cache/art-volatile ' +
          runtime + '/app-data/' + package + '/app_webview ' + runtime + '/app-data/' + args.host +
          (' ' + runtime + '/webview-t-data' if webview_files else '') +
          ' && chown -R ' + str(uid) + ':' + str(uid) + ' ' + runtime +
          ' && chmod 755 ' + runtime + '/appspawn-x')
    # The app's data directory is <runtime>/app-data/<package>: source_app_namespace mounts
    # <runtime>/app-data over /data/data inside the child, so the host's /data/data is never seen.
    # It inherits the host bundle's appdat label, and OpenHarmony denies app processes fifo_file
    # creation there, which Android allows (Realm's .note pipe fails with EACCES under enforcing
    # SELinux). data_app_el2_file, the label of the el2 base directory, grants hap domains dir,
    # file, sock_file and fifo_file, so the app's tree is relabelled; lnk_file stays denied there
    # as well (neverallow for hap_domain).
    shell('chcon -R u:object_r:data_app_el2_file:s0 ' + runtime + '/app-data/' + package)
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
    if webview_files:
        search.append(logical + '/webview-t-lib')
    env = {'WESTLAKE_RUNTIME_ROOT': logical, 'LD_LIBRARY_PATH': ':'.join(search),
           'WESTLAKE_SOURCE_LOG_STDERR': '1',
           'WESTLAKE_SOURCE_PACKAGE': '1',
           'WESTLAKE_TRACE_NATIVE_LOADER': '1',
           'ASX_RUNTIME_OWNER_UID': str(uid), 'ASX_LAUNCH_PKG': package,
           'ASX_NATIVE_LIB_DIR': logical + '/lib/arm64-v8a',
           'ASX_APK_PATH': logical + '/' + base_apk,
           'ASX_SPLIT_APK_PATHS': ':'.join(logical + '/' + name for name in sorted(split_apks)),
           'ASX_LAUNCH_ACTIVITY': launch_activity,
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
    if trace:
        env.update({
            'WESTLAKE_TRACE_JNI_REGISTRATION': '1',
            'WESTLAKE_TRACE_RUN_ID': args.trace_run_id,
            'WESTLAKE_TRACE_SCENARIO': args.trace_scenario,
            'WESTLAKE_TRACE_APK_SHA256': app['apk_sha256'],
            'WESTLAKE_TRACE_RUNTIME_LOCK_ID': trace['runtime_lock_id'],
            'WESTLAKE_TRACE_LIBART_SHA256': staged_bridges['libart.so'],
        })
    preloads = []
    if native_net_targets:
        preloads.append(logical + '/libandroid_native_network_compat.so')
        env.update({
            'WESTLAKE_ANDROID_NATIVE_NET_TARGETS': ':'.join(native_net_targets),
            'WESTLAKE_TRACE_ANDROID_NATIVE_NET': '1',
        })
    if webview_files:
        preloads.append(logical + '/webview-t-lib/libwebview_bionic_shim.so')
        env.update({
            'ASX_WEBVIEW_APK': logical + '/webview-t.apk',
            'ASX_WEBVIEW_LIB_DIR': logical + '/webview-t-lib',
            'ASX_WEBVIEW_DATA_DIR': logical + '/webview-t-data',
        })
    if preloads:
        env['LD_PRELOAD'] = ':'.join(preloads)
    if native_targets:
        # Android NDK libc++ uses std::__ndk1 while the OH platform C++ runtime
        # uses a different ABI. Route only launcher-selected APK DSOs through
        # ART's generic isolated namespace and let their DT_NEEDED graph select
        # the APK's own libc++_shared.so. The bionic boundary is preloaded in
        # that namespace; OH-native framework DSOs stay in the parent namespace.
        namespace_search = [logical + '/lib/arm64-v8a', logical + '/webview-t-lib',
                            logical, '/system/lib64/ndk', '/system/lib64/platformsdk',
                            '/system/lib64/chipset-sdk-sp', '/system/lib64']
        env.update({
            'WESTLAKE_ANDROID_NATIVE_TARGETS': ':'.join(native_targets),
            'WESTLAKE_ANDROID_NATIVE_SEARCH_PATH': ':'.join(namespace_search),
            'WESTLAKE_ANDROID_NATIVE_INHERIT':
                'libc.so:libdl.so:libm.so:libz.so:liblog.so',
            'WESTLAKE_ANDROID_NATIVE_PRELOAD':
                logical + '/webview-t-lib/libwebview_bionic_shim.so',
        })
    if 'liboh_permission_queries.so' in framework['files']:
        env['WESTLAKE_PERMISSION_HELPER_PATH'] = logical + '/liboh_permission_queries.so'
    if 'liboh_account_state.so' in framework['files']:
        env['WESTLAKE_ACCOUNT_HELPER_PATH'] = logical + '/liboh_account_state.so'
    if 'liboh_connectivity_state.so' in framework['files']:
        env['WESTLAKE_CONNECTIVITY_HELPER_PATH'] = logical + '/liboh_connectivity_state.so'
    for item in args.runtime_env:
        key, separator, value = item.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError('--runtime-env wants KEY=VALUE, got ' + item)
        if key in env:
            raise ValueError('--runtime-env may not replace ' + key + ', which the launcher sets')
        env[key] = value
    if args.runtime_env:
        state['runtime_env'] = sorted(args.runtime_env)
        save()
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
    stream_env = ('WL_TOUCH_STREAM=1 WL_TOUCH_STREAM_CLICK=1 '
                  if args.touch_mode == 'stream' else '')
    shell('setsid env ' + stream_env + 'WL_TOUCH_COORD_GAIN=1 ' +
          stage + '/touchfwd ' + touch_device + ' </dev/null >' + stage +
          '/touchfwd.log 2>&1 & exit 0')
    time.sleep(1)
    state['touch'] = {'device': touch_device, 'channel': box, 'mode': args.touch_mode,
                      'forwarder_pid': shell('pidof touchfwd; exit 0').strip()}
    save()
    print('SOURCE_APP_SPAWNED', json.dumps({k: state[k] for k in ['parent', 'child', 'stage', 'runtime']}), flush=True)


if __name__ == '__main__':
    main()
