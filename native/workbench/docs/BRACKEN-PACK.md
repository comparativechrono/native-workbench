# Bracken abundance pack

Pack `bracken` **1.0.0** contains the unchanged estimator from official Bracken
**3.1**, with a private Windows x86-64 Python **3.13.16** runtime. It supports
Workbench **0.6.0** or later. No WSL, Docker, shell, system Python, administrator
installation or analysis-time download is needed. Large databases remain
separate local files.

## Operations

| Operation | Inputs | Result |
| --- | --- | --- |
| Reestimate Kraken2 abundance | A Workbench Kraken2 classification record and the matching registered database descriptor | Abundance at a selected rank, an upstream reestimated taxonomy report, methods, execution log and provenance |
| External Kraken report | A standard six-column Kraken2 report, its matching Bracken distribution, database name/release, read length and explicit compatibility confirmation | The same outputs, prominently marked as user-declared external provenance |

The external operation works with only this pack installed. It does not require
Kraken2 index binaries or the Kraken2 pack. A report contains no intrinsic proof
of its generating database, read length or classifier settings. The required
declaration must therefore be based on the original analysis records; shared
taxon IDs or a plausible filename are insufficient.

Connect Kraken2's **classification record** to Bracken in a pipeline. The JSON
record references its sibling report and binds its SHA-256, database content
fingerprint, classifier settings, actual read-length statistics and counting
units. Keep the result directory together if moving it. The selected resource's
distribution hash and database association are checked. Bracken does not reread
the enormous unused `hash.k2d`, `opts.k2d` and `taxo.k2d` binaries. A registered
external distribution's association remains explicitly user-attested; checksums
establish unchanged bytes, not the truth of an asserted training database or
publisher authentication.

## Scientific choices

Choose **species, genus, family, order, class, phylum or domain**, a read-length
distribution, and the minimum original Kraken clade count (default **10**).
Kraken2 paired mode counts **fragments**, one per pair; those counts are never
doubled. The distribution read length means a mate's length, not the combined
insert length.

The default **exact** policy requires every read, including each mate, to have
the selected distribution length. For variable trimmed reads, an explicitly
selected **representative** policy allows a chosen distribution length inside
the observed length range. This is an approximation, recorded in the methods
and results; the pack neither silently selects the nearest model nor implements
a mixture of length-specific models. External reports require the user to
declare the length because actual read lengths are unavailable.

This first version supports the standard Kraken2 settings: confidence **0**,
minimum hit groups **2**, minimum base quality **0**, and quick mode **off**.
Incompatible recorded settings are rejected. Confidence or read-length changes
can affect the relationship between a distribution and the observed report;
there is no claim of unbiased estimation across arbitrary settings.

Bracken's fractions use retained estimated abundance, excluding unclassified
and unallocated observations. They are not fractions of all input observations,
and read/fragment abundance is not organism cell abundance. The upstream
integer truncation is retained: sums of displayed counts or fractions may fall
slightly short of the unrounded total. Original and reestimated Kraken reports
have different meanings; preserve both. Taxa below threshold are excluded.
No classified taxa at the chosen rank/threshold produces a clear failure with
no invented abundance table, consistent with the upstream no-estimate outcome.

## Boundaries

- Input must be an ordinary six-column Kraken2 taxonomy report. MPA reports,
  minimizer-augmented reports, partial/malformed trees and inconsistent counts
  are rejected before running the estimator.
- The database-specific `.kmer_distrib` file must already exist locally.
  This pack does not expose `bracken-build`, download reference genomes or build
  production models. Those operations need the original database library and
  taxonomy and are a separate future capability.
- Analysis runs the unchanged upstream Python algorithm. Large model files
  can still require substantial memory: upstream loads the distribution in
  memory. Small install size does not imply every database fits on a laptop.
- Inputs and installed pack files are not modified. Explicit output paths keep
  Bracken from writing its default report beside the input.
- This is a research/teaching tool; small synthetic regression checks do not
  establish microbiome sensitivity, pathogen detection performance or clinical
  suitability. No GUI, institutional deployment or large-database performance
  claim follows from native CLI tests.

## Build and verification

From a repository checkout:

```sh
python scripts/fetch_bracken_build_inputs.py --fetch
python scripts/prepare_bracken_pack.py --destination build/bracken-prepared
```

On Linux the scientific suite uses the host Python to execute the same packaged
source; this is explicitly different from the Windows private-runtime gate.
The exact-native gate uses the released application's native importer and both
ordinary and space-containing installation/result paths. A final release also
tests an actual Kraken2-to-Bracken chain using the frozen Kraken2 archive:

```sh
python tests/test_bracken_pack.py --pack PATH --kraken2-archive KRAKEN2_ZIP --report REPORT_JSON
```

Fixtures include independently calculated Bayesian probability truth, genus
and threshold outcomes, and a real synthetic Kraken2 classification whose model
enumerates **every** contiguous 150-base genome window. The generator is retained
in `tools/bracken/build_fixture.py`. Its counts are serialized with unchanged
upstream Bracken code. It is test data, not a production model-building feature.
Failure regressions cover report/model/database mismatch, malformed probabilities,
read lengths, nonstandard classifier settings, threshold/no-estimate outcomes,
input immutability and unverified external provenance.
The suite also checks the unchanged upstream example distribution (including a
valid zero mapped numerator) and actual upstream aggregation of multiple contigs
per genome with unclassified windows. Missing native/dependency prerequisites are
recorded explicitly and cause the release test command to fail rather than
counting a skipped chain as a release pass.

`tools/bracken/windows-lock.json` pins source, runtime and the exact estimator
hash. The pack includes the complete Bracken source archive, GPL-3.0-or-later
license, complete CPython source archive, original embedded-runtime license and
Workbench adapter/build recipes. The official `v3.1` tag is authoritative; its
unused POSIX shell launcher still contains a stale `VERSION=3.0.1` string.
This pack never invokes that launcher.

Publication and final Windows status are recorded separately in the repository
release inventory and exact-archive validation report. Build provenance retains
its truthful creation-time `windowsExecuted: false` status.

## Upstream references

- [Official Bracken 3.1 source](https://github.com/jenniferlu717/Bracken/tree/cfeac04b6445c44c3825866683a6fdd18746cb58)
- [Bracken manual and file formats](https://ccb.jhu.edu/software/bracken/index.shtml?t=manual)
- [Bracken method](https://doi.org/10.7717/peerj-cs.104)
- [Kraken suite protocol](https://doi.org/10.1038/s41596-022-00738-y)
