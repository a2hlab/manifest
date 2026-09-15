#!/usr/bin/env python3
"""Build the source libmedia_jni entry library for the OH MediaCodec bridge."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--westlake-source', type=Path, required=True)
    parser.add_argument('--bridge-build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    westlake = args.westlake_source.resolve()
    bridge = args.bridge_build.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')

    bridge_report_path = bridge / 'artifacts.json'
    bridge_report = json.loads(bridge_report_path.read_text())
    bridge_library = bridge / 'liboh_adapter_bridge.so'
    bridge_entry = bridge_report.get('artifacts', {}).get(bridge_library.name)
    if (bridge_report.get('errors') or bridge_entry is None
            or digest(bridge_library) != bridge_entry['sha256']):
        raise ValueError('Changed or failed source bridge build')

    source = westlake / 'framework/core/jni/media_jni_entry.c'
    if not source.is_file() or not source.resolve().is_relative_to(westlake):
        raise ValueError('Missing media JNI entry source')
    sdk = workspace / 'toolchains/ohos-sdk/native'
    compiler = sdk / 'llvm/bin/clang'
    readelf = sdk / 'llvm/bin/llvm-readelf'
    compiler_rt = sdk / 'llvm/lib/clang/15.0.4/lib/aarch64-linux-ohos'
    jni_include = workspace / 'android-source/libnativehelper/include_jni'
    output.mkdir(parents=True)
    obj = output / 'media_jni_entry.c.o'
    library = output / 'libmedia_jni.so'
    compile_command = [
        str(compiler), '--target=aarch64-linux-ohos', '--sysroot=' + str(sdk / 'sysroot'),
        '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(jni_include),
        '-c', str(source), '-o', str(obj),
    ]
    link_command = [
        str(compiler), '--target=aarch64-linux-ohos', '--sysroot=' + str(sdk / 'sysroot'),
        '-fuse-ld=lld', '-nostdlib', '-shared', '-Wl,-z,defs',
        '-Wl,--allow-shlib-undefined', '-Wl,--build-id=sha1',
        '-Wl,-soname,libmedia_jni.so', str(compiler_rt / 'clang_rt.crtbegin.o'),
        str(obj), '-Wl,--as-needed', str(bridge_library), '-lc',
        str(compiler_rt / 'libclang_rt.builtins.a'),
        str(compiler_rt / 'clang_rt.crtend.o'), '-o', str(library),
    ]
    with (output / 'compile.log').open('x') as log:
        subprocess.run(compile_command, check=True, stdout=log, stderr=subprocess.STDOUT)
    with (output / 'link.log').open('x') as log:
        subprocess.run(link_command, check=True, stdout=log, stderr=subprocess.STDOUT)
    dynamic = subprocess.check_output([str(readelf), '-d', str(library)], text=True)
    needed = re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic)
    if 'liboh_adapter_bridge.so' not in needed:
        raise ValueError('Media JNI entry did not retain the source bridge dependency')
    record = {
        'scope': 'source OH media JNI load-contract entry; device acceptance pending',
        'source': {'path': str(source.relative_to(westlake)), 'sha256': digest(source)},
        'bridge_build_sha256': digest(bridge_report_path),
        'compiler_sha256': digest(compiler),
        'commands': [compile_command, link_command],
        'artifacts': {
            library.name: {
                'sha256': digest(library),
                'bytes': library.stat().st_size,
                'needed': needed,
            },
        },
        'errors': [],
        'device_accepted': False,
    }
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('SOURCE_MEDIA_JNI_BUILT', record['artifacts'][library.name])


if __name__ == '__main__':
    main()
