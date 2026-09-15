#!/usr/bin/env python3
"""Stage the content-locked original APK and its ARM64 libraries unchanged.

Application source is not required to build Android/Westlake. This input is
supplied separately and is never used as a framework/compiler dependency.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(apk, output, entry):
    if output.exists():
        raise ValueError('Output must be new: ' + str(output))
    if apk.stat().st_size != entry['bytes'] or digest(apk) != entry['sha256']:
        raise ValueError('Original APK size/SHA256 does not match app-inputs.lock.json')
    output.mkdir(parents=True)
    staged = output / 'toutiao.apk'
    shutil.copyfile(apk, staged)
    # Recheck the bytes consumed, including a source file changed during copy.
    if staged.stat().st_size != entry['bytes'] or digest(staged) != entry['sha256']:
        staged.unlink()
        raise ValueError('APK changed while staging')
    libraries = {}
    prefix = 'lib/' + entry['abi'] + '/'
    with zipfile.ZipFile(staged) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK ZIP entries')
        selected = [info for info in archive.infolist()
                    if info.filename.startswith(prefix) and not info.is_dir()]
        for info in selected:
            relative = PurePosixPath(info.filename)
            if (len(relative.parts) != 3 or '..' in relative.parts or
                    '\\' in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError('Unsafe native library entry: ' + info.filename)
            if not info.filename.endswith('.so'):
                raise ValueError('Unexpected native library entry: ' + info.filename)
        if not selected:
            raise ValueError('Pinned APK has no libraries for ' + entry['abi'])
        for info in selected:
            target = output / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            with target.open('rb') as stream:
                header = stream.read(20)
            # The original APK contains an ARM32 libcvt.so in arm64-v8a.
            # Preserve app bytes; never count that file as an ARM64 provider.
            elf = len(header) == 20 and header[:4] == b'\x7fELF'
            machine = (int.from_bytes(header[18:20],
                       'little' if header[5] == 1 else 'big') if elf else None)
            libraries[info.filename] = {
                'sha256': digest(target), 'bytes': target.stat().st_size,
                'elf_class': header[4] if elf else None, 'elf_machine': machine,
                'aarch64_provider': elf and header[4:6] == b'\x02\x01' and machine == 183}
    record = {'schema': 1, 'application': entry, 'apk_sha256': digest(staged),
              'apk_modified': False, 'native_libraries': libraries,
              'stack_build_input': False, 'device_accepted': False}
    (output / 'app-input.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    entry = json.loads((ROOT / 'app-inputs.lock.json').read_text())['applications']['toutiao']
    try:
        record = prepare(args.apk.resolve(), args.out.absolute(), entry)
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, 'APP_INPUT_REJECTED: ' + str(error) + '\n')
    print('ORIGINAL_APK_VERIFIED', record['apk_sha256'], len(record['native_libraries']))


if __name__ == '__main__':
    main()
