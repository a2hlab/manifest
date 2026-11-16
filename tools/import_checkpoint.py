#!/usr/bin/env python3
"""One-time, source-only import from the reviewed local checkpoint."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OLD = (Path.home() / 'openharmony/.codex-worktrees/toutiao-repro-20260905')
PACKAGE = OLD / 'repro/toutiao-20260904'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    provenance = {}
    for original, row in json.loads((PACKAGE / 'sources.json').read_text()).items():
        source = OLD / row['stored']
        data = source.read_bytes()
        if digest(data) != row['sha256']:
            raise RuntimeError('Checkpoint source drift: ' + original)
        if original.startswith('bridge-build/src/framework/'):
            target = ROOT / 'westlake/framework' / original.removeprefix('bridge-build/src/framework/')
        else:
            target = ROOT / 'westlake/historical/workspace' / original
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError('Refusing to overwrite: ' + str(target))
        shutil.copy2(source, target)
        provenance[str(target.relative_to(ROOT))] = {'sha256': row['sha256'], 'checkpoint_path': row['stored']}
    art = (Path.home() / 'art-latest')
    selected = subprocess.check_output(['git', '-C', str(art), 'ls-files', '-z',
        'Makefile', 'Makefile.ohos-arm64', 'stubs', 'patches', 'ziparchive_hide.map']).decode().split('\0')
    for name in filter(None, selected):
        path = Path(name)
        if path.suffix not in {'.c', '.cc', '.cpp', '.h', '.hpp', '.S', '.s', '.py', '.map', '.inc', '.def', '.java'} and not path.name.startswith('Makefile'):
            continue
        data = subprocess.check_output(['git', '-C', str(art), 'show', 'HEAD:' + name])
        target = ROOT / 'art-build' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError('Refusing to overwrite: ' + str(target))
        target.write_bytes(data)
        provenance[str(target.relative_to(ROOT))] = {'sha256': digest(data), 'checkpoint_commit': '556ed5f88c329f618e367772a5dd0086489389fc', 'checkpoint_path': name}
    target = ROOT / 'westlake/third_party/jni/jni.h'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(Path.home() / 'bridge-build/aosp/libnativehelper/include_jni/jni.h'), target)
    shutil.copy2(str(Path.home() / 'android-to-openharmony-migration/LICENSE'), ROOT / 'westlake/LICENSE')
    shutil.copy2(str(Path.home() / 'aosp-art-15/NOTICE'), ROOT / 'art-build/NOTICE')
    (ROOT / 'manifest/import-provenance.json').write_text(json.dumps(provenance, sort_keys=True, indent=2) + '\n')
    print('IMPORTED_SOURCE_FILES', len(provenance))


if __name__ == '__main__':
    main()
