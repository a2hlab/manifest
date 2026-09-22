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


def stage_archive(source, staged, expected):
    """Copy one pinned archive into the output and prove the bytes consumed are the pinned ones."""
    if source.stat().st_size != expected['bytes'] or digest(source) != expected['sha256']:
        raise ValueError('Original archive size/SHA256 does not match app-inputs.lock.json: ' + source.name)
    shutil.copyfile(source, staged)
    # Recheck the bytes consumed, including a source file changed during copy.
    if staged.stat().st_size != expected['bytes'] or digest(staged) != expected['sha256']:
        staged.unlink()
        raise ValueError('Archive changed while staging: ' + source.name)


def prepare(apk, output, entry, app='toutiao', splits=()):
    """Stage a pinned base APK plus any pinned split APKs, and extract every native library.

    Libraries are always extracted to plain files, whatever the archive's compression method.
    OpenHarmony's loader does not understand Android's ``base.apk!/lib/<abi>/x.so`` form, so an
    app packaged with ``extractNativeLibs=false`` (libraries stored uncompressed inside a split,
    as McDonald's is) only loads on the board if this step lays its libraries out on disk.
    """
    if output.exists():
        raise ValueError('Output must be new: ' + str(output))
    pinned_splits = {item['name']: item for item in entry.get('splits', [])}
    given_splits = {path.name: path for path in splits}
    if set(pinned_splits) != set(given_splits):
        raise ValueError('Split APKs given do not match the pinned set: expected '
                         + ', '.join(sorted(pinned_splits)) + '; got ' + ', '.join(sorted(given_splits)))
    output.mkdir(parents=True)
    staged = output / (app + '.apk')
    stage_archive(apk, staged, entry)
    staged_splits = {}
    for name, item in pinned_splits.items():
        target = output / (app + '.' + name)
        stage_archive(given_splits[name], target, item)
        staged_splits[name] = {'staged': target.name, 'sha256': digest(target), 'bytes': target.stat().st_size}
    libraries = {}
    prefix = 'lib/' + entry['abi'] + '/'
    for archive_path in [staged, *(output / item['staged'] for item in staged_splits.values())]:
        with zipfile.ZipFile(archive_path) as archive:
            extract_libraries(archive, archive_path.name, output, prefix, libraries)
    # A pure-Java application (the white-box probes) ships no native code; the lock says so
    # explicitly rather than the stager guessing from an empty archive.
    if not libraries and not entry.get('pure_java'):
        raise ValueError('Pinned APK and splits have no libraries for ' + entry['abi'])
    record = {'schema': 1, 'application': entry, 'apk_sha256': digest(staged),
              'apk_modified': False, 'native_libraries': libraries,
              'stack_build_input': False, 'device_accepted': False}
    if staged_splits:
        record['splits'] = staged_splits
    (output / 'app-input.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def extract_libraries(archive, archive_name, output, prefix, libraries):
    """Extract every lib/<abi>/*.so in one archive to plain files under output."""
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
    for info in selected:
        if info.filename in libraries:
            raise ValueError('Native library packaged twice across archives: ' + info.filename)
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
            'aarch64_provider': elf and header[4:6] == b'\x02\x01' and machine == 183,
            'archive': archive_name,
            'stored_uncompressed': info.compress_type == zipfile.ZIP_STORED}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True, help='pinned base APK')
    parser.add_argument('--split', type=Path, action='append', default=[],
                        help='pinned split APK (e.g. split_config.arm64_v8a.apk); repeat')
    parser.add_argument('--app', default='toutiao', help='application key in app-inputs.lock.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    applications = json.loads((ROOT / 'app-inputs.lock.json').read_text())['applications']
    if args.app not in applications:
        parser.exit(1, 'APP_INPUT_REJECTED: unknown application ' + args.app + '\n')
    entry = applications[args.app]
    try:
        record = prepare(args.apk.resolve(), args.out.absolute(), entry, app=args.app,
                         splits=[path.resolve() for path in args.split])
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, 'APP_INPUT_REJECTED: ' + str(error) + '\n')
    print('ORIGINAL_APK_VERIFIED', record['apk_sha256'], len(record['native_libraries']))


if __name__ == '__main__':
    main()
