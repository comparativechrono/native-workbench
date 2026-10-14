Small synthetic examples for the new tool packs

These files are artificial examples for trying the interface. They are not
patient data or evidence that an analysis is biologically appropriate.

One tool: add SeqKit Statistics: FASTQ reads and select reads.fastq. Expect
4 records and 479 bases, with 119 to 120 bases per read, all at Phred33 Q40.

A pipeline: add SeqKit Length filter: nucleotide FASTA. Select
nucleotides.fasta, keep the default lengths, and connect its sequence output
to MUSCLE nucleotide multiple alignment. Select ordinary align for this
small example. The alignment should retain all 3 input sequences; adding
alignment gaps must not change the original residues.

Amplicons: choose VSEARCH dereplication with amplicons.fasta. There are
4 records but 3 unique sequences; one sequence occurs twice. Its output
records carry abundance labels and can feed abundance-aware clustering.
Similarity clusters from this example are not species assignments.

Protein alignment: select proteins.faa for MUSCLE protein alignment.
ID extraction: use nucleotides.fasta and ids.txt to select 2 records.

Keep the entire workbench, inputs and results in paths using ordinary ASCII
characters when testing VSEARCH/MUSCLE on Windows. Non-ASCII path support in
these upstream tool families has not been established.
