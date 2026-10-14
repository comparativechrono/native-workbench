# HISAT2 2.2.3-workbench1

Requires Native Workbench 0.5.3 or newer. Four operations accept uncompressed Phred+33 FASTQ: single/paired RNA alignment and single/paired DNA alignment. Each builds a private 64-bit HISAT2 index from a genomic reference. Paired modes validate mate names, counts and order before indexing.

RNA alignment enables splicing and --dta, exposes real library strandedness and intron bounds, and returns coordinate-sorted BAM with CSI plus an auxiliary unsorted SAM and alignment summary. It discovers splice sites without a supplied gene annotation. RNA alignments have their own data type and cannot be connected to DNA-only calling or duplicate-processing steps. DNA modes explicitly disable splicing and return unsorted SAM suitable for the existing DNA pipeline tools. Paired geometry is ordinary inward-facing FR; RNA strandness means transcript strand, not mate geometry.

Read groups, sample/library/platform/lane, thread count and seed are recorded. Duplicates are retained. RNA sorting uses the stated SAMtools memory amount for one worker. HISAT2 indexing/alignment has no hard memory cap; large genomes require substantial RAM, disk space and time. The 64-bit index avoids the small-index genome-size limit, but does not make large analyses lightweight. Indexes are built anew per operation. No annotation-derived splice database, graph variants, compressed FASTQ, SRA download or reusable prebuilt-index input is exposed by these four operations.

Paths must be ASCII and contain no commas. Spaces are supported. Native Windows binaries were cross-compiled and their DLL imports inspected; Windows execution was not available in the build environment. Four installation self-checks run real synthetic alignments, including a known 100-base splice junction, exact positions/CIGARs and mate flags.

This is a static LLVM-MinGW source build, not an upstream Windows binary. The small documented CLI patch accepts explicit --rna-strandness unstranded and selects precisely the existing upstream default. Alignment/scoring algorithms remain upstream. Exact GPL source, patch and build recipe are in licenses/. Build with scripts/prepare_hisat2_pack.py --fetch --build; matching Linux reference: scripts/build_hisat2_native.py --linux. The pinned LLVM-MinGW toolchain and existing SHA-pinned portable SAMtools/paircheck helpers are required. GNU GPL v3-or-later covers HISAT2; helper/runtime licenses are retained separately.

Cite Kim et al. (2019), Nature Biotechnology 37:907-915, doi:10.1038/s41587-019-0201-4.
