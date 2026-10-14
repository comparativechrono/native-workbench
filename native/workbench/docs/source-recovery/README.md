# Source companions and recovery

This repository starts from the `current/` tree of the Native Workbench 0.6.0
source companion. It contains the current application, pack SDK, build scripts,
documentation and tests. It deliberately does not contain compiled tool packs,
private runtimes, downloaded upstream source archives or the large legacy source
ZIP. A small checkout alone does not reproduce every historical scientific pack.

The release asset `native-workbench-0.6.0-source.zip` contains the matching
`legacy/native-workbench-0.5.4-source.zip`. Obtain that source companion and the
exact pack companions named in `SOURCE-RECOVERY.json` from the corresponding
release assets or an approved offline copy. The metadata records their pack
versions, manifest hashes and the exact hashes of source archives to recover.
Keep these source companions available when distributing the compiled packs.

To recover the historical build inputs, extract the embedded legacy ZIP into a
separate directory. For each listed pack ZIP, copy its `pack/` tree into
`packs/<id>-<version>/` beneath a separate runtime directory. Run the recovered
`scripts/restore_source_archives.py` with `--source-root` naming the extracted
legacy `native-workbench` directory and `--runtime-root` naming that runtime
directory. The script verifies exact hashes and refuses to overwrite different
existing source files. `SOURCE-CONTENTS-0.5.4.json` retains the original inventory;
`SOURCE-RECOVERY.json` describes the 0.6 companion and its 175 recovery aliases.

Use this repository's current application sources when working on 0.6. Do not
replace them wholesale with the older recovered source tree. Historical pack
builds can require the recovered vendor inputs, their original build recipes and
pinned toolchains. Some older tests also require separately installed packs or
runtime fixtures; they are not all pure unit tests.

Native desktop builds use the LLVM-MinGW toolchain selected by `BW_MINGW_ROOT`.
See `desktop/build_desktop_workspace.sh`, `desktop/build_bridge.sh` and
`desktop/build_workspace_update_launcher.sh`. Native Windows execution and
scientific validation are separate from Linux compilation. Pack authoring and
catalogue publication are documented in `../pack-development-0.6.md` and
`../catalogue-publishing-0.6.md`.
