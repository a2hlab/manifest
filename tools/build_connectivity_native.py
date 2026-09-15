#!/usr/bin/env python3
"""Build the source OpenHarmony network-state JNI boundary."""
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
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    westlake = args.westlake_source.resolve()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')

    source = westlake / 'framework/core/jni/oh_connectivity_state.c'
    if not source.is_file() or not source.resolve().is_relative_to(westlake):
        raise ValueError('Missing source connectivity bridge')
    sdk = workspace / 'toolchains/ohos-sdk/native'
    compiler = sdk / 'llvm/bin/clang'
    readelf = sdk / 'llvm/bin/llvm-readelf'
    compiler_rt = sdk / 'llvm/lib/clang/15.0.4/lib/aarch64-linux-ohos'
    jni_include = workspace / 'android-source/libnativehelper/include_jni'
    sdk_lib = sdk / 'sysroot/usr/lib/aarch64-linux-ohos'
    for required in [compiler, readelf, source, jni_include / 'jni.h',
                     sdk_lib / 'libnet_connection.so']:
        if not required.exists():
            raise ValueError('Missing build input: ' + str(required))

    output.mkdir(parents=True)
    obj = output / 'oh_connectivity_state.c.o'
    library = output / 'liboh_connectivity_state.so'
    compile_command = [
        str(compiler), '--target=aarch64-linux-ohos', '--sysroot=' + str(sdk / 'sysroot'),
        '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(jni_include),
        '-c', str(source), '-o', str(obj),
    ]
    link_command = [
        str(compiler), '--target=aarch64-linux-ohos', '--sysroot=' + str(sdk / 'sysroot'),
        '-fuse-ld=lld', '-nostdlib', '-shared', '-Wl,-z,defs', '-Wl,--build-id=sha1',
        '-Wl,-soname,liboh_connectivity_state.so', str(compiler_rt / 'clang_rt.crtbegin.o'),
        str(obj), '-L' + str(sdk_lib), '-Wl,--as-needed', '-lnet_connection', '-lc',
        str(compiler_rt / 'libclang_rt.builtins.a'), str(compiler_rt / 'clang_rt.crtend.o'),
        '-o', str(library),
    ]
    with (output / 'compile.log').open('x') as log:
        subprocess.run(compile_command, check=True, stdout=log, stderr=subprocess.STDOUT)
    with (output / 'link.log').open('x') as log:
        subprocess.run(link_command, check=True, stdout=log, stderr=subprocess.STDOUT)
    dynamic = subprocess.check_output([str(readelf), '-d', str(library)], text=True)
    needed = re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic)
    if 'libnet_connection.so' not in needed:
        raise ValueError('Connectivity bridge did not retain libnet_connection dependency')
    symbols = subprocess.check_output([str(readelf), '--dyn-syms', '--wide', str(library)], text=True)
    jni_symbol = 'Java_adapter_core_OhConnectivityState_nativeSnapshot'
    if jni_symbol not in symbols:
        raise ValueError('Connectivity JNI entry is not exported')
    record = {
        'scope': 'source OH network-state JNI boundary; device acceptance pending',
        'source': {'path': str(source.relative_to(westlake)), 'sha256': digest(source)},
        'compiler_sha256': digest(compiler),
        'commands': [compile_command, link_command],
        'artifacts': {library.name: {'sha256': digest(library),
                                     'bytes': library.stat().st_size, 'needed': needed}},
        'errors': [],
        'device_accepted': False,
    }
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('SOURCE_CONNECTIVITY_JNI_BUILT', record['artifacts'][library.name])


if __name__ == '__main__':
    main()
