# Rebuild status

The requested target is `a2hlab`, not the superseded `a2oh` organization.
Four new private repositories are published without replacing existing projects.

## Current evidence

- ART fork ancestry preserved and pushed at `e70733dcec75e56c2ac25833a47c594e7f5fe141`.
- Westlake source, ART build overlays, legacy header-only sysroot, and curl/JNI
  headers exported without historical `.o`, runtime `.so`, boot images or APKs.
- Eleven initial upstream source projects fetched at exact revisions, with three
  local source patches hash-checked. Additional dlmalloc and five resource-tool
  projects are pinned; final patched Git trees are checked as well as base commits.
- Official SDK and platform compiler downloaded/verified and freshly extracted;
  full tree fingerprints match across two independent extraction roots.
- Four public-SDK helpers built twice with identical bytes; initial tests cover
  fresh outputs, missing SDKs, TLS native inventory and deterministic HAP ZIPs.
- ART clean core/JNI objects, `libart.so` and runtime boundary built from source.
  This is a source-link milestone, not a closed deployment or correctness gate.
- Restool V1 rebuilt from pinned sources; host and Pinyin HAPs built with fresh
  resources and bytecode. Seven Pinyin controller regression groups pass.
- A separate fresh GitHub/public-upstream checkout and independently extracted
  toolchain workspace passed all three locked profiles. Eight output files are
  byte-identical: four native helpers, two unsigned HAPs, ART and its JNI runtime
  boundary. Rehashed-file evidence: `reports/native-repeatability.json`,
  `reports/apps-repeatability.json`, `reports/art-repeatability.json`.
- Eight manifest unit tests, four Westlake portable-build tests and seven Pinyin
  controller regression groups pass. The incomplete `full` profile was checked
  to exit with status2, without building or installing a historical candidate.
- HDC device enumeration returned `[Empty]` during this work. No device writes
  or signing-key changes have been made.

## Still prevents a full claim

1. Core JAR and framework source provenance/build closure. The historical
   `build_aosp_fw.sh` wrapper claims core/framework targets but calls an adapter
   builder that consumes existing board JARs. Working compile headers include a
   separately converted DEX-to-class JAR. The local partial AOSP15 checkout has
   no complete repo manifest or libcore tree.
2. Adapter Java cold-start cycle: framework compilation consumes previously
   built runtime-BCP classes, while runtime-BCP compilation needs framework
   classes. Compile against source-generated headers and partition a single
   explicit class inventory; remove duplicate class ownership.
3. Rebuilt compatible host dex2oat plus the complete ten-JAR boot classpath:
   core-oj, core-libart, core-icu4j, okhttp, bouncycastle, apache-xml,
   adapter-mainline-stubs, framework, adapter-runtime-bcp, oh-adapter-framework.
4. HWUI support closure: AOSP14 HWUI at `299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368`
   has 54 modified files; Minikin at `b8d51a4cfadc330af4045bac8a97db7b68353870`
   has local changes. The old full HWUI recipe selects a different EglManager.cpp
   from the recently fixed source. Its mixed Skia/EGL/GLES providers are not yet
   a declared source-build graph.
5. Full bridge/appspawn need declared include/source-override/provider inventories
   and generated-header recipes. The saved Ninja include list, basename-based
   overrides and wildcard board library links are not a reproducible contract.
6. Runtime process symbol closure and a pinned host environment. The SDK symbol
   audit finds 122 ART strong imports outside its declared dependency exports;
   the locked platform libc++ supplies 121 of them but is not in DT_NEEDED. The
   remaining imports are `program_invocation_short_name` (ART) and
   `JNI_OnLoad_binder_with_cl` (boundary). Also, symbol presence alone does not
   prove implementation completeness: the current ART fallback for WebP decoding
   returns null. See `reports/runtime-provider-gaps.json`. Successful linking and
   byte-identical outputs do not resolve these functional/deployment questions.
7. Device acceptance on the rebuilt candidate and repeated controlled Toutiao
   versus OnePlus 6 measurements. Previous candidate05 successes and candidate13
   SearchActivity IME error12800003 are historical evidence, not a pass for these
   freshly built artifacts. Native performance parity remains unproven.

`tools/rebuild.py --profile full` exits nonzero while these gates remain open.
No branch, report, repository name or archived candidate is labelled as a full
source-reproduction pass.

## Required source handoff

The remaining framework provenance is not available in either local partial
`aosp-15` or `bridge-build/aosp` trees. Historical scripts identify the framework
build as an ECS-only workflow and pull final JARs, not its complete source state.
The required handoff is the matching source manifest plus local patches/generated
source recipes for the original framework/core JAR build and OH firmware/provider
set. A frozen JAR archive or a version label is not an equivalent substitute.
Without that provenance, choosing a fresh generic Android release would create
a new port baseline rather than reproduce the existing working stack.
