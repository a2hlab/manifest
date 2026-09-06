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
