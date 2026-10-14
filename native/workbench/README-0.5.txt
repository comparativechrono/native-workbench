Native Workbench 0.5.0 — Windows integration test build

Extract the complete ZIP into a writable folder, then run start-windows.cmd.
No administrator rights, Docker, WSL, system Python or Linux partition is needed.
The interface opens in a local Edge application window (or your default browser).
The bundled private Python runtime hosts only 127.0.0.1. Biological input files
are read by local native tools; the browser does not upload them.

FIRST CHECK
1. Run check-workspace-windows.cmd. Eight installation checks should pass.
2. Open start-windows.cmd, then Tools & installation > Check installation.
   These are the existing native tool and pipeline checks.
3. Choose Try the bundled example on the empty workspace. The bundled example
   reads are trimmed with fastp, aligned with BWA, prepared with SAMtools, then
   sent to BCFtools and FreeBayes. Each caller has its own statistics branch.
4. Review & run shows the planned methods and checks inputs. Choose an existing
   output folder, then run. No source input is overwritten.

WHAT CHANGED
The task catalogue exposes all 43 existing pack workflows, plus combined
reporting. Each can run alone. Add named outputs to form branches or joins;
DAG steps sharing a dependency occupy the same level. S1/S2 step identities
stay stable across edits. Inputs show their producer, output and consumers.
Remove step leaves dependent inputs unresolved; Undo restores the connection.

Save pipeline stores two or more connected tools, settings, named input slots
and exact pack pins. Local file/sample/library bindings are excluded. A single
tool's reusable settings are saved from its Settings panel as a tool preset.
Saved items live in user-data beside the extracted app. Keep that folder when
moving your installation. Recent results reopen previous result folders.

RESULTS
Each run creates a new folder containing plan.json, graph.json, run.json,
pipeline.svg, methods-planned.txt, methods-completed.txt, and separate step
folders containing native logs, exact commands, tool hashes and outputs.
Completed methods include only successful steps and flag incomplete analyses.
Combined reports show separately labelled sections; caller counts are not
pooled. All-call variants and PASS-only variants retain distinct output labels.

The DAG describes dependencies. This release schedules ready tools one at a
time; some tools use the configured worker count internally. HTSlib worker
threads remain disabled as in the validated portable packs. Closing the window
allows a running analysis to finish. Reopen start-windows.cmd to reconnect.
Cancel explicitly stops the run. The host exits after five idle minutes with
no connected window and no active analysis.

BAM lane merges check reference dictionaries, sample names and distinct read
groups and reject shared graph/read-file lineages. For BAM headers without M5 sequence checksums, reference checks establish
contig names and lengths, not identical reference bases. Header checks cannot
prove that arbitrary external BAMs contain disjoint biological reads. Supply true
separate lanes of one sample, then mark duplicates across the merged lanes.
Calling settings apply uniform haploid/diploid ploidy; choose appropriately.

FASTP FIX
The exact 0.4.1 fastp reporting fix is installed in both fastp and research-
variants packs. Its original evidence is in docs/fastp-report-fix. Pack versions
remain independently pinned: eight packs at 0.4.0, two at 0.4.1.

COMPATIBILITY AND VALIDATION
This new launcher/UI/graph integration was crosscompiled and tested here with
local HTTP/browser tests, real portable tool execution under Linux and the
included truth fixtures. Native execution of the NEW integration on Windows
has not yet been performed. Please run the checks above on Windows and retain
any failed run folder for diagnosis. The classic 0.4.1 app remains available
through start-classic-windows.cmd if needed.

Import packs only from sources you trust. They run native executables with your
ordinary user permissions; this is a portable local workbench, not a sandbox.
Reference download is not implemented in this integration; select local FASTA.

SOURCE
source/native-workbench-source.zip includes the host/UI/native bridge code,
source archives/patches and rebuild instructions in README-0.5.txt.

BUILD
Read docs/BUILD-0.4.txt for the unchanged upstream tools. The exact fastp0.4.1 APE is retained; the patched Linux reference was rebuilt and has separate provenance.
Set BW_MINGW_ROOT to llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.
Run bash desktop/build_bridge.sh and bash desktop/build_workspace_launcher.sh.
Package with python3 scripts/package_workspace.py --app-root <patched-0.4.1-runtime> --output <zip>.
The launcher becomes NativeWorkbench.exe; retain the old one as NativeWorkbenchClassic.exe.
The underlying native runner remains version0.4.1, independent from workspace0.5.0.
Host tests: python3 -m unittest discover -s workspace/tests -v
Engine tests: python3 -m unittest discover -s tests -p test_workspace_engine.py -v
The local HTTP tests need permission to bind127.0.0.1. No external service is used.
