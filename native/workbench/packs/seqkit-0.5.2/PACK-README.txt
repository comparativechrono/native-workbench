SeqKit sequence utilities — pack 0.5.2 / upstream 2.14.0

Unmodified upstream native Windows amd64 executable; no installed Go, shell, network connection or administrator rights are needed to run these workflows. The computer must allow the bundled executable.

Inputs are typed separately as FASTQ reads, nucleotide FASTA and protein FASTA. Paired-end data are deliberately not offered as paired inputs. Never filter or sample the two mates independently and assume pairing is preserved. FASTQ-to-FASTA discards quality scores. Translation does not predict genes or choose a genetic code.

All workflows use separate argv elements, with no shell. Outputs are created in the run folder; input files are unchanged. Empty filter/subset outputs are valid and are recorded as such. FASTQ statistics and sampling include a strict streaming validation pass and a private identifier list because upstream stats/sample2 can otherwise exit successfully after a malformed-input error.

Upstream source: https://github.com/shenwei356/seqkit/tree/v2.14.0
Documentation: https://bioinf.shenwei.me/seqkit/usage/
Galaxy IUC reviewed wrappers: https://github.com/galaxyproject/tools-iuc/tree/5a09e4ee5fd1f9035706cd975e602e9a9de2d401/tools/seqkit
Galaxy wrappers informed workflow choices; this pack implements its own declarative argument lists and does not execute Galaxy XML or shell commands.

MIT-licensed SeqKit and its statically linked dependency/runtime notices are included under licenses. provenance.json records official release SHA256, source tag, embedded Go versions/module checksums and the upstream dirty-build marker. No byte-reproducibility claim is made for upstream binaries.

Validation: Linux upstream counterpart tested on exact sequence, quality, count, sampling and translation expectations. Windows PE imports were inspected. Windows execution has not been performed in this development environment; use Check installation to execute four included scientific checks on Windows.

- Statistics: FASTQ reads: Summarize record counts, lengths, quartiles and N50 in a tab-separated report. FASTQ quality statistics assume Phred+33.
- Length filter: FASTQ reads: Retain records within inclusive length limits; sequence order and FASTQ qualities are preserved. This operation treats one file independently and does not preserve paired-end read synchronization.
- Extract by ID: FASTQ reads: Retain exact IDs from a text list, in input order. Matching is case sensitive and uses the first header token. Missing IDs are omitted; zero matches produce an empty output. This operation treats one file independently and does not preserve paired-end read synchronization.
- Statistics: nucleotide FASTA: Summarize record counts, lengths, quartiles and N50 in a tab-separated report. FASTQ quality statistics assume Phred+33.
- Length filter: nucleotide FASTA: Retain records within inclusive length limits; sequence order and FASTQ qualities are preserved. Length counts residues, including ambiguous bases.
- Extract by ID: nucleotide FASTA: Retain exact IDs from a text list, in input order. Matching is case sensitive and uses the first header token. Missing IDs are omitted; zero matches produce an empty output. 
- Statistics: protein FASTA: Summarize record counts, lengths, quartiles and N50 in a tab-separated report. FASTQ quality statistics assume Phred+33.
- Length filter: protein FASTA: Retain records within inclusive length limits; sequence order and FASTQ qualities are preserved. Length counts residues, including ambiguous bases.
- Extract by ID: protein FASTA: Retain exact IDs from a text list, in input order. Matching is case sensitive and uses the first header token. Missing IDs are omitted; zero matches produce an empty output. 
- Random sample: FASTQ reads: Select exactly the requested count, or all records if fewer are available. Two-pass sampling bounds memory by selected indices. Same input and seed give the same selection. This operation treats one file independently and does not preserve paired-end read synchronization.
- Random sample: nucleotide FASTA: Select exactly the requested count, or all records if fewer are available. Two-pass sampling bounds memory by selected indices. Same input and seed give the same selection. 
- FASTQ to nucleotide FASTA: Convert reads to FASTA, preserving sequence headers and bases. Quality scores are discarded; this output cannot be used as FASTQ reads.
- Reverse complement DNA FASTA: Reverse-complement each DNA sequence. IUPAC ambiguous DNA bases are supported. Input must be DNA, not protein or RNA.
- Translate nucleotide FASTA: Translate one chosen reading frame using the selected genetic code. Stop symbols are retained and the frame is appended to IDs. This is translation, not gene prediction or ORF selection; trailing incomplete codons are omitted.
