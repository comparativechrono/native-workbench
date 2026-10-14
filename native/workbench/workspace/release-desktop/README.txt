Native Workbench 0.5.1 - native Windows desktop development build

Extract the complete ZIP into a writable folder, then double-click
NativeWorkbench.exe. No command prompt or shell is needed.
The workbench opens as a native Windows application. It runs analyses locally
and works offline with the bundled tools and your local input files.

FIRST CHECK
1. Open NativeWorkbench.exe and choose File > Check installation to execute the
   bundled native tool validation.
2. Load the bundled example, review its inputs and settings, then run it in an
   existing output folder. It uses fastp, BWA, SAMtools, BCFtools and FreeBayes,
   with separate statistics branches and a combined report.
3. Retain the run folder if a check fails; its logs identify the failed step.

The .cmd launchers are optional conveniences. check-workspace-windows.cmd runs
additional installation integrity and host/graph checks if command scripts are
permitted on your computer. check-windows.cmd starts the native tool check.

WORKING WITH TOOLS AND PIPELINES
Each installed tool can run individually with its own input fields and settings.
Connect a named output to another tool to build a pipeline. One output may feed
several tools, and compatible inputs may join at a later step. The DAG places
steps at their dependency levels: tools using the same upstream output appear
on the same level. The scheduler executes ready steps one at a time.

Step identities such as S1 and S2 remain stable when you edit a pipeline. Input
connections name their producer and selected output. Removing a step leaves its
downstream inputs unresolved until you reconnect them; Undo restores the edit.

Save pipeline stores two or more connected tools, their settings, named input
slots and pinned pack versions. File paths and sample/library bindings are
excluded. Save a single tool's reusable settings as a tool preset. Saved items
are kept in user-data beside the extracted application; retain that folder when
moving the installation.

Before execution, review the planned methods, inputs and parameters. Results
contain the frozen plan, graph, exact tool identities and commands, step logs,
outputs, a DAG and methods describing the steps that actually completed.
Combined reports retain a separate attributed section for every input; caller
counts are not pooled. All-call and PASS-only variants have distinct outputs.

Keep the workbench open while an analysis runs. Cancel stops the current run.
Closing during a run asks whether to cancel and close or keep the window open.
The retained classic 0.4.1 application is NativeWorkbenchClassic.exe; the optional
start-classic-windows.cmd launcher also opens it.

ANALYSIS DETAILS
BAM lane merges check reference dictionaries, sample names, distinct read groups
and shared input lineage. Use disjoint lanes of one sample and mark duplicates
after merging. Headers without M5 checksums establish matching contig names and
lengths, not identical reference bases. Headers cannot establish that arbitrary
external BAM files contain disjoint biological reads.

Variant callers currently use uniform haploid or diploid ploidy. Choose the
setting for the sample and assay. HTSlib worker threads remain disabled in the
portable tools; trimming and alignment can use their configured worker count.
Select a local uncompressed reference FASTA; reference download is not included.

FASTP FIX AND VALIDATION
The exact 0.4.1 fastp reporting fix is retained in the fastp and research-variants
packs. Original patch evidence and provenance are in docs/fastp-report-fix.
Pack versions are independent of the application version.

The new 0.5.1 desktop integration has been crosscompiled and checked on Linux.
Its graph engine and portable scientific tools have been exercised with the
bundled truth fixtures. Native Windows execution of this new desktop integration
still needs checking on your machine; the steps above provide that check.

INSTITUTIONAL DEPLOYMENT
This is an unsigned development build running with normal user permissions.
It starts native executables and a bundled private Python runtime. There is no
HTTP listener or browser dependency, and no administrator, Docker, WSL or system
Python installation is required. Institutional application-control policy may
need to approve the desktop application, private Python runtime and scientific
tool executables. This package does not bypass those controls.

Import packs only from sources you trust: their executables run with your user
permissions. Analyses use local files and do not send biological data elsewhere.

SOURCE
source/native-workbench-source.zip contains application and tool source inputs,
patches, licenses, validation scripts and README-0.5.1.txt build instructions.
