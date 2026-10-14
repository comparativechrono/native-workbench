Native Workbench 0.10.1 — application and independent tool packs

Extract this complete folder to a location you can write to, then open
NativeWorkbench.exe. The interface is a native Windows application.

The starter includes minimap2 for alignment, SAMtools for alignment processing,
and BCFtools for variant calling. Each task can run alone or in a connected
workflow. Choose the example pipeline to try the bundled tiny scientific data.

Tool setup offers Full (recommended), Starter and Custom selections. Downloads
start only when requested, using the application's reviewed signed official
catalogue. Choose Refresh catalogue, review the selection and download size,
then choose Install selection. The reviewed official source is included.
Starter and already installed tools work without network access.

Setup shows missing download size and progress. Completed packs remain installed
if a later transfer fails or is cancelled. Retry keeps the selected versions;
it may download the unfinished pack again. Manage tools remains available to
import downloaded pack ZIPs or browse explicitly configured publisher catalogues,
including future tools and third-party packs. Installed tools work offline.

Application updates and pack installation are separate. Updating the application
does not replace installed packs, settings, setup progress, references or results.
Pack archives carry their declared executables, private runtimes, scientific
metadata, tests and licences. Saved workflows retain their exact pack versions.

Use References to discover and download public reference files. Each completed
download is kept locally with provider, release, assembly, URL and checksums.
Reference downloads are explicit network operations; analysis files are not
uploaded. References and scientific databases are separate from executable packs.

Every new analysis result includes workflow.cwl alongside the run's methods,
commands, versions, input/output hashes and logs. External CWL reruns require a
CWL engine, Python and the pinned tools and input files; normal Workbench use
continues to use its bundled runtime.

Choose File > Check installation to check the core and installed pack fixtures.
See SOURCE-AVAILABILITY.json for the separately distributed application source
archive and exact pack/source companions. Application and private Python licences
are installed. Native MinGW-w64, winpthreads and LLVM notices are in
runtime/licenses/native; tool licences and source notices remain within each pack.

Consult the candidate's separate validation report for exactly what was tested.
Source/build success does not itself establish execution on native Windows.
