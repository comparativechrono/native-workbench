# Full pack bundle: sizing and recommendation

Measured **2026-10-06** against published application **0.9.0** and the latest
published version of each of **32 packs**. This is a proposal and sizing study;
no application, pack, default download or published release was changed.

| Distribution | Download | Initial extracted file contents |
| --- | ---: | ---: |
| Current Starter (3 packs) | 17.00 MB | 36.47 MB |
| Full selection (32 packs) | 3.813 GB (3.551 GiB) | 4.669 GB (4.349 GiB) |

Units are decimal MB/GB; binary GiB are shown for the full selection. The full
download is the exact sum of the current Starter ZIP and the 29 additional pack
ZIPs: **3,812,575,669 bytes**. It estimates a combined ZIP
using the existing compression; no combined archive or installer was built.
The compressed member payload alone totals 3,811,518,879 bytes,
before new ZIP headers and bundle metadata.

Initial extracted contents total **4,669,444,080 bytes** across
**4,445 files**. The additional pack-manager compatibility receipts
would add only 5,981 bytes. A new full-bundle inventory would add a
small amount not yet designed. Filesystem allocation can differ from file lengths.
Keeping the present download archives and extracted installation together would
use about 8.48 GB before temporary files or analysis work.

These figures include all private runtimes, fixtures, notices and corresponding
source archives already shipped inside the packs. The packs' `licenses/` trees
account for 2.22 GB of extracted file contents; they have been
counted unchanged. Separately published source/evidence companions are excluded
from the ordinary runtime download. In particular, DESeq2's separate R source
companion must remain available alongside distributions of its runtime, as its
[release source instructions](../tools/deseq2/R-RUNTIME-SOURCES.md) specify.

Reference genomes, scientific databases, input data, results and per-run runtime
expansion are **additional disk use**, outside these initial-install figures.

## Recommended direction

Offer **Full** as the main choice for users who want all current tools available
immediately after installation, and retain **Starter** for smaller installations.
Preinstall the unchanged versioned packs; keep the core separate. Preserve
**Manage tools / Import pack**, independent pack updates, exact saved workflow
pins, and the existing pack-authoring route for future and third-party packs.
This is a packaging choice rather than a change to the pack architecture.

Current discovery already scans installed pack folders and derives tool/input
choices from their metadata. Core updates deliberately exclude packs and user
data. The existing starter packager, however, selects exactly three packs, so a
Full distribution needs a separate pinned packaging profile and bundle inventory.
Preserve the existing core manifest identity if retaining its update compatibility.
See [architecture](architecture.md) and [pack development](pack-development.md).

A delivery decision is necessary: GitHub's current
[release documentation](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
states a limit of **under 2 GiB per release asset**. A roughly 3.81 GB ZIP cannot
be one asset there. Options include a native installer that fetches the existing
pack components automatically, a multipart offline installer, or a larger-file
download host. This study does not choose or configure new hosting.

Before release, the full selection needs native Windows validation for discovery,
coexistence, input selection, representative workflows and updates. Startup and
**Check installation** timings should also be measured with all packs present;
prior individual-pack checks do not establish those full-bundle observations.

## Measurement and evidence

- [Live release metadata](evidence/full-bundle-live-packs-2026-10-06.json): all 32 current pack versions and primary ZIP identities agree with the maintained release inventory. Superseded versions and draft releases are excluded.
- [Machine-readable measurement](evidence/full-bundle-sizing-2026-10-06.json): SHA-256 `531078fa2bd2343a7d5ddd9e9d691354ab2c20b61aafa0ea5118c31748b9b13c`.
- [Read-only measurement script](../scripts/measure_full_bundle.py): uses bounded numeric HTTP ranges to read ZIP directories and pack envelopes, rather than transferring all runtime payloads.

All 32 envelopes passed their ZIP-member CRC checks; every payload path and
uncompressed size matched its envelope inventory. The local Starter passed full
SHA-256 and ZIP CRC checks, and all three included pack payloads were hash-matched
to their published envelopes before excluding those packs from the additional
sum. The metadata transfers totalled 18.88 MB.
Remote complete-archive hashes and payload CRCs were **not** verified in this
sizing study, and no all-pack native execution is claimed. Reported GitHub archive
digests are release metadata, not fresh whole-archive hash observations.

The calculation is `Starter + 29 additional packs`; each current pack is counted
once. No published pack file was removed or deduplicated to reduce the estimate.

## Per-pack sizes

Download values are current primary ZIP sizes; extracted values are `pack/`
payload file lengths. Values below use decimal MB. The three packs marked
included are already present in Starter and are not added a second time.

| Pack | Version | ZIP MB | Extracted MB | Included in Starter |
| --- | --- | ---: | ---: | --- |
| mutect2 | 0.5.4 | 683.05 | 812.26 | No |
| gatk | 1.0.0 | 681.73 | 809.63 | No |
| snpeff | 1.0.0 | 498.01 | 632.68 | No |
| vardict | 0.5.3 | 372.59 | 445.71 | No |
| deseq2 | 1.0.0 | 277.50 | 291.06 | No |
| iqtree | 1.0.0 | 248.20 | 268.42 | No |
| multiqc | 1.0.0 | 231.36 | 244.74 | No |
| kraken2 | 1.0.0 | 230.93 | 244.31 | No |
| fastqc | 1.0.0 | 151.00 | 215.58 | No |
| blast | 1.0.0 | 70.02 | 130.29 | No |
| lofreq | 0.5.3 | 56.07 | 59.72 | No |
| mosdepth | 1.0.0 | 39.76 | 44.63 | No |
| bowtie2 | 0.5.3 | 36.40 | 83.21 | No |
| bracken | 1.0.0 | 34.84 | 46.12 | No |
| bedtools | 1.0.0 | 32.02 | 63.72 | No |
| muscle | 0.5.2 | 30.14 | 32.65 | No |
| featurecounts | 1.0.0 | 29.83 | 33.07 | No |
| research-variants | 0.4.1 | 19.30 | 42.48 | No |
| star | 1.0.0 | 16.86 | 21.75 | No |
| trimming | 0.4.0 | 12.68 | 25.85 | No |
| hisat2 | 0.5.3 | 10.09 | 15.66 | No |
| kallisto | 1.0.1 | 9.43 | 12.92 | No |
| seqkit | 0.5.2 | 9.19 | 21.39 | No |
| freebayes | 0.4.0 | 4.56 | 11.66 | No |
| variant-pipeline | 0.4.0 | 3.21 | 7.27 | No |
| vsearch | 0.5.2 | 3.19 | 7.17 | No |
| variants | 0.4.0 | 2.51 | 5.94 | Yes |
| bwa | 0.4.0 | 1.87 | 4.71 | No |
| fastp | 0.4.1 | 1.28 | 3.36 | No |
| bam | 0.4.0 | 1.16 | 3.27 | Yes |
| align | 0.4.0 | 0.57 | 1.14 | Yes |
| reads | 0.4.0 | 0.49 | 0.99 | No |
