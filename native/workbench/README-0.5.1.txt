Native Workbench 0.5.1 - native Windows desktop source

This source distribution contains the native desktop application, its anonymous-
pipe host, typed workflow graph engine, original pack runners, tool patches,
pinned upstream source archives, licenses and validation scripts. The former
0.5.0 browser interface is retained under workspace/web with its host modules as
historical source; those files are excluded from the 0.5.1 desktop runtime.

ARCHITECTURE
NativeWorkbench.exe is built from the Win32 desktop frontend. It starts the
private runtime/python/python.exe with -I and workspace/desktop_host.py, using
anonymous stdin/stdout pipes. The Python host exposes only the defined local
workspace operations. WorkbenchBridge.exe continues to run the existing typed
pack manifests and shell-free native command arguments. There is no HTTP host,
network listener or browser process in the desktop application's startup path.

The runtime Python module allowlist is declared in scripts/package_desktop.py:
catalog.py, engine.py, example.py, desktop_host.py, desktop_model.py, service.py
and verify_installation.py. The private Python distribution is copied from the
existing pinned runtime. python313._pth remains isolated to python313.zip and
its own directory. No system Python packages are installed or required.

BUILD THE DESKTOP COMPONENTS
Use the pinned LLVM-MinGW toolchain described by the existing build scripts.
Set BW_MINGW_ROOT to its root, then run:

    bash desktop/build_bridge.sh
    bash desktop/build_desktop_workspace.sh

The native frontend output is build/desktop/DesktopWorkbench.exe. Packaging
installs it as NativeWorkbench.exe and retains the fixed 0.4.1 classic executable
as NativeWorkbenchClassic.exe. --check starts native installation checks;
--classic opens the retained application. Neither option launches a browser.

Read docs/BUILD-0.4.txt for the scientific tools and pack format. The exact
0.4.1 fastp APE payload is retained. Its original fix evidence is preserved in
docs/fastp-report-fix. The corrected Linux reference rebuild has separate
provenance and validation; its hash need not equal the original compiler build.
HTSlib worker threads remain disabled in the portable scientific packs.

STAGE AND PACKAGE
Work from an extracted, verified 0.5.0 runtime. Keep that baseline intact and
choose a new target directory. To stage a native installation for checks:

    python3 scripts/package_desktop.py --base-root <0.5.0-runtime> \
        --app-root <new-0.5.1-runtime> --stage-only

To create a full release from a fresh target directory, replace --stage-only
with --output <native-workbench-0.5.1-windows.zip>. Packaging verifies both fixed
fastp payloads, includes a complete source archive and generates the release
SHA-256 inventory. Results, saved user settings, Python caches, build objects
and temporary build trees are excluded. The supplied Windows launch scripts
contain real CRLF line endings.

VALIDATION
Python tests use only the standard library and the existing test fixtures:

    python3 -m unittest discover -s workspace/tests -v
    python3 -m unittest discover -s tests -p test_workspace_engine.py -v

Native desktop, anonymous-pipe host and model tests should be run before
packaging. Historical HTTP/browser tests remain source tests for 0.5.0 and are
not dependencies of 0.5.1. On Windows, open NativeWorkbench.exe directly, choose
File > Check installation and run the bundled branched example. Optional
check-workspace-windows.cmd adds integrity checks where command scripts are
permitted; no shell is required for the desktop application itself. Crosscompilation, static PE
inspection and Linux execution of portable tools do not establish successful
native Windows execution of the desktop integration.

DEPLOYMENT
See docs/DEPLOYMENT-0.5.1.txt in the runtime package. The application is an unsigned
development build that runs with normal user permissions. Institutions may need
to approve the private Python executable, its native libraries and scientific
tools as well as the desktop executable. No policy-bypass mechanism is included.

COMPACT UPDATE FROM 0.5.0
The full package supports a separate compact update for the exact 0.5.0 release.
During staging, scripts/reuse_source_zip.py reuses compressed bodies for unchanged
source members and verifies every decompressed hash and persisted ZIP metadata.
The resulting source archive is the same one used by the full native package.

After validating both installations, generate update staging with:

    python3 scripts/make_desktop_update.py --base-root <0.5.0-runtime> \
        --app-root <staged-0.5.1-runtime> --output <new-update-folder> \
        --work <temporary-verification-folder>

The update contains a native folder picker, its Python installer, exact hashed
replacement blobs and an exact-byte source-archive recipe. It verifies the full
baseline, stages and checks the full target, backs up replaced/removed files,
removes only manifest-known historical runtime files and commits the target
manifest last. User results and saved settings remain in place. Transaction
regression tests are in tests/test_desktop_update.py. No fastp patch is reapplied:
the fixed scientific packs are unchanged between these two application versions.
