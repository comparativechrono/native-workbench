# VarDict 0.5.3 reproduction

Run commands from the source distribution's `native-workbench` directory. Python 3, the source tree's baseline SAMtools/BCFtools binaries and their notices are needed to assemble the pack. Only the build/test environment needs Linux build tools; Windows users receive private Java and Perl runtimes.

`python3 scripts/fetch_vardict_vendor.py` verifies all 14 pinned assembly inputs. To restore corresponding-source archives already shipped in the pack and download any missing official release archives, run:

```sh
python3 scripts/fetch_vardict_vendor.py --restore-sources packs/vardict-0.5.3/licenses --download
python3 scripts/prepare_vardict_pack.py --output build/vardict-rebuilt
```

The generator refuses an existing output directory. The fetch helper never runs downloaded code; every input is checked against SHA-256 before use. Sources supplied by GitHub are pinned archive bytes, so a future upstream re-encoding fails closed and can be resolved using the exact corresponding-source archive shipped in `licenses`. Original Windows runtime archives are fetched from the official release URLs. `licenses/BUILD-PROVENANCE.json` records all input hashes. The source ZIP may omit duplicate binary archives and expanded build trees.

To reproduce Linux reference execution, fetch optional test dependencies and unpack the matching Java and Perl source:

```sh
python3 scripts/fetch_vardict_vendor.py --reference-linux --download
mkdir -p build/vardict/linux-jre build/vardict/perl-source
tar -xzf vendor-expanded/vardict/OpenJDK8U-jre_x64_linux_hotspot_8u504b01.tar.gz -C build/vardict/linux-jre
tar -xJf vendor-expanded/vardict/perl-5.42.3.tar.xz -C build/vardict/perl-source
cp vendor-expanded/vardict/ecj-3.26.0.jar build/vardict/ecj-3.26.0.jar
```

In `build/vardict/perl-source/perl-5.42.3`, run `sh Configure -des -Dman1dir=none -Dman3dir=none -Duseshrplib=false -Dusethreads -Duse64bitall` and `make -j4`. No system installation is needed. Return to the source root and run:

```sh
python3 tests/test_vardict_pack.py -v
```

The adapter uses the built Perl executable and pinned Temurin Linux Java, passes the real manifest arguments, and changes only the Java classpath separator to Linux syntax. The fixed Perl adapter resolves its modules relative to its own location. Runtime paths and reference executable hashes from the original validation are recorded in `vardict-0.5.3.json`; a locally rebuilt Perl binary need not have identical bytes.

The Fisher test recompiles `tests/VarDictFisherProbe.java`, executes the actual release library over the 40 recorded tables, and compares against independently obtained R 4.3.3 values. To regenerate those R values, apply `stats::fisher.test(matrix(cells, nrow=2))` to each table and round its p-value and conditional odds-ratio estimate to five decimal places, as the official `teststrandbias.R` does. The original R reference binary was Ubuntu `r-base-core_4.3.3-2build2_amd64.deb`, SHA-256 `086f046230727fc896f70cfb459d693023a30a9f6877492554aa7041dac2e576`, from `https://archive.ubuntu.com/ubuntu/pool/universe/r/r-base/r-base-core_4.3.3-2build2_amd64.deb`. R is only an independent test reference and is not required by the pack.

These Linux tests and the Windows PE import audit do not establish Windows execution. The application installation check executes both declared fixture workflows with the actual bundled Windows Java/Perl/native tools. Upstream experimental Fisher status and the finite scope of validation remain visible in the tool description and generated methods.
