"""Kalign-specific evidence scope contracts, not native execution claims."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kalign_gate', ROOT / 'scripts/check_kalign_windows.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
sys.path.insert(0, str(ROOT / 'scripts'))
audit_spec = importlib.util.spec_from_file_location('kalign_archive_audit', ROOT / 'scripts/audit_kalign_candidate.py')
audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)


class KalignEvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self):
        archive = self.root / 'kalign.zip'
        archive.write_bytes(b'exact Kalign payload')
        source = self.root / 'upstream.tar.gz'
        source.write_bytes(b'exact pinned corresponding source')
        inventory = {'schema': 1, 'sourceCommit': 'a' * 40, 'files': [
            {'path': 'corresponding-sources/kalign/upstream.tar.gz', 'bytes': source.stat().st_size,
             'sha256': gate.sha(source)}]}
        companion = self.root / 'source.zip'
        gate.common.zip_files(companion, [('corresponding-sources/kalign/upstream.tar.gz', source)],
                              {'SOURCE-INVENTORY.json': inventory, 'BUILD-PROVENANCE.json': {}})
        record = {'sourceCommit': 'a' * 40, 'packs': {'kalign': {**gate.file_record(archive), 'id': 'kalign', 'version': '1.0.0'}},
                  'sourceCompanion': gate.file_record(companion)}
        gate.write_json(self.root / 'BUILD-PROVENANCE.json', record)
        return record

    def test_kalign_rejects_an_additional_dependency_presented_as_its_build(self):
        record = self.fixture()
        self.assertEqual(gate.common.verify_candidate(self.root, 'a' * 40), record)
        record['packs']['fasttree'] = record['packs']['kalign']
        gate.write_json(self.root / 'BUILD-PROVENANCE.json', record)
        with self.assertRaisesRegex(ValueError, 'source/packs'):
            gate.common.verify_candidate(self.root, 'a' * 40)

    def test_unchanged_pack_identity_requires_exact_frozen_bytes(self):
        record = self.fixture()
        (self.root / record['packs']['kalign']['file']).write_bytes(b'changed Kalign bytes')
        with self.assertRaisesRegex(ValueError, 'artifact differs'):
            gate.common.verify_candidate(self.root, 'a' * 40)

    def test_recheck_cannot_hide_scientific_or_shared_gate_changes(self):
        for name in ('scripts/build_kalign_native.py', 'scripts/prepare_kalign_pack.py',
                     'tools/kalign/guard.cpp', 'tests/test_kalign_pack.py',
                     'scripts/check_prodigal_fasttree_windows.py', 'workspace/catalog.py'):
            self.assertFalse(gate.common.allowed_gate_change(name))
        with mock.patch.object(gate.common.subprocess, 'check_output', side_effect=[
                'b' * 40 + '\n', b'scripts/check_kalign_gui.py\0scripts/build_kalign_native.py\0']):
            with self.assertRaisesRegex(ValueError, 'production or recipe'):
                gate.common.frozen_source_changes('a' * 40, 'b' * 40)

    def test_private_helper_configuration_preserves_existing_gate(self):
        original_spec = importlib.util.spec_from_file_location('original_pack_gate', ROOT / 'scripts/check_prodigal_fasttree_windows.py')
        original = importlib.util.module_from_spec(original_spec)
        original_spec.loader.exec_module(original)
        self.assertEqual(original.PACK_IDS, ('prodigal', 'fasttree'))
        self.assertEqual(gate.common.PACK_IDS, ('kalign',))
        self.assertEqual(gate.common.OPERATIONS, {'kalign': {'align-nucleotide', 'align-protein'}})
        self.assertEqual(gate.FASTTREE['publicationStatus'], 'unpublished merged review candidate')
        self.assertEqual(gate.FASTTREE['sha256'], '4525aa8001b7b190eecbee5a164bb9586ce9f78d8672635df25ae4e462165c20')

    def correspondence_fixture(self):
        paths = {
            'pack/licenses/guard.cpp': 'tools/kalign/guard.cpp',
            'pack/licenses/fixtures.py': 'tools/kalign/fixtures.py',
            'pack/licenses/record_reference.py': 'tools/kalign/record_reference.py',
            'pack/licenses/record_reference.py': 'tools/kalign/record_reference.py',
            'pack/licenses/upstream_windows_compat.h': 'tools/kalign/upstream_windows_compat.h',
            'pack/licenses/build_kalign_native.py': 'scripts/build_kalign_native.py',
            'pack/licenses/prepare_kalign_pack.py': 'scripts/prepare_kalign_pack.py',
            'pack/PACK-README.md': 'docs/KALIGN-PACK.md',
            'pack/licenses/Workbench-LICENSE.txt': 'LICENSE',
        }
        originals = {name: ('source fixture ' + name).encode() for name in paths.values()}
        retained = {name: originals[source] for name, source in paths.items()}
        patch = b'--- a/src/run_kalign.c\n+++ b/src/run_kalign.c\n@@ -1 +1 @@\n-old\n+new\n'
        build = {'platform': 'windows-x86_64', 'executionTestsPerformedByBuild': False,
                 'version': '3.5.1-workbench1', 'upstreamVersion': '3.5.1',
                 'sourceCommit': '3e6de1df29d111c5fa5beb4c4294ef681978fd23',
                 'upstreamCommit': '3e6de1df29d111c5fa5beb4c4294ef681978fd23',
                 'serial': True, 'openmp': False, 'upstreamScientificAlgorithmsUnmodified': True,
                 'upstreamSourceUnmodified': False, 'patchSha256': audit.digest(patch),
                 'guardSourceSha256': audit.digest(originals['tools/kalign/guard.cpp']),
                 'builderSha256': audit.digest(originals['scripts/build_kalign_native.py']),
                 'windowsCompatibilityHeaderSha256': audit.digest(originals['tools/kalign/upstream_windows_compat.h'])}
        retained['pack/licenses/workbench1.patch'] = patch
        return originals, retained, build

    def assert_correspondence_rejected(self, originals, retained, build, message):
        retained['pack/licenses/build-provenance.json'] = json.dumps(build).encode()
        pack = mock.Mock()
        pack.read.side_effect = retained.__getitem__
        with self.assertRaisesRegex(ValueError, message):
            audit.source_correspondence('kalign', pack, originals)

    def test_correspondence_rejects_changed_retained_header(self):
        originals, retained, build = self.correspondence_fixture()
        retained['pack/licenses/upstream_windows_compat.h'] += b'changed'
        self.assert_correspondence_rejected(originals, retained, build, 'retained source differs')

    def test_correspondence_rejects_unbound_compile_inputs(self):
        for field in ('guardSourceSha256', 'builderSha256', 'windowsCompatibilityHeaderSha256'):
            with self.subTest(field=field):
                originals, retained, build = self.correspondence_fixture()
                build[field] = '0' * 64
                self.assert_correspondence_rejected(originals, retained, build, 'Build source differs')

    def test_correspondence_rejects_changed_patch_even_with_updated_inventory(self):
        originals, retained, build = self.correspondence_fixture()
        retained['pack/licenses/workbench1.patch'] += b'changed'
        self.assert_correspondence_rejected(originals, retained, build, 'Build patch identity differs')

    def test_correspondence_rejects_patch_to_scientific_source_with_matching_hash(self):
        originals, retained, build = self.correspondence_fixture()
        patch = retained['pack/licenses/workbench1.patch'].replace(b'src/run_kalign.c', b'lib/src/align.c')
        retained['pack/licenses/workbench1.patch'] = patch
        build['patchSha256'] = audit.digest(patch)
        self.assert_correspondence_rejected(originals, retained, build, 'more than the CLI boundary')


if __name__ == '__main__':
    unittest.main()
