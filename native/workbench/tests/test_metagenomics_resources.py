"""Strict local resource contracts; synthetic bytes, no scientific execution."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('metagenomics_resources', ROOT / 'tools/metagenomics/resources.py')
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)


class ResourceContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='metagenomics contract ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'external database'
        self.database.mkdir()
        for name in resources.DATABASE_FILES:
            (self.database / name).write_bytes(('synthetic non-scientific ' + name).encode())
        self.distribution = self.database / 'database150mers.kmer_distrib'
        self.distribution.write_text('synthetic distribution bytes\n', encoding='utf-8')
        self.descriptor = self.root / 'database.json'
        self.source = {'description': 'Synthetic contract fixture, not a real taxonomic database',
                       'url': '', 'release': 'test-v1'}
        self.resource = resources.register_database(
            self.database / 'hash.k2d', self.descriptor, label='Test resource',
            source_description=self.source['description'], source_url='', source_release='test-v1',
            kmer_length=35, minimizer_length=31, distributions=[self.distribution], attest_distributions=True)
        self.report = self.root / 'classification.kreport'
        self.report.write_bytes(b'100.00\t2\t2\tU\t0\tunclassified\n')
        self.classification = self.root / 'classification.json'
        self.classification_document = {
            'schema': 1, 'kind': resources.CLASSIFICATION_KIND, 'success': True,
            'databaseFingerprint': self.resource['document']['databaseFingerprint'],
            'report': {'path': self.report.name, 'format': 'kraken2-six-column', **resources.file_record(self.report)},
            'classifier': {'name': 'Kraken2', 'version': '2.17.1', 'confidence': 0,
                           'minimumHitGroups': 2, 'minimumBaseQuality': 0, 'quick': False},
            'reads': {'paired': True, 'unit': 'fragments', 'fragments': 2, 'reads': 4,
                      'bases': 600, 'classifiedFragments': 0, 'unclassifiedFragments': 2,
                      'mate1': {'records': 2, 'bases': 300, 'minLength': 150, 'maxLength': 150},
                      'mate2': {'records': 2, 'bases': 300, 'minLength': 150, 'maxLength': 150}}}
        resources.write_json(self.classification, self.classification_document)

    def rewrite(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_01_registration_does_not_modify_or_copy_indexes(self):
        before = {p.name: resources.file_record(p) for p in self.database.iterdir()}
        checked = resources.validate_resource(self.descriptor, verify_database=True)
        after = {p.name: resources.file_record(p) for p in self.database.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(checked['paths']['hash.k2d'], self.database / 'hash.k2d')
        self.assertEqual(set(p.name for p in self.root.iterdir()),
                         {'external database', 'database.json', 'classification.json', 'classification.kreport'})
        choice = resources.choose_distribution(checked, 150)
        self.assertEqual(choice['path'], self.distribution)
        self.assertEqual(choice['document']['association'], 'user-attested-external')

    def test_02_large_unused_indexes_need_not_be_present_for_bracken(self):
        for name in resources.DATABASE_FILES:
            (self.database / name).unlink()
        resource = resources.validate_resource(self.descriptor)
        resources.validate_classification(self.classification, resource)
        resources.choose_distribution(resource, 150)
        with self.assertRaises(resources.ResourceError):
            resources.validate_resource(self.descriptor, verify_database=True)
        actual_lstat = Path.lstat
        def no_unused_database_stat(path, *args, **kwargs):
            if path == self.database or self.database in path.parents:
                raise AssertionError('Bracken descriptor validation touched an unused database path')
            return actual_lstat(path, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', no_unused_database_stat):
            resources.validate_resource(self.descriptor, verify_database=False)

    def test_03_changed_consumed_file_is_rejected(self):
        for target, operation in [
            (self.database / 'hash.k2d', lambda: resources.validate_resource(self.descriptor, True)),
            (self.distribution, lambda: resources.choose_distribution(self.resource, 150)),
            (self.report, lambda: resources.validate_classification(self.classification, self.resource)),
        ]:
            old = target.read_bytes()
            target.write_bytes(bytes([old[0] ^ 1]) + old[1:])
            with self.assertRaisesRegex(resources.ResourceError, 'checksum changed'):
                operation()
            target.write_bytes(old)

    def test_04_relocation_keeps_database_identity(self):
        relocated = self.root / 'relocated'
        shutil.copytree(self.database, relocated)
        doc = copy.deepcopy(self.resource['document'])
        doc['databaseRoot'] = '.'
        doc['brackenDistributions'][0]['path'] = self.distribution.name
        path = relocated / 'resource.json'
        resources.write_json(path, doc)
        checked = resources.validate_resource(path, True)
        self.assertEqual(checked['document']['databaseFingerprint'], self.resource['document']['databaseFingerprint'])
        self.assertEqual(resources.choose_distribution(checked, 150)['path'], relocated / self.distribution.name)

    def test_05_duplicate_unknown_nonfinite_and_boolean_fields_rejected(self):
        original = self.descriptor.read_bytes()
        with self.descriptor.open('wb') as stream:
            stream.truncate(resources.MAX_JSON_BYTES + 1)
        with mock.patch.object(resources, 'file_record', side_effect=AssertionError('Oversized JSON was hashed')):
            with self.assertRaisesRegex(resources.ResourceError, 'at most 4 MiB'):
                resources.validate_resource(self.descriptor)
        bad_json = [original.replace(b'"schema": 1,', b'"schema": 1, "schema": 1,', 1),
                    original.replace(b'"schema": 1', b'"schema": true', 1)]
        for data in bad_json:
            self.descriptor.write_bytes(data)
            with self.assertRaises(resources.ResourceError):
                resources.validate_resource(self.descriptor)
        for change in ({'unreviewed': 1}, {'kmerLength': True}):
            doc = copy.deepcopy(self.resource['document'])
            doc.update(change)
            self.rewrite(self.descriptor, doc)
            with self.assertRaises(resources.ResourceError):
                resources.validate_resource(self.descriptor)
        doc = copy.deepcopy(self.resource['document'])
        doc['brackenDistributions'][0]['classifierSettings']['confidence'] = float('nan')
        self.rewrite(self.descriptor, doc)
        with self.assertRaises(resources.ResourceError):
            resources.validate_resource(self.descriptor)

    def test_06_traversal_wrong_database_and_missing_length_rejected(self):
        for bad in ('../external database', 'nested/../database', 'C:relative', 'CON', 'bad\\path'):
            doc = copy.deepcopy(self.resource['document'])
            doc['databaseRoot'] = bad
            self.rewrite(self.descriptor, doc)
            with self.assertRaises(resources.ResourceError):
                resources.validate_resource(self.descriptor)
        with self.assertRaisesRegex(resources.ResourceError, 'No registered'):
            resources.choose_distribution(self.resource, 100)
        doc = copy.deepcopy(self.classification_document)
        doc['databaseFingerprint'] = '0' * 64
        self.rewrite(self.classification, doc)
        with self.assertRaisesRegex(resources.ResourceError, 'different Kraken2'):
            resources.validate_classification(self.classification, self.resource)

    def test_07_fragment_counts_no_hit_and_single_units(self):
        checked = resources.validate_classification(self.classification, self.resource)
        self.assertEqual(checked['document']['reads']['classifiedFragments'], 0)
        for key, value in [('unit', 'reads'), ('reads', 2), ('bases', 300), ('classifiedFragments', 1)]:
            doc = copy.deepcopy(self.classification_document)
            doc['reads'][key] = value
            self.rewrite(self.classification, doc)
            with self.assertRaises(resources.ResourceError):
                resources.validate_classification(self.classification, self.resource)
        doc = copy.deepcopy(self.classification_document)
        doc['reads'].update(paired=False, unit='reads', reads=2, bases=300, mate2=None)
        self.rewrite(self.classification, doc)
        resources.validate_classification(self.classification, self.resource)

    def test_08_report_must_be_ordinary_sibling_and_reparse_is_rejected(self):
        for target in ('../classification.kreport', str(self.report), 'folder/report.txt'):
            doc = copy.deepcopy(self.classification_document)
            doc['report']['path'] = target
            self.rewrite(self.classification, doc)
            with self.assertRaises(resources.ResourceError):
                resources.validate_classification(self.classification, self.resource)
        with self.assertRaises(resources.ResourceError):
            resources.file_record(self.database)
        real_lstat = Path.lstat
        def mocked_lstat(path, *args, **kwargs):
            if path == self.report:
                return types.SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
            return real_lstat(path, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', mocked_lstat):
            with self.assertRaisesRegex(resources.ResourceError, 'reparse'):
                resources.file_record(self.report)

    def test_09_external_distributions_require_explicit_attestation(self):
        # A missing declaration must fail before scanning a large database.
        with mock.patch.object(resources, 'file_record', side_effect=AssertionError('Premature large-file hashing')):
            with self.assertRaisesRegex(resources.ResourceError, 'Confirm the distributions'):
                resources.register_database(self.database / 'hash.k2d', self.root / 'unattested.json',
                    label='test', source_description='test', source_url='', source_release='test',
                    kmer_length=35, minimizer_length=31, distributions=[self.distribution])
            with self.assertRaisesRegex(resources.ResourceError, 'Database label'):
                resources.register_database(self.database / 'hash.k2d', self.root / 'invalid-label.json',
                    label='', source_description='test', source_url='', source_release='test',
                    kmer_length=35, minimizer_length=31)
        self.assertFalse((self.root / 'unattested.json').exists())
        doc = copy.deepcopy(self.resource['document'])
        doc['brackenDistributions'].append(copy.deepcopy(doc['brackenDistributions'][0]))
        self.rewrite(self.descriptor, doc)
        with self.assertRaisesRegex(resources.ResourceError, 'Repeated Bracken'):
            resources.validate_resource(self.descriptor)

    def archive(self, members, name='database.tar', gz=False):
        path = self.root / name
        with tarfile.open(path, 'w:gz' if gz else 'w') as output:
            for name, data, kind in members:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.size = len(data) if kind in (tarfile.REGTYPE, tarfile.XHDTYPE) else 0
                if kind == tarfile.SYMTYPE:
                    member.linkname = '../outside'
                output.addfile(member, io.BytesIO(data) if member.size else None)
        return path

    def normal_members(self, prefix='db/'):
        return [(prefix + name, (self.database / name).read_bytes(), tarfile.REGTYPE)
                for name in (*resources.DATABASE_FILES, self.distribution.name)]

    def test_10_stream_archive_extracts_selected_files_and_records_original(self):
        members = self.normal_members() + [('db/README.txt', b'ignored ancillary member', tarfile.REGTYPE)]
        archive = self.archive(members, name='database.tar.gz', gz=True)
        result = resources.extract_database_archive(archive, self.root, include_distributions=True)
        self.assertEqual({p.name for p in result['root'].iterdir()}, set(resources.DATABASE_FILES) | {self.distribution.name})
        for path in result['root'].iterdir():
            self.assertEqual(path.read_bytes(), (self.database / path.name).read_bytes())
        self.assertEqual(result['archive'], {'name': archive.name, **resources.file_record(archive)})
        self.assertEqual(result['anchor'], result['root'] / 'hash.k2d')

    def test_11_archive_links_traversal_collisions_prefix_and_missing_rejected_with_cleanup(self):
        bad_cases = [
            self.normal_members() + [('link', b'', tarfile.SYMTYPE)],
            self.normal_members() + [('../outside', b'bad', tarfile.REGTYPE)],
            self.normal_members() + [('db/HASH.k2d', b'duplicate', tarfile.REGTYPE)],
            self.normal_members() + [('other/database100mers.kmer_distrib', b'wrong prefix', tarfile.REGTYPE)],
            self.normal_members()[:2],
            self.normal_members() + [('fifo', b'', tarfile.FIFOTYPE)],
        ]
        preserved = self.root / 'preserve.txt'
        preserved.write_text('existing user file', encoding='utf-8')
        for index, members in enumerate(bad_cases):
            archive = self.archive(members, name='bad-' + str(index) + '.tar')
            with self.assertRaises(resources.ResourceError):
                resources.extract_database_archive(archive, self.root, include_distributions=True)
            self.assertEqual(list(self.root.glob('database-resource-*')), [])
            self.assertEqual(preserved.read_text(encoding='utf-8'), 'existing user file')

    def test_12_archive_disk_budget_checked_before_write(self):
        archive = self.archive(self.normal_members())
        with mock.patch.object(resources.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=0)):
            with self.assertRaisesRegex(resources.ResourceError, 'Insufficient free disk'):
                resources.extract_database_archive(archive, self.root)
        self.assertEqual(list(self.root.glob('database-resource-*')), [])

    def test_13_archive_oversized_extension_header_is_rejected(self):
        archive = self.archive([('pax', b'x' * (1024 * 1024 + 1), tarfile.XHDTYPE)] + self.normal_members())
        with self.assertRaisesRegex(resources.ResourceError, 'extension header'):
            resources.extract_database_archive(archive, self.root)
        self.assertEqual(list(self.root.glob('database-resource-*')), [])

    def test_14_corrupt_and_truncated_gzip_trailers_fail_with_cleanup(self):
        archive = self.archive(self.normal_members(), name='original.tar.gz', gz=True)
        data = archive.read_bytes()
        broken = [data[:-8], data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]]
        for index, payload in enumerate(broken):
            path = self.root / ('bad-gzip-' + str(index) + '.tar.gz')
            path.write_bytes(payload)
            with self.assertRaisesRegex(resources.ResourceError, 'download is complete'):
                resources.extract_database_archive(path, self.root)
            self.assertEqual(list(self.root.glob('database-resource-*')), [])

    def test_15_gnu_and_pax_sparse_parsers_are_rejected_before_reading_maps(self):
        archive = self.archive([('sparse', b'', tarfile.GNUTYPE_SPARSE)] + self.normal_members())
        with self.assertRaisesRegex(resources.ResourceError, 'sparse'):
            resources.extract_database_archive(archive, self.root)
        for index, sparse_headers in enumerate([
            {'GNU.sparse.map': '0,10'}, {'GNU.sparse.size': '10'},
            {'GNU.sparse.major': '1', 'GNU.sparse.minor': '0'},
        ]):
            path = self.root / ('pax-sparse-' + str(index) + '.tar')
            with tarfile.open(path, 'w', format=tarfile.PAX_FORMAT) as output:
                member = tarfile.TarInfo('sparse')
                member.size = 1
                member.pax_headers = sparse_headers
                output.addfile(member, io.BytesIO(b'x'))
            with self.assertRaisesRegex(resources.ResourceError, 'sparse'):
                resources.extract_database_archive(path, self.root)
            self.assertEqual(list(self.root.glob('database-resource-*')), [])

    def test_16_nested_extension_headers_are_bounded_before_recursive_parse(self):
        nested = [('pax-' + str(index), b'', tarfile.XHDTYPE) for index in range(33)]
        archive = self.archive(nested + self.normal_members())
        with self.assertRaisesRegex(resources.ResourceError, 'nested too deeply'):
            resources.extract_database_archive(archive, self.root)
        self.assertEqual(list(self.root.glob('database-resource-*')), [])

    def test_17_classification_only_extracts_no_models_but_rejects_unsafe_skipped_members(self):
        archive = self.archive(self.normal_members())
        result = resources.extract_database_archive(archive, self.root)
        self.assertEqual({path.name for path in result['root'].iterdir()}, set(resources.DATABASE_FILES))
        self.assertEqual(result['distributions'], [])
        self.assertFalse((result['root'] / self.distribution.name).exists())
        shutil.rmtree(result['root'])
        for index, extra in enumerate([
            ('../database100mers.kmer_distrib', b'unsafe', tarfile.REGTYPE),
            ('db/database100mers.kmer_distrib', b'', tarfile.SYMTYPE),
        ]):
            bad = self.archive(self.normal_members() + [extra], name='unsafe-skipped-' + str(index) + '.tar')
            with self.assertRaises(resources.ResourceError):
                resources.extract_database_archive(bad, self.root, include_distributions=False)
            self.assertEqual(list(self.root.glob('database-resource-*')), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
