# Native programs: the code taken from Native Workbench

Native Workbench (`comparativechrono/workbench`) was a Windows desktop app that ran bioinformatics programs natively,
installed as packs. It is retired. This workbench is to become the one Windows app, and it takes over Native
Workbench's work on the programs – the Windows builds, their patches and their checks – without its interface and
without its packs. This folder holds that code, copied as it was.

**Status:** copied, not yet used. Nothing in the page or the runner refers to it. The next step gives the runner a list
of native programs, starting with the Cosmopolitan builds.

| Path | What it is |
| --- | --- |
| `workbench/` | Native Workbench's tree. Its build scripts expect it to be the top of the tree |
| `TOOLS.md` | the 37 programs: version, how each is built, its recipe, its Windows changes and limits, what it needs to run; and the gaps |
| `COPY-MANIFEST.json` | where every file came from, and what was left out |
| `restore_build_tree.py` | makes the complete build tree from `workbench/`, outside the repository |

## Where it came from

The tree is made from two sources:

- **The repository** `comparativechrono/workbench` at commit `9435fd65636917dab30e2c6b393549d1f371ac3d`: 691 files,
  10.7 MB. Everything was copied except `.git`, `AGENTS.md` and the release receipts in `knowledge/evidence/`.
- **The older 0.5.4 source tree**: the 586 files (17.5 MB) that exist only there. Native Workbench kept this tree in its
  0.16.0 source companion: `native-workbench-0.16.0-source.zip`, from the release `app-v0.16.0`, member
  `legacy/native-workbench-0.5.4-source.zip`. These files are:
  - `vendor-expanded/` (the patched upstream sources and their provenance);
  - `baselines/` and `validation/`;
  - the pack manifests in `packs/`;
  - the linker files of bwfastq.

  They are merged into the same tree, because the build scripts look for them there. Where both sources had a file, the
  repository's version was kept. The 26 older versions that were not copied are listed in the manifest.

Some files were left out of the copy. All are listed in the manifest with their SHA-256, and `restore_build_tree.py`
puts both groups back:

- 22 upstream source archives from the older tree (40.3 MB);
- 485 files whose bytes were already in the copy (16 MB). Most are the same licence text, in a tool's sources and in
  its pack.

Two of Native Workbench's own files are kept where they will not act:

- Its `.gitignore` is kept as `workbench/gitignore.from-workbench`. Here it would have hidden copied files (`vendor/`,
  `packs/`, `*.zip`).
- Its GitHub workflows are in `workbench/.github/workflows/`, where GitHub does not run them.

## Building a program

The build scripts run from the top of the build tree and write into it (`build/`, `variant-build/`, `baselines/bin/`
…). So build in a tree restored outside the repository:

```
python3 native/restore_build_tree.py --out ../nw-build-tree
```

This downloads the 0.16.0 source companion (about 48 MB) and checks it. To use a copy already downloaded, add
`--companion FILE`.

Next, put the toolchains where the scripts expect them. Their URLs and SHA-256 are in `TOOLS.md`:

```
cd ../nw-build-tree
# Cosmopolitan 3.3.10, and its loader for running the portable programs on Linux
mkdir -p variant-build/cosmocc-3.3.10 baselines/bin
unzip -q cosmocc-3.3.10.zip -d variant-build/cosmocc-3.3.10
cp variant-build/cosmocc-3.3.10/bin/ape-x86_64.elf baselines/bin/ape-loader-linux
# LLVM-MinGW 20260922 (UCRT)
mkdir -p build/toolchains
tar -xJf llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz -C build/toolchains
```

Three recipes were built this way on 14 October 2026, on Linux x86-64 with GCC 13.3 and Python 3.13:

```
python3 tools/build_paircheck.py --build all --test
python3 tools/build_bwa.py --build all
python3 scripts/build_fasttree_native.py --fetch \
    --toolchain build/toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64
```

The results:

- **paircheck** (Linux and Cosmopolitan): its 37 checks passed, and the two builds gave the same output in every one.
- **BWA 0.7.19** (Linux and Cosmopolitan, from a restored archive): the two builds made the same index files and the
  same alignments. The test aligned the yeast reads of `data/examples/rnaseq/` to yeast chromosome I: 580 records,
  byte for byte the same apart from the `@PG` line.
- **FastTree 2.2.0** (Windows): the recipe checks that the program is a 64-bit Windows executable that imports only
  Windows' own C runtime.

Most recipes fetch their upstream sources (`--fetch`), each pinned by SHA-256. Some come from `codeload.github.com`, so
the build machine must be able to reach it. What each recipe needs is in `TOOLS.md`.

## The copied documents

The documents in `workbench/` describe Native Workbench: its interface, its packs, its releases and its own working
rules. They include its READMEs, `docs/`, `knowledge/`, and the release notes and handovers. They are its history and
the evidence behind the recipes. They are not instructions for this project.

## Licences

Native Workbench's own code is under the MIT licence (`workbench/LICENSE`).

The upstream sources, patches and programs it builds keep their own licences. Several are under the GNU GPL (BWA,
HISAT2, Bowtie 2, MUSCLE and others). Their notices are kept with them, in `vendor-expanded/`, `tools/`,
`baselines/licenses/` and `packs/*/licenses/`.

There are no executables in this repository yet. When there are, each will be listed in `THIRD_PARTY.md` with its
licence and source, as the WebAssembly programs are.
