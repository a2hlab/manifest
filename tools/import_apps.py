#!/usr/bin/env python3
"""One-time source-only host/Pinyin relocation, retaining engine and dictionary provenance."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WESTLAKE = ROOT.parent / 'westlake'
OLD = WESTLAKE / 'historical/workspace/bridge-build-arm64'


def copy(source, target):
    if target.exists():
        raise ValueError('Refusing to overwrite: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def main():
    for name in ['EntryAbility.js', 'Index.js']:
        copy(OLD / 'ime-ability-window-20260904/host' / name, WESTLAKE / 'apps/imehost' / name)
    pinyin = OLD / 'gap-repair-20260904/pinyin'
    for name in ['EntryAbility.js', 'Keyboard.js', 'Settings.js', 'ServiceExtAbility.js',
                 'pinyin_napi.cpp', 'module.json', 'test_controller.js']:
        copy(pinyin / name, WESTLAKE / 'apps/pinyin' / name)
    for source in (pinyin / 'resources').rglob('*'):
        if source.is_file():
            copy(source, WESTLAKE / 'apps/pinyin/resources' / source.relative_to(pinyin / 'resources'))
    upstream = (Path.home() / 'bridge-build-arm64/gap-repair-20260904/pinyin/upstream')
    revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    assert revision == 'cd27df54150e5d96d86757dc7315ead69d469d9b'
    assert not subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'])
    names = subprocess.check_output(['git', '-C', str(upstream), 'ls-files',
        'entry/src/main/cpp/include', 'entry/src/main/cpp/share',
        'entry/src/main/resources/rawfile/dict_pinyin.dat', 'LICENSE'], text=True).splitlines()
    provenance = {'url': 'https://gitee.com/ohos_port/applications_inputmethod.git',
                  'revision': revision, 'files': []}
    for name in names:
        relative = name.removeprefix('entry/src/main/cpp/').removeprefix('entry/src/main/resources/rawfile/')
        target = WESTLAKE / 'third_party/pinyin' / relative
        copy(upstream / name, target)
        provenance['files'].append({'path': relative, 'upstream_path': name,
                                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (WESTLAKE / 'third_party/pinyin/UPSTREAM.json').write_text(json.dumps(provenance, sort_keys=True, indent=2) + '\n')
    print('IMPORTED_APPS_AND_PINYIN', len(names), 'unchanged engine/dictionary/license files')


if __name__ == '__main__':
    main()
