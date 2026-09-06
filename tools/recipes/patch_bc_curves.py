#!/usr/bin/env python3
"""Trim CustomNamedCurves to the curves this client can actually negotiate.

Measured on the shrunk build under -Xint: 114 of the 164 org.bouncycastle.math.ec
classes that load are per-curve implementations, and they cover *every* SEC
curve -- all nine binary curves (sect113 ... sect571) plus secp128/160/192/224.
TlsBootstrap pins

    jdk.tls.namedGroups = x25519,secp256r1

so none of them can ever be selected for key exchange.  They load anyway because
CustomNamedCurves holds a static holder per curve and the class references pull
them in during verification.

Why removing them is safe rather than merely unused: CustomNamedCurves is an
*optimisation* table, not the curve registry.  ECUtil consults it first and falls
back to the generic implementation when it returns null --

    X9ECParameters params = CustomNamedCurves.getByOID(oid);
    if (params == null) { params = ECNamedCurveTable.getByOID(oid); }

-- and ECNamedCurveTable resolves from SECNamedCurves / X962NamedCurves /
NISTNamedCurves, which are plain BigInteger implementations of the same curves.
So a curve dropped here still resolves; it just loses its hand-written field
arithmetic.  For a curve that is never negotiated, that costs nothing, and for an
unexpected certificate on secp224r1 the result is a slower verification rather
than a failure.

Kept: curve25519 (X25519), secp256r1 (the pinned group and almost every server
certificate), plus secp384r1 / secp521r1 / secp256k1 because a certificate chain
can legitimately use them and each is only a handful of classes.

    patch_bc_curves.py <bcprov-src.jar> <out-dir>
"""

import os
import re
import sys
import zipfile

SRC = "org/bouncycastle/crypto/ec/CustomNamedCurves.java"

KEEP_HOLDERS = {"curve25519", "secp256r1", "secp384r1", "secp521r1", "secp256k1"}

# Aliases resolve through oidToCurve and defineCurveAlias throws
# IllegalStateException if the OID was never registered, so an alias for a
# dropped curve would fail the class initialiser rather than be ignored.
KEEP_ALIAS_OIDS = {"secp256r1", "secp384r1", "secp521r1", "secp256k1", "curvey25519"}

HOLDER_DEF = re.compile(
    r"^[ \t]*static X9ECParametersHolder (\w+) = new X9ECParametersHolder\(\)",
    re.M,
)


def strip_holder(src, start):
    """Delete the holder initialiser beginning at `start`, through its `};`.

    Each holder is preceded by a javadoc block whose only content is the curve
    name, so removing the code alone leaves an orphaned `/** * secp128r1 */`
    behind -- which is a comment, not a reference, but it defeats the
    dangling-reference assertion below and leaves the source misleading.  The
    comment is taken with it.
    """
    head = src.rfind("*/", 0, start)
    if head != -1 and src[head + 2:start].strip() == "":
        open_doc = src.rfind("/*", 0, head)
        if open_doc != -1:
            line_start = src.rfind("\n", 0, open_doc) + 1
            if src[line_start:open_doc].strip() == "":
                start = line_start

    brace = src.index("{", start)
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
        raise SystemExit("patch failed: unbalanced braces in holder")
    end = src.index(";", i) + 1
    while end < len(src) and src[end] == "\n":
        end += 1
    return src[:start] + src[end:]


def main(src_jar, out_dir):
    with zipfile.ZipFile(src_jar) as z:
        src = z.read(SRC).decode("utf-8")

    all_holders = set(HOLDER_DEF.findall(src))
    unknown = KEEP_HOLDERS - all_holders
    if unknown:
        raise SystemExit(f"patch failed: kept curves not present in source: {sorted(unknown)}")
    drop = all_holders - KEEP_HOLDERS

    # Repeatedly find the first droppable holder and cut it; offsets shift after
    # every removal, so rescanning is simpler than tracking them.
    removed = 0
    while True:
        for m in HOLDER_DEF.finditer(src):
            if m.group(1) in drop:
                src = strip_holder(src, m.start())
                removed += 1
                break
        else:
            break

    # Registrations naming a holder we removed.
    lines, kept_lines, dropped_defs = src.split("\n"), [], 0
    for line in lines:
        m = re.search(r"defineCurve(?:WithOID)?\(\"[^\"]+\",[^;]*?(\w+)\);", line)
        if m and m.group(1) in drop:
            dropped_defs += 1
            continue
        a = re.search(r"defineCurveAlias\(\"[^\"]+\",\s*\w+\.(\w+)\);", line)
        if a and a.group(1) not in KEEP_ALIAS_OIDS:
            dropped_defs += 1
            continue
        kept_lines.append(line)
    src = "\n".join(kept_lines)

    # Any surviving mention of a dropped holder would be a dangling reference.
    for name in sorted(drop):
        if re.search(r"\b" + name + r"\b", src):
            raise SystemExit(f"patch failed: reference to dropped curve {name} remains")

    out = f"{out_dir}/{SRC}"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"      patched CustomNamedCurves: kept {len(KEEP_HOLDERS)} of "
          f"{len(all_holders)} curves ({removed} holders, {dropped_defs} "
          f"registrations removed)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
