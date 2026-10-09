#!/usr/bin/env python3
"""Launch the pinned original APK with verified source outputs and fresh data.

The installed OH window host is a recorded platform prerequisite. A successful
spawn is diagnostic progress, not acceptance of the app's UI or source closure.
"""
import argparse
import hashlib
import io
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



# DT_ANDROID_RELR{,SZ,ENT} -> DT_RELR{,SZ,ENT}. lld writes Android's own tag numbers for RELR on
# Android targets; the encoding is the standard one. OH's musl applies DT_RELR (its own libraries
# carry it) and DT_ANDROID_RELA, but not these tags, so the pointers they cover kept their
# link-time values and Facebook, Instagram and Messenger died calling an INIT_ARRAY entry.
ANDROID_RELR_TAGS = {0x6FFFE000: 36, 0x6FFFE001: 35, 0x6FFFE003: 37}


def android_relr_retagged(path):
    """The library's bytes with DT_ANDROID_RELR* renamed to DT_RELR*, or None if it has none."""
    data = bytearray(path.read_bytes())
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        return None
    phoff = int.from_bytes(data[0x20:0x28], 'little')
    count = int.from_bytes(data[0x38:0x3a], 'little')
    changed = False
    for index in range(count):
        header = phoff + index * 56
        if int.from_bytes(data[header:header + 4], 'little') != 2:  # PT_DYNAMIC
            continue
        offset = int.from_bytes(data[header + 8:header + 16], 'little')
        size = int.from_bytes(data[header + 32:header + 40], 'little')
        tags = [int.from_bytes(data[offset + i:offset + i + 8], 'little') for i in range(0, size, 16)]
        if 36 in tags:
            return None
        for position in range(0, size, 16):
            tag = int.from_bytes(data[offset + position:offset + position + 8], 'little')
            if tag == 0:
                break
            if tag in ANDROID_RELR_TAGS:
                data[offset + position:offset + position + 8] = ANDROID_RELR_TAGS[tag].to_bytes(8, 'little')
                changed = True
    return bytes(data) if changed else None

# The board's cache of launch inputs that are the same from one launch to the next, one file per
# content hash (--input-cache). Every launch sent the WebView payload (185 MB) and any runtime
# library overrides with the app, about 40 s over wireless hdc for files that had not changed; the
# launcher's cleanup removes each launch's stage and runtime, so nothing else kept them. A file
# enters the cache only after its hash checks, and every copy taken from it is checked again in the
# runtime, as a sent file is. Entries unused for three days are dropped.
INPUT_CACHE = '/data/local/tmp/a2hlab-input-cache'
INPUT_CACHE_DAYS = 3

# Dynamic tags init_array_sanitized reads. A library relocated by Android's packed format
# (DT_ANDROID_REL/RELA) is left alone: which slots its relocations cover is not decoded here.
DT_RELA, DT_RELASZ, DT_RELAENT = 7, 8, 9
DT_INIT_ARRAY, DT_FINI_ARRAY, DT_INIT_ARRAYSZ, DT_FINI_ARRAYSZ = 25, 26, 27, 28
ANDROID_PACKED_TAGS = {0x6000000F, 0x60000010, 0x60000011, 0x60000012}


def init_array_sanitized(data):
    """The library's bytes with null and -1 entries dropped from its init and fini arrays, or None if
    it has none.

    Bionic skips such entries (soinfo::call_array); OH's musl calls them, so the load jumps to
    address 0 (pc 0 from do_init_fini). Obfuscators null an initializer after it runs: TikTok ships
    eight libraries like that. ART's OpenNativeLibrary drops them from a library it loads, but not
    from one the loader brings in as a dependency (TikTok's libttffmpeg.so, under libttmverify.so),
    so every packaged library is fixed here. The entries left keep their order; one that moves
    takes its RELA relocation with it.
    """
    data = bytearray(data)
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        return None
    u64 = lambda at: int.from_bytes(data[at:at + 8], 'little')
    phoff, count = u64(0x20), int.from_bytes(data[0x38:0x3a], 'little')
    loads, dynamic = [], None
    for index in range(count):
        header = phoff + index * 56
        kind = int.from_bytes(data[header:header + 4], 'little')
        if kind == 1:  # PT_LOAD: (vaddr, file offset, file size)
            loads.append((u64(header + 16), u64(header + 8), u64(header + 32)))
        elif kind == 2:
            dynamic = (u64(header + 8), u64(header + 32))
    if dynamic is None:
        return None

    def offset_of(vaddr):
        for start, offset, size in loads:
            if start <= vaddr < start + size:
                return offset + vaddr - start
        return None

    tags = {}
    for position in range(dynamic[0], dynamic[0] + dynamic[1], 16):
        tag = u64(position)
        if tag == 0:
            break
        tags.setdefault(tag, (position, u64(position + 8)))
    if ANDROID_PACKED_TAGS & set(tags):
        return None
    relocations = []  # file offsets of RELA entries
    if DT_RELA in tags and DT_RELASZ in tags:
        start, size = offset_of(tags[DT_RELA][1]), tags[DT_RELASZ][1]
        entry = tags.get(DT_RELAENT, (0, 24))[1]
        if start is not None and entry:
            relocations = list(range(start, start + size, entry))
    changed = False
    for array, size_tag in ((DT_INIT_ARRAY, DT_INIT_ARRAYSZ), (DT_FINI_ARRAY, DT_FINI_ARRAYSZ)):
        if array not in tags or size_tag not in tags:
            continue
        base, slots = tags[array][1], tags[size_tag][1] // 8
        start = offset_of(base)
        if start is None or not slots:
            continue
        relocated = {}
        for entry in relocations:
            target = u64(entry)
            if base <= target < base + slots * 8 and (target - base) % 8 == 0:
                relocated[(target - base) // 8] = entry
        values = [u64(start + 8 * i) for i in range(slots)]
        kept = [i for i in range(slots) if i in relocated or values[i] not in (0, 0xFFFFFFFFFFFFFFFF)]
        if len(kept) == slots:
            continue
        # An entry without a RELA relocation is RELR-relocated in place (or absolute): it cannot
        # move, so only trailing entries are dropped then.
        if any(new != old and old not in relocated for new, old in enumerate(kept)):
            kept = list(range(max(kept) + 1)) if kept else []
            if len(kept) == slots:
                continue
        for new, old in enumerate(kept):
            if new == old:
                continue
            data[start + 8 * new:start + 8 * new + 8] = values[old].to_bytes(8, 'little')
            if old in relocated:
                data[relocated[old]:relocated[old] + 8] = (base + 8 * new).to_bytes(8, 'little')
        for slot in range(len(kept), slots):
            data[start + 8 * slot:start + 8 * slot + 8] = bytes(8)
        position = tags[size_tag][0]
        data[position + 8:position + 16] = (8 * len(kept)).to_bytes(8, 'little')
        changed = True
    return bytes(data) if changed else None


def loader_compat_bytes(path):
    """The library's bytes as the board's loader needs them, or None if it needs no change, and
    which changes were made."""
    retagged = android_relr_retagged(path)
    sanitized = init_array_sanitized(retagged if retagged is not None else path.read_bytes())
    changes = (['DT_ANDROID_RELR'] if retagged is not None else []) + (['null init/fini entries'] if sanitized else [])
    return (sanitized or retagged), changes


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
    parser.add_argument('--app-oat-dir', type=Path,
                        help='host-compiled ART code for the app (<app>.odex and <app>.vdex, optionally '
                             '<app>.art), staged as oat/arm64/<app>.* beside the APK, where ART looks first')
    parser.add_argument('--runtime-library-build', type=Path,
                        help='build_android_native.py output whose --runtime-library entries replace '
                             "the framework stage's copies in this launch only (a fix tried before a deploy)")
    parser.add_argument('--runtime-library', action='append', default=[], metavar='NAME',
                        help='library of --runtime-library-build to use in place of the staged one. Repeatable')
    parser.add_argument('--input-cache', action='store_true',
                        help='stage the WebView files and runtime library overrides from a cache on the '
                             'board, keyed by content, and send only the files it lacks (' + INPUT_CACHE + ')')
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
    parser.add_argument('--android-native-net-app-libraries', action='store_true',
                        help='preload the network ABI translation for libraries the app writes and '
                             'loads at run time (SoLoader/superpack), which no --android-native-net-target '
                             'can name in advance')
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
    # A manifest may name its classes relative to the package (Emacs's ".EmacsLauncherPreferencesActivity",
    # built without Gradle's manifest merger); Android's parser expands them, and a launch by the
    # relative name failed in ClassNotFoundException.
    if launch_activity.startswith('.'):
        launch_activity = package + launch_activity
    elif '.' not in launch_activity:
        launch_activity = package + '.' + launch_activity
    if not re.fullmatch(r'[a-zA-Z0-9_.$]+', launch_activity):
        raise ValueError('Invalid launch activity: ' + launch_activity)
    # Split APKs carry no code, but the density and language splits own the
    # resources: McDonald's keeps 886 drawables and its own resources.arsc in
    # split_config.xxxhdpi.apk. Every split must reach the asset manager or the
    # app comes up unable to resolve most of its own resources.
    # Each split goes on the board under the name Android installs it with, split_<name>.apk:
    # Facebook's SoLoader picks its native-library split by a path ending split_config.<abi>.apk
    # and otherwise reads the base APK, which carries no libraries (Threads).
    split_sources = {'split_' + name: item['staged'] for name, item in (app.get('splits') or {}).items()}
    split_apks = {'split_' + name: {'sha256': item['sha256']}
                  for name, item in (app.get('splits') or {}).items()}
    app_files = {base_apk: {'sha256': app['apk_sha256']}, **split_apks, **app['native_libraries']}
    # Compiled code for the app, made on the host against the deployed boot image: without it ART has
    # only the interpreter, since OH's policy denies an app domain the executable memory a JIT needs.
    oat_files = {}
    if args.app_oat_dir:
        for ext in ('odex', 'vdex', 'art'):
            path = args.app_oat_dir / (args.app + '.' + ext)
            if path.is_file():
                oat_files['oat/arm64/' + args.app + '.' + ext] = path.resolve()
        if not {'oat/arm64/' + args.app + '.odex', 'oat/arm64/' + args.app + '.vdex'} <= set(oat_files):
            raise ValueError('--app-oat-dir needs ' + args.app + '.odex and ' + args.app + '.vdex')
    for name, entry in app_files.items():
        path = args.app_input.resolve() / split_sources.get(name, name)
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
        # The NDK libraries the shim build stages beside it, on the Android namespace's path:
        # libaaudio.so, a name for DT_NEEDED whose entry points the shim itself exports.
        for name, entry in sorted(shim_report['artifacts'].items()):
            if name == 'libwebview_bionic_shim.so':
                continue
            path = shim_root / name
            if (not re.fullmatch(r'lib[a-zA-Z0-9_.+-]+\.so', name)
                    or 'webview-t-lib/' + name in webview_files
                    or digest(path) != entry['sha256']):
                raise ValueError('Changed or failed bionic shim build: ' + name)
            webview_files['webview-t-lib/' + name] = {
                'sha256': entry['sha256'], 'provenance': 'source-built'}
            webview_paths['webview-t-lib/' + name] = path
    runtime_overrides = {}
    if args.runtime_library:
        if not args.runtime_library_build:
            raise ValueError('--runtime-library needs --runtime-library-build')
        build_root = args.runtime_library_build.resolve()
        build_report = json.loads((build_root / 'artifacts.json').read_text())
        for name in args.runtime_library:
            entry = build_report['artifacts'].get(name)
            path = build_root / 'lib' / name
            if (entry is None or name not in framework['files'] or build_report.get('errors')
                    or digest(path) != entry['sha256']):
                raise ValueError('Runtime library override is not a built, staged library: ' + name)
            runtime_overrides[name] = path
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

    def stage_from_cache(files, runtime, stage):
        """Copies files (runtime name -> local path) into runtime from the board's input cache, after
        sending the ones the cache lacks. Returns which names were sent and which were reused."""
        sums = {name: digest(path) for name, path in files.items()}
        shell('mkdir -p ' + INPUT_CACHE + ' && rm -rf ' + INPUT_CACHE + '/.incoming')
        present = set(shell('ls -1 ' + INPUT_CACHE).split())
        missing = {}
        for name, path in sorted(files.items()):
            if sums[name] not in present:
                missing.setdefault(sums[name], path)
        if missing:
            bundle = output / 'input-cache.tar'
            with tarfile.open(bundle, 'w') as tar:
                for value, path in sorted(missing.items()):
                    tar.add(path, arcname=value, recursive=False)
            send(bundle, stage + '/' + bundle.name)
            incoming = INPUT_CACHE + '/.incoming'
            shell('mkdir ' + incoming + ' && tar -xf ' + stage + '/' + bundle.name + ' -C ' + incoming)
            arrived = {incoming + '/' + value: value for value in missing}
            if hashes(sorted(arrived)) != arrived:
                raise ValueError('Changed transfer into the input cache')
            shell('mv ' + ' '.join(sorted(arrived)) + ' ' + INPUT_CACHE + '/ && rmdir ' + incoming)
            bundle.unlink()
        directories = sorted({str(Path(runtime + '/' + name).parent) for name in files})
        commands = ['mkdir -p ' + ' '.join(map(shlex.quote, directories))]
        commands += ['cp ' + INPUT_CACHE + '/' + sums[name] + ' ' + shlex.quote(runtime + '/' + name)
                     for name in sorted(files)]
        commands.append('touch ' + ' '.join(INPUT_CACHE + '/' + value for value in sorted(set(sums.values()))))
        shell(' && '.join(commands))
        shell('for f in $(find ' + INPUT_CACHE + ' -type f -mtime +' + str(INPUT_CACHE_DAYS) + '); do rm -f "$f"; done; true')
        return {'dir': INPUT_CACHE,
                'sent': sorted(name for name in files if sums[name] in missing),
                'reused': sorted(name for name in files if sums[name] not in missing)}

    def drop_from_cache(files):
        """Removes the cache entries for files whose staged copies failed their hash check."""
        shell('rm -f ' + ' '.join(INPUT_CACHE + '/' + digest(path) for path in files.values()))

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
    # Libraries the board's loader would mishandle travel fixed (see android_relr_retagged and
    # init_array_sanitized); the device copy is checked against the fixed bytes.
    loader_compat, compat_changes = {}, {}
    for name in sorted(app['native_libraries']):
        fixed, changes = loader_compat_bytes(args.app_input / name) if name.endswith('.so') else (None, [])
        if fixed is not None:
            loader_compat[name] = fixed
            compat_changes[name] = changes
            app_files[name] = dict(app_files[name], sha256=hashlib.sha256(fixed).hexdigest())
    for change in ('DT_ANDROID_RELR', 'null init/fini entries'):
        names = sorted(n for n, c in compat_changes.items() if change in c)
        if names:
            print('LOADER_COMPAT %s:' % ('DT_ANDROID_RELR retagged to DT_RELR' if change == 'DT_ANDROID_RELR'
                                         else 'null init/fini entries dropped'), ' '.join(names), flush=True)
    state['android_relr_retagged'] = sorted(n for n, c in compat_changes.items() if 'DT_ANDROID_RELR' in c)
    state['init_array_sanitized'] = sorted(n for n, c in compat_changes.items() if 'null init/fini entries' in c)
    cached = {}
    if args.input_cache:
        cached = {name: webview_paths[name] for name in webview_files}
        cached.update(runtime_overrides)
    with tarfile.open(archive, 'w') as tar:
        for name in sorted(app_files):
            if name in loader_compat:
                info = tar.gettarinfo(args.app_input / name, arcname=name)
                info.size = len(loader_compat[name])
                tar.addfile(info, io.BytesIO(loader_compat[name]))
            else:
                tar.add(args.app_input / split_sources.get(name, name), arcname=name, recursive=False)
        for name in sorted(oat_files):
            tar.add(oat_files[name], arcname=name, recursive=False)
        if webview_files:
            for name in sorted(webview_files):
                if name not in cached:
                    tar.add(webview_paths[name], arcname=name, recursive=False)
        for name in sorted(runtime_overrides):
            if name not in cached:
                tar.add(runtime_overrides[name], arcname=name, recursive=False)
    send(archive, stage + '/' + archive.name)
    shell('tar -xf ' + stage + '/' + archive.name + ' -C ' + runtime)
    if cached:
        state['input_cache'] = stage_from_cache(cached, runtime, stage)
        save()
    expected_app = {runtime + '/' + n: e['sha256'] for n, e in app_files.items()}
    expected_app.update({runtime + '/' + n: digest(p) for n, p in oat_files.items()})
    if hashes(sorted(expected_app)) != expected_app:
        raise ValueError('Candidate original APK files changed')
    if runtime_overrides:
        expected_overrides = {runtime + '/' + n: digest(p) for n, p in runtime_overrides.items()}
        if hashes(sorted(expected_overrides)) != expected_overrides:
            if cached:
                drop_from_cache(runtime_overrides)
            raise ValueError('Runtime library override did not land')
        state['runtime_overrides'] = {n: digest(p) for n, p in runtime_overrides.items()}
        save()
    if webview_files:
        expected_webview = {runtime + '/' + n: e['sha256'] for n, e in webview_files.items()}
        if hashes(sorted(expected_webview)) != expected_webview:
            if cached:
                drop_from_cache({name: webview_paths[name] for name in webview_files})
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
    if native_net_targets or args.android_native_net_app_libraries:
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
            # libwestlake_asset_bridge.so, when the runtime ships it, is shared from the parent: the
            # WebView shim's libandroid here resolves AAsset* through it, and only the parent's copy
            # reaches the initialized framework AssetManager2 (a copy loaded here would not).
            # So is the GL stack: the runtime's libGLESv1_CM.so needs OH's libGLES_mali.z.so, which this
            # namespace's path does not reach (supertuxkart's SDL, routed, failed to load it), and one
            # driver and one OH GL wrapper must serve both namespaces: EGL makes a context current in
            # the parent's, and GL calls from here must see it.
            'WESTLAKE_ANDROID_NATIVE_INHERIT':
                'libc.so:libdl.so:libm.so:libz.so:liblog.so'
                + ':libEGL.so:libGLESv1_CM.so:libGLESv2.so:libGLESv3.so:libGLES_mali.z.so'
                + (':libwestlake_asset_bridge.so' if 'libwestlake_asset_bridge.so' in framework['files'] else ''),
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
