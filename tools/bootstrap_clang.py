#!/usr/bin/env python3
"""Compatibility entry point: install the compiler from the checked-in LFS archive."""
import argparse
from pathlib import Path
from install_toolchains import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    install(args.workspace, ['platform-clang'], args.out)


if __name__ == '__main__':
    main()
