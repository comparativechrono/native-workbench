# Independent pack development, API 1

The Windows application and scientific packs have separate release lifecycles.
The application owns the native interface, graph model, process runner, reports,
pack manager and compatibility checks. A pack owns its executable files,
dependencies, declared commands, typed inputs and outputs, citations, fixtures
and scientific assertions. Installing a new pack does not rebuild the app.

This project uses one repository with independent application and pack tags,
such as `app-v0.6.0` and `pack-seqkit-v0.5.2`. A separate pack repository is also
possible, but is not required for independent releases. Do not use one shared
tag that requires rebuilding every tool. Keep previous releases available for
saved pipelines and reproducibility. See the
[publishing guide](github-publication.md) and maintained
[project knowledge base](../knowledge/README.md).

## Versions and identity

| Value | Meaning | Example |
| --- | --- | --- |
| Application version | Interface and runner release | `0.6.0` |
| Pack API | Archive/installation contract | `1` |
| Minimum app version | Earliest runner validated for the pack | `0.6.0` |
| Pack ID | Stable identity used in saved graphs | `seqkit` |
| Pack version | Pack author's independent release | `1.0.1` |
| Tool version | Exact upstream executable build | `2.14.0` |
| Manifest hash | Identity of the execution definition | SHA-256 of `pack.ini` |

API 1 uses stable three-part numeric pack versions. Pre-release/build suffixes
are not accepted for pack versions; upstream tool version strings may include
their existing suffixes. Increment the pack version whenever any packaged bytes,
defaults, commands, metadata, checks or licences change. Never replace published
bytes under the same `(ID, version)` pair. A compiler-only rebuild still requires
a new pack version even when the upstream tool version stays the same.

Preserve all current pack IDs, workflow IDs, versions and manifest bytes during
migration. Existing IDs such as `align`, `bam` and `variants` are established
identities, even when the displayed product names are Minimap2, Samtools and
BCFtools. Renaming a folder or changing a manifest to a preferred marketing name
breaks saved pins. Give future versions independent numbers greater than the old
version and explain the migration. Saved graphs identify the pack version and
manifest hash; installing an update must retain the old version.

## Contents and contracts

An installed pack has the following content. Every runtime file must be declared
by a tool or asset entry in `pack.ini`; licence/source material belongs below
`licenses/`.

```text
pack.ini
bin/tool.exe
workbench-schema.json
workbench-checks.json
fixtures/...
licenses/...
pack-readme.md
```

The `pack.ini` format remains version 2. It describes argument arrays and data
references, never shell command strings. Declare every executable and runtime
asset with its SHA-256. Keep dependencies inside the pack in API 1 so installation
does not alter PATH, global Java/Python installations, registry or other packs.

`workbench-schema.json` supplies categories, methods text, citations, semantic
ports, cardinality and data-state requirements. Pin it through
`[asset:workbench-schema]`. See `workspace/PACK-METADATA.md` and working pack
definitions for the full scientific contract. A BAM extension alone does not
establish sorting, indexing or sample identity. Preserve biologically meaningful
types and require the actual state consumed by the tool.

`workbench-checks.json`, pinned as `[asset:workbench-checks]`, supplies small
scientific tests run through the ordinary execution engine. Fixtures must be
pinned assets too. Compare results to an independent known answer: exact
sequences, alignments, genotypes, alleles or record counts. A successful exit code
or a `--version` response alone is not a scientific validation.

Methods text should identify the operation and important interpretation choices;
the result report supplies exact executable versions and parameters. Document
limitations, resource requirements and relevant references in the pack README.
Keep web retrieval separate from the analysis command: downloaded public
resources become explicit local inputs with recorded provenance.

## Prepare and package

`pack-examples/independent-pack/` is a small Seqtk wrapper template. It includes
typed FASTA ports, exact reverse-complement truth and a preparation script. It
deliberately contains no compiled executable. Supply your own pinned native
Windows build, upstream licence and build provenance; do not represent the
template as an already validated distributed tool.

From the application/SDK checkout:

```powershell
python scripts/package_split.py pack --pack-root C:/build/example-seqtk-1.0.0 --output C:/releases/example-seqtk-1.0.0.zip
python scripts/validate_pack_release.py C:/releases/example-seqtk-1.0.0.zip
```

The packager preserves the installed pack files byte-for-byte and creates a ZIP
containing `workbench-pack.json` plus `pack/...`. The envelope pins the pack ID,
version, API, minimum app version, platform, manifest hash and full file
inventory. The current builder targets API 1 / application 0.6.0; a future
minimum version increase needs an explicit builder/SDK change and compatibility
tests, not an edit to an already published archive.

Current importer limits are 1 GiB expanded per pack, 2,000 files and implied
folders combined, and 512 MiB per runtime file in the native pack contract. The archive
reader rejects unsafe paths, case collisions, links, extra files and changed
hashes. Keep shallow paths to support managed Windows installations. Static
validation does not run a scientific executable.

For every native build, retain pinned source archives or immutable commit IDs,
all patches, build commands, compiler and dependency versions, licence notices,
and observed PE/DLL import evidence. Publish required corresponding source with
the same release when the component licence requires it. Avoid naming a source
archive without actually attaching and hashing it. Source companions are
publisher records; they are not downloaded into the end user's analysis pack by
the catalogue manager.

## Native Windows release gate

Use an extracted, SHA-verified released application in a disposable directory:

```powershell
& C:/ci/app/native-workbench/runtime/python/python.exe -I scripts/check_pack_release_windows.py --app-root C:/ci/app/native-workbench --archive C:/releases/example-seqtk-1.0.0.zip --report C:/ci/evidence/native-pack.json
```

This gate uses the released app's Python code and native bridge. It verifies and
imports the archive, executes the candidate's declared scientific checks and
checks duplicate-version rejection. It refuses to run on Linux and refuses a
pack with no scientific checks. It modifies the disposable app; never run it
against a colleague's working installation. Test the oldest supported app and
the current app. Keep the JSON result with release evidence; a Linux static test
must never be described as a native Windows pass.

`pack-examples/independent-pack/ci/windows-pack.yml` is a manual GitHub Actions
template. It takes explicit SHA-pinned app and candidate archive URLs. It installs
no compiler and assumes the published app includes its own Python and bridge.
Copy it into the pack repository's `.github/workflows/` after supplying the SDK
script at the documented path. Pin any action revisions according to your
repository policy before using release secrets. This check workflow needs no
signing key and does not publish a release.

The Windows test protocol must also cover:

1. Ordinary paths and paths with spaces for app, inputs and outputs.
2. Unicode, long and punctuation-containing paths. Tools with a demonstrated
   limitation must declare a `pathPolicy` and reject them before allocating a run;
   record rejection as expected behavior, not scientific execution success.
3. Offline installation and execution with networking disabled after downloads;
   no browser launch, administrator rights or external runtime installation.
4. Invalid input and parameter rejection, cancellation, failed subprocesses and
   absence of apparently complete results after failure.
5. Upgrade beside the old pack version, exact saved-graph resolution, unchanged
   inputs, and meaningful methods/command/version records in the output.

The included CI template automates ordinary/space-path native pack checks. The
remaining cases require tool-specific tests or a recorded manual run; they are
not implied by a green template job.

## App release gate

Application tests should use small artificial packs for parser, signature,
archive, compatibility and transaction failures. They should not require every
optional scientific tool to be installed. The starter installation includes the
three ordinary Minimap2, Samtools and BCFtools packs. Run core checks against that
starter, then run each optional pack's gate separately. Keep pack release
evidence with its pack version rather than making every optional tool a mandatory
application release dependency.
