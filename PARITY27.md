# Android-reference parity follow-up

`sources.lock.json` pins the generic JIT file-cache correction, Android process
stream/CPU-time compatibility, window power policy, process specialization and
network interface corrections. Source is split across `aosp-art-15`, `art-build`
and `westlake`; this repository pins their exact commits.

## Reproduce the committed components

```sh
python3 tools/fetch_sources.py --workspace /absolute/new-workspace
python3 tools/install_toolchains.py --workspace /absolute/new-workspace
python3 tools/rebuild.py --workspace /absolute/new-workspace --profile native --out /absolute/new-workspace/out/native
python3 tools/rebuild.py --workspace /absolute/new-workspace --profile art --out /absolute/new-workspace/out/art --jobs 6
```

These profiles require new outputs and verify source/toolchain inventories.
For window policy, deterministic comparison APKs, native probes, benchmarks and
USB networking, follow [Westlake's guide](https://github.com/a2hlab/westlake/blob/main/docs/parity/REPRODUCE.md).
The rebuilt `control24` benchmark and `control26` window/CPU control DEX bytes
match the measured APKs. Sign one rebuilt APK with your own identity for both
devices; the original development private key is not a reproduction input.

## Binary dependencies

Yes, there are binary dependencies, separate from the generic runtime fix:

| Input | Status |
| --- | --- |
| OH SDK6.1.0.31/API23 and platform clang15 | Actual archives in `a2hlab/toolchains` Git LFS, verified by normal bootstrap |
| Android SDK build-tools34/API34 and optional NDK25.2.9519653 | Operator supplied; SDK hashes in Westlake `tests/parity/android-sdk.lock.json` |
| Window helper link providers | Operator supplied `libipc_single.z.so` and `libutils.z.so`, hash-locked in Westlake `tests/parity/window-providers.lock.json`; object compilation needs neither |
| Ten framework/core JARs and matching ART/OAT/VDEX boot images | Historical compiled inputs; complete matching source recipe remains missing |
| Full bridge/HWUI/runtime providers and OH firmware/vendor graphics | Observed immutable hashes recorded; complete source/build closure remains missing |
| WebView and Toutiao APK/native libraries | External application inputs; identities recorded, application binaries not distributed |
| gnirehtet Windows relay/Android VPN client | Optional official v2.5.1 input; scripts verify relay/client hashes |
| Host OS, Git/LFS, Python, Make, host compiler/Java and signing identity | Operator environment; no checked-in hermetic host image |

`parity27-runtime-inputs.lock.json` records **410 observed immutable files**:
75 bridge/runtime, six WebView, 42 application and 287 firmware files. It excludes
private app data, cookies, databases, learned dictionaries, sockets and JIT
mappings. This is an observed-load inventory, not proof that every dynamically
loaded dependency was exercised. `parity27-candidate26.lock.json` separately
pins all 66 historical candidate artifacts; the runtime inventory captures the
actual v27/appspawn/network/popen overrides used by the final launch.

Check a supplied, dereferenced local tree mirroring the device's absolute paths:

```sh
python3 tools/verify_parity_inputs.py --root /path/to/reference-input-tree
```

Missing or changed inputs fail. This read-only check neither uploads binaries
nor treats hashes as a source build. Matching names alone are insufficient.

The two window **link-input** hashes are distinct from the deployed firmware
hashes in the runtime inventory. The former describe the libraries used by the
compiler/linker; the latter describe what actually loaded on the phone. Do not
replace one set with the other based only on names. This distinction is part of
the remaining complete platform/provider source-closure gate.

## Evidence and remaining gate

`reports/parity27/verification.json` records a fresh GitHub fetch of the pinned
projects and offline SDK extraction/builds. Rehashing actual files verifies
18 byte-identical repeated artifacts: six native helpers, window object/DSO,
two unsigned APKs and their DEX files, ART/runtime boundary, and four Android/OH
native probes. All three control variants match the measured APKs' DEX bytes.
Seventeen manifest tests and six Westlake tests pass. The source verifier uses
an isolated index when computing Git trees, avoiding shared-index contention
between concurrent component checks. Synthetic log fixtures are explicitly
tracked so sample verification works in a fresh clone.

The historical four-run comparison keeps JIT enabled and alternates file and
anonymous backing in the same ART binary. Page-ready p90 is 105–114 ms versus
261–309 ms; median process CPU through the last page falls 10.5%. Westlake
publishes benchmark markers, raw samples and a recomputation verifier. These
are not physical presentation, live Toutiao startup/scrolling latency, or proof
of hardware-independent Android speed parity.

The accepted global runtime/data were preserved. The isolated candidate26/v27
passed Chinese input/search/scroll, IME, network/TLS, CPU-time and window-flag
checks. Newly repository-built process-stream probes also pass on both phones.
The fresh source-built ART link retains separate provider/device acceptance
gates; it is not relabelled as the historical device-accepted binary.

**Full source-only runtime reproduction is still blocked by the matching
core/framework/boot-image source recipe and complete OH firmware/provider
manifest.** `full-build-gaps.json` and `rebuild.py --profile full` stay fail-closed.
The needed source handoff is documented in `DEPENDENCIES.md` and `STATUS.md`.
