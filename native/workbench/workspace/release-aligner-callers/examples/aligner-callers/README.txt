Small deterministic DNA-alignment teaching inputs

reference.fasta: 4,096-base synthetic genomic reference named demo.
reads-R1.fastq / reads-R2.fastq: 24 matching 100-base Phred33 pairs from 300-base fragments.
reads-single.fastq: the same first-mate sequences for a single-read operation.
targets.bed: the complete synthetic contig, in zero-based half-open BED coordinates.

Choose a DNA aligner operation and the matching reference/read files. These
reads have no introduced variants and shallow coverage. They demonstrate file
connections and alignment, not caller accuracy, sensitivity or RNA splicing.
For each caller or RNA alignment use File > Check installation, which runs
that pack's dedicated scientific fixture and validates its expected output.
