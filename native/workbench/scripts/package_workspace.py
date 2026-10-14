#!/usr/bin/env python3
"""Package the 0.5 workspace over an extracted, fastp-patched 0.4.1 release.

No tool downloads, manifest rewriting or automatic pack upgrades occur here.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
VERSION = "0.5.0"
FASTP_SHA = "1dc1c089"  # Full hash is checked against preserved patch metadata below.


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(data)
    return value.hexdigest()


def archive(path, files, base, prefix="native-workbench"):
    temporary = path.with_name(path.name + ".partial")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as output:
        for file in sorted(files):
            if file.is_symlink():
                raise ValueError("Refusing to package a symbolic link: " + str(file))
            name = prefix + "/" + file.relative_to(base).as_posix()
            info = zipfile.ZipInfo(name, (2026, 10, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (file.stat().st_mode & 0xFFFF) << 16
            with file.open("rb") as source, output.open(info, "w", force_zip64=True) as dest:
                shutil.copyfileobj(source, dest, 1024 * 1024)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = args.app_root.resolve()
    output = args.output.resolve()
    if not (app / "manifest.json").is_file():
        raise ValueError("Extract the original runtime and apply the 0.4.1 fix before packaging.")
    if (SOURCE / "docs/fastp-report-fix").is_dir():
        shutil.copytree(SOURCE / "docs/fastp-report-fix", app / "docs/fastp-report-fix", dirs_exist_ok=True)
    metadata = json.loads((app / "docs/fastp-report-fix/patch-metadata.json").read_text())
    expected = metadata["files"]["files/fastp.exe"]
    if not expected.startswith(FASTP_SHA):
        raise ValueError("Unexpected fastp patch identity")
    for pack in ("fastp-0.4.1", "research-variants-0.4.1"):
        if sha(app / "packs" / pack / "bin/fastp.exe") != expected:
            raise ValueError("The fixed fastp executable is missing: " + pack)
    if not (app / "NativeWorkbenchClassic.exe").exists():
        shutil.copyfile(app / "NativeWorkbench.exe", app / "NativeWorkbenchClassic.exe")
    for built, installed in (("WorkspaceLauncher.exe", "NativeWorkbench.exe"), ("WorkbenchBridge.exe", "WorkbenchBridge.exe")):
        shutil.copyfile(SOURCE / "build/desktop" / built, app / installed)
    runtime = app / "runtime/python"
    if not runtime.is_dir():
        shutil.copytree(app / "packs/trimming-0.4.0/runtime/python", runtime,
                        ignore=shutil.ignore_patterns("packages", "__pycache__"))
    (runtime / "python313._pth").write_text("python313.zip\n.\n", encoding="ascii")
    shutil.copytree(SOURCE / "workspace", app / "workspace", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "catalog.json", "tests", "release-files"))
    # User-facing launchers/docs are kept as release inputs in the source bundle.
    release_inputs = SOURCE / "workspace/release-files"
    if release_inputs.is_dir():
        shutil.copytree(release_inputs, app, dirs_exist_ok=True)
    source_zip = app / "source/native-workbench-source.zip"
    source_zip.parent.mkdir(exist_ok=True)
    source_files = [p for p in SOURCE.rglob("*") if p.is_file()
                    and not set(p.relative_to(SOURCE).parts) & {"__pycache__", "fastp-build", "node_modules", ".git"}
                    and p.suffix not in (".pyc", ".o", ".obj")
                    and not (p.relative_to(SOURCE).parts[0] == "build" and p.suffix == ".exe")]
    archive(source_zip, source_files, SOURCE)
    exclude = {"results", "user-data", "updates", "__pycache__"}
    files = [p for p in app.rglob("*") if p.is_file() and not set(p.relative_to(app).parts) & exclude
             and p != app / "manifest.json" and p.name != "workspace-startup-error.txt" and p.suffix != ".pyc"]
    manifest = {"schema_version": 1, "version": VERSION, "manifest_includes_itself": False, "platform": "windows-x86_64", "release_status": "integration-test-build",
                "native_windows_integration_tested": False, "fastp_patch": "fastp-report-fix-0.4.1",
                "note": "Pack versions are independent. Results, saved user settings and updater backups are excluded.",
                "files": [{"path": p.relative_to(app).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(files)]}
    (app / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    archive(output, [*files, app / "manifest.json"], app)
    print(json.dumps({"path": str(output), "bytes": output.stat().st_size, "sha256": sha(output),
                      "files": len(files) + 1, "source_zip_bytes": source_zip.stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
