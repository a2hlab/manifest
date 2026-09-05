# Verification evidence

All records here describe the September5 source rebuild under `a2hlab`.
No raw device/app logs, account data, signing keys or binary build outputs are
committed. Files were re-hashed by `tools/compare_builds.py`, not accepted solely
because two prewritten hash manifests matched.

The two builds used distinct source and output roots. The second workspace
fetched the exact locked commits from GitHub/public upstream and applied only
the manifest's verified patches. Both compiler archives were rehashed and
freshly extracted into a second toolchain root with identical tree fingerprints.

The first ART trial exposed missing dlmalloc and asm definition source inputs;
those were fixed and committed before the second trial. No old workstation
object or runtime DSO was substituted. The second ART trial started with an
empty output directory and passed the complete declared core/JNI object build.
Both linked outputs were byte-identical after those source-input fixes.

Three records prove eight byte-identical unsigned/source-built files:

- `native-repeatability.json`: network, TLS, public IME, WebView startup helpers.
- `apps-repeatability.json`: host HAP and offline Chinese Pinyin HAP.
- `art-repeatability.json`: ART runtime and JNI runtime boundary.

`runtime-provider-gaps.json` is a separate negative/readiness audit. It checks
symbols against SDK link stubs and the locked platform libc++, **not** the
actual firmware's loader namespace, installed DSOs, functional implementation,
or runtime data. It explicitly does not grant deployment acceptance.

Host controls:8 manifest unit tests +4 Westlake portable-build tests;7 Pinyin
controller groups. No fresh Toutiao or OnePlus benchmark was performed: HDC
enumeration was empty. The full framework/boot/graphics payload was not rebuilt.
