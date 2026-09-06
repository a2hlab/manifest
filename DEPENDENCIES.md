# Dependency closure: what is actually checked in

The `native`, `apps` and `art` component profiles consume only locked a2hlab
project repositories plus declared standard host prerequisites. The full Toutiao
stack is **not yet reproducible from these repositories alone**.

The [parity follow-up](PARITY27.md) adds concrete SDK/provider/application locks
and a 410-file observed runtime inventory. These expose remaining binary inputs;
they do not supply the missing corresponding framework/boot/firmware sources.

| Input | Repository coverage | Remaining limitation |
| --- | --- | --- |
| ART, JNI/boundary, host and Pinyin sources | `westlake`, `art-build`, `aosp-art-15` | Component build evidence is not full process acceptance |
| 16 upstream support/resource dependencies | `dep-*`, locked snapshots preserving original source trees and licenses | Original ancestry metadata retained; snapshots do not contain all upstream Git history |
| OH SDK6.1.0.31 and platform clang15 | `toolchains`, actual LFS archives and hash-locked installation | Prebuilt compiler inputs, not compiler source bootstrap |
| HWUI14, Minikin14, FreeType11, HarfBuzz11, WebP11 and local bridge/HWUI headers | `legacy-runtime-sources`, per-file provenance and local patches | Preserved sources, not yet a closed build/provider graph |
| Linux, Git/LFS, Python, Make, patch, host GCC/libstdc++ headers/libraries | Declared workstation prerequisites; tested on Ubuntu24.04 | No checked-in host image/sysroot; cross-host bit identity is unproven |
| Exact core/framework JAR sources and generation recipes | Missing matching source handoff | Local AOSP11 libcore is not proven to match the frozen JARs; historical scripts pulled final ECS artifacts |
| Host dex2oat and ten-JAR boot image | Incomplete source recipe | No historical `.art/.oat/.vdex` substituted |
| OH firmware, full bridge/Skia and board provider set | Not closed/pinned as a complete source build | Mixed revisions/generated headers/vendor graphics providers must be resolved |
| Toutiao/WebView APKs, proprietary native libraries | Not distributed | Redistribution permission and exact identities/licensing required |
| Private app state, signing keys and device credentials | Deliberately excluded | Operators supply their own; these must not become repository dependencies |

## Required handoff to finish the full stack

Provide the source manifest, local patches and generated-source recipes for the
ECS build that produced the accepted core/framework JARs, plus the exact board
OS/firmware build and provider manifest. The known historical workflow pulls
final JARs from the builder; it does not capture corresponding source state.
The local libcore license contains GPL with Classpath Exception, so unmatched
sources or an Apache NOTICE cannot establish a corresponding-source release.

For proprietary app/vendor files, confirm redistribution rights separately. A
private organization does not itself establish those rights. Raw user-data
snapshots, request files, learned dictionaries and credentials are not substitutes
for a fresh-install recipe and must remain excluded.

The audited candidate05 core consists of 15 framework files, 11 runtime files
and 30 boot files (56 files, 172824635 bytes). This is an inventory of historical
inputs, **not a published or accepted reproduction bundle**. Its runtime files
have 68 distinct direct DT_NEEDED names, only three provided within that group.
Normal platform dependencies must be resolved against the exact board ABI,
not filled with arbitrary DSOs found on a workstation.

`full-build-gaps.json` and `tools/rebuild.py --profile full` remain fail-closed.
No Toutiao functionality or native-performance-parity claim follows from an
offline component build or from committing additional source dependencies.
