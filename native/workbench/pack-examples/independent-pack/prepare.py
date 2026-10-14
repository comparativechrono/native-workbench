#!/usr/bin/env python3
"""Prepare the example from an explicitly supplied, already-built Seqtk EXE."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from string import Template

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-exe', required=True, type=Path)
    parser.add_argument('--tool-version', required=True)
    parser.add_argument('--pack-version', default='1.0.0')
    parser.add_argument('--license', required=True, type=Path)
    parser.add_argument('--provenance', required=True, type=Path, help='Your build record with pinned source, compiler and dependency versions')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', args.pack_version):
        parser.error('Use a stable semantic pack version, for example 1.0.0')
    if not re.fullmatch(r'[A-Za-z0-9.+_-]{1,64}', args.tool_version):
        parser.error('Invalid upstream tool version')
    if args.output.exists():
        parser.error('Output must be a new folder')
    for path in (args.tool_exe, args.license, args.provenance):
        if not path.is_file() or path.is_symlink():
            parser.error('Supply regular executable, licence and provenance files')
    if not isinstance(json.loads(args.provenance.read_text(encoding='utf-8')), dict):
        parser.error('Provenance must be a JSON object')
    shutil.copytree(ROOT / 'pack', args.output)
    (args.output / 'bin').mkdir(exist_ok=True)
    (args.output / 'licenses').mkdir(exist_ok=True)
    shutil.copyfile(args.tool_exe, args.output / 'bin/seqtk.exe')
    shutil.copyfile(args.license, args.output / 'licenses/SEQTK-LICENSE.txt')
    shutil.copyfile(args.provenance, args.output / 'licenses/build-provenance.json')
    values = {'pack_version': args.pack_version, 'tool_version': args.tool_version,
              'tool_sha': sha(args.output / 'bin/seqtk.exe'), 'schema_sha': sha(args.output / 'workbench-schema.json'),
              'checks_sha': sha(args.output / 'workbench-checks.json'), 'fixture_sha': sha(args.output / 'fixtures/sequences.fasta')}
    (args.output / 'pack.ini').write_text(Template((ROOT / 'pack.ini.in').read_text()).substitute(values), encoding='utf-8', newline='\n')
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
