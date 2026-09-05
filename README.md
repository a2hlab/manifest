# A2H Lab: legacy Toutiao rebuild manifest

Canonical organization: **https://github.com/a2hlab**. These private repositories
are independent of the organization's Android 16 work:

| Repository | Contents |
| --- | --- |
| [westlake](https://github.com/a2hlab/westlake) | Framework/boundary source, source-built host and Chinese Pinyin apps, historical regression recipes |
| [art-build](https://github.com/a2hlab/art-build) | ART overlays, portable ARM64 makefile, source JNI boundary and declared linker |
| [aosp-art-15](https://github.com/a2hlab/aosp-art-15) | Modified ART source with its original upstream Git ancestry |
| [manifest](https://github.com/a2hlab/manifest) | Exact revisions/patches, toolchain content locks, bootstrap/build/verification tools and open full-build gates |

Profile: `toutiao-aosp15-oh61-legacy`. **This is not yet a complete reproducible
Toutiao stack.** Native helpers, unsigned host/Pinyin packages, and ART source
builds are separate milestones. `full-build-gaps.json` is machine-readable and
the `full` build command fails closed; it never substitutes candidate04, old
objects, board JARs or copied device libraries. See [STATUS.md](STATUS.md) for
exact verified scope and remaining work.

## Bootstrap on a clean Linux x86-64 workstation

Requirements: GitHub read access to the private repos, Git, Python 3.12+ (or a
Python with `tarfile.data_filter`), GNU Make, patch, a host GCC/libstdc++ development
installation, and ~20 GB free space for these milestones. Full framework/OS
builds will require substantially more. Network access is needed for pinned
public source projects and two official compiler/SDK archives. Keep their
licenses; the archives are downloaded, not committed. SDK native metadata is
6.1.0.31/API23; app bytecode explicitly targets API20 for the legacy device.

```sh
git clone https://github.com/a2hlab/manifest.git a2hlab-manifest
cd a2hlab-manifest
python3 tools/fetch_sources.py --workspace /absolute/new-a2hlab-workspace
python3 tools/bootstrap_sdk.py --out /absolute/new-a2hlab-workspace/toolchains/ohos-sdk
python3 tools/bootstrap_clang.py --out /absolute/new-a2hlab-workspace/toolchains/clang-15
```

`--archive /path/to/previous-download.tar.gz` avoids downloading an archive again;
its complete length and SHA256 are still checked before extraction. Extraction
rejects escaping paths/links and preserves compiler executable bits. Source
fetches require unused checkout directories. A failed partial fetch must be
inspected; use a new workspace for a new full trial. No existing checkout is
reset or overwritten.

## Verified-source build entry points

Each command rechecks all locked source revisions, patched Git trees and the
full installed toolchain tree. It requires a **new** output directory.

```sh
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile native --out /absolute/new-a2hlab-workspace/out/native
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile apps --out /absolute/new-a2hlab-workspace/out/apps
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile art --out /absolute/new-a2hlab-workspace/out/art --jobs 6
```

Outputs include complete logs, source/toolchain provenance, artifact sizes and
SHA256 values. `apps` builds V1 Restool from pinned public sources, recompiles all
JavaScript and Pinyin native code, regenerates resource indexes, and writes
deterministic unsigned HAPs. No signing keys, profiles, installed apps, raw app
logs or user data are distributed. Signing and device installation are separate
operator-controlled steps; do not deploy unaccepted runtime candidates.

The ART source link records unresolved dynamic symbols. This is intentional
visibility, not permission to ignore them: the full process must supply the
correct platform libc++, binder JNI, WebP and other providers before deployability
can pass. The old `Makefile` host and historical scripts are not portable entry
points and are not part of the accepted source-build profiles.

## Repeatability

Repeat the bootstrap/build commands in an independently located workspace, then
rehash and compare actual files (not just their recorded hashes):

```sh
python3 tools/compare_builds.py --first /workspace-a/out/native/native --second /workspace-b/out/native/native
python3 tools/compare_builds.py --first /workspace-a/out/apps/apps --second /workspace-b/out/apps/apps
python3 tools/compare_builds.py --first /workspace-a/out/art/runtime --second /workspace-b/out/art/runtime
python3 -m unittest discover -s tests -v
```

An identical unsigned payload does not prove device compatibility or native
performance. Host Restool currently also records the host libstdc++ archive
hash; the complete host-container environment is not yet content-locked. No
cross-host/cross-distribution hermetic claim is made.

## Source provenance and preservation

`import-provenance.json` and `art-support-provenance.json` preserve the reviewed
checkpoint's original locations/hashes. `tools/import_*.py` are one-time audit
exports only, **not** bootstrap dependencies. Import fixes and portability
changes are normal subsequent source commits. Original source line endings and
third-party license notices were retained; historical whitespace warnings were
not reformatted into unrelated diffs. All original repos, device data, and
validated binary baselines remain untouched.
