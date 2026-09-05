#!/usr/bin/env python3
"""One-time allowlisted source preservation; NOT a full-runtime build recipe.

Copies reviewed tracked source scopes plus explicit local C/C++ overlays. Records
base revisions, complete content fingerprints and local diffs. Never copies an
app, board DSO, object file, boot image, user data, credential or backup file.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from bootstrap_sdk import fingerprint


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def copy_one(source, target, allowed_absolute=()):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        link = os.readlink(source)
        if Path(link).is_absolute():
            if source.resolve() not in allowed_absolute:
                raise ValueError('Absolute source symlink requires manual review: ' + str(source))
            shutil.copy2(source.resolve(), target)
            return
        target.symlink_to(link)
    else:
        shutil.copy2(source, target)
    if not target.is_symlink():
        # Git records one executable bit, not separate owner/group/other bits.
        # Normalize exported modes to match the fingerprint's any-execute model.
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.absolute()
    if out.exists():
        parser.error('--out must be new')
    out.mkdir(parents=True)
    projects = [
        ('aosp14-hwui', 'aosp-14-base', ['libs/hwui', 'NOTICE']),
        ('aosp14-minikin', 'aosp-14-minikin', ['.']),
        ('aosp11-freetype', 'aosp-android-11/external/freetype', ['.']),
        ('aosp11-harfbuzz', 'aosp-android-11/external/harfbuzz_ng', ['.']),
        ('aosp11-webp', 'aosp-android-11/external/webp', ['.']),
    ]
    records = []
    patches = out / 'provenance/patches'
    patches.mkdir(parents=True)
    for name, folder, scopes in projects:
        source, target = source_root / folder, out / name
        names = git(source, 'ls-files', '-z', '--', *scopes).decode().split('\0')
        files = [p for p in names if p]
        for relative in files:
            path = source / relative
            if path.exists() or path.is_symlink():
                copy_one(path, target / relative)
        patch = git(source, 'diff', '--binary', '--full-index', 'HEAD', '--', *scopes)
        patch_path = patches / (name + '.patch')
        patch_path.write_bytes(patch)
        remotes = git(source, 'remote').decode().splitlines()
        remote = 'origin' if 'origin' in remotes else 'aosp'
        record = {'path': name, 'original_location': folder, 'selected_scopes': scopes,
                  'upstream_url': git(source, 'remote', 'get-url', remote).decode().strip(),
                  'upstream_revision': git(source, 'rev-parse', 'HEAD').decode().strip(),
                  'upstream_tree': git(source, 'rev-parse', 'HEAD^{tree}').decode().strip(),
                  'local_patch': str(patch_path.relative_to(out)), 'content': fingerprint(target)}
        records.append(record)
        print('EXPORTED', name, len(record['content']['files']), flush=True)
    local = [
        ('bridge-build-arm64/overlay', 'local/overlay'),
        ('bridge-build-arm64/stubinc', 'local/stubinc'),
        ('bridge-build-arm64/hwui_stubinc', 'local/hwui_stubinc'),
        ('bridge-build/build/skia_compat_headers', 'local/skia_compat_headers'),
        ('bridge-build/aosp_patches/libs/hwui', 'local/hwui-overrides'),
    ]
    allowed = {'.h', '.hpp', '.c', '.cc', '.cpp', '.inl', '.inc', '.patch', '.md', '.bp'}
    for folder, name in local:
        source, target = source_root / folder, out / name
        for path in sorted(source.rglob('*')):
            if path.suffix.lower() in allowed and path.is_file():
                # These generated compatibility headers are preserved as inputs,
                # not misrepresented as having a recovered generator recipe.
                copy_one(path, target / path.relative_to(source), allowed_absolute=[
                    source_root / 'aosp-android-11/external/zlib/zlib.h',
                    source_root / 'aosp-android-11/external/zlib/zconf.h'])
        records.append({'path': name, 'original_location': folder,
                        'selected_suffixes': sorted(allowed), 'content': fingerprint(target)})
    for name in ['libcxx_compat_arm64.h', 'musl_compat.h', 'musl_compat.c']:
        copy_one(source_root / 'bridge-build-arm64' / name, out / 'local' / name)
    for relative in ['openharmony/third_party/skia/LICENSE', 'aosp-14-base/NOTICE']:
        copy_one(source_root / relative, out / 'notices' / relative.replace('/', '__'))
    records.append({'path': 'local', 'content': fingerprint(out / 'local')})
    (out / 'provenance/index.json').write_text(json.dumps(
        {'schema': 1, 'source_preservation_only': True, 'complete_runtime_build': False,
         'device_accepted': False, 'projects': records}, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    main()
