# Source-built Android/Westlake with an original Toutiao APK

The target is a source-built Android/Westlake runtime on the connected OHOS
platform, with Toutiao supplied as an unchanged, content-locked application.
Toutiao application source is **not required**. The APK is never decompiled,
patched, re-signed, or used to compile framework classes.

The September 15 restored-board API-shim result and remaining proof gaps are
recorded in [the board report](reports/toutiao-api-board-gaps-20260915.md).
The unchanged APK reached a populated feed, while full source/UI acceptance
remains false and the OH network helper still used kernel-route fallback.

`app-inputs.lock.json` pins `com.ss.android.article.news` version 13.9.0
(versionCode 13900), 138641340 bytes, SHA-256
`a1112a0c941f865847c2fab9138cf815735268fbfcd41d697412fb80992c7395`.
Supply that original APK separately:

```sh
python3 tools/prepare_app.py --apk /path/to/original-toutiao.apk --out /workspace/out/toutiao-input
```

The command copies the verified APK unchanged, extracts its declared ARM64
directory, and records every library hash and actual ELF architecture. The
original includes an ARM32 `libcvt.so` in that directory; it is preserved and
explicitly excluded from the inventory of AArch64 symbol providers. A changed
APK or reused output directory is rejected.

## Implemented source build paths

Use the merged `main` branch. Bootstrap
`sources.lock.json` and the standard toolchains as described in README.md, then
fetch each additional lock once into the same workspace:

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock core-sources.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock java-extensions.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock framework-sources.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock native-sources.lock.json
python3 tools/install_java.py --workspace /workspace
python3 tools/rebuild.py --workspace /workspace --profile host-tools --out /workspace/out/host-tools --jobs 6
python3 tools/rebuild.py --workspace /workspace --profile core-java --out /workspace/out/core-java
python3 tools/rebuild.py --workspace /workspace --profile native-support --out /workspace/out/native-support --jobs 6
python3 tools/build_java_extensions.py --workspace /workspace --core-build /workspace/out/core-java/java --out /workspace/out/java-extensions
python3 tools/rebuild.py --workspace /workspace --profile art --native-build /workspace/out/native-support/native --out /workspace/out/art --jobs 6
python3 tools/build_core_boot.py --host-build /workspace/out/host-tools/host --core-build /workspace/out/core-java/java --extension-build /workspace/out/java-extensions --out /workspace/out/core-boot
```

This builds all seven core JARs and their boot image. `--native-build` selects
source ICU JNI and Conscrypt dependencies in the runtime. Omitting it retains
the older component-only profile and is insufficient for the complete stack.

All project and compiler inputs in these locks are fetched from a2hlab
repositories. The OHOS SDK, platform Clang, Temurin JDK 21.0.6+7 and Android D8
are pinned compiler inputs, not compilers bootstrapped from source by this
workflow. The JDK installer checks the original release archive and extracted
tree hashes; the build does not select Java from the workstation PATH. The running OHOS firmware is the host platform; this
target does not rebuild its kernel or system services.

* `host-tools` builds host `dex2oat`, zlib, disassemblers, and Android 15 x86-64
  entrypoints/handler tables. It generates layout constants, links a declared
  object inventory, and fails on compile/link errors. It does not ignore
  unresolved symbols or pick up arbitrary objects from old output directories.
* `core-java` compiles 2977 declared Android 15 Java source files together to
  break the libcore/ICU/OkHttp bootstrap cycle, then partitions classes into
  `core-oj`, `core-libart`, `core-icu4j`, and `okhttp`. Class ownership is checked;
  duplicate/unowned classes are errors. It uses `--system none`, source-generated
  compile headers, and D8's Android platform/record flags. No device JAR,
  decompiled class, or Android SDK JAR participates in compilation.
* The Conscrypt `SSLSockets` API signature generates a **compile-only** header.
  That class and the ICU flag-name header are omitted from every runtime JAR.
  `core-all-compile-only.jar` is a compiler input, never a deployable boot JAR.
  The extension/native-support recipes compile Conscrypt's full Java/native implementation.
* `art` builds the real WebP decoder and links it into the runtime dependency
  graph. The null decoder fallback is removed. ART declares platform libc++'s
  `std::__h` provider, uses OHOS musl's program-name symbol, and delegates Binder
  library loading to the normal ART loader. The SDK/provider audit must pass.

The extension recipe builds Conscrypt, Bouncy Castle and Apache XML, preserves
resource files and checks DEX ownership against the core. The device probe in
`tools/probe_core_vm.py --compatibility` validates all seven JARs, real ICU JNI,
Unicode regex/charset behavior, SHA-256/AES-GCM, Bouncy Castle provider loading,
Chinese XML and physical boot-JAR resource lookup. See
`reports/source-stack-progress.json`; this is not a full Toutiao launch result.

The complete AOSP framework source snapshot is included above. Additional framework
dependency and compiler source locks are available separately:

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock framework-dependencies.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock framework-tools-sources.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock framework-generator-dependencies.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock framework-mainline-sources.lock.json
```

It preserves upstream licenses and source provenance. Its upstream Gradle
distribution exceeds GitHub's normal blob limit and is stored in Git LFS, with
its exact original size/hash recorded. Fetching this source does not itself
build `framework.jar` or `framework-res.apk`.

The source-built host tool also generates an ARM64 boot image for these seven
core JARs. This is a core image, not the final framework/Westlake boot image.
The builder verifies the input artifact hashes and records all twenty-one image,
OAT, and VDEX outputs. Core JAR verification rejects duplicate DEX definitions,
compile-header leakage, and loss of required ART classes such as `java.lang.Record`.

## Framework compiler dependencies

After the core/native source checkouts, a new checkout can fetch the remaining
framework build sources with `tools/fetch_sources.py --lock framework-inputs.lock.json`.
This aggregate includes the individual framework locks above; do not fetch both
into the same directories. The installer refuses to overwrite an existing checkout.

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock framework-inputs.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock compiler-inputs.lock.json
python3 tools/fetch_sources.py --workspace /workspace --lock rust-inputs.lock.json
python3 tools/install_android_compilers.py --workspace /workspace
python3 tools/install_rust.py --workspace /workspace
unshare -Urn python3 tools/build_aconfig.py --workspace /workspace --out /workspace/out/aconfig
unshare -Urn python3 tools/build_xsdc.py --workspace /workspace --out /workspace/out/xsdc
unshare -Urn python3 tools/build_parser_tools.py --workspace /workspace --out /workspace/out/parser-tools
unshare -Urn python3 tools/build_framework_java_support.py --workspace /workspace --core-build /workspace/out/core-java/java --out /workspace/out/framework-java-support
```

The Java support build emits source annotation and Guava JARs, the SafeParcel
annotation processor, and the protobuf lite runtime. It follows protobuf's
upstream compile-only Unsafe header contract and excludes that header from the
runtime JAR. The parser build compiles M4, Bison and Flex from release sources;
release configure files are retained, so no undeclared autotools regeneration
is needed after a Git checkout.

Westlake's `framework-tools/libraries.json` declares the source protobuf host
tools. `tools/build_framework_generators.py` builds stats and sysprop generators;
`tools/build_hidl_generator.py` builds HIDL using the source parser tools and
BoringSSL. Each verifies its prerequisite artifact hashes. The framework Java
module selection is recorded in `westlake/framework-tools/java-profile.json`.
AIDL, HIDL, release flags, protocols, properties and statistics each have a
separate generator and artifact report. These are build milestones; complete
device acceptance remains required.

The checked framework compiler now builds 13,034 input source files plus 58
SafeParcel-generated sources, into 34,463 owned classes. The Android 15 adapter
port builds 64 source files into 107 classes. It preserves activity tokens on
individual lifecycle items, uses the Android 15 relayout result container, and
routes asynchronous input binding through the existing OH input session. New
service capabilities with no OH implementation fail explicitly; compilation
does not imply those capabilities are implemented.

`tools/build_framework_java.py` consumes the verified AIDL, flags, module,
HIDL, miscellaneous, Cronet, audio-schema and resource generator reports, plus
source-built core and support JARs. It checks duplicate source ownership and
preserves libphonenumber's data resources. Its unrelocated class JAR is an
intermediate, not a boot artifact. `tools/build_westlake_java.py` compiles the
adapters against that source class JAR and rejects framework class overrides.

The original Kotlin 1.8.22 compiler distribution is pinned in
`kotlin-inputs.lock.json` and `kotlin-compiler.lock.json`.
`tools/install_kotlin.py` verifies archive and extracted-tree hashes;
`tools/build_experimental_annotations.py` builds AndroidX experimental annotations
from the original Kotlin sources. Kotlin compiler libraries are not deployed.
`tools/build_jarjar.py` builds the Android JarJar CLI and ASM from the source
projects in `framework-java-compiler-tools.lock.json`; unused Ant/Maven plugin
integrations are excluded.

`tools/package_framework_runtime.py` emits `framework.jar` and
`adapter-runtime-bcp.jar`. This process profile shares framework module
dependencies once, using `westlake/framework-tools/runtime-jarjar-rules.txt` to
isolate Guava, ExoPlayer, Chromium and other private dependencies from APKs.
The packager rejects relocation collisions, checks the actual JarJar output,
excludes compile-only classes, and verifies every DEX class against core and
framework ownership. D8-generated synthetic classes must carry the synthetic
flag and identify an owned originating class. The pinned upstream D8 warns
about API 35 exceeding its API database; the retained `CharSequence.compare`
method exists in this source libcore. Device compatibility is still a gate.

`tools/build_framework_boot.py` adds both runtime JARs to the seven core JARs
and generates all 27 ART/OAT/VDEX files with the source-built dex2oat. The
resulting nine-JAR image is built, but has not passed full device UX acceptance.

The Android 15 renderer now combines 1041 verified objects, including 319
Ganesh GPU/FreeType units, 45 image-codec units and nine source support units.
Eight original Skia translation units supply actual C++ RTTI; the synthetic
RTTI library is excluded. `combine_native_objects.py` rejects duplicate
ownership unless an explicit replacement records both original object hashes.
The source profile excludes the historical TextureLayer instruction patch and
uses the original Android 15 graphics JNI.

`skia-gpu-dependencies.lock.json` pins the OH Vulkan headers and checked-memory
source. The matching Wuffs, Vulkan memory allocator, JPEG and WebP sources are
already present in the published OH Skia repository. JPEG (64 units), WebP
(115), securec (39), and Wuffs (one original generated C implementation) build
as source libraries. HWUI and its graphics shim strictly link with firmware
Skia explicitly excluded as a provider.

## Reproduce the core device check

After the builds above, use the connected OHOS device's HDC executable and serial:

```sh
python3 tools/probe_core_vm.py --workspace /workspace --runtime /workspace/out/art/runtime --core /workspace/out/core-java/java --boot /workspace/out/core-boot --extension-build /workspace/out/java-extensions --native-build /workspace/out/native-support/native --compatibility --out /workspace/out/core-device-probe --hdc /path/to/hdc --serial DEVICE_SERIAL
```

This compiles the probe, verifies build reports and transfers each artifact into
an isolated, newly created `/data/local/tmp/a2hlab-core-*` directory. Every
transfer is hash-checked. It creates the VM and tests Record resolution,
monotonic time, OS-derived properties and I/O limits, and the system class loader.
It records native-registration diagnostics even when these specific checks pass.
The existing JNI boundary still contains legacy registrations that do not match
all Android 15 classes; passing startup is not a complete class-library test.

## Acceptance boundary

The Java source baseline is the explicit upstream `android-15.0.0_r1` snapshot.
It is a new source baseline for completing the port; it is not claimed to be
the unknown source state that produced the earlier frozen device JARs.

`--profile full` remains unavailable until the remaining native bridge/appspawn,
HWUI linking and runtime provider graph are built and the resulting payload
launches Toutiao on the device. The app-input lock, source component builds, a successful dynamic
loader probe, and the earlier binary-runtime UX demonstration are separate
pieces of evidence. None alone establishes a complete source-built UX.

The initial native source profile linked `libhwui.so`, `liboh_hwui_shim.so`,
`liboh_skia_rtti_shim.so`, `liboh_adapter_bridge.so`,
`liboh_android_runtime.so` and `libwestlake_binder.so` with `-z defs`.
That profile used AOSP's Binder RPC graph. The Android 15 replacement builds
25 Binder units, including the actual Parcel/IPCThreadState/ProcessState source,
and uses the original framework Binder/Parcel JNI. ART critical-native calling
conventions are selected explicitly without changing the OH libc target.
The source Binder NDK service lookup calls the Java OH service registry; it does
not fabricate Android kernel Binder services. Resource JNI uses Android 15's matching reference
ownership and configuration APIs. Its sandbox framework resource path is
explicitly supplied through `WESTLAKE_FRAMEWORK_RES_PATH`.

`build_oh61_headers.py` generates twelve OH IPC interfaces and unpacks JsonCpp
from pinned source. Westlake's native inventories and `compile_native_inventory.py`
record translation units, included headers, transforms and compiler identity.
`build_native_imports.py` generates link-only declarations from source object
exports and the checked-in `native/oh61-firmware-abi.json`. Their functions trap;
these declarations must never be deployed. `link_native_platform.py` links the
actual source libraries. The host-firmware ABI inventory now includes 46 libraries, including the device
Vulkan loader. Device probes verify their installed SHA-256 identities.

`probe_native_platform.py` staged the six source libraries and twenty source
core libraries in a new device directory and passed eager native loading on
2026-09-08. This checks relocations and constructors; full Java framework boot
and Toutiao UI acceptance are still pending. It does not accept captured
Android or Westlake binaries as source outputs.

The isolated Appspawn probe verifies boot JAR order, boot images, framework
resources, ICU data and the declared firmware hashes. The initial Android 14 renderer
failed an Android 15 Paint signature check. The Android 15 candidate now passes
strict linking for 24 libraries and passes the Appspawn preload entrypoint with
35 framework and all 52 upstream HWUI registration modules. This profile uses
HWUI's own APEX registrar, its JavaVM setup and real Typeface registration;
legacy Typeface cleanup overrides and the TextureLayer instruction patch are
excluded. The log still records a MediaCodec class initialization failure for
missing `libmedia_jni.so`. Preload success is not full framework/API acceptance.

The isolated RGBA8888 buffer probe passes a direct OH allocator control,
Android/OH format and stride comparison, reference lifetime, and CPU write/read
round trip. RGB565 did not pass; the separate direct host-control run exited
139 and remains unresolved. The Java contract probe additionally exercises
Parcel primitive/string calls, HardwareBuffer Parcel ownership and a software
Canvas pixel round trip. These Java contracts now pass. The original Android
NDK asset manager and all three `libjnigraphics` translation units also build.
Device checks validate NDK bitmap pixel sharing with Java, PNG and lossless WebP
round trips, JPEG within a stated lossy tolerance, and a one-pixel GIF decode.
The independent source Ganesh probe also passes on the Mali-G57: a direct GLES
control, source-provider identity, GPU rectangle/circle drawing, and four pixel
readbacks. This is an offscreen GPU contract; window presentation and Toutiao
UI acceptance remain required.

`probe_source_app.py` verifies a previously accepted framework stage and the
original APK, then creates app-owned source/runtime copies and fresh app data.
Its source helper mounts only those directories in a private namespace. It
can verify the installed host HAP against a signed source build. The rebuilt
`org.westlake.sourcehost` now runs under its own UID and window. Android 15 AIDL
Stubs use an OH token PermissionEnforcer that does not recursively initialize
the system context. Original Linux and TrafficStats JNI are built and registered;
the TrafficStats device contract checks EBADF, honest EOPNOTSUPP for unavailable
per-tag accounting, and preservation of the socket. The original Android legacy
C++ ABI runtime is also built, including async-safe logging and futex guards.

`SourcePackageRegistry` uses the original Android PackageParser for the supplied
APK, with certificate verification on signing-info requests. It returns separate
value objects using the current OH UID and isolated app paths. Device parsing
confirms versionCode 13900 and targetSdk 30; the earlier direct-launch defaults
reported targetSdk 33. Opening a library through the app-data `lib/arm64` symlink was denied in the
application process. The source launcher now supplies the real extracted
`lib/arm64-v8a` directory, and the original `libflipped.so` loads successfully.
`oh61-account-sources.lock.json` supplies canonical account headers. The source
helper queries OH account/storage state and the application confirms account 100
is active with verified storage. Application binding now completes and MainActivity
opens the source window session. Inspection attempt 24 retained live parent and
child processes and produced a complete DecorView/view tree for the Toutiao main
shell, including its tabs and a three-item recycler. The visible feed reported
`当前网络不可用，点击重试` (network unavailable, tap to retry), so
`full_source_ui_accepted` remains false. A later source probe also retained live
parent and child processes while reporting `source_ui_accepted=false` and
`full_source_closure=false`. This is a structural rendering milestone, not device
acceptance; network/provider integration, input behavior, media JNI and WebView
integration remain open.

The Bionic compatibility library supplies Android's `LIBC` symbol versions and
declares global symbol visibility for OH's relocation rules. Device checks cover
versioned lookup, thread-local errno, real syscall errors and exact output from
both Android legacy and ordinary host stdio handles. Original Android character
tables and ancillary-message traversal are built from the pinned Bionic source.
Original Android MessageQueue JNI and NDK Looper now use source-built libutils;
device checks verify Java polling dispatches NDK callbacks and the acquired
native looper survives disposal of the Java wrapper.

The Appspawn socket receiver now copies its fixed header before resizing the
request buffer. Its socket regression reproduces the previous use-after-free
under AddressSanitizer and passes after the fix. Device spawning also passes.
The graphics shim builder accepts an explicit Westlake source checkout and
reproduces all 21 existing objects byte-for-byte from that checkout.

`framework-fonts.lock.json` pins eight a2hlab font repositories. The asset
inventory follows Android 15's Blueprint selections: 206 fonts, two compatibility
aliases and two font configurations, packaged with source ICU data. Filesystem
ports redirect the original `SystemFonts` paths into the isolated runtime stage.
Appspawn uses the framework's SharedMemory font-map serialization/deserialization
path before forking. The device enumerates 220 font faces entirely inside the
source stage and renders the Chinese glyph `你` with 408 ink pixels. The core
boundary now registers the original AOSP `OsConstants` initializer against OH's
headers, and `java.lang.Character` uses source ICU 75 rather than firmware ICU.

The Android 15 candidate also compiles 30 Minikin, 48 Ultra HDR, seven GIF,
eight Binder NDK, 14 stats-pull and eight stats-socket units. AIDL interfaces
and stats logging code are generated from their pinned source schemas.
The OH SurfaceTexture facade uses the consumer buffer queue, fences, crop,
transform and color metadata. Buffer format and byte/pixel stride conversions
use the canonical platform declarations. EGL cache setup selects the host
EGL cache directory. Aggregate OH allocator accounting is reported as
unavailable rather than substituted with Android gralloc statistics.

`compose_native_runtime.py` records explicit replacements such as Minikin 14
to 15, verifies every input hash and rejects failed builds, link-only import
libraries and undeclared collisions. These native candidates still need
framework preload and complete Toutiao device acceptance. Full rebuild status
remains false; the historical captured-runtime UI is separate evidence.

Chromium 109.0.5414.123 builds as a standalone arm64 WebView provider.
Its build configuration disables optional WebLayer, ARCore and VR. All 136 Git source dependencies have been published under a2hlab
and pinned in `chromium109-dependencies.lock.json`. The 79,660,460-byte APK has
SHA-256 `566318270480029e6749febefdce560d038c02df099e8e931f798241b611c556`;
its two packaged native libraries match the build outputs. ProGuard's retained
class map still includes 445 Google Play Services, 705 AndroidX, 101 Kotlin and
58 Kotlin coroutines classes, so source-only Java dependency closure remains
open. Compiler-input pinning,
source builds of Java runtime dependencies, a fresh repository-only checkout
and native Android/OH provider integration remain acceptance steps; a Chromium compile alone does not prove a source-only WebView payload.

The host signing recipe fetches `host-signing-sources.lock.json` from a2hlab and
uses the upstream public OpenHarmony development certificates. The original
Android APK is never passed to that tool. It checks every program/resource ZIP
entry after signing; the executable-page bitmap `.pages.info` is generated by
the pinned signer. Production identities remain external. The separate source
host leaves the previously installed IME host in place.
