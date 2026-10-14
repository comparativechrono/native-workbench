# FastQC pack 1.0.0

This optional pack runs **unmodified FastQC 0.13.0** locally on Windows x86-64
with a complete private Temurin 8u504-b01 Java runtime. No system Java, Python,
Docker, WSL, browser launch or network connection is required for analysis.
The desktop application remains native; the resulting HTML can be viewed in an
approved offline viewer. Text and ZIP outputs remain useful without a browser.

## Operations and results

Choose **one FASTQ file** or **paired reads**. Plain and gzip four-line FASTQ
are accepted. Select Phred+33 for modern data, or Phred+64 only for documented
legacy Illumina data. Input structure, sequence/quality lengths and encoding
ranges are checked before analysis. Paired mode also checks mate names, order
and counts, and reports each mate separately. It does not infer library quality
or experimental suitability from filenames.

For each input, the results contain self-contained `fastqc.html`, the unchanged
upstream `fastqc.zip`, extracted `fastqc_data.txt` and `summary.txt`. The original
sample filename remains in FastQC's report and archive. Use either the ZIP or
data output as input to MultiQC; do not select both copies of the same result.
The input validation JSON records read counts and bases. Workbench additionally
retains methods, exact parameters, command arguments, versions and file hashes.

FastQC keeps its default modules, adapter/contaminant lists, grouping and
thresholds. No trimming, read filtering or normalization occurs. A warning or
failure flag requires interpretation: RNA composition, amplicons and intentional
duplicates can trigger flags in suitable data. QC is not a clinical validation.

## Supported limits

- The two mate files run sequentially; each file uses 1–4 FastQC workers
  (default 2). Default Java heap is 512 MiB, adjustable to 16 GiB; allow extra
  RAM for Java, the adapter and Workbench. Very long reads may need more heap.
- Paths must be ASCII and cannot contain a semicolon; spaces are supported.
  Rename input filenames beginning with lowercase `stdin`: FastQC treats these
  names as a stream sentinel, so the adapter rejects them before launching.
  Native Windows CI is separate from Linux scientific execution.
- FAST5, BAM/SAM QC, bzip2, CASAVA grouping, streaming, custom module limits,
  custom adapter/contaminant lists and upstream length filtering are not exposed.
  A paired operation expects real synchronized mates; independent files use
  separate single-file steps that can branch into a common report.
- FastQC 0.13.0 has an upstream diagnostic typo that calls the default encoding
  “Phred32” and displays a lowest-quality value one too high when all qualities
  are high. Its actual calculation uses offset 33; tests assert `I` gives Q40.
  Upstream report calculations are not patched.

## Sources, licensing and preparation

FastQC is GPL-3.0-or-later. Its pinned corresponding source archive is included
under `licenses`, with the upstream notices and the adapter source/build recipe.
Unmodified upstream classes/resources are repackaged into one jar to keep the
pack inventory small. Apache Commons IO/Compress retain their Apache notices
and exact versioned source jars;
the embedded Commons Math source/notices remain in the FastQC source archive.
The BAM/FAST5 dependency jars are not runtime dependencies of the supported
FASTQ operations and are omitted from the executable classpath.

Temurin's complete corresponding OpenJDK source archive, GPLv2/ClassPath
Exception notices and third-party notices are bundled. Microsoft runtime DLLs
included in the official JRE are separately inventoried with Microsoft's
original runtime license document; they are not represented as OpenJDK GPL code.
The adapter is MIT licensed. Exact source URLs and SHA-256 pins are in
`licenses/provenance.json` and the preparation script. This source coverage makes
the optional download larger than the application itself.

From a source checkout with Python 3.12+ on Linux:

```sh
python3 scripts/prepare_fastqc_pack.py --fetch
NW_FASTQC_JDK="$PWD/vendor-expanded/java/linux/jdk8u504-b01" python3 -m unittest discover -s tests -p test_fastqc_pack.py -v
python3 scripts/package_split.py pack --pack-root packs/fastqc-1.0.0 --output dist/native-workbench-pack-fastqc-1.0.0.zip
python3 scripts/validate_pack_release.py dist/native-workbench-pack-fastqc-1.0.0.zip
```

The build accepts `--vendor`, `--java-cache`, `--jdk` and `--destination` for
explicit caches. The destination must be new or empty. `--fetch` is a build-time
operation only. Compilation uses Temurin `javac 1.8.0_504` for Java-8 bytecode.
Linux tests execute the exact packaged upstream jars through the named Linux
JDK and assert independent read/base/GC/quality truth, gzip, paired synchronization,
encoding, errors, report self-containment and thread agreement. They do not claim
execution of Windows `java.exe` or GUI acceptance. Run the native Windows release
gate against the frozen archive through the released Workbench 0.6.0 before
publishing it as validated.

Upstream: <https://www.bioinformatics.babraham.ac.uk/projects/fastqc/> and
<https://github.com/s-andrews/FastQC/releases/tag/v0.13.0>.
