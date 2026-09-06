#!/usr/bin/env bash
# Regenerate prebuilts/oh-adapter-runtime.jar.
#
# The jar is checked in because producing it needs a dexer, and a dexer is not
# in the locked toolchain set -- the same reason wl-tls-min.jar is checked in.
# Everything else about it is source in westlake, so this recipe is short: it
# points the westlake builder at a workspace and copies the result.
#
# The builder itself (westlake tools/build_adapter_runtime.py) is where the
# interesting decisions live -- which classes ship, why the compile runs against
# compile-only stand-ins, why it fails closed without a dexer. This file exists
# so "how do I regenerate this binary" has an answer next to the binary.
#
#   WORKSPACE   a fetched workspace (default: /opt/a2h/ws)
#   R8          path to r8.jar; Google publishes D8 inside it, run through java.
#               Fetch with:
#                 curl -O https://dl.google.com/dl/android/maven2/\
#                 com/android/tools/r8/9.4.17/r8-9.4.17.jar
#               The version and SHA256 actually used are recorded in the
#               build.json this produces, and in the prebuilts lock entry.
#   OUT         new output directory (default: ./out/adapter-runtime)
#   JAVA_HOME   a JDK 11+
#
# The jar is deterministic: same sources and same dexer give the same bytes.
# Verified by building twice into different directories and comparing.
set -euo pipefail

WORKSPACE="${WORKSPACE:-/opt/a2h/ws}"
OUT="${OUT:-$PWD/out/adapter-runtime}"

[ -n "${R8:-}" ] || { echo "set R8 to an r8.jar (see the header)" >&2; exit 1; }
[ -f "$R8" ] || { echo "no such r8 jar: $R8" >&2; exit 1; }

BUILDER="$WORKSPACE/westlake/tools/build_adapter_runtime.py"
[ -f "$BUILDER" ] || { echo "no westlake builder at $BUILDER -- is WORKSPACE fetched?" >&2; exit 1; }

python3 "$BUILDER" --out "$OUT" --r8 "$R8"

echo
echo "jar:  $OUT/oh-adapter-runtime.jar"
sha256sum "$OUT/oh-adapter-runtime.jar"
echo "record: $OUT/build.json"
