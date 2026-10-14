"""Static deployment evidence: adversarial paths, PE bounds and ownership.

These fixtures establish parser/report behavior, not Windows execution, licence
completeness or publisher trust. Real release-byte inventories run separately.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment_inventory as inventory


def pe_image(*, pe32=False, imports=True):
    """Small PE fixture with headers + .idata; no executable instructions."""
    image = bytearray(2048)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 60, 128)
    image[128:132] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', image, 132, 0x14c if pe32 else 0x8664,
                     1, 0, 0, 0, 224 if pe32 else 240, 0x2022)
    optional = 152
    struct.pack_into('<H', image, optional, 0x10b if pe32 else 0x20b)
    struct.pack_into('<I', image, optional + 60, 512)
    directory = optional + (96 if pe32 else 112)
    struct.pack_into('<I', image, directory - 4, 16)
    if imports:
        struct.pack_into('<II', image, directory + 8, 0x1000, 60)
        struct.pack_into('<IIIII', image, 512, 0x1100, 0, 0, 0x1080, 0x1120)
        struct.pack_into('<IIIII', image, 532, 0x1140, 0, 0, 0x1090, 0x1160)
        image[640:653] = b'KERNEL32.dll\0'
        image[656:669] = b'UCRTBASE.dll\0'
    section = optional + (224 if pe32 else 240)
    image[section:section + 8] = b'.idata\0\0'
    struct.pack_into('<IIII', image, section + 8, 1024, 0x1000, 1024, 512)
    return bytes(image)


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def manifest(root, files=(), **fields):
    value = {'schema_version': 2, 'version': '0.16.0', 'ownership': 'core',
             'files': list(files), **fields}
    put(root, 'manifest.json', json.dumps(value).encode())


class PEParser(unittest.TestCase):
    def parse(self, data):
        return inventory._parse_pe(io.BytesIO(data), len(data))

    def test_x64_import_names_and_certificate_presence_do_not_claim_trust(self):
        image = bytearray(pe_image())
        directory = 152 + 112
        struct.pack_into('<II', image, directory + 4 * 8, 1800, 16)
        struct.pack_into('<II', image, directory + 13 * 8, 0x1200, 32)
        result = inventory._executable(io.BytesIO(image), len(image), 'tool.exe')
        self.assertEqual(result['machine'], 'x86-64')
        self.assertEqual(result['directImports'], ['KERNEL32.dll', 'UCRTBASE.dll'])
        self.assertEqual(result['parseStatus'], 'parsed')
        self.assertTrue(result['certificateTablePresent'])
        self.assertTrue(result['delayImportDirectoryPresent'])
        self.assertEqual(result['signatureStatus'], 'not-checked')
        self.assertNotIn('publisher', result)

    def test_pe32_and_a_valid_empty_import_directory(self):
        result = self.parse(pe_image(pe32=True, imports=False))
        self.assertEqual(result['machine'], 'x86')
        self.assertEqual(result['peKind'], 'PE32')
        self.assertEqual(result['directImports'], [])

    def test_malformed_recognized_images_keep_imports_unknown(self):
        original = pe_image()
        def corrupt(offset, fmt, *values):
            image = bytearray(original)
            struct.pack_into(fmt, image, offset, *values)
            return image
        cases = {
            'truncated-dos': b'MZ',
            'header-outside-file': corrupt(60, '<I', 0xfffffff0),
            'header-overlap': corrupt(60, '<I', 2),
            'section-count': corrupt(134, '<H', 65535),
            'optional-size': corrupt(148, '<H', 65535),
            'optional-magic': corrupt(152, '<H', 0),
            'directory-count': corrupt(260, '<I', 0xffffffff),
            'small-headers': corrupt(212, '<I', 160),
            'section-past-eof': corrupt(392 + 20, '<I', 0xffffffff),
            'section-virtual-overflow': corrupt(392 + 12, '<I', 0xfffffff0),
            'import-unmapped': corrupt(272, '<I', 0x7000),
            'import-truncated': corrupt(276, '<I', 19),
            'import-too-large': corrupt(276, '<I', 1_000_000),
            'import-inconsistent': corrupt(272, '<I', 0),
            'no-null-descriptor': corrupt(276, '<I', 40),
            'dll-name-unmapped': corrupt(524, '<I', 0x8000),
            'dll-name-empty': corrupt(640, '<B', 0),
            'dll-name-control': corrupt(640, '<B', 1),
            'certificate-past-eof': corrupt(296, '<II', 2000, 4096),
        }
        for label, image in cases.items():
            with self.subTest(label=label):
                result = inventory._executable(io.BytesIO(image), len(image), 'tool.dll')
                self.assertEqual(result['parseStatus'], 'error')
                self.assertIsNone(result['directImports'])
                self.assertIn('PE', result['parseError'])
                self.assertEqual(result['signatureStatus'], 'not-checked')

    def test_ambiguous_section_mapping_is_rejected(self):
        image = bytearray(pe_image())
        struct.pack_into('<H', image, 134, 2)
        image[432:472] = image[392:432]
        with self.assertRaisesRegex(inventory.PEError, 'ambiguous'):
            self.parse(image)

    def test_unterminated_import_name_is_bounded(self):
        image = bytearray(pe_image())
        image[640:640 + 513] = b'a' * 513
        with self.assertRaisesRegex(inventory.PEError, 'bounded'):
            self.parse(image)

    def test_non_pe_formats_do_not_invent_dependencies_or_machine(self):
        cases = [('elf', b'\x7fELF', 'ELF'), ('x.exe', b'plain data', 'unknown'),
                 ('run.cmd', b'@echo off', 'script'), ('run', b'#!/bin/sh\n', 'script'),
                 ('x.jar', b'PK\x03\x04', 'Java-archive-candidate'),
                 ('x.class', b'\xca\xfe\xba\xbe', 'fat-Mach-O-or-Java-class'),
                 ('x.wasm', b'\0asm', 'WebAssembly')]
        for name, data, expected in cases:
            with self.subTest(name=name):
                result = inventory._executable(io.BytesIO(data), len(data), name)
                self.assertEqual(result['format'], expected)
                self.assertIsNone(result['directImports'])
                self.assertIsNone(result['machine'])
        self.assertIsNone(inventory._executable(io.BytesIO(b'hello'), 5, 'README.txt'))


class InventoryTree(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.parent = Path(self.temporary.name).resolve()
        self.root = self.parent / 'native-workbench'
        self.root.mkdir()
        manifest(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def report(self):
        return inventory.inventory_tree(self.root, 'starter')

    def pack(self, prefix='packs/align-0.4.0', version='2.28-r1209'):
        tool = put(self.root, prefix + '/bin/minimap2.exe', pe_image())
        descriptor = ('[pack]\nid=align\nname=Read alignment\nversion=0.4.0\nplatform=windows-x86_64\n'
                      '[tool:minimap2]\npath=bin/minimap2.exe\nversion=' + version + '\nsha256=' + tool['sha256'] + '\n')
        put(self.root, prefix + '/pack.ini', descriptor.encode())
        licence = put(self.root, prefix + '/licenses/NOTICE.txt', b'Actual notice bytes\n')
        return tool, licence

    def test_exact_membership_distinguishes_core_private_runtime_and_pack(self):
        ui = put(self.root, 'NativeWorkbench.exe', pe_image())
        runtime = put(self.root, 'runtime/python/python313.dll', pe_image())
        licence = put(self.root, 'LICENSE', b'Application licence bytes')
        source = put(self.root, 'SOURCE-AVAILABILITY.json', b'{"sourceArtifact":{"file":"matching-source.zip"}}')
        tool, pack_licence = self.pack()
        manifest(self.root, [ui, runtime, licence, source])
        result = self.report()
        files = {entry['path']: entry for entry in result['files']}
        self.assertEqual(files[ui['path']]['componentIds'], ['application'])
        self.assertEqual(files[runtime['path']]['componentIds'], ['application', 'private-python-runtime'])
        self.assertEqual(files[tool['path']]['componentIds'], ['pack:packs/align-0.4.0'])
        components = {entry['id']: entry for entry in result['components']}
        pack = components['pack:packs/align-0.4.0']
        self.assertEqual(pack['tools'][0]['version'], '2.28-r1209')
        self.assertEqual(pack['tools'][0]['file']['status'], 'verified')
        self.assertIsNone(components['private-python-runtime']['version'])
        self.assertIsNone(pack['licenceExpression'])
        self.assertEqual(pack['sourceCompleteness'], 'not-assessed')
        self.assertEqual({entry['path'] for entry in result['licenceFiles']}, {licence['path'], pack_licence['path']})
        self.assertEqual(result['sourceAvailabilityFiles'][0]['sha256'], source['sha256'])

    def test_modified_missing_and_unowned_files_are_explicit(self):
        item = put(self.root, 'NativeWorkbench.exe', pe_image())
        missing = put(self.root, 'missing.dll', pe_image())
        wrong_size = put(self.root, 'wrong-size.txt', b'unchanged')
        wrong_size['bytes'] += 1
        manifest(self.root, [item, missing, wrong_size])
        (self.root / item['path']).write_bytes(b'changed')
        (self.root / missing['path']).unlink()
        put(self.root, 'unclaimed.exe', b'unknown executable')
        result = self.report()
        claims = {entry['path']: entry['status'] for entry in result['components'][0]['fileClaims']}
        self.assertEqual(claims, {'NativeWorkbench.exe': 'sha256-mismatch', 'missing.dll': 'missing',
                                  'wrong-size.txt': 'size-mismatch'})
        self.assertIn({'path': 'unclaimed.exe', 'field': 'component', 'status': 'unknown'}, result['unknowns'])

    def test_missing_metadata_does_not_infer_versions_licences_or_complete_sources(self):
        manifest(self.root, version=None)
        put(self.root, 'runtime/python/python313.dll', pe_image())
        result = self.report()
        self.assertTrue(all(entry['version'] is None for entry in result['components']))
        self.assertEqual(result['licenceFiles'], [])
        self.assertEqual(result['sourceAvailabilityFiles'], [])
        self.assertIn({'field': 'licenceFiles', 'status': 'none-observed'}, result['unknowns'])

    def test_app_core_cannot_take_pack_or_user_ownership(self):
        for name in ('packs/align-0.4.0/tool.exe', 'user-data/notes.txt', 'results/private.txt'):
            with self.subTest(path=name):
                manifest(self.root, [{'path': name, 'sha256': '0' * 64}])
                with self.assertRaisesRegex(inventory.InventoryError, 'independent pack/user'):
                    self.report()

    def test_descriptor_traversal_and_windows_aliases_never_read_external_files(self):
        names = ('../outside.txt', '/etc/passwd', 'C:/private.txt', 'folder\\private.txt',
                 'folder/../outside', 'folder//file', 'file:stream', 'CON', 'dir/nul.txt', 'tail. ')
        for name in names:
            with self.subTest(path=name):
                manifest(self.root, [{'path': name, 'sha256': '0' * 64}])
                with self.assertRaisesRegex(inventory.InventoryError, 'relative path'):
                    self.report()
        manifest(self.root)
        put(self.root, 'packs/escape/pack.ini', b'[pack]\nid=escape\n[tool:escape]\npath=../../outside.txt\n')
        with self.assertRaisesRegex(inventory.InventoryError, 'relative path'):
            self.report()

    def test_duplicate_claim_and_duplicate_json_key_are_rejected(self):
        claim = put(self.root, 'file.txt', b'bytes')
        manifest(self.root, [claim, claim])
        with self.assertRaisesRegex(inventory.InventoryError, 'Duplicate application'):
            self.report()
        (self.root / 'manifest.json').write_text('{"files": [], "files": []}')
        with self.assertRaisesRegex(inventory.InventoryError, 'Malformed JSON'):
            self.report()

    def test_output_is_identical_after_relocation_and_contains_no_absolute_root(self):
        tool, _ = self.pack()
        manifest(self.root, [put(self.root, 'NativeWorkbench.exe', pe_image())])
        before = self.report()
        relocated = self.parent / 'Folder With Spaces'
        shutil.copytree(self.root, relocated)
        self.assertEqual(before, inventory.inventory_tree(relocated, 'starter'))
        serialized = json.dumps(before)
        self.assertNotIn(str(self.parent), serialized)
        self.assertNotIn('createdUtc', before)
        self.assertEqual([entry['path'] for entry in before['files']], sorted(entry['path'] for entry in before['files']))

    def test_only_fresh_recognized_roots_are_accepted(self):
        empty = self.parent / 'unrelated'
        empty.mkdir()
        with self.assertRaisesRegex(inventory.InventoryError, 'extraction root'):
            inventory.inventory_tree(empty, 'starter')
        for folder in ('user-data', 'results', 'references', 'updates'):
            (self.root / folder).mkdir()
            with self.subTest(folder=folder), self.assertRaisesRegex(inventory.InventoryError, 'fresh extraction'):
                self.report()
            (self.root / folder).rmdir()

    def test_symlink_file_directory_root_and_ancestor_are_rejected(self):
        outside = self.parent / 'outside'
        outside.mkdir()
        (outside / 'private.txt').write_text('private content must not be read')
        target = self.root / 'linked'
        try:
            target.symlink_to(outside / 'private.txt')
        except OSError as error:
            self.skipTest('Symbolic link creation unavailable: ' + type(error).__name__)
        with self.assertRaisesRegex(inventory.InventoryError, 'Link or reparse'):
            self.report()
        target.unlink()
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(inventory.InventoryError, 'Link or reparse'):
            self.report()
        target.unlink()
        alias = self.parent / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(inventory.InventoryError, 'Link or reparse'):
            inventory.inventory_tree(alias, 'starter')
        nested = self.root / 'nested'
        nested.mkdir()
        manifest(nested)
        with self.assertRaisesRegex(inventory.InventoryError, 'Link or reparse'):
            inventory.inventory_tree(alias / 'nested', 'starter')

    def test_reparse_attribute_is_rejected_even_without_symlink_mode(self):
        original = Path.lstat
        selected = self.root / 'reparse.exe'
        selected.write_bytes(b'bytes')
        class ReparseStat:
            st_mode = stat.S_IFREG | 0o644
            st_file_attributes = 0x400
        def inspect(path):
            return ReparseStat() if path == selected else original(path)
        with patch.object(Path, 'lstat', inspect), self.assertRaisesRegex(inventory.InventoryError, 'Link or reparse'):
            self.report()

    @unittest.skipUnless(hasattr(__import__('os'), 'mkfifo'), 'Named-pipe fixture requires POSIX')
    def test_special_file_is_rejected_without_blocking_open(self):
        import os
        os.mkfifo(self.root / 'not-a-regular-file')
        with self.assertRaisesRegex(inventory.InventoryError, 'Special file'):
            self.report()

    def test_case_collisions_and_ambiguous_disk_names_are_rejected(self):
        put(self.root, 'A.txt', b'first')
        if (self.root / 'a.txt').exists():
            self.skipTest('Case-collision fixture requires a case-sensitive filesystem')
        put(self.root, 'a.txt', b'second')
        with self.assertRaisesRegex(inventory.InventoryError, 'collision'):
            self.report()
        (self.root / 'a.txt').unlink()
        if sys.platform != 'win32':
            put(self.root, 'CON', b'bad Windows name')
            with self.assertRaisesRegex(inventory.InventoryError, 'ambiguous'):
                self.report()

    def test_changed_open_file_and_oversized_metadata_are_rejected(self):
        original = inventory._executable
        put(self.root, 'NativeWorkbench.exe', pe_image())
        def mutate(stream, size, name):
            result = original(stream, size, name)
            if name == 'NativeWorkbench.exe':
                with (self.root / name).open('ab') as changed:
                    changed.write(b'x')
            return result
        with patch.object(inventory, '_executable', mutate), self.assertRaisesRegex(inventory.InventoryError, 'changed during'):
            self.report()
        with patch.object(inventory, 'MAX_METADATA_BYTES', 8), self.assertRaisesRegex(inventory.InventoryError, 'metadata byte limit'):
            self.report()

    def test_entry_and_depth_bounds_are_enforced(self):
        put(self.root, 'a/b/c.txt', b'file')
        with patch.object(inventory, 'MAX_DEPTH', 1), self.assertRaisesRegex(inventory.InventoryError, 'depth limit'):
            self.report()
        with patch.object(inventory, 'MAX_FILES', 2), self.assertRaisesRegex(inventory.InventoryError, 'entry limit'):
            self.report()

    def test_updater_blob_destinations_keep_original_hashes_and_notice_identity(self):
        (self.root / 'manifest.json').unlink()
        operations, entries = [], []
        payloads = [('NativeWorkbench.exe', pe_image()), ('workspace/helper.py', b'print("fixture")'),
                    ('SOURCE-AVAILABILITY.json', b'{"sourceArtifact": {"file": "source.zip"}}'),
                    ('LICENSE', b'actual licence material')]
        for destination, raw in payloads:
            digest = hashlib.sha256(raw).hexdigest()
            entries.append(put(self.root, 'update/blobs/' + digest, raw))
            operations.append({'path': destination, 'bytes': len(raw), 'sha256': digest, 'blob': digest})
        recipe = {'kind': 'native-core-update', 'base_version': '0.11.0', 'target_version': '0.16.0',
                  'operations': operations}
        entries.append(put(self.root, 'update/update-manifest.json', json.dumps(recipe).encode()))
        put(self.root, 'update-inventory.json', json.dumps({'schema': 1, 'files': entries}).encode())
        result = inventory.inventory_tree(self.root, 'updater')
        component = result['components'][0]
        self.assertEqual((component['baseVersion'], component['version']), ('0.11.0', '0.16.0'))
        self.assertTrue(all(entry['status'] == 'verified' for entry in component['fileClaims']))
        by_destination = {entry['destinations'][0]: entry for entry in result['executables']}
        self.assertEqual(by_destination['NativeWorkbench.exe']['directImports'], ['KERNEL32.dll', 'UCRTBASE.dll'])
        self.assertEqual(by_destination['workspace/helper.py']['format'], 'script')
        self.assertEqual(result['licenceFiles'][0]['destinations'], ['LICENSE'])
        self.assertEqual(result['sourceAvailabilityFiles'][0]['destinations'], ['SOURCE-AVAILABILITY.json'])
        self.assertTrue(result['sourceAvailabilityFiles'][0]['path'].startswith('update/blobs/'))

    def test_updater_cannot_point_blobs_outside_root_or_update_packs(self):
        (self.root / 'manifest.json').unlink()
        put(self.root, 'update-inventory.json', b'{"files": []}')
        for destination, blob in [('core.py', '../../outside'), ('packs/align/tool.exe', '0' * 64),
                                  ('../outside', '0' * 64)]:
            put(self.root, 'update/update-manifest.json', json.dumps({'operations': [{'path': destination, 'blob': blob}]}).encode())
            with self.subTest(destination=destination, blob=blob), self.assertRaises(inventory.InventoryError):
                inventory.inventory_tree(self.root, 'updater')

    def test_pack_archive_envelope_keeps_separate_observed_execution_descriptor(self):
        (self.root / 'manifest.json').unlink()
        tool, _ = self.pack(prefix='pack')
        raw = (self.root / 'pack/pack.ini').read_bytes()
        envelope = {'schema': 1, 'id': 'align', 'version': '0.4.0', 'minAppVersion': '0.16.0',
                    'manifestSha256': hashlib.sha256(raw).hexdigest(),
                    'files': [{**tool, 'path': 'bin/minimap2.exe'}]}
        put(self.root, 'workbench-pack.json', json.dumps(envelope).encode())
        result = inventory.inventory_tree(self.root, 'additional-pack')
        components = {entry['id']: entry for entry in result['components']}
        self.assertEqual(components['pack-envelope']['manifestClaim']['status'], 'verified')
        self.assertEqual(components['pack:pack']['tools'][0]['version'], '2.28-r1209')
        self.assertEqual(components['pack-envelope']['fileClaims'][0]['status'], 'verified')
        envelope['files'][0]['path'] = '../outside'
        put(self.root, 'workbench-pack.json', json.dumps(envelope).encode())
        with self.assertRaisesRegex(inventory.InventoryError, 'relative path'):
            inventory.inventory_tree(self.root, 'additional-pack')


if __name__ == '__main__':
    unittest.main()
