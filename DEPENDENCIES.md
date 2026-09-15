# Source and compiler dependency closure

The target is a source-built Android/Westlake runtime on the existing OHOS host,
with the original Toutiao APK pinned separately. Toutiao application source is
not required. Historical device JARs, boot images and Android/Westlake DSOs are
not build inputs.

| Component | Source/build coverage | Acceptance |
| --- | --- | --- |
| ART, JNI boundary, WebP and host dex2oat | Locked a2hlab sources and declared object/link recipes | Offline builds and core device probes pass |
| Seven core JARs and boot image | Android 15 libcore, ICU, Conscrypt, OkHttp, Bouncy Castle and Apache XML | Device Unicode, regex, crypto, XML and boot-resource probes pass |
| Android native support | Source log/base/cutils/utils/nativehelper, zlib/ZIP, Expat/PNG, FreeType, ICU/JNI, HarfBuzz, Minikin, androidfw, BoringSSL/Conscrypt | 19 artifacts; 18-output independent builds were byte-identical; native device behavior probes pass |
| Framework resources | Original Android 15 resources, generated resource IDs and release flag inputs | Source build passes; complete UI acceptance is pending |
| Framework generators | Source protobuf/streaming/nano, stats, sysprop, XSD and aconfig tools; versioned AIDL | Source builds and generation pass; complete framework Java/DEX build is in progress |
| HWUI, bridge and appspawn | Preserved Android/OH sources, full Android 15 dependencies, OH Skia and the pinned OH header carrier | Complete compile/link/provider recipes remain in progress |
| OH host firmware providers | Running OHOS platform | Every required provider must be inventoried and verified against the target ABI |
| Toutiao | Unchanged original APK in `app-inputs.lock.json` | Supplied separately; never rebuilt or decompiled |

The compiler inputs are pinned OHOS SDK/Clang, JDK/D8, AAPT2/AIDL and Rust
archives hosted under a2hlab. Rust crate sources are vendored with Cargo.lock
and package checksums; aconfig builds with `--offline --locked`. Archive
installers verify bytes and extracted-tree fingerprints and have no download
fallback. Compiler bootstrapping and rebuilding the OH kernel/system services
are outside this target.

Git/LFS, Python, Make, standard Linux host development headers/libraries and
user/network namespaces remain declared host prerequisites. Network-isolated
build evidence is recorded separately from cross-host byte identity; there is
no claim that an entire workstation image has been made hermetic.

The complete source-built payload still needs the framework/adapter ownership
graph, full boot classpath, rendering/bridge provider closure, and fresh Toutiao
UI/scroll/input acceptance. WebView support must also be source-built or proven
to be a declared OH host-firmware provider. Captured runtime copies do not meet
that requirement.

See `reports/source-stack-progress.json` for the current core/native evidence.
`full-build-gaps.json` and `tools/rebuild.py --profile full` remain fail-closed
until the complete source-built application process passes device acceptance.
