Native Workbench 0.5.4 - native Mutect2 expansion source

The 0.5.4 package is staged over the exact validated 0.5.3 release inventory.
Its original 17 tool-pack directories and fixed fastp executable are preserved
byte-for-byte. Application and pack versions remain independently recorded.
The source tree contains builders for the Mutect2 pack, its
license/provenance records and scientific checks. See the installed
README and docs/MUTECT2-0.5.4.txt for the final included operations.

BUILD AND PACKAGE
Build both components with the pinned LLVM-MinGW toolchain:

    bash desktop/build_desktop_workspace.sh
    bash desktop/build_bridge.sh

The desktop embeds the normal-user asInvoker manifest. The bridge creates
scientific child processes with a private environment that removes Java/Perl
launch-variable overrides. It never edits the user's or machine environment.

Keep the 0.5.3 installation intact. Stage into a new directory:

    python3 scripts/package_mutect2.py --base-root <0.5.3-runtime> --app-root <new-0.5.4-runtime> --stage-only

The packager verifies baseline hashes, the closed new-pack file inventory and
native file-count/size budgets, preserves all original packs, and copies the
exact eight private Python runtime modules. It includes both rebuilt native
executables and does not copy user settings or analysis results.

After validation, freeze and package the staged installation:

    python3 scripts/package_mutect2.py --base-root <0.5.3-runtime> --app-root <staged-0.5.4-runtime> --finish --output <release.zip>

Use scripts/make_desktop_update.py to make the compact update from those exact
0.5.3/0.5.4 trees. It verifies and stages all changes, reconstructs the exact
source ZIP, holds the native instance mutex, and commits the manifest last.
The update preserves user settings/results and independently installed extras.

SOURCE CONTENTS AND RESTORING ARCHIVES
SOURCE-CONTENTS.json inside the source ZIP, also installed as
 docs/SOURCE-CONTENTS-0.5.4.json, records corresponding-source archives under
packs/*/licenses. Complete source archives already supplied there are not
repeated inside this application-source ZIP. Every referenced copy is checked
against the same byte count and SHA-256 before omission.

To restore the expected archive paths after extracting the source ZIP:

    python3 scripts/restore_source_archives.py --runtime-root <0.5.4-runtime>

This copies only matching local archives, refuses mismatched existing files,
and downloads nothing. Then follow each pack builder's --help. Builders may
use a separate vendor cache or acquire explicitly pinned downloads when that
cache is absent; the installed application never invokes those build steps.
Compiler products, expanded rebuildable vendor trees, bundled runtime copies,
old benchmark outputs and temporary directories are excluded. Application
history, build/test code, provenance and patches remain available. Locally
modified redistributions must retain their patch recipe and complete usable
corresponding sources, including any required upstream dependencies.

MUTECT2 RUNTIME AND LOCAL PATH ADAPTATION
The scientific implementation is GATK 4.7.0.0. The pack records the Workbench
adaptation separately as 4.7.0.0-workbench1: one IOUtils method converts local
file paths correctly when they contain spaces or non-ASCII characters. A small
compatibility JAR loads that class before the unchanged upstream GATK JAR.
It retains the upstream Main-Class and Add-Opens manifest entries; the relative
Class-Path points to the adjacent gatk.jar. Calling/filtering algorithms and
model parameters are unchanged by this adaptation.

scripts/build_mutect2_compat.py is the deterministic build recipe. The full
modified IOUtils source, exact patch and provenance are retained under
packs/mutect2-0.5.4/licenses. The original source comes from the pinned GATK
source archive. Compiler products and the expanded compiler JDK are excluded
from this source ZIP; its explicit --download-compiler option obtains the
pinned compiler only when needed.

After restoring source archives, these commands verify/acquire the remaining
pinned inputs and build the compatibility JAR:

    python3 scripts/fetch_mutect2_vendor.py --download
    python3 scripts/fetch_mutect2_thirdparty_sources.py --restore-sources packs/mutect2-0.5.4/licenses
    python3 scripts/build_mutect2_compat.py --download-compiler

The pack builder also requires the unchanged SAMtools and BCFtools APE binaries
as baselines/bin/samtools-cosmo.exe and baselines/bin/bcftools-cosmo.exe. Build
them using the retained original tool recipes, or copy the checksum-identical
bin/samtools.exe and bin/bcftools.exe from the distributed Mutect2 pack to those
names. The builder verifies their exact hashes before using them. Then assemble
into a new, empty destination:

    python3 scripts/prepare_mutect2_pack.py --output <new-Mutect2-pack-directory>

The third-party inventory retains exact source JARs, native/full source archives,
license notices and Maven metadata. Source JARs are explicitly classified by
name and SHA-256; general compiled JARs remain excluded from the application
source ZIP. All 31 source aliases from 0.5.3 remain available alongside the new
GATK, OpenJDK and dependency aliases. The installation's normal analysis path
does not invoke source restoration, downloads or compilation.

The upstream LoFreq full tarball is deliberately excluded because its unused
CDF/uniq component has separate restrictive terms. Only the documented,
filtered corresponding-source distribution and exact exclusion/build recipe
are redistributed with the LoFreq pack. The excluded uniq command is not
available in the shipped tool.

VALIDATION
Run workspace tests, updater transaction tests and pack-specific scientific
checks. Linux comparisons and PE dependency inspection do not establish native
Windows execution. File > Check installation executes the new pack's fixed
fixtures on the user's Windows machine and saves the scientific check reports.
