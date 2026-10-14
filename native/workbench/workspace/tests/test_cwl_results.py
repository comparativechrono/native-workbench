"""CWL evidence in real Engine result folders, using a synthetic backend."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import load_catalog
from cwl_export import definition_sha256
from engine import Engine, pin_for
from test_pack_versions import make_pack, RecordingBackend


class CWLResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workbench-cwl-results-')
        self.root = Path(self.tmp.name)
        self.old_folder = make_pack(self.root, '1.0.0')
        make_pack(self.root, '2.0.0')
        catalog = load_catalog(self.root)
        new, old = catalog['toolVersions']['example/process']
        source = self.root / 'input.dat'
        source.write_bytes(b'Synthetic input\n')
        self.graph = {'schema': 1, 'name': 'Pinned CWL result', 'sources': [
            {'id': 'input-1', 'type': 'file', 'files': {'source': str(source)}}], 'nodes': [
            {'id': 'step-1', 'tool': 'example/process', 'pin': pin_for(old),
             'params': {'threshold': '3'}, 'inputs': {'source': ['input-1']}},
            {'id': 'step-2', 'tool': 'example/process', 'pin': pin_for(new),
             'params': {'threshold': '8'}, 'inputs': {'source': ['step-1::result']}}]}
        self.backend = RecordingBackend()
        self.engine = Engine(self.root, catalog, backend=self.backend)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, plan, name='workflow.cwl'):
        return json.loads((Path(plan['folder']) / name).read_text(encoding='utf-8'))

    def check_result(self, plan, record, statuses):
        cwl = self.read(plan)
        self.assertEqual(cwl['cwlVersion'], 'v1.2')
        main = cwl['$graph'][0]
        self.assertEqual(main['nw:planSha256'], plan['sha256'])
        self.assertEqual(main['nw:execution']['status'], record['status'])
        outcome = json.loads(main['nw:execution']['recordJson'])
        self.assertEqual([item['status'] for item in outcome['nodes']], statuses)
        self.assertEqual(outcome['outputs'], record['outputs'])
        definition = definition_sha256(cwl)
        self.assertEqual(definition, plan['workflowExport']['definitionSha256'])
        self.assertEqual(definition, record['workflowExport']['definitionSha256'])
        checksum = hashlib.sha256((Path(plan['folder']) / 'workflow.cwl').read_bytes()).hexdigest()
        self.assertEqual(record['workflowExport']['sha256'], checksum)
        self.assertEqual(self.read(plan, 'run.json'), record)
        return cwl

    def test_completed_results_bind_pinned_workflow_and_actual_outcome(self):
        plan = self.engine.prepare(self.graph, self.root)
        before = self.read(plan)
        self.assertEqual(before['$graph'][0]['nw:execution']['status'], 'planned')
        self.assertEqual([node['tool']['packVersion'] for node in plan['nodes']], ['1.0.0', '2.0.0'])
        record = self.engine.execute(plan)
        self.assertTrue(record['success'])
        after = self.check_result(plan, record, ['success', 'success'])
        self.assertEqual(before['$graph'][1:], after['$graph'][1:])
        self.assertEqual(before['$graph'][0]['steps'], after['$graph'][0]['steps'])
        self.assertEqual([request['values']['threshold'] for request in self.backend.requests], ['3', '8'])

    def test_modified_export_rejected_before_backend_or_success_evidence(self):
        for modification in ('command', 'plan-hash', 'source'):
            with self.subTest(modification=modification):
                plan = self.engine.prepare(self.graph, self.root)
                altered = self.read(plan)
                if modification == 'command':
                    altered['$graph'][1]['arguments'] = ['fake-command']
                elif modification == 'plan-hash':
                    altered['$graph'][0]['nw:planSha256'] = '0' * 64
                else:
                    altered['$graph'][0]['inputs']['untracked'] = {'type': 'string', 'default': 'changed'}
                (Path(plan['folder']) / 'workflow.cwl').write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'CWL workflow export'):
                    self.engine.execute(plan)
                self.assertFalse((Path(plan['folder']) / 'run.json').exists())
        self.assertEqual(self.backend.requests, [])

    def test_failed_manifest_check_retains_original_export_and_blocks_descendant(self):
        plan = self.engine.prepare(self.graph, self.root)
        before = self.read(plan)
        with (self.old_folder / 'pack.ini').open('a') as stream:
            stream.write('\n; changed after prepare\n')
        record = self.engine.execute(plan)
        self.assertFalse(record['success'])
        after = self.check_result(plan, record, ['failed', 'blocked'])
        self.assertEqual(before['$graph'][1:], after['$graph'][1:])
        self.assertEqual(self.backend.requests, [])

    def test_cancelled_run_is_not_exported_as_completed_analysis(self):
        plan = self.engine.prepare(self.graph, self.root)
        cancel = threading.Event()
        cancel.set()
        record = self.engine.execute(plan, cancel=cancel)
        self.assertFalse(record['success'])
        self.assertEqual(record['status'], 'cancelled')
        self.check_result(plan, record, ['cancelled', 'cancelled'])
        self.assertEqual(self.backend.requests, [])

    def test_missing_export_cannot_create_success_record(self):
        plan = self.engine.prepare(self.graph, self.root)
        (Path(plan['folder']) / 'workflow.cwl').unlink()
        with self.assertRaises(FileNotFoundError):
            self.engine.execute(plan)
        self.assertEqual(self.backend.requests, [])
        self.assertFalse((Path(plan['folder']) / 'run.json').exists())


if __name__ == '__main__':
    unittest.main()
