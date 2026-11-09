#!/usr/bin/env python3
"""board_global_exports.py <workspace> <board-libraries-dir> <runtime-index.json> -- write <workspace>/board-global-exports.txt
and <workspace>/board-library-names.txt.

The names that libraries global in a launched app's process export: the board's system and vendor
libraries a running app maps (copied from the board into <board-libraries-dir>, keeping their
paths), and the runtime's libraries (the bridge_libraries of a harness runtime index).
probe_source_app.py (--workspace <workspace>) binds, in own_exports_bound_locally, an app library's references to its own
definition of any of these names. The C and C++ runtimes (musl, libc++, libunwind) are left out:
the app keeps binding to the board's copies of those."""
import json
import subprocess
import sys
from pathlib import Path

RUNTIME_LIBRARIES = ('ld-musl', 'libc.so', 'libc++.so', 'libc++_shared.so', 'libunwind', 'libclang_rt')


def exports(readelf, path):
    out = subprocess.run([str(readelf), '--dyn-syms', '-W', str(path)], capture_output=True, text=True).stdout
    names = set()
    for line in out.splitlines():
        field = line.split()
        if len(field) >= 8 and field[0].endswith(':') and field[6] != 'UND' and field[4] in ('GLOBAL', 'WEAK') \
                and field[3] in ('FUNC', 'OBJECT'):
            names.add(field[7].split('@')[0])
    return names


def main():
    workspace = Path(sys.argv[1])
    readelf = workspace / 'toolchains/ohos-sdk/native/llvm/bin/llvm-readelf'
    board, index = Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
    names = set()
    for path in sorted(board.rglob('*.so')):
        if not path.name.startswith(RUNTIME_LIBRARIES):
            names |= exports(readelf, path)
    for library in index['bridge_libraries']:
        if not library['name'].startswith(RUNTIME_LIBRARIES):
            names |= set(library['exported_symbols'])
    out = workspace / 'board-global-exports.txt'
    out.write_text(''.join(n + '\n' for n in sorted(names)))
    print(out, len(names))
    # Every board library's basename, the C and C++ runtimes' included (StarMaker's non-ELF libc++.so
    # shadowed the board's): an APK's non-ELF .so of such a name is not staged (probe_source_app.py).
    library_names = sorted({path.name for path in board.rglob('*.so')})
    out_names = workspace / 'board-library-names.txt'
    out_names.write_text(''.join(n + '\n' for n in library_names))
    print(out_names, len(library_names))


if __name__ == '__main__':
    main()
