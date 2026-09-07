#!/usr/bin/env python3
"""Regenerate prebuilts/SHA256SUMS from the lock, and verify it matches reality.

The lock is the source of truth; this file is a convenience copy in the format
`shasum -a 256 -c` understands. Two records of the same fact drift, so this
regenerates rather than edits, and refuses if the lock and the files on disk
disagree -- there is no point writing a checksum file from a lock that is
already wrong.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

HEADER = """# SHA256SUMS for manifest/prebuilts
#
# Generated from the "prebuilts" array in sources.lock.json -- that array is
# the source of truth and tools/verify_prebuilts.py is what enforces it. This
# file exists so the checksums can be handed to `shasum -a 256 -c` by anyone
# who has the files but not the tooling.
#
# Regenerate:  python3 tools/write_sha256sums.py
# Check:       cd prebuilts && shasum -a 256 -c SHA256SUMS
"""


def main():
    entries = json.loads((ROOT / 'sources.lock.json').read_text())['prebuilts']
    # HEADER ends with a newline; joining it as a list element would leave a
    # blank line, which `shasum -c` reports as improperly formatted.
    lines = [HEADER.rstrip('\n')]
    for entry in sorted(entries, key=lambda e: e['path']):
        path = ROOT / entry['path']
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry['sha256']:
            print('lock disagrees with the file: %s' % entry['path'], file=sys.stderr)
            return 1
        lines.append('%s  %s' % (actual, path.name))
    (ROOT / 'prebuilts/SHA256SUMS').write_text('\n'.join(lines) + '\n')
    print('wrote prebuilts/SHA256SUMS with %d entries' % len(entries))
    return 0


if __name__ == '__main__':
    sys.exit(main())
