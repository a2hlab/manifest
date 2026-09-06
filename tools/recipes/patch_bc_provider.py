#!/usr/bin/env python3
"""Patch BouncyCastleProvider so the TLS build can actually drop what it does not use.

Two things in this one class defeat tree shaking and cost real start-up time:

1.  `loadPQCKeys()` is called from the constructor and contains several hundred
    lines of

        addKeyInfoConverter(BCObjectIdentifiers.sphincsPlus, new SPHINCSPlusKeyFactorySpi());

    Those are *static* references to fifteen post-quantum key-factory packages.
    R8 therefore cannot remove the pqc tree no matter what the keep rules say
    (-whyareyoukeeping traces it straight back to the provider), and deleting the
    tree from the input instead just moves the failure to runtime:

        ClassNotFoundException: org.bouncycastle.pqc.jcajce.provider.
                                sphincsplus.SPHINCSPlusKeyFactorySpi

    Emptying the method removes the dependency and several hundred map
    insertions from provider construction.  What is lost is the ability to parse
    a certificate whose subject key is post-quantum; no host in this app's
    traffic serves one, and if one ever did, the handshake would fail rather than
    misbehave.

2.  The algorithm-name arrays drive `loadAlgorithms()`, which resolves
    `<family>$Mappings` by name for every entry.  A stock provider loads 94 of
    them -- Zuc, VMPC, GOST, Grain128, Whirlpool, Haraka and so on -- and each
    one it *cannot* find still costs a thrown-and-caught ClassNotFoundException.
    Trimming the arrays to the families TLS negotiates removes both the work and
    the exception churn.

Everything here is a deletion.  No behaviour is added, and the remaining
families are exactly the ones a live handshake against the six production hosts
exercises -- which scripts/build_tls_min.sh then verifies for real before the
result is dexed.

    patch_bc_provider.py <bcprov-src.jar> <out-dir>
"""

import re
import sys
import zipfile

SRC = "org/bouncycastle/jce/provider/BouncyCastleProvider.java"

# Families kept, by array.  Each list is the TLS-reachable subset of the stock
# one; see the module docstring for why the rest go.
ARRAYS = {
    # PBE/scrypt key derivation is for password-based keystores we do not open.
    "SYMMETRIC_GENERIC": '"TLSKDF"',
    # Poly1305 is the MAC half of CHACHA20_POLY1305.
    "SYMMETRIC_MACS": '"Poly1305"',
    # AES for the GCM/CBC suites, ChaCha for CHACHA20_POLY1305.
    "SYMMETRIC_CIPHERS": 'service("AES", 256), service("ChaCha", 128)',
    # X509 is the CertificateFactory the PEM trust bundle is parsed with.
    "ASYMMETRIC_GENERIC": '"X509"',
    # EC/EdEC: ECDHE, ECDSA, X25519, Ed25519.  RSA: the server certificates.
    # DSA/DH kept for a chain or 1.2 fallback that still needs them.
    "ASYMMETRIC_CIPHERS": '"DSA", "DH", "EC", "RSA", "EdEC"',
    # SHA-1 and MD5 stay for certificate signatures and the TLS 1.2 PRF.
    "DIGESTS": '"MD5", "SHA1", "SHA224", "SHA256", "SHA384", "SHA512"',
    # The trust store is a plain PEM bundle read through CertificateFactory
    # precisely so no KeyStore implementation is needed.
    "KEYSTORES": "",
    "SECURE_RANDOMS": '"DRBG"',
}


def replace_array(src, name, body):
    """Rewrite the initialiser of `private static final ...[] NAME = { ... };`."""
    pat = re.compile(
        r"(private\s+static\s+final\s+\S+\[\]\s+" + re.escape(name) + r"\s*=\s*)\{.*?\}",
        re.S,
    )
    new, n = pat.subn(lambda m: m.group(1) + "{ " + body + " }", src, count=1)
    if n != 1:
        raise SystemExit(f"patch failed: array {name} not found exactly once (n={n})")
    return new


def empty_method(src, name):
    """Replace the body of a private void method with an empty one."""
    start = src.find(f"private void {name}()")
    if start < 0:
        raise SystemExit(f"patch failed: method {name} not found")
    brace = src.find("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        raise SystemExit(f"patch failed: unbalanced braces in {name}")
    return src[:brace] + "{\n        // WESTLAKE: emptied -- see patch_bc_provider.py\n    }" + src[i + 1:]


def main(src_jar, out_dir):
    with zipfile.ZipFile(src_jar) as z:
        src = z.read(SRC).decode("utf-8")

    original_len = len(src)

    src = empty_method(src, "loadPQCKeys")

    # getPublicKey() also special-cases Picnic ahead of the generic converter
    # lookup, which is a second static reference into the pqc tree:
    #
    #     if (publicKeyInfo.getAlgorithm().getAlgorithm().on(BCObjectIdentifiers.picnic_key))
    #     {
    #         return new PicnicKeyFactorySpi().generatePublic(publicKeyInfo);
    #     }
    #
    # Dropping the shortcut leaves the generic path, which returns null for an
    # algorithm with no registered converter -- the same answer the caller
    # already handles for every other unknown key type.
    # The condition itself contains nested calls -- getAlgorithm().getAlgorithm()
    # -- so the parenthesis run cannot be matched with a negated character class.
    src, n_picnic = re.subn(
        r"\n[ \t]*if \(.*picnic_key.*\)\s*\n[ \t]*\{[^{}]*\}\n",
        "\n",
        src,
    )
    if n_picnic != 1:
        raise SystemExit(f"patch failed: picnic shortcut not removed exactly once (n={n_picnic})")

    # The imports are now unreferenced; dropping them is what actually lets the
    # pqc packages leave the build, since javac would otherwise still resolve them.
    src, n_imports = re.subn(r"^import\s+org\.bouncycastle\.pqc\..*?;\n", "", src, flags=re.M)

    for name, body in ARRAYS.items():
        src = replace_array(src, name, body)

    # Removing the imports turns any surviving use into a bare simple name, which
    # a search for "org.bouncycastle.pqc." would miss -- that is exactly how the
    # Picnic shortcut above got through the first time, surfacing as a javac
    # "cannot find symbol" rather than as a failed check here.  So assert on both
    # the qualified form and every simple name whose import was dropped.
    leftover = re.findall(r"org\.bouncycastle\.pqc\.[A-Za-z0-9_.]*", src)
    for simple in ("PicnicKeyFactorySpi", "SPHINCSPlusKeyFactorySpi", "DilithiumKeyFactorySpi",
                   "FalconKeyFactorySpi", "NTRUKeyFactorySpi", "KyberKeyFactorySpi",
                   "BIKEKeyFactorySpi", "CMCEKeyFactorySpi", "HQCKeyFactorySpi",
                   "LMSKeyFactorySpi", "NHKeyFactorySpi", "Sphincs256KeyFactorySpi",
                   "XMSSKeyFactorySpi", "XMSSMTKeyFactorySpi", "PQCObjectIdentifiers"):
        if re.search(r"\b" + simple + r"\b", src):
            leftover.append(simple)
    if leftover:
        raise SystemExit(f"patch failed: pqc references remain: {sorted(set(leftover))[:6]}")

    out = f"{out_dir}/{SRC}"
    import os

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"      patched BouncyCastleProvider: -{n_imports} pqc imports, "
          f"loadPQCKeys emptied, {len(ARRAYS)} arrays trimmed "
          f"({original_len} -> {len(src)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
