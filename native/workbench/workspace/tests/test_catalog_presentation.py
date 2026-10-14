"""Presentation-only scientific tool labels from exact starter manifests."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import _workflow_presentation, describe_workflow, load_pack


class CatalogPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packs = {identity: load_pack(ROOT / 'pack-examples' / (identity + '.ini'))
                     for identity in ('align', 'bam', 'variants')}

    def operation(self, identity):
        pack_id, workflow_id = identity.split('/')
        pack = self.packs[pack_id]
        return describe_workflow(pack, pack['workflows'][workflow_id],
                                 'packs/' + pack_id + '-' + pack['version'], pack['manifestSha256'])

    def test_starter_manifest_bytes_still_match_published_profile(self):
        profile = json.loads((ROOT / 'workspace/starter-check-profile.json').read_text())
        for pin in profile['packs']:
            with self.subTest(pack=pin['id']):
                raw = (ROOT / 'pack-examples' / (pin['id'] + '.ini')).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), pin['manifestSha256'])

    def test_minimap2_is_foregrounded_instead_of_pair_validator(self):
        for identity in ('align/single-end', 'align/paired-end'):
            tool = self.operation(identity)
            self.assertTrue(tool['displayName'].startswith('minimap2 — '))
            self.assertTrue(tool['displayName'].endswith('(SAM)'))
            self.assertNotIn('paircheck', tool['displayName'])
        # Discovery cannot depend on alphabetical executable ordering.
        tool['executables'].reverse()
        _workflow_presentation(tool)
        self.assertEqual(tool['displayName'], 'minimap2 — Paired-end alignment (SAM)')

    def test_sort_conversion_is_discoverable_without_changing_semantics(self):
        tool = self.operation('bam/sort')
        self.assertEqual(tool['displayName'], 'SAMtools — Coordinate sort to BAM (SAM/BAM input)')
        self.assertIn('SAM to BAM', tool['searchTerms'])
        self.assertIn('does not repair mates or mark duplicates', tool['displayDescription'])
        self.assertEqual(tool['name'], 'Coordinate sort')
        self.assertEqual(tool['outputs'][0]['state']['sort'], 'coordinate')
        names = self.operation('bam/name-sort')
        self.assertEqual(names['outputs'][0]['state']['sort'], 'queryname')
        self.assertIn('Name sort to BAM', names['displayName'])

    def test_faidx_is_identified_as_lookup_index_not_alignment_prerequisite(self):
        tool = self.operation('bam/reference-index')
        self.assertEqual(tool['displayName'], 'SAMtools — FASTA lookup index (.fai)')
        self.assertIn('not an aligner index', tool['displayDescription'])
        self.assertIn('not a prerequisite', tool['displayDescription'])
        self.assertEqual(tool['name'], 'Index a reference')
        self.assertEqual(tool['steps'][-1]['args'], ['faidx', '{output:reference}'])

    def test_combined_variant_operation_is_not_mislabelled_as_faidx(self):
        tool = self.operation('variants/call')
        self.assertEqual(tool['displayName'], 'BCFtools — Call variants from a BAM')
        self.assertNotIn('FASTA lookup index', tool['displayName'])
        self.assertNotIn('not a prerequisite', tool['displayDescription'])

    def test_pipe_producer_and_sink_are_named_from_actual_steps(self):
        tool = {'name': 'Align paired reads', 'description': 'Align and encode BAM.',
                'executables': [{'id': 'paircheck'}, {'id': 'samtools'}, {'id': 'bwa'}],
                'ports': [], 'outputs': [{'id': 'bam', 'type': 'bam', 'final': True,
                                         'manifestOutputs': ['bam'], 'files': {'bam': 'alignment.bam'}}],
                'steps': [{'kind': 'exec', 'tool': 'paircheck', 'args': ['--reads1'],
                           'stdout': 'check', 'produces': []},
                          {'kind': 'pipe', 'tool': 'bwa', 'sinkTool': 'samtools',
                           'args': ['mem'], 'sinkArgs': ['view', '-b'], 'stdout': 'bam', 'produces': []}]}
        _workflow_presentation(tool)
        self.assertEqual(tool['displayName'], 'BWA + SAMtools — Align paired reads')

    def test_presentation_preserves_execution_fields_pins_and_existing_branding(self):
        for pack in self.packs.values():
            for workflow in pack['workflows'].values():
                tool = describe_workflow(pack, workflow, 'packs/example', pack['manifestSha256'])
                original = copy.deepcopy(tool)
                _workflow_presentation(tool)
                self.assertEqual(tool, original, 'Presentation must be idempotent and preserve all contract fields')
                self.assertEqual(tool['steps'], workflow['steps'])
                self.assertEqual(tool['name'], workflow['name'])
                self.assertEqual(tool['manifestSha256'], pack['manifestSha256'])
        tool = self.operation('align/single-end')
        tool['name'] = 'minimap2: short-read alignment'
        _workflow_presentation(tool)
        self.assertEqual(tool['displayName'], 'minimap2: short-read alignment (SAM)')


if __name__ == '__main__':
    unittest.main()
