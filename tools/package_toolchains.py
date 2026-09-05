#!/usr/bin/env python3
"""One-time deterministic packaging of verified redistributable toolchain inputs."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from bootstrap_sdk import ROOT, digest, fingerprint


def package(root, target, omit):
    inventory = fingerprint(root)['files']
    excluded = {name: value for name, value in inventory.items() if omit(name)}
    selected = {name: value for name, value in inventory.items() if name not in excluded}
    expected = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as raw, gzip.GzipFile(fileobj=raw, filename='', mode='wb', mtime=0, compresslevel=6) as zipped:
        with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(selected):
                path = root / name
                item = archive.gettarinfo(str(path), name)
                item.uid = item.gid = 0
                item.uname = item.gname = ''
                item.mtime = 0
                item.pax_headers = {}
                if item.isfile():
                    item.mode = 0o755 if selected[name]['executable'] else 0o644
                    with path.open('rb') as stream:
                        archive.addfile(item, stream)
                elif item.issym():
                    item.mode = 0o777
                    archive.addfile(item)
                else:
                    raise ValueError('Unexpected package member: ' + name)
    return {'path': target.name, 'sha256': digest(target), 'bytes': target.stat().st_size,
            'tree_sha256': expected, 'file_count': len(selected), 'excluded': excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--original-index', type=Path, required=True,
                        help='Published toolchains/index.json with original input provenance')
    args = parser.parse_args()
    workspace, repository = args.workspace.resolve(), args.repository.resolve()
    lock = {key: entry['original'] for key, entry in
            json.loads(args.original_index.read_text())['packages'].items()}
    index = {'schema': 1, 'packages': {}}
    names = [('ohos-sdk', 'ohos-sdk', 'ohos-sdk-6.1.0.31-build-inputs.tar.gz'),
             ('platform-clang', 'clang-15', 'ohos-clang-15.0.4-81cdec-build-inputs.tar.gz')]
    for key, folder, filename in names:
        source = workspace / 'toolchains' / folder
        actual = fingerprint(source)['sha256']
        if actual != lock[key]['tree_sha256']:
            raise ValueError('Original toolchain tree drift: ' + folder)

        def omit(name):
            if key != 'ohos-sdk':
                return False
            return (Path(name).suffix.lower() in {'.p12', '.pfx', '.jks', '.keystore', '.key', '.pem'}
                    or name in {'toolchains/libselinux.so', 'toolchains/libsepol.so', 'toolchains/diff'})

        record = package(source, repository / 'artifacts' / filename, omit)
        record['path'] = 'artifacts/' + filename
        record['original'] = {'url': lock[key]['url'], 'sha256': lock[key]['sha256'],
                              'tree_sha256': actual, 'bytes': lock[key]['bytes']}
        index['packages'][key] = record
        for path in source.glob('*/NOTICE.txt') if key == 'ohos-sdk' else [source / 'NOTICE']:
            target = repository / 'notices' / folder / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        print('PACKAGED', key, record['bytes'], record['sha256'], 'excluded=' + str(len(record['excluded'])), flush=True)
    (repository / 'index.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
