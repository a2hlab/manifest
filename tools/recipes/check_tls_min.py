#!/usr/bin/env python3
"""Check that every algorithm the shrunk provider still advertises can be built.

The live self-test proves the paths it exercises.  It cannot prove anything about
the algorithms the provider registers but the test never requests, and those are
exactly where this shrink is fragile: BouncyCastle's $Mappings classes register
their SPI implementations by *string name*,

    provider.addAlgorithm("Cipher.AES", PREFIX + "$ECB");

so R8 has no edge to follow, and a class removed out from under a surviving
registration produces a Provider entry that resolves to nothing.  The failure
surfaces only when something asks for that algorithm -- potentially on the board,
weeks later, as a ClassNotFoundException inside a handshake.

So: read the string constants out of every surviving $Mappings class, treat the
ones shaped like class names as claims the provider is making, and verify each
claim against the jar.  This is a structural check over *all* registered
algorithms rather than a behavioural check over the tested ones.

    check_tls_min.py <jar>

Exit status is non-zero if the provider advertises anything it cannot deliver.
"""

import re
import sys
import zipfile

# Class names as they appear in the constant pool.  Property keys such as
# "org.bouncycastle.ec.disable_mqv" match this too, so the results are filtered
# below on the shape of the final segment.
NAME = re.compile(rb"org\.bouncycastle\.[A-Za-z0-9_.$]+")

# Schemes build_tls_min.sh removes on purpose from families it otherwise keeps.
# Their registrations survive as names, which is harmless -- nothing requests
# them -- but it means "missing" is the expected state, not a defect.  Listing
# them explicitly is what lets this check fail loudly on anything *else*.
P = "org.bouncycastle.jcajce.provider.asymmetric."
INTENTIONALLY_REMOVED = (
    P + "ec.IESCipher",        # ECIES: integrated encryption, not a TLS construct
    P + "ec.IESKEMCipher",
    P + "ec.GM",               # SM2/SM9, the Chinese national suite
    P + "dh.IESCipher",
    P + "edec.IESCipher",
    P + "rsa.ISOSignatureSpi",  # ISO 9796-2, superseded by PKCS#1 v1.5 and PSS
    P + "rsa.X931SignatureSpi", # ANSI X9.31, likewise
)


def looks_like_a_class(name):
    """Class names have an upper-case final segment; property keys do not."""
    last = name.rsplit(".", 1)[-1]
    return bool(last) and (last[0].isupper() or "$" in last)


def main(jar_path):
    with zipfile.ZipFile(jar_path) as z:
        present = {n[:-len(".class")].replace("/", ".")
                   for n in z.namelist() if n.endswith(".class")}
        mappings = sorted(n for n in z.namelist() if n.endswith("$Mappings.class"))

        claims = {}
        for entry in mappings:
            raw = z.read(entry)
            owner = entry[:-len(".class")].replace("/", ".")
            for m in NAME.finditer(raw):
                name = m.group(0).decode("ascii")
                if looks_like_a_class(name):
                    claims.setdefault(name, set()).add(owner)

    absent = {n: o for n, o in claims.items() if n not in present}
    expected = {n: o for n, o in absent.items()
                if n.startswith(INTENTIONALLY_REMOVED)}
    missing = {n: o for n, o in absent.items() if n not in expected}

    print(f"  $Mappings surviving : {len(mappings)}")
    print(f"  classes advertised  : {len(claims)}")
    print(f"  classes present     : {len(claims) - len(absent)}")
    print(f"  removed on purpose  : {len(expected)}")

    if missing:
        print(f"  UNEXPECTEDLY MISSING: {len(missing)}")
        # Group by the family that registered them, which is how a human decides
        # whether the loss is intended (a scheme we pruned) or a shrink bug.
        by_owner = {}
        for name, owners in sorted(missing.items()):
            for o in owners:
                by_owner.setdefault(o.rsplit(".", 1)[-1], []).append(name)
        for owner, names in sorted(by_owner.items()):
            print(f"    {owner}: {len(names)}")
            for n in sorted(names)[:4]:
                print(f"      {n}")
            if len(names) > 4:
                print(f"      ... and {len(names) - 4} more")
        return 1

    print("  OK: every advertised algorithm resolves "
          "(bar the ones removed on purpose)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
