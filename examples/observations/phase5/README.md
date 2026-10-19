# Genuine Phase 5 observations

These 13 files are byte-for-byte copies of the actual reports generated under
`results/phase5/baseline-2026-10-17/`. Phase 6 imports them without compiling or
executing programs again. No measurements were created or changed for this
fixture collection. The original commands, compiler identity, platform, input
hashes, raw observations, timing samples and reliability flags remain in each
report. See [Phase 5 validation](../../../docs/PHASE5_VALIDATION.md).

The six constants/unrolling/combined O0/O2 comparisons all have `unreliable`
timing classifications. The additional negative-result timing comparison is
also unreliable. Their measured values remain observations and are excluded
from quantitative fingerprint comparisons by default; they do not establish
algorithmic speedups or compiler identification. The remaining reports retain
inapplicability, rejection, mismatch, undefined behavior, disabled-sanitizer
inconclusiveness and timeout outcomes with no timing samples.

Absolute source names and temporary artifact paths are historical provenance.
Temporary executables were cleaned up after the original runs. Importing these
files must not require those paths to exist or follow paths in their contents.
The reports record one Apple Clang toolchain on macOS arm64, not cross-vendor
compiler evidence. Input source hashes identify the original source bytes;
canonical emitted C has its own formatting and need not have that same hash.

SHA-256 of each complete copied file:

| File | SHA-256 |
| --- | --- |
| `constants-O0.json` | `5a9329dd960b656fb919d5d7312d0f9de3c0caf34374974ce668910242df8c7c` |
| `constants-O2.json` | `0a429ced8aaec072c8391a749c7f51fd2a46cd801ae60c7b6db5ff279b888391` |
| `unroll-O0.json` | `9f12e99ee300ecaff36ad12c8a73927b5d6a6903805e5d7c2e65a87e83e1fa96` |
| `unroll-O2.json` | `6e0975bffbf59ac78cb79f5b58838444ac2ad48b5a3cd86c1bc15311baefb54c` |
| `combined-O0.json` | `b66594d1b5f2a9f0e6e5dccb1fe7adb53a6df23cfdfd6b80a16d1b38056110a5` |
| `combined-O2.json` | `b743acd8c2e3c03a1b50df81457ffdbc8faecd40e92e812d05d3facda5ad7cdd` |
| `negative.json` | `36fd0f0ca64a2af48b6d9a362f0e900d8b600f0939790ae6a5460ae53ba28f46` |
| `inapplicable.json` | `42447c0116751e5c5d90fc4f4afa6665e8f6452ddd212a3f125d407eb1940b11` |
| `rejected.json` | `6597419fe6292f56e99a5e051c53c00b347465648d17ad8df4e4d7d880af7db9` |
| `mismatch.json` | `0cffad3de29beea2541c129cbeeea7d6b99373b08ec1b0a26df15a7f53e1e145` |
| `undefined.json` | `ec4bb2eb96e306f7176c34a47397de1f46badd18fb93c27065d49d1254fc7029` |
| `inconclusive.json` | `ebe738ac147e834c80f2f07e864ba9294e256d0662c4659523201ffc450c0df5` |
| `timeout.json` | `a6652c87e64d49d9eb061b5f6aa660483570cc7429c1edb0e63017126f6bb739` |
