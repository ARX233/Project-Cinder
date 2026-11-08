# Android 1.35 AO numerical profile

The packaged converter explicitly selects **numerical profile 2**, not C ABI 2. ABI stays 1, structs stay 88/24/240 bytes, and size/rays stay 256/96. No quality downgrade or environment-controlled profile switch exists.

Every translation unit: C11, `-O2 -fwrapv -ffp-contract=on -fno-fast-math -pthread -fPIC -fvisibility=hidden -Wall -Wextra -Werror`. Android: NDK 28.0.13004108, aarch64-linux-android28, max/common page size16384 and no undefined symbols. Legacy numerical profile1 uses contraction off and remains separate.

One complete Apple M4/macOS/clang17 host run converted214 fresh original-derived WPKs:214/214 reference-byte matches,208 maps plus6 authentic zero-map files,13,644,016B,2174.573s. All source SHA before/after, strictWAO1 layouts and zero live-allocation results passed. The previous off run had68 differing files; none remain in the measured on run. These are finite host observations, not historical compiler claims.

Pinned Android image SHA256: `9f14e959fbf5552e316be90025b83a75dcbd5f4d943899a732ad027a10212ead`, cross-compiled with NDK clang19, four PT_LOAD segments aligned0x4000, only oa_default_limits/oa_bake_fd exports. The signed Python recipe verifies this image before loading. Historical off images are preserved and never silently substituted.

Android/bionic/libm byte equivalence is **not verified**. This original-source lane binds AO ownership and exact map identities/dimensions to the controlled algorithm and authenticated complete source snapshot. A later private installation HMAC protects that controlled result from subsequent tampering. It is neither a presigned output catalog nor permission to scan and bless player-provided AO. Prepared-resource signature rules are unchanged.

The accompanying header update is documentation only; no executable C algorithm or ABI changes. Future numerical-profile changes need explicit APK recipe/library pins and independent evidence, not caller/job/environment values.
