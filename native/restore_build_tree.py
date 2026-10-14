#!/usr/bin/env python3
"""Make Native Workbench's complete build tree from the copy in native/workbench.

The copy in Git leaves out two kinds of file, both listed in COPY-MANIFEST.json:
  - upstream source archives of the legacy 0.5.4 tree (vendor-expanded/*/archives/ ...): they are restored from
    Native Workbench's 0.16.0 source companion (downloaded once, or given with --companion), checked by SHA-256;
  - files whose bytes appear twice in that tree (the same licence text in a tool's sources and in its pack): they are
    copied from the one kept.
The result is the tree the build scripts expect (scripts/, tools/, vendor-expanded/, packs/, baselines/ ... at its top),
written to a new folder outside the repository. Nothing is changed in native/workbench.

  python3 native/restore_build_tree.py --out ../nw-build-tree [--companion native-workbench-0.16.0-source.zip]

Standard library only. The companion is about 48 MB; the restored archives are about 40 MB.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
COPY = os.path.join(HERE, 'workbench')
MANIFEST = os.path.join(HERE, 'COPY-MANIFEST.json')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='a new folder for the build tree (must not exist)')
    ap.add_argument('--companion', help='native-workbench-0.16.0-source.zip, if already downloaded')
    ap.add_argument('--no-archives', action='store_true', help='restore only the duplicated files')
    args = ap.parse_args()

    with open(MANIFEST) as f:
        m = json.load(f)
    out = os.path.abspath(args.out)
    if os.path.exists(out):
        sys.exit(f'{out} exists: choose a new folder')
    if out == COPY or out.startswith(os.path.join(os.path.dirname(HERE), '')):
        sys.exit('write the build tree outside the repository')

    shutil.copytree(COPY, out, symlinks=False)
    # the copy renamed the workbench's .gitignore (it would have hidden copied files in this repository)
    for original, renamed in m.get('renamed', {}).items():
        if os.path.exists(os.path.join(out, renamed)):
            os.rename(os.path.join(out, renamed), os.path.join(out, original))

    for d in m['duplicates_left_out']:
        src, dst = os.path.join(out, d['same_bytes_as']), os.path.join(out, d['path'])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    print(f"{len(m['duplicates_left_out'])} duplicated files restored")

    if args.no_archives:
        return
    data = None
    if args.companion:
        with open(args.companion, 'rb') as f:
            data = f.read()
    else:
        url = m['legacy']['companion']
        print(f'downloading {url} …')
        with urllib.request.urlopen(url) as r:
            data = r.read()
    if sha256_bytes(data) != m['legacy']['companion_sha256']:
        sys.exit('the source companion does not have the expected SHA-256')
    outer = zipfile.ZipFile(io.BytesIO(data))
    legacy = zipfile.ZipFile(io.BytesIO(outer.read(m['legacy']['member'])))
    names = set(legacy.namelist())
    for a in m['excluded_archives']:
        member = 'native-workbench/' + a['path'].replace(os.sep, '/')
        if member not in names:
            sys.exit(f'{member} is not in the source companion')
        blob = legacy.read(member)
        if sha256_bytes(blob) != a['sha256']:
            sys.exit(f"{a['path']}: unexpected SHA-256")
        dst = os.path.join(out, a['path'])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(blob)
    print(f"{len(m['excluded_archives'])} upstream archives restored and checked")
    print(f'build tree: {out}')


if __name__ == '__main__':
    main()
