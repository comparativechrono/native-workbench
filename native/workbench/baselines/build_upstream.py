#!/usr/bin/env python3
"""Rebuild pinned Linux references and optional Cosmopolitan APE executables.

Run on Linux with GCC, GNU make, zlib development headers and Python 3.12+.
No upstream source or algorithm patches are applied.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent / "vendor"
COSMO_URL = "https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip"
COSMO_SHA256 = "00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de"


def verified(path, expected):
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    if digest != expected:
        raise SystemExit(f"SHA256 mismatch for {path}: {digest}")


def extract_toolchain(archive):
    verified(archive, COSMO_SHA256)
    destination = HERE / "build" / "cosmocc-3.3.10"
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            output = destination / member.filename
            if not output.resolve().is_relative_to(root):
                raise SystemExit("Unexpected archive path")
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            mode = member.external_attr >> 16
            data = zipped.read(member)
            if stat.S_ISLNK(mode):
                target = data.decode()
                if not (output.parent / target).resolve().is_relative_to(root):
                    raise SystemExit("Unexpected archive symlink")
                if output.exists() or output.is_symlink():
                    output.unlink()
                output.symlink_to(target)
            else:
                if output.is_symlink():
                    output.unlink()
                output.write_bytes(data)
                output.chmod(mode & 0o777 or 0o644)
    return destination


def run(command, cwd, log, env):
    with log.open("ab") as output:
        output.write((json.dumps(list(map(str, command))) + "\n").encode())
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=output, stderr=output, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--toolchain-archive", type=Path, help=f"Pinned archive from {COSMO_URL}; SHA256 verified")
    group.add_argument("--cosmocc-root", type=Path, help="Already extracted, verified cosmocc 3.3.10")
    args = parser.parse_args()
    provenance = json.loads((VENDOR / "provenance.json").read_text())
    (HERE / "bin").mkdir(exist_ok=True)
    (HERE / "build" / "tmp").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TMPDIR": str(HERE / "build" / "tmp")}
    cosmo = extract_toolchain(args.toolchain_archive.resolve()) if args.toolchain_archive else args.cosmocc_root
    if cosmo:
        cosmo = cosmo.resolve()
    for build in ("linux", "cosmo") if cosmo else ("linux",):
        directory = HERE / "build" / ("rebuild-" + build)
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        for source in provenance["source_archives"]:
            archive = VENDOR / source["file"]
            verified(archive, source["sha256"])
            with tarfile.open(archive) as tar:
                tar.extractall(directory, filter="data")
            tool = source["tool"]
            src = directory / ("seqtk-1.4" if tool == "seqtk" else "minimap2-2.28")
            log = HERE / (tool + "-" + build + "-rebuild.log")
            log.write_text("")
            if build == "linux":
                run(["make", "-j2", "CC=gcc"], src, log, env)
                shutil.copy2(src / tool, HERE / "bin" / (tool + "-linux"))
                continue
            cc = cosmo / "bin" / "x86_64-unknown-cosmo-cc"
            includes = "-I" + str(cosmo / "include" / "third_party" / "zlib")
            output = HERE / "bin" / (tool + "-cosmo.exe")
            if tool == "seqtk":
                run([cc, "-O2", "-g", includes, "seqtk.c", "-o", output, "-lm"], src, log, env)
            else:
                run(["make", "-j2", "CC=" + str(cc), "INCLUDES=" + includes, "LIBS=-lm -lpthread"], src, log, env)
                # The cross compiler produces APE for an .exe output name.
                run([cc, "-g", "-Wall", "-O2", "-Wc++-compat", "main.o", "-o", output,
                     "-L.", "-lminimap2", "-lm", "-lpthread"], src, log, env)
        if cosmo:
            shutil.copy2(cosmo / "bin" / "ape-x86_64.elf", HERE / "bin" / "ape-loader-linux")
    print("Build complete. Run: python baselines/benchmark_upstream.py")


if __name__ == "__main__":
    main()
