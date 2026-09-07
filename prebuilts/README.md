# prebuilts

Binaries that are checked in rather than built by a profile. Each one is locked
by SHA256 in the `prebuilts` array of `sources.lock.json`, and
`tools/verify_prebuilts.py` compares every file against that record before any
profile runs, so a swapped or truncated prebuilt stops the build.

Nothing here is a file taken off a device. Every entry names a recipe under
`tools/recipes/` that produced it, and that recipe is in the tree. The rule this
directory follows is the one `full-build-gaps.json` states: historical board
JARs must not become unrecorded build inputs. A build output of a recipe we own
is a different thing from a binary of unknown origin, and the lock plus the
recipe are what make the difference checkable rather than a matter of trust.

## wl-tls-min.jar

The TLS stack the adapter loads at runtime: R8-shrunk BouncyCastle 1.78.1
(bcprov / bcutil / bctls, jdk18on) plus `westlake.tls`, dexed for min-api 30.

It is checked in rather than built per-profile because the build needs R8, D8, a
JDK and Maven access, none of which are in the locked toolchain set. Recipe:
`tools/recipes/build_tls_min.sh`.

Why a shrunk build exists at all: stock BouncyCastle is 5403 classes, and on a
runtime forced to `-Xint` the provider constructor alone -- 94 `$Mappings`
classes, fifteen post-quantum key factories -- costs seconds that the app spends
inside TTNet's connect timeout. The recipe removes what TLS does not use, and
verifies the result rather than assuming it: a structural check that every
advertised algorithm can still be instantiated, then a live handshake against
six production hosts over TLS 1.3 and 1.2, run against the shrunk classfiles
*before* they are dexed. An over-shrink shows up there instead of as a
`user_canceled` alert on a board.

The Java half of the stack is source in westlake at
`framework/security/java/westlake/tls/`, and the gate in front of it is
`framework/security/java/WlTlsGate.java`. This jar is the packaging, not the
only copy of the logic.

## oh-adapter-runtime.jar

The adapter runtime the child process loads: `ActivityManagerRouting`, the TLS
gate and its bootstrap, and the `android.net.ssl.SSLSockets` stand-in okhttp
reaches for on SDK >= 29. Four sources, 32 classes, one `classes.dex` at
min-api 30. Recipe: `tools/recipes/build_adapter_runtime.sh`.

Unlike the TLS jar, every input to this one is source in westlake. It is
checked in for one reason only: dexing needs a dexer, and no dexer is in the
locked toolchain set. `build.json` beside it records which one was used, down to
its SHA256 and self-reported version, because that tool decides the artifact's
bytes and nothing else pins it.

It is deterministic — three independent builds into different directories
produced these same bytes — so the checked-in copy is a convenience, not the
only copy that can exist. Anyone with a dexer can regenerate it and compare.

`compiled_against_real_framework` is `false`, and that is not an oversight. The
adapter's `framework.jar` is a dex archive and `javac` cannot compile against
dex, so the build runs against the compile-only stand-ins in westlake's
`framework/activity/stubs`. That is the cold-start dependency cycle
`full-build-gaps.json` records, seen from the compile side, and it is the same
path the frontline validated on hardware. Five platform types are involved and
bytecode references them by name and descriptor, so a stand-in of the same shape
yields the same constant-pool entries — but the closure is still open, and the
flag says so rather than letting a reader assume otherwise.

What it does *not* contain, deliberately: `westlake.tls` (that is
`wl-tls-min.jar`, loaded through its own DexClassLoader) and the rest of
`framework/activity/java` (fifteen classes that need the real platform).

## oh-adapter-runtime-unified.jar — transitional

61 classes in one `classes.dex`: **37 compiled from westlake source, 23 from
`baseline-classes-retarget.dex`**, plus one d8 synthetic. `build.json` beside it
lists both sets by name, and the lock entry says `fully_source_built: false`.

This exists because the source-only `oh-adapter-runtime.jar` above, for all that
it is genuinely closed over its own classes, **cannot replace the deployed
runtime** — it lacks `AppSpawnXInit`, the child bootstrap entry point, so
swapping it in would stop every app launching.
`westlake tools/check_runtime_replacement.py` refuses that swap and passes this
one:

```
candidate defines 61 classes; deployed defines 28
SAFE: the candidate is a superset.
```

The price is a prebuilt dex in the middle of the build — the thing this
workstream exists to remove. It is a step backwards taken deliberately and
under a decision, not by drift. Retiring it needs the two adapter entries in
`full-build-gaps.json` closed: a classfile-form platform classpath (the
adapter's `framework.jar` is dex-only, so `javac` cannot use it) and a source
owner for `PmProxy`.

`baseline-classes-retarget.dex` is archived alongside for one reason: without
it the fusion could only be reproduced from a frontline home directory. Pinning
its identity here is not an endorsement of it.

Deterministic: two independent builds gave identical bytes. **Not pushed to any
device.**
