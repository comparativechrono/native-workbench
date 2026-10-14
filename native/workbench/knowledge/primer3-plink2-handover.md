# Primer3 and PLINK2 optional packs

**Merge update, 2026-10-13:** this pack stage and its dependent PR stack are now
merged into `main` at `9c9cdeacf35d1bf3aa60277f0fb05d5af41c6254` on the owner's
instruction. Source trees and candidate archives are unchanged by the merges.
The [integration receipt](evidence/stack-integration-2026-10-13.json) supersedes
only the draft/unmerged status in the original review handover below. No release
or catalogue publication occurred; validation and acceptance limits still apply.

Date: 2026-10-13. Status: ready for unpublished review in
[draft PR #18](https://github.com/comparativechrono/workbench/pull/18).

Development is on `feature/primer3-plink2-packs`, based on Kalign delivery
`8c0321d0cf04751a7c921d42098bed13ebb7b11a`, tree
`4c126c5c06fdf554dc02a24af3e3a73347220a3b`. The PR is stacked on
`feature/kalign-pack`; Kalign PR #17 remains draft and unmerged. PR #16's prior
integration merge is preserved. No merge, release or catalogue publication is
included. Published application **0.16.0** and frozen UI candidate **0.16.1** are
unchanged. Each new pack has independent version **1.0.0**.

## Implemented scientific contracts

- `primer3/design-pcr`: standard paired PCR primer design from one uncompressed,
  ungapped A/C/G/T/N DNA FASTA template (60–100000 bases, at most 2 MiB). Thirteen
  options expose product size, pair count, primer length, calculated Tm and
  chemistry. Effective annealing oligo concentration is not template DNA
  concentration. TSV contains sequences, zero-based half-open binding coordinates,
  product size and upstream measurements; raw Boulder request/result, settings,
  JSON measurements and diagnostics are retained. Raw Boulder right coordinates
  denote the rightmost base. A zero-pair answer is a valid completed run with
  guidance. The guard verifies template binding, reverse complement and product
  size. This does not establish genome-wide specificity, in-silico PCR,
  experimental PCR success or clinical suitability; probe modes are not included.
- `plink2/summarize-vcf`: ALT frequencies, hardcall genotype counts and sample/
  variant missingness from uncompressed VCF 4.2/4.3, GT-only diploid biallelic
  A/C/G/T SNPs on human autosomes 1–22. Bounds: 2–1000 samples, 1–100000 variants,
  at most 10 million genotypes and 64 MiB. Full missing calls are accepted;
  half-calls, dosage/likelihood fields, extra FORMAT fields, indels, multiallelic,
  sex/MT chromosomes and non-diploid calls are rejected with guidance. Unique
  sample/variant IDs are required; reserved sample ID `0` is rejected. Underscores
  and leading zeroes are preserved with `--const-fid 0`. All supplied samples and
  variants are counted, including nonfounders and non-PASS FILTER records; phase
  is not used. ALT frequency is not necessarily minor allele frequency; entirely
  missing variants have undefined frequency. Outputs include `.afreq`, `.gcount`,
  `.smiss`, `.vmiss`, JSON measurements/settings and logs. PCA, association,
  ancestry inference and reusable PGEN interfaces are deferred.

Both use one compute thread, ASCII paths with spaces supported, native guards,
typed inputs, exact pack pins and recorded Methods. PLINK2 requests a 640 MiB
required workspace allocation, not a total-process memory cap or runtime forecast.
Neither operation applies automatic QC filters or invents pass thresholds.

## Source and build

Tested pack, recipe and validator source is
`3d1d83b70d053af625b5cb45362851c0fefab2a1`, tree
`32becfa4831b7e50cdcfe342645d0ac02d32b8cb`. The later delivery commit only updates
knowledge/evidence; it does not replace the tested source identity or archives.

Primer3 uses unmodified **2.6.1**, commit
`7f9f17d6012f404e83bbf0f931a4d06eb4af465b`, source archive SHA-256
`c981e42765ceb525f56607c6a7cf989ac5068483731c6e083b1e9fb22816463b`.
Its native OS_WIN build excludes the unsupported masker. All 34 runtime
configuration files match the pinned upstream bytes. GPL-2.0-or-later materials
and the compiled Amplicon3 GPL-3.0-or-later notice/source are retained.

PLINK2 uses unmodified **2.0.0-a.7.12**, commit
`5c1f185d4144e62fa23087d68760162f712cd2a8`, archive SHA-256
`bcfa30a7cfca2e117bacb94c94a2248ab190396ff8d2711f600ef42ebf5f9198`.
The baseline x64 no-LAPACK build has no SSE4.2/AVX/AVX2 requirement and retains
the upstream `NL` banner. Static zlib **1.3.2** archive SHA-256 is
`bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16`.
The recipe force-includes standard `math.h` for a declaration without patching
the source. GPL/LGPL, QD, SIMDe, libdeflate, zstd, zlib, SFMT and compiler notices
and corresponding source are retained.

Both scientific executables and guards have x64 PE headers, an 8 MiB stack
reserve/64 KiB commit and system/UCRT-only imports. The compiler is pinned
LLVM/MinGW 20260922 UCRT, archive SHA-256
`bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21`.
The source companion includes source, fixtures, recipes, build records and
licensing materials. This establishes correspondence, not independent
bit-identical recompilation.

Local development corrections before the frozen hosted run were Primer3's
version probe (`--about`; upstream `--version` exits 255), PLINK2's minimum
workspace (640 MiB instead of rejected 256 MiB), and separate `-Xlinker` stack
arguments to avoid driver comma splitting. These are not successful native
candidate results. The final hosted run passed without a failed candidate retry.

## Exact validation

[Build and native run 38403212748](https://github.com/comparativechrono/workbench/actions/runs/38403212748)
passed all three jobs at the tested source above.

- Linux source validation: **112 selected tests, 111 passed and one explicit
  Windows-only long-path filesystem skip**. This comprises 11 batch evidence
  tests, eight shared evidence tests, 14 pack-check tests, 47 selected pack-manager
  tests (one skip), 15 Primer3 tests and 17 PLINK2 tests. The Primer3 suite includes
  three freshly built pristine-upstream reference cases. No scientific suite skips.
- Each ordinary and spaced Windows path: **14 Primer3 tests and 17 PLINK2 tests**,
  no selected skips/errors (40 and 52 tracked tool executions respectively).
  Primer3's Linux reference class is excluded from the selected Windows suite.
  Eight science gates and ten GUI gates pass per path. These are gate counts,
  not 18 additional independent scientific test cases.
- Exact ZIP import, declared checks, duplicate-version rejection, stale/incompatible
  typed pin rejection, normal graph execution, Methods, CWL export and searchable
  Results pass. Eight normal graphs across both applications/path cases bind
  saved run/plan hashes, eight fixture inputs, 16 executable version/hash bindings
  and 56 output hashes. Independent rereading confirms primer binding intervals
  `[40,60)` and `[200,220)` with a 180 bp product, and PLINK2's six-variant/four-sample
  truth: 24 genotypes, 17 called, seven missing, 34 called alleles and 18 ALT alleles.
- Each path's combined installation regression passes seven core checks, one
  Starter science check and all four installed pack checks. Application files
  remain unchanged before/after: **274 released 0.16.0 files** for science and
  **277 frozen 0.16.1 files** for UI. Exported CWL is checked; scientific Linux CWL
  execution is not established.
- The independently downloaded source audit matches **984 Git files** and
  **1288 companion inventory entries**, upstream archives, source recipes,
  licences, fixtures, four executable identities and all 34 Primer3 config files.
  All four outer artifact hashes and ZIP CRCs were checked after download.
- All **38 actual BitBlt display images** were visually reviewed at full width;
  38 PrintWindow images remain supplementary. All 76 capture hashes match.
  Primer3's top plus seven pages and PLINK2's top plus three pages start at zero
  and reach the true end. Bold wrapped names, regular descriptions, separate
  Methods, Results search/status and exact version/hash details are legible.
  No blocking layout issue was found at 96 DPI, 1024×768 desktop/1024×728 app.

The unchanged native Results parser does **not** interpret these packs' JSON
measurements. It displays status and provenance and explicitly reports unavailable
summary measurements. Use the recorded output files for measurements. This is
an outstanding application enhancement, not evidence of missing scientific output.
Finite screenshots do not prove zero flicker. No representative-PC, broader DPI/
monitor/trackpad, large-data or clinical acceptance is claimed.

## Review downloads and evidence

[Download both packs and matching source companion](https://github.com/comparativechrono/workbench/actions/runs/38403212748/artifacts/11816422463).
The outer Actions artifact is 86157868 bytes, SHA-256
`e7a1e09e28ddefe92f6bbeb5b7b88c05b89dc1d75bc3aea5b636b74d330cf7c6`.
Extract the download and import each desired inner pack ZIP through Manage tools.
Minimum app version is 0.16.0. These are optional packs, not a replacement app.

| Inner archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-pack-primer3-1.0.0.zip` | 33355562 | `f8e39d2fad068c77913f1daef711101dd3f941f1fe4b9e6a23f398db2e745d82` |
| `native-workbench-pack-plink2-1.0.0.zip` | 9060836 | `34c2f382e72f34c78098b6222f0ac3d09f562bf0b74ccf5d08ae546c3736bdce` |
| `native-workbench-primer3-plink2-1.0.0-source-evidence.zip` | 43732659 | `247379057f4425e12ccb6c9dc14aa6365e5d3fad01cf32a0018c36e00d0ceb5c` |

Raw [build evidence](https://github.com/comparativechrono/workbench/actions/runs/38403212748/artifacts/11815628559),
[ordinary-path reports/screenshots](https://github.com/comparativechrono/workbench/actions/runs/38403212748/artifacts/11816303628)
and [spaced-path reports/screenshots](https://github.com/comparativechrono/workbench/actions/runs/38403212748/artifacts/11815763649)
remain downloadable. Actions artifacts expire **2026-11-12** and may require
GitHub sign-in. Preserve them before expiry for later review; a hash does not
retain access. The repository keeps focused receipts and original report/capture
hashes without opaque run IDs or runner folders.

The [final index](evidence/primer3-plink2-1.0.0-final-review-2026-10-13.json) links
source, archive, native and visual evidence. Benchmarking, representative-PC
acceptance, signing/institutional deployment, scientific Linux CWL and release/
updater validation remain separate. No merge or publication follows automatically.
