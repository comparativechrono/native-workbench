Native Workbench 0.5.2 - tool expansion source

This release adds self-contained SeqKit, VSEARCH and MUSCLE tool packs to the
native 0.5.1 desktop application. Existing variant pack contents are retained.
The source archive contains the application, reproducible manifest builders,
pinned provenance and license material, and validation code. Source archives
for GPL tools are included with their packs; SeqKit dependency notices are
included. Upstream binary provenance is recorded without claiming our local
builds reproduce upstream executable bytes.

BUILD
Build the native UI with desktop/build_desktop_workspace.sh using the pinned
LLVM-MinGW toolchain as described in README-0.5.1.txt. The core bridge is
unchanged. The new pack builders are:

    scripts/prepare_seqkit_pack.py
    scripts/prepare_vsearch_pack.py
    scripts/prepare_muscle_pack.py

Read each builder's --help and pinned upstream provenance. Normal installation
and tool execution do not need a network connection or a compiler.

The optional asset:workbench-schema asset holds the pack's SHA-256-pinned
category, ports, output semantics, methods text and citations. It contains no
executable commands. The original format-2 manifest remains the execution
authority. See docs/PACK-SCHEMA-0.5.2.txt for the authoring contract.

The optional asset:workbench-checks asset holds data-driven scientific
self-checks. Every fixture is a separately hashed manifest asset. The generic
workspace/pack_checks.py runner executes each check through the ordinary graph
engine and native backend; assertions inspect fixed declared outputs. New
checks cannot supply shell commands or Python expressions.

PACKAGE
Keep the original 0.5.1 runtime intact. Choose a new directory and run:

    python3 scripts/package_expansion.py --base-root <0.5.1-runtime>         --app-root <new-0.5.2-runtime> --stage-only

After scientific and integration validation, finish the source archive,
release inventory and full ZIP:

    python3 scripts/package_expansion.py --base-root <0.5.1-runtime>         --app-root <staged-0.5.2-runtime> --finish --output <release.zip>

The compact updater can be generated with scripts/make_desktop_update.py
from the exact 0.5.1 and 0.5.2 runtime trees. It stages and verifies the target,
retains user settings/results, and commits the release manifest last.

VALIDATE
Run the new pack tests and metadata/engine regression tests. Real Linux test
adapters execute matching upstream Linux binaries against the actual pack
command manifests. No mocked results count as scientific validation. PE import
inspection establishes dependency packaging, not successful Windows execution.
The GUI's installation check runs bundled new-pack fixtures through the native
Windows runner when requested on Windows, and keeps full run evidence.
