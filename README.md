# A2H Lab: Android/Westlake source rebuild manifest

The target is **source-built Android/Westlake with Toutiao supplied as a pinned
original APK**. Toutiao source code is not a build requirement. See
[SOURCE_STACK.md](SOURCE_STACK.md) for the source build paths, original APK
staging command, and remaining full-stack gates. The [source-core validation
record](reports/source-stack-progress.json) contains fresh offline build hashes
and connected-device startup results.

Canonical organization: **https://github.com/a2hlab**. These private repositories
are independent of the organization's Android 16 work:

| Repository | Contents |
| --- | --- |
| [westlake](https://github.com/a2hlab/westlake) | Framework/boundary source, source-built host and Chinese Pinyin apps, historical regression recipes |
| [art-build](https://github.com/a2hlab/art-build) | ART overlays, portable ARM64 makefile, source JNI boundary and declared linker |
| [aosp-art-15](https://github.com/a2hlab/aosp-art-15) | Modified ART source with its original upstream Git ancestry |
| [manifest](https://github.com/a2hlab/manifest) | Exact revisions/patches, toolchain content locks, bootstrap/build/verification tools and open full-build gates |
| [toolchains](https://github.com/a2hlab/toolchains) | Actual SDK/compiler build-input archives in Git LFS, with hashes and original notices |
| `dep-*` (exact revisions in the source locks) | Vendored upstream source trees; exact revisions and patches in the included locks |
| [legacy-runtime-sources](https://github.com/a2hlab/legacy-runtime-sources) | Preserved HWUI/Minikin/FreeType/HarfBuzz/WebP sources and local compatibility headers; not an accepted full runtime build |

Profile: `toutiao-aosp15-oh61-legacy`. **This is not yet a complete reproducible
Toutiao stack.** Native helpers, unsigned host/Pinyin packages, ART/host dex2oat, seven core Java
JARs with a boot image, native support, and framework source generators are separate milestones. `full-build-gaps.json` is machine-readable and
the `full` build command fails closed; it never substitutes candidate04, old
objects, board JARs or copied device libraries. See [STATUS.md](STATUS.md) for
exact verified scope and remaining work.

The [Android-reference parity follow-up](PARITY27.md) pins the generic JIT
file-cache/runtime fixes, portable controls, benchmark verification and binary
dependency inventories. It retains the full-build gate.

## Bootstrap on a clean Linux x86-64 workstation

Requirements: GitHub read access to **all** private dependency repos, Git and
Git LFS, Python 3.12+ (or a
Python with `tarfile.data_filter`), GNU Make, patch, a host GCC/libstdc++ development
installation, and ~35 GB free space for these milestones. Full framework/OS
builds will require substantially more. **All project dependencies and SDK/compiler
archives used by these three profiles are now fetched from checked-in `a2hlab`
repositories.** No public-upstream fetch or release-download fallback is used.
LFS transfers about 1.57 GB of archives; GitHub's source ZIP download does not
replace a clone with its LFS objects. SDK native metadata is
6.1.0.31/API23; app bytecode explicitly targets API20 for the legacy device.

```sh
git clone https://github.com/a2hlab/manifest.git a2hlab-manifest
cd a2hlab-manifest
python3 tools/fetch_sources.py --workspace /absolute/new-a2hlab-workspace
python3 tools/install_toolchains.py --workspace /absolute/new-a2hlab-workspace
```

The installer is offline: it requires the pinned repository revision and verifies
the LFS archive size/SHA256 and full extracted tree. Missing pointer objects,
corrupt archives and modified toolchains fail closed. Extraction rejects escaping
paths/links and preserves compiler executable bits. Source
fetches require unused checkout directories. A failed partial fetch must be
inspected; use a new workspace for a new full trial. No existing checkout is
reset or overwritten.

The SDK/compiler are **checked-in prebuilt build inputs**, not compilers rebuilt
from source in this workflow. Original archive identities and the eight omitted
SDK files are recorded in `toolchains/index.json`. Signing material and unused
SELinux/diff tools were excluded. Supply your own signing identity separately.
The workstation OS and standard host prerequisites above are still external:
this is not a checked-in hermetic host image or a complete source bootstrap.

## Verified-source build entry points

Each command rechecks all locked source revisions, patched Git trees and the
full installed toolchain tree. It requires a **new** output directory.

```sh
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile native --out /absolute/new-a2hlab-workspace/out/native
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile apps --out /absolute/new-a2hlab-workspace/out/apps
python3 tools/rebuild.py --workspace /absolute/new-a2hlab-workspace --profile art --out /absolute/new-a2hlab-workspace/out/art --jobs 6
```

After fetching, installation and all three builds were also tested inside
`unshare -Urn` (a new Linux user/network namespace, with no external networking).
To enforce the same condition, prefix each install/build command with
`unshare -Urn`. Hosts that disallow user namespaces need an equivalent separately
configured network-isolated environment; do not interpret a normal build as an
offline test.

Outputs include complete logs, source/toolchain provenance, artifact sizes and
SHA256 values. `apps` builds V1 Restool from vendored sources, recompiles all
JavaScript and Pinyin native code, regenerates resource indexes, and writes
deterministic unsigned HAPs. No signing keys, profiles, installed apps, raw app
logs or user data are distributed. Signing and device installation are separate
operator-controlled steps; do not deploy unaccepted runtime candidates.

The ART profile records dynamic imports and requires closure against its
explicit SDK/platform dependencies. WebP is built from preserved source;
platform libc++ supplies the correct ABI. `host-tools` uses `Makefile.host`,
not the historical `Makefile`. Device runtime/UX acceptance remains separate.

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

## Preserved sources for the unfinished full runtime

The preserved graphics repository is now included by the default source lock
(WebP is needed by ART). To fetch it separately into an otherwise new checkout:

```sh
python3 tools/fetch_sources.py --workspace /absolute/new-a2hlab-workspace --lock runtime-sources.lock.json
python3 tools/verify_preserved_sources.py --repository /absolute/new-a2hlab-workspace/preserved/runtime-sources
```

This verifies preservation of the local graphics dependencies and compatibility
overlays. The ART profile builds its WebP decoder. The remaining graphics/framework
recipes and full payload acceptance are still open; the original APK has its
own content lock. See [DEPENDENCIES.md](DEPENDENCIES.md).

## Source provenance and preservation

`import-provenance.json` and `art-support-provenance.json` preserve the reviewed
checkpoint's original locations/hashes. `tools/import_*.py` are one-time audit
exports only, **not** bootstrap dependencies. Import fixes and portability
changes are normal subsequent source commits. Original source line endings and
third-party license notices were retained; historical whitespace warnings were
not reformatted into unrelated diffs. All original repos, device data, and
validated binary baselines remain untouched.

`dependency-source-provenance.json` records each vendored project's original URL,
commit and Git tree. Those upstream URLs are provenance, not active downloads.
`tools/vendor_sources.py`, `tools/package_toolchains.py` and the import scripts
are one-time maintainer exports, not dependencies on the original workstation.
