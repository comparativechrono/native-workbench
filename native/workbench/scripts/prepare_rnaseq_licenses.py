"""Retain exact notices and reused-helper source records in independent RNA packs.

This copies local, hash-pinned notices only; preparation makes no network calls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _copy(root, destination, source, name):
    source = Path(root) / source
    target = Path(destination) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {'file': name, 'sha256': sha(target), 'sourceRepositoryPath': source.relative_to(root).as_posix()}


def _notice(root, licenses, folder, filename, expected):
    source = Path(root) / 'tools' / folder / filename
    metadata = source.with_suffix('.provenance.json')
    record = json.loads(metadata.read_text())
    if sha(source) != expected or record['sha256'] != expected or record['file'] != filename:
        raise ValueError('Pinned third-party notice differs: ' + filename)
    shutil.copy2(source, Path(licenses) / filename)
    shutil.copy2(metadata, Path(licenses) / metadata.name)
    return record


def retain_rna_notices(root, destination, pack_id):
    """Add readable attribution and source/build lineage, leaving runtime bytes alone."""
    root, destination = Path(root), Path(destination)
    licenses = destination / 'licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    records = [_copy(root, licenses, 'LICENSE', 'Workbench-MIT-LICENSE.txt'),
               _copy(root, licenses, 'scripts/prepare_rnaseq_licenses.py', 'prepare_rnaseq_licenses.py')]
    if pack_id == 'star':
        records.append(_notice(root, licenses, 'star', 'OpenMP-LICENSE.txt',
                               'fdad1758a9e1f9d5a81e18879b3406772115edc92c24bfa36b70c654f325e8e4'))
        records.extend([
            _copy(root, licenses, 'tools/paircheck.c', 'helpers/paircheck.c'),
            _copy(root, licenses, 'tools/build_paircheck.py', 'helpers/build_paircheck.py'),
            _copy(root, licenses, 'build_variant.py', 'helpers/build_variant.py'),
            _copy(root, licenses, 'variant-provenance.json', 'helpers/variant-provenance.json'),
        ])
        original = json.loads((root / 'variant-provenance.json').read_text())
        record = {'schema': 1, 'samtools': {
            'binary': 'bin/samtools.exe', 'sha256': sha(destination / 'bin/samtools.exe'),
            'sourceArchive': next(item for item in original['source_archives'] if item['tool'] == 'samtools'),
            'buildRecipe': 'helpers/build_variant.py', 'upstreamSourceChanges': 'none',
            'buildRecord': 'helpers/variant-provenance.json',
            'recordNote': 'The retained original build record also describes BCFtools; that executable is not shipped in this RNA pack.'},
            'paircheck': {'binary': 'bin/paircheck.exe', 'sha256': sha(destination / 'bin/paircheck.exe'),
                          'source': 'helpers/paircheck.c', 'sourceSha256': sha(root / 'tools/paircheck.c'),
                          'buildRecipe': 'helpers/build_paircheck.py', 'version': '1.0.1'},
            'portableToolchain': original['portable_toolchain'],
            'executionNote': 'These are reused, byte-pinned helper builds. This record does not assert new execution or bit-for-bit rebuild results.'}
        (licenses / 'helpers/provenance.json').write_text(json.dumps(record, indent=2) + '\n')
        description = ('STAR source and embedded Opal/HTSlib notices are retained in STAR-2.7.11b.tar.gz.\n'
                       'OpenMP-LICENSE.txt is the runtime-specific notice at the recorded LLVM commit.\n'
                       'samtools-runtime/ and portable-runtime/ retain SAMtools, HTSlib, codec, Cosmopolitan and embedded notices.\n'
                       'helpers/ retains paircheck source, source/build recipes and reused-helper provenance.\n'
                       'The exact SAMtools source URL/hash is in helpers/provenance.json; that source archive is not bundled here.\n')
    elif pack_id == 'kallisto':
        records.append(_notice(root, licenses, 'kallisto', 'CRoaring-LICENSE.txt',
                               '5b223235c64f595576d15ba2d983ef14f8e9e3ec45aafcad689dc40008e1b29e'))
        records.append(_copy(root, licenses, 'scripts/prepare_kallisto_pack.py', 'prepare_kallisto_pack.py'))
        description = ('kallisto-v0.52.0.tar.gz retains the complete pinned upstream source, including Bifrost and embedded source-header notices.\n'
                       'Bifrost-BSD-2-Clause.txt covers Bifrost; CRoaring-LICENSE.txt covers the embedded CRoaring 0.2.52 implementation.\n'
                       'Bifrost embedded zstr and wyhash notices remain in their source headers within the source archive.\n'
                       'CRoaring private-inline linkage and Bifrost aligned-allocation/free changes are identified in MODIFICATIONS.txt and workbench1.patch.\n'
                       'Workbench-MIT-LICENSE.txt covers the Workbench adapters and build/preparation scripts.\n')
    else:
        raise ValueError('Unknown RNA pack: ' + pack_id)
    (licenses / 'THIRD-PARTY.txt').write_text(description, encoding='utf-8')
    record = {'schema': 1, 'pack': pack_id, 'noticesAndHelperRecords': records,
              'note': 'Licence/source record additions only; native execution and scientific validation are recorded separately.'}
    (licenses / 'notice-provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record
