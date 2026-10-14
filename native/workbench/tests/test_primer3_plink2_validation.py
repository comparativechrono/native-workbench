"""Fail-closed batch evidence contracts; these tests do not execute Windows."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('primer3_plink2_gate', ROOT / 'scripts/check_primer3_plink2_windows.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
sys.path.insert(0, str(ROOT / 'scripts'))
audit_spec = importlib.util.spec_from_file_location('primer3_plink2_audit', ROOT / 'scripts/audit_primer3_plink2_candidate.py')
audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)


class Primer3Plink2EvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self):
        packs = {}
        for identity in ('primer3', 'plink2'):
            archive = self.root / (identity + '.zip')
            archive.write_bytes(('exact ' + identity + ' payload').encode())
            packs[identity] = {**gate.file_record(archive), 'id': identity, 'version': '1.0.0'}
        source = self.root / 'upstream.tar.gz'
        source.write_bytes(b'exact corresponding source fixture')
        name = 'corresponding-sources/primer3/upstream.tar.gz'
        inventory = {'schema': 1, 'sourceCommit': 'a' * 40, 'files': [
            {'path': name, 'bytes': source.stat().st_size, 'sha256': gate.sha(source)}]}
        companion = self.root / 'source.zip'
        gate.common.zip_files(companion, [(name, source)],
                              {'SOURCE-INVENTORY.json': inventory, 'BUILD-PROVENANCE.json': {}})
        record = {'sourceCommit': 'a' * 40, 'packs': packs, 'sourceCompanion': gate.file_record(companion)}
        gate.write_json(self.root / 'BUILD-PROVENANCE.json', record)
        return record

    def test_candidate_requires_both_exact_selected_pack_identities(self):
        record = self.fixture()
        self.assertEqual(gate.common.verify_candidate(self.root, 'a' * 40), record)
        for missing in ('primer3', 'plink2'):
            with self.subTest(missing=missing):
                changed = {**record, 'packs': {key: value for key, value in record['packs'].items() if key != missing}}
                gate.write_json(self.root / 'BUILD-PROVENANCE.json', changed)
                with self.assertRaisesRegex(ValueError, 'source/packs'):
                    gate.common.verify_candidate(self.root, 'a' * 40)
        record['packs']['kalign'] = record['packs']['primer3']
        gate.write_json(self.root / 'BUILD-PROVENANCE.json', record)
        with self.assertRaisesRegex(ValueError, 'source/packs'):
            gate.common.verify_candidate(self.root, 'a' * 40)

    def test_each_frozen_pack_requires_exact_bytes(self):
        record = self.fixture()
        for identity in ('primer3', 'plink2'):
            with self.subTest(identity=identity):
                path = self.root / record['packs'][identity]['file']
                original = path.read_bytes()
                path.write_bytes(b'changed candidate bytes')
                with self.assertRaisesRegex(ValueError, 'artifact differs'):
                    gate.common.verify_candidate(self.root, 'a' * 40)
                path.write_bytes(original)

    def test_companion_requires_exact_bytes_and_commit(self):
        record = self.fixture()
        with self.assertRaisesRegex(ValueError, 'source/packs'):
            gate.common.verify_candidate(self.root, 'b' * 40)
        path = self.root / record['sourceCompanion']['file']
        path.write_bytes(path.read_bytes() + b'extra')
        with self.assertRaisesRegex(ValueError, 'artifact differs'):
            gate.common.verify_candidate(self.root, 'a' * 40)

    def test_validator_recheck_cannot_hide_production_or_shared_helper_changes(self):
        for name in ('scripts/build_primer3_native.py', 'scripts/prepare_plink2_pack.py',
                     'tools/primer3/guard.cpp', 'tools/plink2/guard.cpp',
                     'tests/test_primer3_pack.py', 'tests/test_plink2_pack.py',
                     'scripts/check_prodigal_fasttree_windows.py', 'workspace/catalog.py'):
            self.assertFalse(gate.common.allowed_gate_change(name), name)
        with mock.patch.object(gate.common.subprocess, 'check_output', side_effect=[
                'b' * 40 + '\n', b'scripts/check_primer3_plink2_gui.py\0tools/plink2/guard.cpp\0']):
            with self.assertRaisesRegex(ValueError, 'production or recipe'):
                gate.common.frozen_source_changes('a' * 40, 'b' * 40)

    def test_private_helper_configuration_preserves_existing_candidate(self):
        original_spec = importlib.util.spec_from_file_location('original_pack_gate', ROOT / 'scripts/check_prodigal_fasttree_windows.py')
        original = importlib.util.module_from_spec(original_spec)
        original_spec.loader.exec_module(original)
        self.assertEqual(original.PACK_IDS, ('prodigal', 'fasttree'))
        self.assertEqual(gate.PACK_IDS, ('primer3', 'plink2'))
        self.assertEqual(gate.common.OPERATIONS, {'primer3': {'design-pcr'}, 'plink2': {'summarize-vcf'}})
        self.assertEqual(gate.APPLICATIONS, original.APPLICATIONS)

    def test_source_or_skipped_report_cannot_claim_native_science(self):
        passed = {'success': True, 'nativeWindowsExecuted': True, 'testsRun': 2,
                  'skipped': [], 'executions': [{'returncode': 0}]}
        self.assertTrue(gate.scientific_report_passed(passed))
        for field, value in [('success', False), ('nativeWindowsExecuted', False),
                             ('testsRun', 0), ('testsRun', None),
                             ('skipped', [['test_x', 'no executable']]), ('executions', [])]:
            with self.subTest(field=field, value=value):
                self.assertFalse(gate.scientific_report_passed({**passed, field: value}))

    @staticmethod
    def correspondence_fixture(identity):
        paths = {
            'pack/licenses/guard.cpp': 'tools/' + identity + '/guard.cpp',
            'pack/licenses/fixtures.py': 'tools/' + identity + '/fixtures.py',
            'pack/licenses/build_' + identity + '_native.py': 'scripts/build_' + identity + '_native.py',
            'pack/licenses/prepare_' + identity + '_pack.py': 'scripts/prepare_' + identity + '_pack.py',
            'pack/PACK-README.md': 'docs/' + identity.upper() + '-PACK.md',
            'pack/licenses/Workbench-LICENSE.txt': 'LICENSE',
        }
        originals = {name: ('committed fixture ' + name).encode() for name in paths.values()}
        retained = {name: originals[source] for name, source in paths.items()}
        version, commit = audit.UPSTREAM_IDENTITIES[identity]
        build = {'platform': 'windows-x86_64', 'executionTestsPerformedByBuild': False,
                 'version': version, 'upstreamVersion': version, 'sourceCommit': commit,
                 'upstreamCommit': commit, 'upstreamSourceUnmodified': True,
                 'upstreamScientificAlgorithmsUnmodified': True,
                 'builderSha256': audit.digest(originals['scripts/build_' + identity + '_native.py']),
                 'guardSourceSha256': audit.digest(originals['tools/' + identity + '/guard.cpp']),
                 'serial': True, 'openmp': False, 'lapack': False,
                 'compilerNotices': {}, 'files': {}, 'sources': {}}
        # A synthetic PE header exercises the auditor's architecture and stack
        # checks. It is fixture data, not a compiled executable or build claim.
        header = bytearray(256)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 60, 64)
        header[64:68] = b'PE\0\0'
        struct.pack_into('<H', header, 68, 0x8664)
        struct.pack_into('<H', header, 88, 0x20b)
        struct.pack_into('<QQ', header, 160, 8388608, 65536)
        for name in [('primer3_core.exe' if identity == 'primer3' else 'plink2.exe'), identity + '-guard.exe']:
            data = bytes(header) + name.encode()
            retained['pack/bin/' + name] = data
            build['files'][name] = {'bytes': len(data), 'sha256': audit.digest(data)}
        if identity == 'primer3':
            tables = {'dangle.dh': b'known thermodynamic table\n'}
            notices = {'LICENSE': b'GPL fixture', 'src/LICENSE_GPL3_for_Amplicon3': b'GPL3 fixture',
                       'src/amplicontm.c': b'amplicon source notice fixture'}
            members = {**notices, **{'src/primer3_config/' + name: data for name, data in tables.items()}}
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for name, data in members.items():
                    info = tarfile.TarInfo('primer3-' + commit + '/' + name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            retained['pack/licenses/primer3-2.6.1.tar.gz'] = stream.getvalue()
            for name, data in tables.items():
                retained['pack/bin/primer3_config/' + name] = data
            build['configurationFiles'] = {name: audit.digest(data) for name, data in tables.items()}
            retained['pack/licenses/Primer3-GPL-2.0.txt'] = notices['LICENSE']
            retained['pack/licenses/Amplicon3-GPL-3.0.txt'] = notices['src/LICENSE_GPL3_for_Amplicon3']
            retained['pack/licenses/Amplicon3-source-notices.c'] = notices['src/amplicontm.c']
        else:
            for name in audit.UPSTREAM_PINS[identity]:
                retained['pack/licenses/' + name] = ('synthetic upstream fixture ' + name).encode()
        pins = {name: audit.digest(retained['pack/licenses/' + name]) for name in audit.UPSTREAM_PINS[identity]}
        build['sources'] = {name: {'sha256': checksum} for name, checksum in pins.items()}
        return originals, retained, build, pins

    def correspondence(self, identity, originals, retained, build, pins):
        retained['pack/licenses/build-provenance.json'] = json.dumps(build).encode()
        pack = mock.Mock()
        pack.read.side_effect = retained.__getitem__
        pack.namelist.side_effect = lambda: list(retained)
        # Replace only known test archive pins, so all byte/provenance checks run
        # over a tiny self-contained fixture rather than downloaded sources.
        with mock.patch.dict(audit.UPSTREAM_PINS, {identity: pins}):
            return audit.source_correspondence(identity, pack, originals)

    def test_compiled_guard_and_recipe_must_match_the_committed_sources(self):
        for identity in ('primer3', 'plink2'):
            for field in ('guardSourceSha256', 'builderSha256'):
                with self.subTest(identity=identity, field=field):
                    originals, retained, build, pins = self.correspondence_fixture(identity)
                    build[field] = '0' * 64
                    with self.assertRaisesRegex(ValueError, 'Compiled .* provenance differs'):
                        self.correspondence(identity, originals, retained, build, pins)

    def test_retained_guard_cannot_be_changed_to_match_a_different_build(self):
        for identity in ('primer3', 'plink2'):
            with self.subTest(identity=identity):
                originals, retained, build, pins = self.correspondence_fixture(identity)
                retained['pack/licenses/guard.cpp'] += b' changed'
                build['guardSourceSha256'] = audit.digest(retained['pack/licenses/guard.cpp'])
                with self.assertRaisesRegex(ValueError, 'retained source differs from Git'):
                    self.correspondence(identity, originals, retained, build, pins)

    def test_unreviewed_source_pin_is_rejected_even_with_updated_build_hash(self):
        for identity in ('primer3', 'plink2'):
            with self.subTest(identity=identity):
                originals, retained, build, pins = self.correspondence_fixture(identity)
                name = next(iter(pins))
                retained['pack/licenses/' + name] += b' changed upstream bytes'
                build['sources'][name]['sha256'] = audit.digest(retained['pack/licenses/' + name])
                with self.assertRaisesRegex(ValueError, 'Pinned corresponding source changed'):
                    self.correspondence(identity, originals, retained, build, pins)

    def test_unreviewed_upstream_commit_is_rejected(self):
        for identity in ('primer3', 'plink2'):
            with self.subTest(identity=identity):
                originals, retained, build, pins = self.correspondence_fixture(identity)
                build['sourceCommit'] = build['upstreamCommit'] = '0' * 40
                with self.assertRaisesRegex(ValueError, 'Unexpected upstream identity'):
                    self.correspondence(identity, originals, retained, build, pins)

    def test_thermodynamic_runtime_table_cannot_change_with_reinventoried_bytes(self):
        originals, retained, build, pins = self.correspondence_fixture('primer3')
        passed = self.correspondence('primer3', originals, retained, build, pins)
        self.assertEqual(passed['runtimeConfigurationFilesMatchedToUpstream'], 1)
        retained['pack/bin/primer3_config/dangle.dh'] += b' altered parameter\n'
        # The runtime envelope may be rehashed after alteration; the separate
        # source-correspondence check still compares with pinned upstream data.
        with self.assertRaisesRegex(ValueError, 'Changed thermodynamic table'):
            self.correspondence('primer3', originals, retained, build, pins)
        build['configurationFiles']['dangle.dh'] = audit.digest(retained['pack/bin/primer3_config/dangle.dh'])
        with self.assertRaisesRegex(ValueError, 'configuration does not match pinned source'):
            self.correspondence('primer3', originals, retained, build, pins)


if __name__ == '__main__':
    unittest.main()
