#!/usr/bin/env python3
"""Verify every preserved runtime source against its committed content inventory."""
import argparse
import json
from pathlib import Path
from bootstrap_sdk import fingerprint, inside


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository.resolve()
    data = json.loads((root / 'provenance/index.json').read_text())
    for entry in data['projects']:
        if fingerprint(inside(root, entry['path'])) != entry['content']:
            raise ValueError('Preserved source drift: ' + entry['path'])
        print('VERIFIED_PRESERVED_SOURCE', entry['path'])
    print('SOURCE_PRESERVATION_ONLY: no full build or device acceptance claim')


if __name__ == '__main__':
    main()
