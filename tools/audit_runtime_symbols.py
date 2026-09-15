#!/usr/bin/env python3
"""Report process symbol gaps against SDK link stubs; never certify a device ABI."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    workspace, runtime = args.workspace.resolve(), args.runtime.resolve()
    sdk = workspace / 'toolchains/ohos-sdk/native'
    nm, readelf = sdk / 'llvm/bin/llvm-nm', sdk / 'llvm/bin/llvm-readelf'
    platform_dir = workspace / 'toolchains/clang-15/lib/aarch64-linux-ohos'
    search = [runtime, sdk / 'sysroot/usr/lib/aarch64-linux-ohos',
              sdk / 'llvm/lib/aarch64-linux-ohos', platform_dir]

    def symbols(path, defined):
        option = '--defined-only' if defined else '--undefined-only'
        output = subprocess.check_output([str(nm), '-D', option, '--format=posix', str(path)], text=True)
        result = set()
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and (defined or parts[1] == 'U'):
                result.add(parts[0].split('@')[0])
        return result

    inventory = json.loads((runtime / 'artifacts.json').read_text())
    roots = []
    for name, entry in inventory['artifacts'].items():
        path = runtime / name
        if not name.endswith('.so') or not path.resolve().is_relative_to(runtime) or digest(path) != entry['sha256']:
            raise ValueError('Invalid/changed declared runtime artifact: ' + name)
        roots.append(path)
    queue, visited, missing_libraries = list(roots), {}, set()
    exports = set()
    while queue:
        path = queue.pop(0)
        if path.name in visited:
            continue
        dynamic = subprocess.check_output([str(readelf), '-d', str(path)], text=True)
        needed = re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic)
        exports |= symbols(path, True)
        visited[path.name] = {'sha256': digest(path), 'needed': needed}
        for name in needed:
            # SDK libc++.so is a linker script for the incompatible __ndk1
            # ABI. libart declares the locked platform __h provider explicitly.
            folders = [platform_dir] if name == 'libc++.so' else search
            candidates = [folder / name for folder in folders if (folder / name).is_file()]
            if not candidates:
                missing_libraries.add(name)
            else:
                queue.append(candidates[0])
    missing = {path.name: sorted(symbols(path, False) - exports) for path in roots}
    platform = platform_dir / 'libc++.so'
    platform_exports = symbols(platform, True)
    after_platform = {name: [sym for sym in names if sym not in platform_exports] for name, names in missing.items()}
    report = {
        'scope': 'SDK link-stub audit, not installed-board runtime-provider verification',
        'sdk_needed_libraries': visited,
        'missing_needed_libraries': sorted(missing_libraries),
        'unresolved_against_needed_sdk_stubs': missing,
        'platform_libcxx': {'sha256': digest(platform),
                           'declared_by_needed': 'libc++.so' in visited},
        'remaining_even_with_platform_libcxx': after_platform,
        'deployment_accepted': False,
        'source_runtime_symbols_complete': not missing_libraries and not any(missing.values()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print('UNRESOLVED_NEEDED', {name: len(items) for name, items in missing.items()})
    print('UNRESOLVED_WITH_PLATFORM_LIBCXX', {name: len(items) for name, items in after_platform.items()})
    if args.require_complete and not report['source_runtime_symbols_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
