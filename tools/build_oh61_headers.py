#!/usr/bin/env python3
"""Generate OH 6.1 bridge interfaces and unpack its pinned JsonCpp source."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from bootstrap_sdk import ROOT, digest
from install_toolchains import extract_tar
from rebuild import verify_sources, verify_toolchains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    record = {'sources': verify_sources(workspace, ROOT / 'oh61-dependencies.lock.json'),
              'toolchains': verify_toolchains(workspace, False), 'inputs': {},
              'commands': [], 'artifacts': {}, 'scope': 'source bridge compile headers'}
    compiler = workspace / 'toolchains/ohos-sdk/toolchains/idl'
    record['compiler_sha256'] = digest(compiler)
    output.mkdir(parents=True)
    source = workspace / 'android-source'
    archive = source / 'oh-jsoncpp/jsoncpp-1.9.6.tar.gz'
    record['inputs'][str(archive.relative_to(workspace))] = digest(archive)
    extract_tar(archive, output / 'jsoncpp')
    interfaces = [source / 'oh-bundle-framework/interfaces/inner_api/appexecfwk_core' / name
                  for name in ['IBundleMgrExt.idl', 'IVerifyManager.idl']]
    imf = source / 'oh-imf/frameworks/native'
    for component in ['inputmethod_controller', 'inputmethod_ability']:
        for path in sorted((imf / component).glob('*.idl')):
            record['inputs'][str(path.relative_to(workspace))] = digest(path)
            if path.name != 'InputMethodClientTypes.idl':
                interfaces.append(path)
    env = dict(os.environ, LC_ALL='C', TZ='UTC', SOURCE_DATE_EPOCH='1772755200')
    for path in interfaces:
        record['inputs'][str(path.relative_to(workspace))] = digest(path)
        target = output / 'idl' / path.stem
        target.mkdir(parents=True)
        command = [str(compiler), '--intf-type', 'sa', '--gen-cpp', '-c', str(path), '-d', str(target)]
        record['commands'].append(command)
        subprocess.run(command, env=env, check=True)
        if not list(target.glob('*.h')):
            raise ValueError('IDL compiler produced no headers: ' + str(path))
    # Separate output directories preserve interface import provenance. Include
    # duplicate generated definitions only when they are byte-identical.
    headers = {}
    for path in sorted((output / 'idl').rglob('*.h')):
        if path.name in headers and headers[path.name] != digest(path):
            raise ValueError('Conflicting generated interface: ' + path.name)
        headers[path.name] = digest(path)
    record['include_directories'] = ['jsoncpp/jsoncpp-1.9.6/include']
    record['include_directories'] += [str(p.relative_to(output)) for p in sorted((output / 'idl').iterdir())]
    for path in sorted(output.rglob('*')):
        if path.is_file():
            record['artifacts'][str(path.relative_to(output))] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    (output / 'artifacts.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    print('OH61_HEADERS', len(headers), 'INTERFACES', len(interfaces), flush=True)


if __name__ == '__main__':
    main()
