Native Workbench 0.5.2 - sequence and amplicon tool expansion

Open NativeWorkbench.exe directly after extracting the complete folder.
This release retains the native Windows desktop application and existing
variant tools, including the validated fastp 0.4.1 report fix.

NEW TOOL PACKS - 25 new operations, 69 tasks in total
SeqKit: sequence statistics, format conversion, filtering, sampling,
ID selection, reverse complements and translation.
VSEARCH: overlapping read-pair merging, amplicon filtering, dereplication,
clustering and chimera assessment.
MUSCLE 5.3-workbench1: nucleotide and protein multiple sequence alignment.

Search for a tool in the library, add it to the workspace, then select its
input files. Each task can run individually. Compatible outputs can also feed
other steps, including several branches from the same output. The methods
preview includes the selected parameters, tool versions and pack citations.
Save a tool preset for its settings, or a connected pipeline for reuse.

Each new pack contains its own typed connection metadata, fixed executable
hashes, provenance, licenses, fixture data and scientific self-checks. Packs
can describe nucleotide FASTA, protein FASTA and multiple alignments distinctly;
an arbitrary FASTA file is not silently treated as a genomic reference.

CHECK THE INSTALLATION
Choose File > Check installation and select a writable results folder.
After the existing native checks, the workbench runs the new packs against
small bundled fixtures and checks their expected outputs. The results include
a pack-checks.json report and the individual runs, methods and command logs.
This check uses only bundled local data and does not download anything.

The new tools were tested here using matching Linux releases, with separate
Windows executable/dependency inspection. Actual Windows execution must be
validated using the application. A successful Linux test is not a Windows test.

GALAXY AS A GUIDE
Galaxy Tool Shed wrappers and upstream documentation informed the tool choices
and interfaces. These are independently packaged local workbench operations;
the workbench does not install or execute arbitrary Galaxy wrappers, Conda
recipes, containers or shell scripts. See docs/TOOL-EXPANSION-0.5.2.txt.

INPUTS AND LIMITS
Read each operation's help. Independent single-read filtering or sampling
must not be used separately on the two mates of a paired dataset. Amplicon
similarity clustering does not establish species identity, and chimera tests
have algorithm- and reference-dependent limits. MUSCLE consumes homologous
sequence sets, not a reference genome and sequencing reads for mapping.

The installation and its scientific tools run locally. There is no browser,
HTTP listener, WSL, Docker or required global Python environment. Additional
network/reference-download support is not part of this expansion.

See docs/DEPLOYMENT-0.5.1.txt for deployment constraints and the included
source/native-workbench-source.zip for application and pack-builder source.
Try the bundled examples/sequence-expansion files for a short hands-on check.
For VSEARCH and MUSCLE Windows testing, use input/output paths containing
ordinary ASCII characters; non-ASCII path support is not established.

