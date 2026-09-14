#!/usr/bin/env python3
"""Sign a source Westlake host HAP with published OH development certificates.

These are public upstream sample credentials, for development devices only.
The original third-party Android APK is not an input to this tool.
"""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile
from bootstrap_sdk import digest
from install_java import verify_java


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'host-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / 'host-signing-sources.lock.json').read_text())['projects'][0]
    source = workspace / lock['path']
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != lock['revision'] or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']):
        raise ValueError('Signing input checkout differs from the published pin')
    build = args.host_build.resolve()
    report = json.loads((build / 'artifacts.json').read_text())
    hap = build / 'imehost-unsigned.hap'
    if report.get('errors') or digest(hap) != report['artifacts'][hap.name]['sha256']:
        raise ValueError('Source host HAP differs from its build report')
    with zipfile.ZipFile(hap) as archive:
        module = json.loads(archive.read('module.json'))
        if not module['app']['bundleName'].startswith('org.westlake.'):
            raise ValueError('Only source Westlake host HAPs are supported')
        payload = {n: archive.read(n) for n in archive.namelist()}
    java, java_tree = verify_java(workspace)
    dist = source / 'dist'
    signer = workspace / 'toolchains/ohos-sdk/toolchains/lib/hap-sign-tool.jar'
    output.mkdir(parents=True)
    profile = json.loads((dist / 'UnsgnedReleasedProfileTemplate.json').read_text())
    profile['bundle-info']['bundle-name'] = module['app']['bundleName']
    profile['validity'] = {'not-before': 1767225600, 'not-after': 1924991999}
    profile['acls']['allowed-acls'] = []
    unsigned_profile = output / 'profile.json'
    unsigned_profile.write_text(json.dumps(profile, indent=2) + '\n')
    record = {'development_credentials_public': True, 'production_signing': False,
              'host_build_sha256': digest(build / 'artifacts.json'), 'jdk_tree_sha256': java_tree,
              'signing_source_pin': lock, 'signer_sha256': digest(signer), 'inputs': {},
              'commands': [], 'artifacts': {}, 'errors': []}
    for name in ['OpenHarmony.p12', 'OpenHarmonyApplication.pem', 'OpenHarmonyProfileRelease.pem',
                 'UnsgnedReleasedProfileTemplate.json']:
        record['inputs'][name] = digest(dist / name)
    # The password is the documented public upstream sample password.
    common = ['-signAlg', 'SHA256withECDSA', '-mode', 'localSign',
              '-keystoreFile', str(dist / 'OpenHarmony.p12'),
              '-keyPwd', '123456', '-keystorePwd', '123456']
    tool = [str(java / 'bin/java'), '-jar', str(signer)]
    signed_profile = output / 'profile.p7b'
    signed_hap = output / 'source-host.hap'
    commands = [tool + ['sign-profile', '-keyAlias', 'openharmony application profile release',
                       '-profileCertFile', str(dist / 'OpenHarmonyProfileRelease.pem'),
                       '-inFile', str(unsigned_profile), '-outFile', str(signed_profile)] + common,
                tool + ['sign-app', '-keyAlias', 'openharmony application release',
                        '-appCertFile', str(dist / 'OpenHarmonyApplication.pem'),
                        '-profileFile', str(signed_profile), '-inFile', str(hap),
                        '-outFile', str(signed_hap), '-compatibleVersion',
                        str(module['app']['minAPIVersion']), '-signCode', '1'] + common]
    for index, command in enumerate(commands):
        record['commands'].append(command)
        with (output / ('sign-' + str(index) + '.log')).open('x') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    with zipfile.ZipFile(signed_hap) as archive:
        # Upstream PageInfoGenerator writes the executable-page bitmap during
        # code signing. It is signing metadata, separate from the ArkUI page
        # resource at resources/base/profile/main_pages.json.
        metadata = {'.pages.info'}
        if (set(archive.namelist()) - metadata != set(payload) - metadata or
                any(archive.read(n) != b for n, b in payload.items() if n not in metadata)):
            raise ValueError('Signing changed the source host payload')
        import hashlib
        record['signing_metadata'] = {n: hashlib.sha256(archive.read(n)).hexdigest()
                                      for n in metadata if n in archive.namelist()}
    record['program_and_resources_match_source'] = True
    for path in [unsigned_profile, signed_profile, signed_hap]:
        record['artifacts'][path.name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2) + '\n')
    print('SOURCE_HOST_SIGNED', digest(signed_hap))


if __name__ == '__main__':
    main()
