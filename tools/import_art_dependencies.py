#!/usr/bin/env python3
"""One-time source/patch export of the reviewed legacy ART support inputs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / 'art-build'
OLD_AOSP = Path('/home/dspfac/aosp-android-11')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def main():
    project_names = ['art', 'system/core', 'libnativehelper', 'external/zlib',
                     'external/lz4', 'external/vixl', 'external/lzma',
                     'external/icu', 'external/tinyxml2', 'external/fmtlib']
    projects = []
    for name in project_names:
        repo = OLD_AOSP / name
        entry = {'path': 'upstream/aosp-11/' + name,
                 'url': git(repo, 'remote', 'get-url', 'aosp').decode().strip(),
                 'revision': git(repo, 'rev-parse', 'HEAD').decode().strip()}
        patch = git(repo, 'diff', '--binary', 'HEAD')
        if patch:
            path = ROOT / ('patches/aosp-11/' + name.replace('/', '_') + '.patch')
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(patch)
            entry['patch'] = path.relative_to(ROOT).as_posix()
            entry['patch_sha256'] = hashlib.sha256(patch).hexdigest()
        projects.append(entry)
    projects.append({'path': 'upstream/art-15',
                     'url': 'https://github.com/a2hlab/aosp-art-15.git',
                     'revision': '814cc9385f8f8eaba6f4bfd1d723160c2132c76e'})
    (ROOT / 'upstream.lock.json').write_text(json.dumps({'schema': 1, 'projects': projects}, indent=2) + '\n')
    origins = [
        (Path('/home/dspfac/android-to-openharmony-migration/dalvik-port/ohos-sysroot/usr/include'), OUTPUT / 'legacy-sysroot/usr/include'),
        (Path('/home/dspfac/openharmony/third_party/curl/include'), OUTPUT / 'third_party/curl/include'),
    ]
    provenance = []
    for source, target in origins:
        if target.exists():
            raise ValueError('Refusing to overwrite: ' + str(target))
        for src in sorted(source.rglob('*')):
            if src.is_dir():
                continue
            if src.is_symlink():
                raise ValueError('Review symlink before export: ' + str(src))
            dst = target / src.relative_to(source)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            provenance.append({'path': dst.relative_to(OUTPUT).as_posix(),
                               'sha256': hashlib.sha256(dst.read_bytes()).hexdigest(),
                               'original': str(src)})
    licenses = [
        ('/home/dspfac/openharmony/third_party/musl/COPYRIGHT', 'legacy-sysroot/MUSL-COPYRIGHT'),
        ('/home/dspfac/openharmony/third_party/curl/COPYING', 'third_party/curl/COPYING'),
    ]
    for source, name in licenses:
        shutil.copyfile(source, OUTPUT / name)
    (ROOT / 'art-support-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print('EXPORTED', len(provenance), 'source headers;', len(projects), 'pinned source projects')


if __name__ == '__main__':
    main()
