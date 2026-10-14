Native Workbench 0.5.3 - additional aligners and variant callers

Open NativeWorkbench.exe after extracting the complete folder. This release
retains every original 0.5.2 tool pack and the fixed fastp executable.

Find a task in the library, add it to the workspace, select its inputs and
parameters, and run it on local files. Each task runs on its own or as a step
in a connected pipeline. Methods and run records retain tool/pack versions,
parameters, commands and citations. The four new packs add 12 operations;
all 69 existing tasks remain available.

Bowtie2 and HISAT2 provide additional alignment choices. DNA alignment outputs
can connect to the existing preparation/calling tools. HISAT2 RNA outputs are
marked separately so they cannot silently feed a DNA-only variant pipeline.
LoFreq and VarDict provide additional caller choices with their own input,
reference, sample and interval requirements. VarDict uses upstream experimental
Java Fisher mode and the official Perl converter. Read each operation's help.
The release notes describe the final packaged workflows and limitations.

CHECK THE INSTALLATION
Choose File > Check installation and select a writable results folder. The
application runs its native checks and each pack's bundled scientific fixtures,
then saves the detailed reports and individual tool logs. Use this to establish
Windows execution on your machine; Linux tests and dependency inspection alone
do not establish that result.

Examples for short-read DNA alignment are in examples/aligner-callers. They
are deliberately small teaching inputs, not a variant-calling accuracy or
performance benchmark. RNA checks use the separate fixtures inside that pack.

Programs and their private runtimes run locally with no WSL, Docker, browser,
HTTP listener or global Java/Perl/Python installation requirement. Bundled
runtimes are private to their packs. No system environment settings are changed.
For VarDict, use a short ASCII installation path without spaces while validating
this development build; broader Windows path support remains unverified.

See docs/ALIGNER-CALLERS-0.5.3.txt for operation details and deployment limits,
docs/SOURCE-CONTENTS-0.5.3.json for source locations, and the complete application
source inventory in source/native-workbench-source.zip.
