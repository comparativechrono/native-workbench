#!/usr/bin/env python3
"""Create a separately versioned Windows-validation archive without editing a pack.

Only the pack identity version and a README prefix change. All tools, commands,
schemas, fixtures, scientific checks and build provenance retain their bytes.
The correspondence JSON is outside both archives. A candidate pass does not
replace testing the exact final archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from package_split import build_pack, pack_inventory


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-root', type=Path, required=True)
    parser.add_argument('--version', required=True, help='Unused numeric development version, e.g. 0.0.1')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    source = args.pack_root.resolve()
    pack, _, _ = pack_inventory(source)
    if not re.fullmatch(r'0\.0\.[1-9][0-9]*', args.version):
        parser.error('Use a nonzero 0.0.N development version')
    if args.version == pack['version'] or args.output.exists() or args.record.exists():
        parser.error('Candidate identity and output/record paths must be new')
    before = inventory(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='candidate-', dir=args.output.parent) as temp:
        candidate = Path(temp) / 'pack'
        shutil.copytree(source, candidate)
        manifest = candidate / 'pack.ini'
        raw = manifest.read_bytes()
        # Restrict the replacement to the [pack] section; executable versions
        # and operation definitions must remain byte-for-byte unchanged.
        match = re.search(rb'(?ms)^\[pack\]\r?\n.*?(?=^\[|\Z)', raw)
        if not match:
            raise ValueError('Expected a pack identity section')
        section = match.group(0)
        altered, count = re.subn(rb'(?m)^version=' + re.escape(pack['version'].encode()) + rb'(?=\r?$)',
                                b'version=' + args.version.encode(), section)
        if count != 1:
            raise ValueError('Expected exactly one pack version')
        manifest.write_bytes(raw[:match.start()] + altered + raw[match.end():])
        names = [p for p in candidate.iterdir()
                 if p.is_file() and p.name.lower() in ('pack-readme.md', 'pack-readme.txt', 'readme.txt')]
        readme = names[0] if names else candidate / 'PACK-README.md'
        original = readme.read_bytes() if readme.exists() else b''
        prefix = (f'DEVELOPMENT VALIDATION CANDIDATE: {pack["id"]} {args.version}\n\n'
                  f'This separately versioned diagnostic archive tests the proposed {pack["version"]} pack. '
                  'Do not use it for analysis. Retained build documentation below describes the proposed final pack. '
                  'A native candidate pass does not establish that the final archive passed.\n\n')
        readme.write_bytes(prefix.encode('utf-8') + original)
        after = inventory(candidate)
        changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
        allowed = {'pack.ini', readme.name}
        if changed != allowed:
            raise ValueError('Unexpected candidate changes: ' + repr(changed))
        archive = build_pack(candidate, args.output)
        record = {'schema': 1, 'kind': 'validation-candidate-correspondence',
                  'packId': pack['id'], 'proposedFinalVersion': pack['version'],
                  'proposedFinalManifestSha256': pack['manifestSha256'],
                  'candidate': archive, 'unchangedFileCount': sum(before[name] == after.get(name) for name in before),
                  'allowedChanges': sorted(changed),
                  'files': [{'path': name, 'finalSha256': before.get(name), 'candidateSha256': after.get(name)}
                            for name in sorted(before.keys() | after.keys())],
                  'nativeWindowsExecuted': False,
                  'note': 'This record compares bytes only. Attach native execution evidence separately.'}
    if inventory(source) != before:
        raise ValueError('Source pack changed while preparing candidate')
    args.record.parent.mkdir(parents=True, exist_ok=True)
    with args.record.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(json.dumps(archive, indent=2))


if __name__ == '__main__':
    main()
