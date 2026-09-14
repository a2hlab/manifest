#!/usr/bin/env python3
"""Project the locked Java framework release flags into native profile headers."""
import argparse
import json
from pathlib import Path
import re
from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flag-build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.flag_build.resolve(), args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    report = json.loads((source / 'artifacts.json').read_text())
    for name, entry in report['artifacts'].items():
        path = source / name
        if not path.resolve().is_relative_to(source) or digest(path) != entry['sha256']:
            raise ValueError('Changed framework flags prerequisite: ' + name)
    output.mkdir(parents=True)
    record = {'scope': 'fixed release configuration shared with the Java source build',
              'prerequisite_sha256': digest(source / 'artifacts.json'),
              'flags': {}, 'artifacts': {}, 'include_directories': ['.']}
    for package in ['com.android.text.flags', 'com.android.graphics.hwui.flags']:
        flags = {name[len(package) + 1:]: value for name, value in report['flags'].items()
                 if name.startswith(package + '.')}
        if not flags or any(not re.fullmatch(r'[a-z][a-z_0-9]*', name) or type(value) is not bool
                            for name, value in flags.items()):
            raise ValueError('Invalid native release flag package: ' + package)
        prefix = package.replace('.', '_')
        text = '#pragma once\n#include <stdbool.h>\n'
        for name, value in sorted(flags.items()):
            text += f'static inline bool {prefix}_{name}(void) {{ return {str(value).lower()}; }}\n'
        text += '#ifdef __cplusplus\nnamespace ' + '::'.join(package.split('.')) + ' {\n'
        for name in sorted(flags):
            text += f'inline bool {name}() {{ return {prefix}_{name}(); }}\n'
        text += '}\n#endif\n'
        target = output / (prefix + '.h')
        target.write_text(text)
        record['flags'][package] = flags
        record['artifacts'][target.name] = {'sha256': digest(target), 'bytes': target.stat().st_size}
    (output / 'artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('FRAMEWORK_NATIVE_RELEASE_FLAGS', sum(map(len, record['flags'].values())), flush=True)


if __name__ == '__main__':
    main()
