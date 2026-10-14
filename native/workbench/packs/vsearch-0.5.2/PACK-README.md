# VSEARCH amplicon tools

Pack 0.5.2; official VSEARCH 2.32.0 Windows x86-64 binary, plus paircheck 1.0.1 for strict paired-read validation. Everything executes locally using argv without a shell. No Python, Docker, WSL or separate VSEARCH installation is required by the tool pack.

The seven workflows cover paired-read merging, expected-error quality filtering, raw and abundance-aware full-length dereplication, abundance filtering, greedy OTU-style clustering, and reference-based chimera screening. Each workflow also runs alone. Logs and UC/UCHIME tables retain individual tool results; they must not be pooled as though they describe the same read population. Filtering and clustering are not ASV denoising. This is not a complete taxonomic or differential-abundance analysis pipeline.

All sequence operations require unaligned nucleotide data. Raw dereplication counts records once; weighted dereplication sums positive size annotations. Clustering preserves abundance with sizein/sizeout. Reference chimera screening requires a suitable user-supplied chimera-free nucleotide reference and writes nonchimera, chimera and borderline outputs separately. Empty filtering outputs are valid; a downstream sequence tool will ask for nonempty input. FASTQ workflows use Phred+33. Paired inputs are validated before VSEARCH, which itself pairs by position.

## Windows validation scope

The executable and bundled compression DLLs are official x86-64 PE files. Only operating-system DLLs are imported. Scientific reference tests use the separately pinned Linux build of the same VSEARCH version; those are not Windows execution tests. The workbench installation check executes the actual Windows pack's merging, dereplication and weighted-clustering fixtures on the user's machine.

VSEARCH uses narrow-character filename APIs. Non-ASCII and very long Windows paths have not been validated and may fail on a machine's code page. Use short ASCII paths for installation, inputs and result folders for this pack. The archive uses flat license and manual paths to avoid deeply nested import paths.

## Provenance and redistribution

VSEARCH is dual licensed under BSD 2-Clause or GPLv3-or-later; unmodified notices and the exact corresponding source archive are included. The bundled zlib and bzip2 DLLs retain their notices. Paircheck source, build instructions and flattened Cosmopolitan notices are included separately.

The current official Windows archive was replaced on 2026-09-28 after SHA256SUMS was published on 2026-09-18. Its current hash matches the official GitHub release asset digest, not the stale Windows line in SHA256SUMS. See licenses/upstream-downloads.json and licenses/github-release-metadata.json for exact provenance. The source archive agrees with its separate SHA256 checksum. Do not substitute an archive with the stale checksum without revising and validating the pin.

Official project: https://github.com/torognes/vsearch
Citation: Rognes et al. (2016), PeerJ 4:e2584, https://doi.org/10.7717/peerj.2584
