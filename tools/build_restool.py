#!/usr/bin/env python3
"""Build the board-compatible V1 resource compiler from locked public sources."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from bootstrap_sdk import digest


def run(*command, **kwargs):
    subprocess.run([str(x) for x in command], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    out = args.out.absolute()
    if out.exists():
        parser.error('--out must be new')
    out.mkdir(parents=True)
    source = workspace / 'upstream/ohos'
    restool = source / 'developtools/global_resource_tool'
    third = source / 'third_party'
    generated = out / 'sources'
    generated.mkdir()
    for name, archive in [('jsoncpp', 'jsoncpp-1.9.5.tar.gz'), ('libpng', 'libpng-1.6.38.tar.gz')]:
        with tarfile.open(third / name / archive) as packed:
            packed.extractall(generated, filter='data')
    jsoncpp = generated / 'jsoncpp-1.9.5'
    png = generated / 'libpng-1.6.38'
    patches = [(jsoncpp, third / 'jsoncpp/Fix error whenparses the value of 5E-324 with libc++.patch')]
    patches += [(png, third / 'libpng' / p) for p in [
        'CVE-2019-6129.patch', 'huawei_libpng_CMakeList.patch', 'libpng-fix-arm-neon.patch',
        'libpng-multilib.patch', 'backport-libpng-1.6.37-enable-valid.patch', 'CVE-2018-14048.patch']]
    for target, patch in patches:
        run('patch', '-p1', '--fuzz=0', '--no-backup-if-mismatch', '-i', patch, '-d', target)
    shutil.copyfile(third / 'libpng/pnglibconf.h', png / 'pnglibconf.h')
    secure = third / 'bounds_checking_function'
    zlib = third / 'zlib'
    compiler = workspace / 'toolchains/clang-15/bin/clang++'
    c_compiler = workspace / 'toolchains/clang-15/bin/clang'
    includes = [restool / 'include', jsoncpp / 'include', png, secure / 'include', zlib]
    flags = ['-O2', '-fPIC', '-Werror=date-time', '-ffile-prefix-map=' + str(workspace) + '=/src',
             '-ffile-prefix-map=' + str(out) + '=/build/restool'] + ['-I' + str(p) for p in includes]
    sources = sorted(restool.glob('src/*.cpp')) + sorted(jsoncpp.glob('src/lib_json/*.cpp'))
    sources += sorted(secure.glob('src/*.c')) + sorted(zlib.glob('*.c'))
    sources += [p for p in sorted(png.glob('*.c')) if p.name not in ['pngtest.c']]
    env = dict(os.environ, SOURCE_DATE_EPOCH='1772755200', TZ='UTC', LC_ALL='C')
    objdir = out / 'obj'
    objdir.mkdir()

    def compile_one(entry):
        index, path = entry
        obj = objdir / (str(index) + '-' + path.stem + '.o')
        tool = compiler if path.suffix == '.cpp' else c_compiler
        lang = ['-std=c++17', '-stdlib=libstdc++'] if path.suffix == '.cpp' else ['-std=gnu11']
        run(tool, *flags, *lang, '-c', path, '-o', obj, env=env)
        return obj

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        objects = list(pool.map(compile_one, enumerate(sources)))
    binary = out / 'restool'
    run(compiler, '-stdlib=libstdc++', '-static-libstdc++', '-static-libgcc', '-Wl,--build-id=sha1',
        *objects, '-pthread', '-lm', '-o', binary, env=env)
    version = subprocess.check_output([str(binary), '-v'], text=True).strip()
    if version != 'Info: Restool version= Restool 4.105':
        raise ValueError('Unexpected resource compiler: ' + version)
    record = {'sha256': digest(binary), 'version': version,
              'compiler_sha256': digest(compiler),
              'host_libstdcxx': subprocess.check_output(['c++', '-print-file-name=libstdc++.a'], text=True).strip(),
              'sources': len(sources)}
    record['host_libstdcxx_sha256'] = digest(Path(record['host_libstdcxx']))
    (out / 'build.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    print('RESTOOL_BUILT', record['sha256'], flush=True)


if __name__ == '__main__':
    main()
