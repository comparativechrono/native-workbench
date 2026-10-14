Native Workbench 0.5.3 - native aligner and caller expansion source

The 0.5.3 package is staged over the exact validated 0.5.2 release inventory.
Its original 13 tool-pack directories and fixed fastp executable are preserved
byte-for-byte. Application and pack versions remain independently recorded.
The source tree contains builders for the new aligner/caller packs, their
patches, license/provenance records and scientific checks. See the installed
README and docs/ALIGNER-CALLERS-0.5.3.txt for the final included operations.

BUILD AND PACKAGE
Build both components with the pinned LLVM-MinGW toolchain:

    bash desktop/build_desktop_workspace.sh
    bash desktop/build_bridge.sh

The desktop embeds the normal-user asInvoker manifest. The bridge creates
scientific child processes with a private environment that removes Java/Perl
launch-variable overrides. It never edits the user's or machine environment.

Keep the 0.5.2 installation intact. Stage into a new directory:

    python3 scripts/package_aligner_callers.py --base-root <0.5.2-runtime> --app-root <new-0.5.3-runtime> --stage-only

Only confirmed new packs should be selected; --pack may be repeated. The
packager verifies baseline hashes, the closed new-pack file inventory and
native file-count/size budgets, preserves all original packs, and copies the
exact eight private Python runtime modules. It includes both rebuilt native
executables and does not copy user settings or analysis results.

After validation, freeze and package the staged installation:

    python3 scripts/package_aligner_callers.py --base-root <0.5.2-runtime> --app-root <staged-0.5.3-runtime> --finish --output <release.zip>

Use scripts/make_desktop_update.py to make the compact update from those exact
0.5.2/0.5.3 trees. It verifies and stages all changes, reconstructs the exact
source ZIP, holds the native instance mutex, and commits the manifest last.
The update preserves user settings/results and independently installed extras.

SOURCE CONTENTS AND RESTORING ARCHIVES
SOURCE-CONTENTS.json inside the source ZIP, also installed as
 docs/SOURCE-CONTENTS-0.5.3.json, records corresponding-source archives under
packs/*/licenses. Complete source archives already supplied there are not
repeated inside this application-source ZIP. Every referenced copy is checked
against the same byte count and SHA-256 before omission.

To restore the expected archive paths after extracting the source ZIP:

    python3 scripts/restore_source_archives.py --runtime-root <0.5.3-runtime>

This copies only matching local archives, refuses mismatched existing files,
and downloads nothing. Then follow each pack builder's --help. Builders may
use a separate vendor cache or acquire explicitly pinned downloads when that
cache is absent; the installed application never invokes those build steps.
Compiler products, expanded rebuildable vendor trees, bundled runtime copies,
old benchmark outputs and temporary directories are excluded. Application
history, build/test code, provenance and patches remain available. Locally
modified redistributions must retain their patch recipe and complete usable
corresponding sources, including any required upstream dependencies.

The upstream LoFreq full tarball is deliberately excluded because its unused
CDF/uniq component has separate restrictive terms. Only the documented,
filtered corresponding-source distribution and exact exclusion/build recipe
are redistributed with the LoFreq pack. The excluded uniq command is not
available in the shipped tool.

VALIDATION
Run workspace tests, updater transaction tests and pack-specific scientific
checks. Linux comparisons and PE dependency inspection do not establish native
Windows execution. File > Check installation executes the new packs' fixed
fixtures on the user's Windows machine and saves the scientific check reports.
