Bowtie 2 DNA alignment — pack 0.5.3 / upstream 2.5.5

Requires Native Workbench 0.5.3 or newer. Four local workflows combine reference indexing with single-end or paired-end short-read DNA alignment. Small indexes support references below 4 billion bases; the separate large-index workflows use 64-bit indexes and can require more memory. Indexing occurs for every run. Existing indexes are not silently reused. This is not a splice-aware RNA aligner.

The pack invokes official native Windows build/align executables directly; it does not run upstream Python wrappers, shell scripts, Docker, WSL or network clients. Executables import only Windows KERNEL32.dll and msvcrt.dll. Pack/input/output paths must contain ASCII characters and no commas because the native CLI uses comma-separated file lists and its Windows Unicode paths have not been verified. Spaces are supported through argument vectors.

References must be uncompressed FASTA. Reads may be plain or gzip FASTQ, with Phred+33 qualities. Paired inputs must have matching names, counts and order; paircheck validates them before indexing. All inputs are unchanged. End-to-end alignment, input-order output, one primary alignment per read, unmapped records and Bowtie 2 default discordant/single-mate fallback are retained. Select the library orientation and fragment bounds from the experiment.

SAM includes sample (SM), read-group (ID), library (LB) and platform (PL) tags. Use unique read-group IDs across lanes. SAM is unsorted and no duplicate marking is performed. Connect the SAM output to BAM preparation/sorting workflows before downstream steps that require prepared BAM. The copied reference and all six index files remain recorded as intermediate outputs.

License: GPLv3 or later for Bowtie 2. Complete Bowtie 2 source, linked compression sources, upstream build instructions, GCC runtime exception, MinGW/winpthreads notices and existing paircheck/Cosmopolitan notices accompany the pack under licenses. Official binaries are unmodified. Their published archive SHA256 digests were verified. The upstream compiler/runtime details do not establish byte-reproducible builds; see licenses/provenance.json.

Validation uses the exact manifest commands with the matching pinned Linux release binaries. Four included installation checks assert mapped positions, pair flags, reference dictionary and sample/read-group metadata on the user Windows computer. Windows execution has not been performed in this development environment.

Upstream: https://github.com/BenLangmead/bowtie2/releases/tag/v2.5.5
Galaxy guidance: https://github.com/galaxyproject/tools-iuc/tree/405eb069a3f4888ba19d9be7e3e7d9f23e54c5d0/tools/bowtie2
Citation: Langmead B, Salzberg SL (2012). Fast gapped-read alignment with Bowtie 2. Nature Methods 9:357–359. https://doi.org/10.1038/nmeth.1923
