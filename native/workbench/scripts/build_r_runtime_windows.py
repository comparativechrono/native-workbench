#!/usr/bin/env python3
"""Recover a pinned, relocatable private R runtime on a disposable Windows builder.

This is a build-only installer invocation. Workbench users receive the resulting
ZIP and do not run an installer. No analysis or contributed R packages run here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

VERSION = '4.6.1'
INSTALLER = dict(url='https://cran.r-project.org/bin/windows/base/R-4.6.1-win.exe',
                 bytes=91749976, sha256='c5424c40cd70ef85765a55d2ff96bb602b5f30ed536938ff004f14db5db3c2df')
SOURCE = dict(url='https://cran.r-project.org/src/base/R-4/R-4.6.1.tar.gz',
              bytes=40926649, sha256='4da6e61d2c0aac5f14a2e7e432cb5fcc269efe83da4293050ba7f03dff4e2cf4')
CHUNK_BYTES = 24 * 1024 * 1024


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    result = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Unexpected runtime link: ' + str(path))
        if path.is_file():
            result.append(dict(path=path.relative_to(root).as_posix(), bytes=path.stat().st_size, sha256=sha(path)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New build directory')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This build-only recovery must run on native Windows.')
    root = args.output.resolve()
    if root.exists():
        raise ValueError('Use a new output directory; existing builds are never overwritten.')
    root.mkdir(parents=True)
    export = root / 'export'
    export.mkdir()
    installer = root / ('R-' + VERSION + '-win.exe')
    with urllib.request.urlopen(INSTALLER['url'], timeout=180) as response, installer.open('xb') as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    if installer.stat().st_size != INSTALLER['bytes'] or sha(installer) != INSTALLER['sha256']:
        raise ValueError('Official R installer bytes differ from the pinned download.')
    original = root / 'installed-r'
    flags = ['/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
             '/COMPONENTS=main,x64,translations',
             '/MERGETASKS=!desktopicon,!quicklaunchicon,!recordversion,!associate',
             '/DIR=' + str(original), '/LOG=' + str(root / 'installer.log')]
    subprocess.run([str(installer), *flags], check=True, timeout=600)
    # Installer-generated uninstallers are not an R runtime component.
    excluded = []
    for path in original.glob('unins*'):
        if path.is_file() and path.suffix.lower() in ('.exe', '.dat', '.msg'):
            excluded.append(dict(path=path.name, bytes=path.stat().st_size, sha256=sha(path)))
            path.unlink()
    before = inventory(original)
    relocated = root / 'relocated R runtime'
    shutil.copytree(original, relocated)
    if inventory(relocated) != before:
        raise ValueError('Runtime bytes changed while making the relocation copy.')
    user = root / 'smoke-user'
    user.mkdir()
    private_library = user / 'library'
    private_library.mkdir()
    child_env = {k: v for k, v in os.environ.items() if not k.upper().startswith('R_')}
    child_env.update(R_USER=str(user), R_LIBS_USER=str(private_library), R_LIBS_SITE=str(private_library), R_LIBS=str(private_library))
    code = "stopifnot(getRversion() == numeric_version('4.6.1')); cat(R.version.string, '\\n', normalizePath(R.home(), winslash='/'), '\\n', sum(1:10), '\\n', sep='')"
    process = subprocess.run([str(relocated / 'bin/x64/Rscript.exe'), '--vanilla', '-e', code],
                             cwd=user, env=child_env, capture_output=True, text=True, timeout=60, check=True)
    lines = process.stdout.strip().splitlines()
    if len(lines) != 3 or Path(lines[1]).resolve() != relocated or lines[2] != '55':
        raise ValueError('Relocated runtime did not identify its private location: ' + process.stdout)
    if inventory(relocated) != before:
        raise ValueError('R startup modified the private runtime.')
    archive_path = root / 'r-runtime.zip'
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in before:
            info = zipfile.ZipInfo(item['path'], date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            with (relocated / item['path']).open('rb') as source, archive.open(info, 'w') as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Runtime ZIP CRC verification failed.')
    parts = []
    with archive_path.open('rb') as stream:
        while data := stream.read(CHUNK_BYTES):
            path = export / ('r-runtime.part%03d' % len(parts))
            path.write_bytes(data)
            parts.append(dict(name=path.name, bytes=len(data), sha256=sha(path)))
    if len(parts) > 8:
        raise ValueError('Runtime exceeds this workflow export bound.')
    report = dict(schema=1, kind='private-r-runtime-recovery', rVersion=VERSION,
                  sourceCommit=os.environ.get('GITHUB_SHA'), workflowRun=os.environ.get('GITHUB_RUN_ID'),
                  platform=sys.platform, python=sys.version, installer=INSTALLER, correspondingRSource=SOURCE,
                  installerArguments=flags, excludedInstallerFiles=excluded, runtimeFiles=before,
                  runtimeArchive=dict(name=archive_path.name, bytes=archive_path.stat().st_size, sha256=sha(archive_path)),
                  parts=parts, relocatedWindowsStartup=dict(success=True, pathContainsSpaces=True,
                  runtimeUnchanged=True, stdout=process.stdout, stderr=process.stderr),
                  scope='Build-only extraction and relocated base-R startup. No DESeq2 tests, pack import, GUI or analysis data.',
                  recovery='Concatenate parts in listed order, verify runtimeArchive SHA-256 and extract paths relative to the R installation root.')
    (export / 'r-runtime-provenance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('rVersion', 'runtimeArchive', 'parts', 'relocatedWindowsStartup', 'scope')}, indent=2))


if __name__ == '__main__':
    main()
