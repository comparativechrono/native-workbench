# Single-operation pack template

This is a developer example for a Seqtk reverse-complement operation, not an
installed or prevalidated tool. It includes a format-2 manifest template, typed
FASTA ports, methods text, citation and a two-record independent truth test.
No binary, build toolchain, production catalogue or signing key is included.

Provide a native Windows Seqtk executable from your pinned build, its original
licence and a JSON provenance object recording the exact source, patches,
compiler and dependencies. Then run from the SDK checkout:

```powershell
python pack-examples/independent-pack/prepare.py --tool-exe C:/build/seqtk.exe --tool-version 1.4-r122 --pack-version 1.0.0 --license C:/source/seqtk/LICENSE --provenance C:/build/provenance.json --output C:/build/example-seqtk-1.0.0
python scripts/package_split.py pack --pack-root C:/build/example-seqtk-1.0.0 --output C:/releases/example-seqtk-1.0.0.zip
python scripts/validate_pack_release.py C:/releases/example-seqtk-1.0.0.zip
```

The version shown is an example: record the version actually built. The
preparation script computes hashes from the supplied files and refuses an
existing output folder. Build recipes and redistribution obligations remain the
publisher's responsibility; copying an executable is not a reproducible build.

Run `scripts/check_pack_release_windows.py` against a disposable released app on
Windows before publication. Read `docs/pack-development-0.6.md` and
`docs/catalogue-publishing-0.6.md` for the release and trust contract. Adapt the
optional `ci/windows-pack.yml` workflow after placing the check script in the pack
repository. The workflow downloads only explicit, SHA-pinned release URLs and
publishes nothing.
