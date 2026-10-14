Native Workbench 0.5.4 - Mutect2 somatic variant calling

Open NativeWorkbench.exe after extracting the complete folder. This release
retains all seventeen 0.5.3 tool packs and the fixed fastp executable.

The Mutect2 pack adds local GATK somatic variant calling to the native desktop.
Its tasks run individually or as steps in connected pipelines. Inputs, tool
versions, parameters, commands, methods and citations remain in the run record.
Choose a Mutect2 task in the tool library and read its input requirements.

Mutect2 outputs require filtering. The pack runs the caller, learns its read
orientation model and applies FilterMutectCalls. Raw candidates, filter labels
and separate PASS calls are retained. A PASS label is a model result; it does
not establish that every call is a true somatic mutation. Tumor-only results
have greater uncertainty about germline variants than matched-normal analysis.

GATK runs in a bundled private Java runtime. No system Java installation, WSL,
Docker, browser or server is needed. Analysis files remain local. This Java
route favors portability over Intel native acceleration and may be slower than
an accelerated Linux GATK installation. Choose memory appropriate for your PC.

CHECK THE INSTALLATION
Choose File > Check installation and select a writable results folder. It runs
native application checks and the packs' scientific fixtures, saving detailed
reports and individual tool logs. Use this to establish execution on your
Windows machine; Linux tests and dependency inspection do not establish it.

See docs/MUTECT2-0.5.4.txt for the included workflows and limitations,
docs/SOURCE-CONTENTS-0.5.4.json for source locations, and the full application
source inventory in source/native-workbench-source.zip.

Earlier pack details remain in docs/ALIGNER-CALLERS-0.5.3.txt. In particular,
VarDict still uses its upstream experimental Java Fisher mode and private
Perl runtime; its previously documented path and caller limitations apply.
