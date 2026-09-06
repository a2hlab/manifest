# R8 rules for out/wl-tls-min.jar -- the TLS stack with everything TLS does not
# use removed.
#
# WHY THIS IS SAFE, AND WHAT MAKES IT UNSAFE
#
# BouncyCastle's JCA provider does not reference its algorithm implementations
# statically.  BouncyCastleProvider holds arrays of algorithm *names* and does:
#
#     Class clazz = ClassUtil.loadClass(BouncyCastleProvider.class,
#                                       packageName + serviceName + "$Mappings");
#     if (clazz != null) { ((AlgorithmProvider)clazz.newInstance()).configure(this); }
#
# and ClassUtil.loadClass catches ClassNotFoundException and returns null
# (verified in bcprov-src 1.78.1).  So an algorithm family whose $Mappings class
# is absent is *silently skipped* -- removing families is a supported outcome,
# not a crash.  On a stock build 94 $Mappings classes load, registering Zuc,
# VMPC, GOST, Grain128, Dilithium, Falcon, NTRU, SPHINCS+, Haraka, Whirlpool and
# so on, none of which any TLS handshake touches.
#
# The same string-name indirection is what makes this dangerous in the other
# direction.  Each $Mappings.configure() registers its SPI classes by name too:
#
#     provider.addAlgorithm("Cipher.AES", PREFIX + "$ECB");
#
# R8 cannot see through that, so for every family we keep, the whole family has
# to be kept -- keeping only $Mappings would leave the provider advertising
# algorithms whose implementations no longer exist, and the failure would not
# appear until something actually requested that algorithm.
#
# Two consequences, both load-bearing:
#
#   -dontobfuscate  Renaming a class breaks every one of those string lookups.
#                   This is not a debuggability preference; the output does not
#                   work without it.
#
# Optimisation IS enabled, which was not the obvious call -- R8's horizontal
# class merging can fuse two classes into one even with names preserved, and that
# would break the same lookups.  It is enabled because the effect was measured
# rather than assumed: scripts/check_tls_min.py reads the string constants out of
# every surviving $Mappings and checks each advertised class against the jar, and
# the optimised and unoptimised builds resolve an identical 250 of 294 with the
# identical 44 absentees (all of them schemes pruned on purpose).  If that ever
# stops being true the check fails the build.
#
# Verification is therefore two-sided.  scripts/build_tls_min.sh runs the real
# handshake self-test (six live hosts, TLS 1.3 and 1.2, plus the okhttp path) for
# behaviour on the paths that matter, and check_tls_min.py covers the algorithms
# the self-test never requests -- which is exactly where a string-name shrink
# fails silently.

-dontobfuscate
-dontpreverify
-dontnote
-ignorewarnings

# BC references optional/absent things (JDK-internal, JSSE variants, EdDSA
# provider hooks).  They were already absent in the stock jar and unreferenced at
# runtime; warnings about them are noise.
-dontwarn org.bouncycastle.**
-dontwarn javax.**
-dontwarn java.**
-dontwarn sun.**

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

# Loaded reflectively by AMR (Class.forName from the adapter jar), so nothing
# statically reaches it.
-keep class westlake.tls.** { *; }

# Both providers are instantiated by name and registered into java.security.
-keep class org.bouncycastle.jce.provider.BouncyCastleProvider { *; }
-keep class org.bouncycastle.jsse.provider.BouncyCastleJsseProvider { *; }

# Every JCA/JSSE SPI is reached only through Provider.Service.newInstance(),
# i.e. Class.forName on a registered name, so keep the no-arg constructors that
# reflection uses.
-keepclassmembers class * extends java.security.Provider$Service { <init>(...); }
-keepclassmembers class org.bouncycastle.** {
    public <init>();
}

# ---------------------------------------------------------------------------
# JSSE -- the whole provider package
#
# ProvSSLContextSpi and friends are registered by string name from
# BouncyCastleJsseProvider, and the package is small (172 classes) and almost
# entirely on the handshake path, so there is nothing to gain by splitting it.
# ---------------------------------------------------------------------------
-keep class org.bouncycastle.jsse.** { *; }

# ---------------------------------------------------------------------------
# Algorithm families TLS actually needs
#
# Chosen from what a live handshake against the six production hosts negotiates:
#   TLS 1.3  TLS_CHACHA20_POLY1305_SHA256, TLS_AES_*_GCM_SHA*, X25519 key share
#   TLS 1.2  TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256 and the AES-GCM suites
#   certs    RSA and ECDSA signatures, SHA-256/384 digests, X.509 parsing
# ---------------------------------------------------------------------------

# Digests.  SHA-1 and MD5 stay because certificate chains and the TLS 1.2 PRF
# still reference them; SHA-224 stays because some intermediate CAs sign with it.
-keep class org.bouncycastle.jcajce.provider.digest.SHA1** { *; }
-keep class org.bouncycastle.jcajce.provider.digest.SHA224** { *; }
-keep class org.bouncycastle.jcajce.provider.digest.SHA256** { *; }
-keep class org.bouncycastle.jcajce.provider.digest.SHA384** { *; }
-keep class org.bouncycastle.jcajce.provider.digest.SHA512** { *; }
-keep class org.bouncycastle.jcajce.provider.digest.MD5** { *; }

# Symmetric.  AES for the GCM/CBC suites, ChaCha + Poly1305 for
# CHACHA20_POLY1305, TLSKDF for the TLS 1.2 PRF.
-keep class org.bouncycastle.jcajce.provider.symmetric.AES** { *; }
-keep class org.bouncycastle.jcajce.provider.symmetric.ChaCha** { *; }
-keep class org.bouncycastle.jcajce.provider.symmetric.Poly1305** { *; }
-keep class org.bouncycastle.jcajce.provider.symmetric.TLSKDF** { *; }

# Asymmetric.  EC/EdEC cover ECDHE, ECDSA, X25519 and Ed25519; RSA covers the
# server certificates actually served by these hosts; DSA and DH are kept
# because a chain or a 1.2 fallback suite can still need them; X509 is the
# CertificateFactory the trust bundle is parsed with.
-keep class org.bouncycastle.jcajce.provider.asymmetric.EC** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.ec.** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.EdEC** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.edec.** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.RSA** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.rsa.** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.DSA** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.dsa.** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.DH** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.dh.** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.X509** { *; }
-keep class org.bouncycastle.jcajce.provider.asymmetric.x509.** { *; }

# NOTE: the three `provider.*.util` packages are deliberately NOT kept.
#
# Keeping org.bouncycastle.jcajce.provider.util.** with `{ *; }` looked harmless
# and cost 266 classes.  That package holds the AsymmetricKeyInfoConverter
# *interface*; keeping an interface method forces R8 to keep every override of
# it, and BCDilithiumPublicKey / Falcon / Kyber / McEliece key factories all
# implement it -- so the entire post-quantum tree came back in through a rule
# meant to preserve six small helper types.  R8's -whyareyoukeeping named the
# rule directly.
#
# Nothing is lost by dropping them: these are ordinary superclasses and
# interfaces (AlgorithmProvider, BaseBlockCipher, BaseCipherSpi ...) referenced
# *statically* by the family classes above, so tree shaking keeps exactly the
# ones still reachable and no more.

# SecureRandom.  DRBG's clinit probes for other providers and finds none here,
# which is why westlake.tls.UrandomEntropySourceProvider exists; both halves
# have to survive.
-keep class org.bouncycastle.jcajce.provider.drbg.** { *; }

# Shared provider plumbing referenced by name from the families above.
-keep class org.bouncycastle.jcajce.provider.config.** { *; }

# PKIX path validation, registered by name from BouncyCastleProvider and used by
# BCJSSE's trust manager.
-keep class org.bouncycastle.jce.provider.PKIXCertPathValidatorSpi { *; }
-keep class org.bouncycastle.jce.provider.PKIXCertPathBuilderSpi { *; }
-keep class org.bouncycastle.jce.provider.PKIXNameConstraintValidator { *; }
-keep class org.bouncycastle.jce.provider.CertStoreCollectionSpi { *; }
-keep class org.bouncycastle.jce.provider.BouncyCastleProviderConfiguration { *; }

# ---------------------------------------------------------------------------
# Explicitly dropped
#
# Listed for the record -- these need no rule, they simply are not kept.  Named
# here so a future reader can see the removal was a decision and not an
# oversight:
#
#   org.bouncycastle.pqc.**    975 classes.  Post-quantum (Dilithium, Falcon,
#                              NTRU, SPHINCS+, Kyber...).  No TLS suite in use
#                              negotiates any of it.
#   org.bouncycastle.oer.**    315 classes.  OER encoding, used only for ITS /
#                              ETSI certificates.
#   org.bouncycastle.i18n.**   Localised error messages for the X.509 tooling.
#   ...jcajce.provider.keystore.**  BC/BCFKS/PKCS12 KeyStore formats.  The trust
#                              store here is a plain PEM bundle read through
#                              CertificateFactory precisely to avoid PKCS12.
#   ...provider.symmetric.{Zuc,VMPC,GOST*,Grain*,Camellia,SEED,SM4,IDEA,...}
#   ...provider.digest.{GOST3411,Whirlpool,Skein,Haraka,Blake*,SM3,Tiger,...}
#   ...provider.asymmetric.{GOST,DSTU4145,ElGamal,IES,GM,LMS,Dilithium,Falcon,
#                           NTRU,SPHINCSPlus,COMPOSITE,EXTERNAL}
# ---------------------------------------------------------------------------
