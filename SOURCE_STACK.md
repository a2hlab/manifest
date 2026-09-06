# Source-built Android/Westlake with an original Toutiao APK

The target is a source-built Android/Westlake runtime on the connected OHOS
platform, with Toutiao supplied as an unchanged, content-locked application.
Toutiao application source is **not required**. The APK is never decompiled,
patched, re-signed, or used to compile framework classes.

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

While these changes are in review, start with the `source-stack-closure` branch:

```sh
git clone --branch source-stack-closure https://github.com/a2hlab/manifest.git a2hlab-manifest
cd a2hlab-manifest
```

Bootstrap the standard source/toolchain locks as described in README.md. The
ART profile now also fetches the preserved WebP source through the default lock.
For the additional Android core sources and compiler:

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock core-sources.lock.json
python3 tools/install_java.py --workspace /workspace
python3 tools/rebuild.py --workspace /workspace --profile host-tools --out /workspace/out/host-tools --jobs 4
python3 tools/rebuild.py --workspace /workspace --profile core-java --out /workspace/out/core-java
python3 tools/rebuild.py --workspace /workspace --profile art --out /workspace/out/art --jobs 6
python3 tools/build_core_boot.py --host-build /workspace/out/host-tools/host --core-build /workspace/out/core-java/java --out /workspace/out/core-boot
```

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
  Conscrypt's full Java/native implementation is still required by the stack.
* `art` builds the real WebP decoder and links it into the runtime dependency
  graph. The null decoder fallback is removed. ART declares platform libc++'s
  `std::__h` provider, uses OHOS musl's program-name symbol, and delegates Binder
  library loading to the normal ART loader. The SDK/provider audit must pass.

Bouncy Castle and Apache XML have an additional source recipe using the
verified core compile classes and the same pinned JDK/D8:

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock java-extensions.lock.json
python3 tools/build_java_extensions.py --workspace /workspace --core-build /workspace/out/core-java/java --out /workspace/out/java-extensions
```

It compiles 1291 declared Java sources, preserves Apache XML resources, and
checks compiled-class ownership and duplicate DEX definitions against the core.
These JARs have not yet been accepted as part of the complete boot classpath.

The additional complete AOSP framework source snapshot is available separately:

```sh
python3 tools/fetch_sources.py --workspace /workspace --lock framework-sources.lock.json
```

It preserves upstream licenses and source provenance. Its upstream Gradle
distribution exceeds GitHub's normal blob limit and is stored in Git LFS, with
its exact original size/hash recorded. Fetching this source does not itself
build `framework.jar` or `framework-res.apk`.

The source-built host tool also generates an ARM64 boot image for these four
core JARs. This is a core image, not the final framework/Westlake boot image.
The builder verifies the input artifact hashes and records all twelve image,
OAT, and VDEX outputs. Core JAR verification rejects duplicate DEX definitions,
compile-header leakage, and loss of required ART classes such as `java.lang.Record`.

## Reproduce the core device check

After the builds above, use the connected OHOS device's HDC executable and serial:

```sh
python3 tools/probe_core_vm.py --workspace /workspace --runtime /workspace/out/art/runtime --core /workspace/out/core-java/java --boot /workspace/out/core-boot --out /workspace/out/core-device-probe --hdc /path/to/hdc --serial DEVICE_SERIAL
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

`--profile full` remains unavailable until the framework/resources, adapter
Java cycle, complete boot classpath/image, HWUI, bridge/appspawn, and runtime
deployment graph are built and the resulting payload launches Toutiao on the
device. The app-input lock, source component builds, a successful dynamic
loader probe, and the earlier binary-runtime UX demonstration are separate
pieces of evidence. None alone establishes a complete source-built UX.
