#!/usr/bin/env bash
# Build out/wl-tls-min.jar -- the R8-shrunk TLS stack.
#
# The stock out/wl-tls.jar carries all 5403 BouncyCastle classes.  On this board
# the runtime is forced to -Xint, and BouncyCastleProvider's constructor eagerly
# loads 94 $Mappings classes and registers every algorithm family BC ships, so
# installing the provider costs seconds that the app spends inside TTNet's
# connect timeout.  Everything TLS does not use is removed here.
#
# The shrink is verified, not assumed.  R8 emits classfiles first, the real
# handshake self-test runs against them on this host -- six live production hosts,
# TLS 1.3 and 1.2, plus the okhttp code path -- and only then are they dexed.
# A shrink that silently drops an algorithm shows up as a failed probe here
# rather than as a user_canceled on the board.
#
#   JAVA_HOME   a JDK 11+     R8/D8   paths     BC_VERSION   default 1.78.1
#   SKIP_VERIFY=1             skip the live handshake (offline)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BC_VERSION="${BC_VERSION:-1.78.1}"
WORK="$ROOT/work/bc"
OUT="$ROOT/out"
BUILD="$ROOT/build/min"

if [ -n "${JAVA_HOME:-}" ]; then
    JAVAC="$JAVA_HOME/bin/javac"; JAVA="$JAVA_HOME/bin/java"
else
    JAVAC="$(command -v javac)"; JAVA="$(command -v java)"
fi
R8="${R8:-$(command -v r8 || true)}"
D8="${D8:-$(command -v d8 || true)}"
for t in "$JAVAC" "$JAVA" "$R8" "$D8"; do
    [ -x "$t" ] || { echo "missing tool: ${t:-<unset>} (set JAVA_HOME / R8 / D8)" >&2; exit 1; }
done

BCCP="$WORK/bcprov-jdk18on-$BC_VERSION.jar:$WORK/bcutil-jdk18on-$BC_VERSION.jar:$WORK/bctls-jdk18on-$BC_VERSION.jar"
for j in $(echo "$BCCP" | tr ':' ' '); do
    [ -f "$j" ] || { echo "missing $j -- run scripts/build_tls.sh first" >&2; exit 1; }
done

rm -rf "$BUILD"; mkdir -p "$BUILD" "$OUT"

echo "[1/5] compile westlake.tls"
mkdir -p "$BUILD/classes"
find "$ROOT/src" -name '*.java' -exec "$JAVAC" --release 8 -nowarn -cp "$BCCP" \
    -d "$BUILD/classes" {} +

# BC ships multi-release jars; d8/r8 reject module-info and META-INF/versions.
echo "[2/5] stage BC (dropping multi-release + module-info)"
mkdir -p "$BUILD/bc"
( cd "$BUILD/bc"
  for a in bcprov-jdk18on bcutil-jdk18on bctls-jdk18on; do
      unzip -o -q "$WORK/$a-$BC_VERSION.jar" \
          -x 'META-INF/versions/*' 'module-info.class' 'META-INF/*.SF' \
             'META-INF/*.DSA' 'META-INF/*.RSA' 2>/dev/null || true
  done
  rm -f module-info.class )

# Patch BouncyCastleProvider before anything else looks at the tree.
#
# Its constructor calls loadPQCKeys(), which statically instantiates fifteen
# post-quantum key factories, and drives loadAlgorithms() over arrays naming 94
# algorithm families.  The first pins the whole pqc tree into the build no matter
# what the keep rules say; the second is pure start-up cost.  Both are removed at
# source level because neither can be expressed as an R8 rule.
SRCJAR="$WORK/bcprov-src.jar"
if [ ! -f "$SRCJAR" ]; then
    echo "      fetching bcprov sources"
    curl -sSL --max-time 300 -o "$SRCJAR" \
        "https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk18on/$BC_VERSION/bcprov-jdk18on-$BC_VERSION-sources.jar"
fi
python3 "$HERE/patch_bc_provider.py" "$SRCJAR" "$BUILD/patched-src"
# CustomNamedCurves holds a static holder per SEC curve, which is why all nine
# binary curves and every small prime curve load on a client that only ever
# offers x25519 and secp256r1.  Trimming it is safe because ECUtil falls back to
# the generic ECNamedCurveTable when the optimised table misses.
python3 "$HERE/patch_bc_curves.py" "$SRCJAR" "$BUILD/patched-src"

# Compiled against the *stock* jars so every unrelated reference still resolves;
# only the patched classes are overlaid, so the result carries no pqc references
# and no dropped-curve references.
mkdir -p "$BUILD/patched-classes"
"$JAVAC" --release 8 -nowarn -cp "$BCCP" -d "$BUILD/patched-classes" \
    "$BUILD/patched-src/org/bouncycastle/jce/provider/BouncyCastleProvider.java" \
    "$BUILD/patched-src/org/bouncycastle/crypto/ec/CustomNamedCurves.java"

# Anonymous inner classes are numbered by source order, so removing holders
# renumbers them.  The stock CustomNamedCurves$NN.class files must go before the
# patched ones land, or the tree ends up with a mix of both numberings.
rm -f "$BUILD/bc/org/bouncycastle/crypto/ec/"CustomNamedCurves*.class
for pkg in jce/provider crypto/ec; do
    cp "$BUILD/patched-classes/org/bouncycastle/$pkg/"*.class \
       "$BUILD/bc/org/bouncycastle/$pkg/"
done
echo "      overlaid $(find "$BUILD/patched-classes" -name '*.class' | wc -l | tr -d ' ') patched class file(s)"

# Prune whole families before R8 sees them.
#
# These could in principle be left to tree shaking, but R8 keeps them anyway and
# -whyareyoukeeping shows why: BouncyCastleProvider.getPublicKey() invokes
# AsymmetricKeyInfoConverter.generatePublic(), an interface method, so R8's
# virtual-dispatch analysis conservatively retains every implementor in the
# program -- which is every post-quantum key factory, and through them the whole
# pqc tree (292 classes survived a build that had no rule keeping them).
#
# Deleting the input is deterministic where a keep rule is an argument with the
# optimiser, and it is safe for exactly the reason the whole shrink is safe:
# BouncyCastleProvider.loadServiceClass() resolves each family's $Mappings via
# ClassUtil.loadClass(), which returns null on ClassNotFoundException, so an
# absent family is skipped rather than fatal.
STAGED=$(find "$BUILD/bc" -name '*.class' | wc -l | tr -d ' ')
echo "      staged: $STAGED classes; pruning families TLS never uses"
( cd "$BUILD/bc"
  # NOTE: org/bouncycastle/x509 is deliberately NOT in this list.  It looks like
  # dead legacy API, but PKIXCertPathValidatorSpi reaches ExtendedPKIXParameters
  # through it, and pruning it turned every probe into
  #   NoClassDefFoundError: org/bouncycastle/x509/ExtendedPKIXParameters
  # at startHandshake.  It is 38 classes; R8 shrinks it to what is reachable.
  for p in pqc oer i18n \
           jcajce/provider/keystore \
           jcajce/provider/asymmetric/ecgost \
           jcajce/provider/asymmetric/ecgost12 \
           jcajce/provider/asymmetric/compositesignatures; do
      [ -d "org/bouncycastle/$p" ] && rm -rf "org/bouncycastle/$p"
  done
  # $Mappings entry points for families whose implementation packages are gone,
  # plus the ones BouncyCastleProvider would otherwise still load eagerly.
  rm -f org/bouncycastle/jcajce/provider/asymmetric/{GOST,ECGOST,DSTU4145,ElGamal,IES,GM,LMS,COMPOSITE,EXTERNAL,CompositeSignatures,Dilithium,Falcon,NTRU,SPHINCSPlus,Kyber,Picnic,Rainbow,SABER,Frodo,BIKE,HQC,CMCE,NTRUPrime,SNTRUPrime,XMSS,SPHINCS,McEliece,NH,QTESLA}*.class 2>/dev/null

  # Schemes inside families we do keep.  The keep rules have to name whole
  # packages (the $Mappings register their SPIs by string, so R8 cannot trace
  # them), which drags in every scheme the family implements.  These are removed
  # here instead:
  #   ECIES / IES-KEM   integrated encryption, not a TLS construct
  #   GM*               SM2/SM9, the Chinese national suite
  #   X931 / ISO9796    legacy RSA signature encodings, superseded by PKCS#1 and
  #                     PSS, both of which stay
  # Their $Mappings entries survive as registered *names*; a name whose class is
  # gone only fails if something asks for that algorithm, and nothing does.
  rm -f org/bouncycastle/jcajce/provider/asymmetric/ec/{IESCipher,IESKEMCipher,GMCipherSpi,GMSignatureSpi,GMKeyPairGeneratorSpi}*.class 2>/dev/null
  rm -f org/bouncycastle/jcajce/provider/asymmetric/rsa/{X931SignatureSpi,ISOSignatureSpi}*.class 2>/dev/null
  rm -f org/bouncycastle/jcajce/provider/asymmetric/dh/IESCipher*.class 2>/dev/null
  rm -f org/bouncycastle/jcajce/provider/asymmetric/edec/IESCipher*.class 2>/dev/null
  echo "      remaining input classes: $(find . -name '*.class' | wc -l | tr -d ' ')" )

( cd "$BUILD/bc" && zip -q -r -X "$BUILD/bc-clean.jar" . )
# R8 takes class/zip/jar files, not directories.
( cd "$BUILD/classes" && zip -q -r -X "$BUILD/wl-classes.jar" . )

echo "[3/5] r8 shrink -> classfiles"
"$R8" --classfile --release \
    --lib "${JAVA_HOME:-$(dirname "$(dirname "$JAVA")")}" \
    --pg-conf "$HERE/tls-shrink.pro" \
    --pg-conf-output "$BUILD/pg-conf-effective.txt" \
    --output "$BUILD/min-classes.jar" \
    "$BUILD/bc-clean.jar" "$BUILD/wl-classes.jar"

PRUNED=$(unzip -l "$BUILD/bc-clean.jar" | grep -c '\.class$' || true)
AFTER=$(unzip -l "$BUILD/min-classes.jar" | grep -c '\.class$' || true)
echo "      classes: $STAGED staged -> $PRUNED after prune -> $AFTER after r8"

echo "[4/5] verify"
# Structural check first: it needs no network, and it covers every algorithm the
# provider still advertises rather than only the ones the handshake exercises.
python3 "$HERE/check_tls_min.py" "$BUILD/min-classes.jar" || {
    echo "structural check failed -- the provider advertises algorithms it cannot build" >&2
    exit 1
}
echo "      live handshake against the shrunk classes"
if [ "${SKIP_VERIFY:-0}" = "1" ]; then
    echo "      (SKIP_VERIFY=1 -- skipped)"
else
    BUNDLE="${TRUST_BUNDLE:-$OUT/wl-cacerts.pem}"
    [ -f "$BUNDLE" ] || { echo "no trust bundle at $BUNDLE" >&2; exit 1; }
    # Only the shrunk jar on the classpath: if R8 removed something the
    # handshake needs, there is no unshrunk copy to fall back to.
    set +e
    "$JAVA" -Dwestlake.tls.trustBundle="$BUNDLE" \
        -cp "$BUILD/min-classes.jar" \
        westlake.tls.TlsBootstrap ib.snssdk.com 443 https://ib.snssdk.com/ \
        > "$BUILD/verify.log" 2>&1
    rc=$?
    set -e
    grep -aE '^\[WL-TLS\] (ok|FAILED|probe)|^selftest:' "$BUILD/verify.log" | sed 's/^/      /'
    # "handshake=OK" is the claim that matters; a MATCH count below six means a
    # host stopped negotiating, which is exactly what an over-shrink looks like.
    if [ $rc -ne 0 ] || ! grep -aq 'handshake=OK' "$BUILD/verify.log"; then
        echo "VERIFY FAILED (rc=$rc) -- see $BUILD/verify.log" >&2
        exit 1
    fi
    matches=$(grep -ac ' -> MATCH ' "$BUILD/verify.log" || true)
    echo "      probes matched: $matches/6"
    [ "$matches" -eq 6 ] || { echo "VERIFY FAILED: only $matches/6 probes matched" >&2; exit 1; }
fi

echo "[5/5] dex + package"
rm -rf "$BUILD/dex"; mkdir -p "$BUILD/dex"
"$D8" --release --min-api 30 --output "$BUILD/dex" \
    ${JAVA_HOME:+--lib "$JAVA_HOME"} "$BUILD/min-classes.jar"
rm -f "$OUT/wl-tls-min.jar"
( cd "$BUILD/dex" && zip -q -X "$OUT/wl-tls-min.jar" classes.dex )

echo
STOCK=$(stat -f %z "$OUT/wl-tls.jar" 2>/dev/null || echo 0)
MIN=$(stat -f %z "$OUT/wl-tls-min.jar")
echo "  stock (wl-tls.jar)     : $STOCK bytes / $STAGED classes"
echo "  min   (wl-tls-min.jar) : $MIN bytes / $AFTER classes"
shasum -a 256 "$OUT/wl-tls-min.jar"
