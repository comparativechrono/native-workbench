"""Real local recovery receipts and deterministic synthetic scheduler execution.

No synthetic backend result is a native scientific validation claim.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import execution_resources
import recovery
from catalog import load_catalog
from test_pack_versions import make_pack


class Backend:
    def __init__(self):
        self.requests = []
        self.failed = set()
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0
        self.overlap = threading.Event()
        self.wait_for_overlap = False
        self.cancel_after_overlap = False

    def run(self, request, event, cancel):
        identity = Path(request['output_folder']).name
        with self.lock:
            self.requests.append(copy.deepcopy(request))
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            if self.active == 2:
                self.overlap.set()
        try:
            if self.wait_for_overlap:
                self.overlap.wait(2)
                if self.cancel_after_overlap:
                    cancel.set()
            if cancel.is_set():
                return {'success': False, 'cancelled': True}
            if identity in self.failed:
                return {'success': False, 'message': 'Synthetic failed step.'}
            path = Path(request['output_folder']) / 'result.dat'
            path.write_bytes(Path(request['values']['source']).read_bytes() + ('|' + request['values']['threshold']).encode())
            return {'success': True, 'folder': request['output_folder']}
        finally:
            with self.lock:
                self.active -= 1


class RecoveryExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nw-recovery-')
        self.root = Path(self.temp.name)
        make_pack(self.root, '1.0.0')
        self.source = self.root / 'one.dat'; self.source.write_bytes(b'one')
        self.other = self.root / 'two.dat'; self.other.write_bytes(b'two')
        self.backend = Backend()
        self.engine = engine.Engine(self.root, load_catalog(self.root), self.backend)
        self.cpu_patch = patch.object(execution_resources.os, 'cpu_count', return_value=4)
        self.cpu_patch.start()

    def tearDown(self):
        self.cpu_patch.stop()
        self.temp.cleanup()

    def graph(self):
        return {'schema': 1, 'name': 'Restart fixture', 'sources': [
            {'id': 'input-1', 'type': 'file', 'files': {'source': str(self.source)}},
            {'id': 'input-2', 'type': 'file', 'files': {'source': str(self.other)}}], 'nodes': [
            {'id': 'step-1', 'tool': 'example/process', 'params': {}, 'inputs': {'source': ['input-1']}},
            {'id': 'step-2', 'tool': 'example/process', 'params': {}, 'inputs': {'source': ['step-1::result']}},
            {'id': 'step-3', 'tool': 'example/process', 'params': {}, 'inputs': {'source': ['input-2']}}]}

    def completed(self):
        plan = self.engine.prepare(self.graph(), self.root)
        record = self.engine.execute(plan)
        self.assertTrue(record['success'], record)
        return plan, record

    def actions(self, review):
        return {item['id']: item['action'] for item in review['nodes']}

    def project(self):
        return {'schema': 1, 'id': 'c' * 32, 'manifestSha256': 'd' * 64,
                'referencesAreHistorical': True, 'sampleMetadata': {'description': 'Synthetic imported context'},
                'validationTools': {}, 'dependencies': [
                    {'id': 'data-' + str(index).zfill(6), 'bytes': path.stat().st_size,
                     'sha256': engine.digest_file(path), 'boundPath': str(path),
                     'references': {'source': 'Synthetic historical receipt, not authenticated'}}
                    for index, path in enumerate((self.source, self.other), 1)]}

    def test_complete_restart_copies_bytes_preserves_old_files_and_records_truth(self):
        plan, record = self.completed()
        old = Path(plan['folder'])
        before = {path.relative_to(old): path.read_bytes() for path in old.rglob('*') if path.is_file()}
        review = self.engine.review_restart(plan['graph'], old)
        self.assertEqual(set(self.actions(review).values()), {'reuse'})
        second = self.engine.prepare(plan['graph'], self.root, restart_from=review)
        self.backend.requests.clear()
        reused = self.engine.execute(second)
        self.assertTrue(reused['success'], reused)
        self.assertEqual(self.backend.requests, [])
        self.assertNotEqual(second['folder'], plan['folder'])
        for ref, output in reused['outputs'].items():
            self.assertEqual(output['sha256'], record['outputs'][ref]['sha256'])
            self.assertTrue(all(Path(path).is_relative_to(second['folder']) for path in output['files'].values()))
        self.assertEqual(before, {path.relative_to(old): path.read_bytes() for path in old.rglob('*') if path.is_file()})
        self.assertEqual([item['recovery']['action'] for item in reused['nodes']], ['reused'] * 3)
        self.assertIn('scientific command was not run', reused['methods'])
        metrics = json.loads((Path(second['folder']) / 'performance.json').read_text())
        self.assertTrue(all(item['backendMetrics']['reason'] == 'completed_step_reused_without_native_command' for item in metrics['steps']))
        cwl = json.loads((Path(second['folder']) / 'workflow.cwl').read_text())
        self.assertIn('nw:recovery', cwl['$graph'][0])
        self.assertTrue(cwl['$graph'][0]['steps'], 'CWL retains a complete independent replay definition')

    def test_changed_input_invalidates_its_branch_and_preserves_independent_step(self):
        plan, _ = self.completed(); self.source.write_bytes(b'changed')
        review = self.engine.review_restart(plan['graph'], plan['folder'])
        self.assertEqual(self.actions(review), {'step-1': 'run', 'step-3': 'reuse', 'step-2': 'run'})
        self.backend.requests.clear()
        result = self.engine.execute(self.engine.prepare(plan['graph'], self.root, restart_from=review))
        self.assertTrue(result['success'])
        self.assertEqual([Path(item['output_folder']).name for item in self.backend.requests], ['S1', 'S2'])

    def test_changed_parameter_invalidates_only_node_and_descendants(self):
        plan, _ = self.completed(); graph = copy.deepcopy(plan['graph'])
        graph['nodes'][0]['params']['threshold'] = '3'
        self.assertEqual(self.actions(self.engine.review_restart(graph, plan['folder'])),
                         {'step-1': 'run', 'step-3': 'reuse', 'step-2': 'run'})

    def test_changed_dependency_binding_invalidates_the_consumer(self):
        plan, _ = self.completed(); graph = copy.deepcopy(plan['graph'])
        graph['nodes'][1]['inputs']['source'] = ['step-3::result']
        self.assertEqual(self.actions(self.engine.review_restart(graph, plan['folder'])),
                         {'step-1': 'reuse', 'step-3': 'reuse', 'step-2': 'run'})

    def test_missing_or_changed_output_invalidates_descendants(self):
        for change in ('missing', 'changed'):
            with self.subTest(change=change):
                plan, result = self.completed()
                output = Path(result['outputs']['step-1::result']['files']['result'])
                output.unlink() if change == 'missing' else output.write_bytes(b'changed')
                self.assertEqual(self.actions(self.engine.review_restart(plan['graph'], plan['folder'])),
                                 {'step-1': 'run', 'step-3': 'reuse', 'step-2': 'run'})

    def test_changed_installed_executable_is_never_reused(self):
        plan, _ = self.completed()
        (self.root / 'packs/example-1.0.0/bin/worker.exe').write_bytes(b'changed')
        review = self.engine.review_restart(plan['graph'], plan['folder'])
        self.assertEqual(set(self.actions(review).values()), {'run'})
        self.assertIn('integrity changed', review['nodes'][0]['reason'])

    def test_changed_exact_pack_pin_invalidates_node_and_descendants(self):
        plan, _ = self.completed()
        make_pack(self.root, '2.0.0')
        self.engine = engine.Engine(self.root, load_catalog(self.root), self.backend)
        graph = copy.deepcopy(plan['graph'])
        graph['nodes'][0]['pin'] = engine.pin_for(self.engine.catalog['tools']['example/process'])
        self.assertEqual(self.actions(self.engine.review_restart(graph, plan['folder'])),
                         {'step-1': 'run', 'step-3': 'reuse', 'step-2': 'run'})

    def test_review_binding_rejects_changed_history_before_queue_preparation(self):
        plan, _ = self.completed()
        review = self.engine.review_restart(plan['graph'], plan['folder'])
        path = Path(plan['folder']) / 'run.json'
        data = json.loads(path.read_text()); data['finished'] = 'changed'
        engine.write_json(path, data)
        with self.assertRaisesRegex(ValueError, 'reviewed restart evidence changed'):
            self.engine.prepare(plan['graph'], self.root, restart_from=review)

    def test_output_changed_after_freeze_fails_closed_at_consumption(self):
        plan, record = self.completed()
        second = self.engine.prepare(plan['graph'], self.root, restart_from=plan['folder'])
        Path(record['outputs']['step-1::result']['files']['result']).write_bytes(b'changed')
        self.backend.requests.clear()
        result = self.engine.execute(second)
        status = {item['id']: item for item in result['nodes']}
        self.assertEqual(status['step-1']['status'], 'failed')
        self.assertEqual(status['step-2']['status'], 'blocked')
        self.assertEqual(status['step-3']['status'], 'success')
        self.assertEqual(self.backend.requests, [])

    def test_interrupted_run_reuses_only_persisted_completed_steps(self):
        plan = self.engine.prepare(self.graph(), self.root)
        def stop(item):
            if item.get('type') == 'step' and item.get('status') == 'success':
                raise SystemExit('Synthetic abrupt host boundary')
        with self.assertRaises(SystemExit):
            self.engine.execute(plan, event=stop)
        old = json.loads((Path(plan['folder']) / 'run.json').read_text())
        self.assertEqual(old['status'], 'running')
        self.assertEqual(old['nodes'][0]['status'], 'success')
        self.assertEqual(self.actions(self.engine.review_restart(plan['graph'], plan['folder'])),
                         {'step-1': 'reuse', 'step-3': 'run', 'step-2': 'run'})

    def test_batch_identity_is_preserved_automatically_in_restart(self):
        metadata = {'batchId': 'a' * 32, 'sampleId': 'sample', 'metadata': {'condition': 'control'}}
        plan = self.engine.prepare(self.graph(), self.root, run_metadata=metadata)
        self.assertTrue(self.engine.execute(plan)['success'])
        review = self.engine.review_restart(plan['graph'], plan['folder'])
        second = self.engine.prepare(plan['graph'], self.root, restart_from=review)
        self.assertEqual(second['batch'], metadata)
        self.assertEqual(set(self.actions(second['recovery']).values()), {'reuse'})

    def test_parallel_ready_branches_overlap_with_explicit_cpu_reservations(self):
        self.backend.wait_for_overlap = True
        policy = {'cpuBudget': 2, 'maxParallel': 2, 'stepCpus': {'step-1': 1, 'step-2': 1, 'step-3': 1}}
        plan = self.engine.prepare(self.graph(), self.root, resource_policy=policy)
        result = self.engine.execute(plan)
        self.assertTrue(result['success'], result)
        self.assertTrue(self.backend.overlap.is_set())
        self.assertEqual(self.backend.maximum, 2)
        self.assertEqual(Path(self.backend.requests[-1]['output_folder']).name, 'S2')

    def test_budget_and_unknown_reservations_keep_execution_exclusive(self):
        for policy in ({'cpuBudget': 1, 'maxParallel': 3, 'stepCpus': {'step-1': 1, 'step-2': 1, 'step-3': 1}},
                       {'cpuBudget': 4, 'maxParallel': 3, 'stepCpus': {}}):
            with self.subTest(policy=policy):
                self.backend.maximum = 0
                result = self.engine.execute(self.engine.prepare(self.graph(), self.root, resource_policy=policy))
                self.assertTrue(result['success'])
                self.assertEqual(self.backend.maximum, 1)
                if not policy['stepCpus']:
                    self.assertTrue(all(item['reservation']['source'] == 'unknown-exclusive' for item in result['nodes']))

    def test_independent_failure_does_not_cancel_other_branch(self):
        self.backend.failed.add('S1')
        policy = {'cpuBudget': 2, 'maxParallel': 2, 'stepCpus': {'step-1': 1, 'step-2': 1, 'step-3': 1}}
        result = self.engine.execute(self.engine.prepare(self.graph(), self.root, resource_policy=policy))
        self.assertEqual({item['id']: item['status'] for item in result['nodes']},
                         {'step-1': 'failed', 'step-3': 'success', 'step-2': 'blocked'})

    def test_cancellation_reaches_active_workers_and_never_starts_descendant(self):
        self.backend.wait_for_overlap = True; self.backend.cancel_after_overlap = True
        policy = {'cpuBudget': 2, 'maxParallel': 2, 'stepCpus': {'step-1': 1, 'step-2': 1, 'step-3': 1}}
        result = self.engine.execute(self.engine.prepare(self.graph(), self.root, resource_policy=policy))
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual({Path(item['output_folder']).name for item in self.backend.requests}, {'S1', 'S3'})
        self.assertEqual(self.backend.active, 0)

    def test_cancel_at_admission_does_not_launch_native_runner(self):
        cancel = threading.Event()
        def event(item):
            if item.get('type') == 'step' and item.get('status') == 'running':
                cancel.set()
        result = self.engine.execute(self.engine.prepare(self.graph(), self.root), event=event, cancel=cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.backend.requests, [])

    def test_scratch_uses_owned_subfolders_and_preserves_existing_files(self):
        scratch = self.root / 'scratch'; scratch.mkdir(); marker = scratch / 'user-file'; marker.write_bytes(b'keep')
        plan = self.engine.prepare(self.graph(), self.root, resource_policy={'temporaryFolder': str(scratch)})
        result = self.engine.execute(plan)
        self.assertTrue(result['success'])
        self.assertEqual(marker.read_bytes(), b'keep')
        folders = [Path(request['temporary_folder']) for request in self.backend.requests]
        self.assertEqual(len(set(folders)), 3)
        # Windows TEMP can spell the same directory with an 8.3 name while
        # production canonicalizes it. Verify filesystem identity, not the
        # lexical spelling of an otherwise identical owned parent.
        owned = scratch / ('native-workbench-' + plan['id'])
        self.assertEqual({path.name for path in folders}, {'S1', 'S2', 'S3'})
        physical_identity = all(engine._io_path(path.parent).samefile(engine._io_path(owned)) for path in folders)
        lexical_containment = all(path.is_relative_to(owned) for path in folders)
        if not lexical_containment:
            print(json.dumps({'testObservation': 'temporary folder spelling differs from the same filesystem directory',
                              'lexicalContainment': lexical_containment, 'physicalParentIdentity': physical_identity,
                              'stepFolderNames': sorted(path.name for path in folders)}), flush=True)
        self.assertTrue(physical_identity)

    def test_invalid_or_unavailable_resource_settings_fail_before_new_result(self):
        for policy in ({'cpuBudget': True}, {'cpuBudget': 5}, {'cpuBudget': 0}, {'maxParallel': 33},
                       {'cpuBudget': 1, 'stepCpus': {'step-1': 2}}, {'stepCpus': {'step-9': 1}},
                       {'temporaryFolder': 'relative'}, {'temporaryFolder': str(self.root / 'missing')}, {'guess': 1}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.engine.prepare(self.graph(), self.root, resource_policy=policy)
        self.assertEqual(list(self.root.glob('run-*')), [])

    def test_zero_free_space_fails_without_assuming_tool_requirement(self):
        from collections import namedtuple
        usage = namedtuple('Usage', 'total used free')
        with patch.object(execution_resources.shutil, 'disk_usage', return_value=usage(100, 100, 0)):
            with self.assertRaisesRegex(ValueError, 'No free space'):
                self.engine.prepare(self.graph(), self.root)

    def test_same_index_builders_in_parallel_share_one_verified_publication(self):
        from test_reference_indexes import fixture_pack, FixtureBackend
        fixture_pack(self.root)
        reference = self.root / 'reference.fa'; reference.write_text('>one\nACGTACGT\n')
        graph = {'schema': 1, 'sources': [{'id': 'input-1', 'type': 'reference', 'files': {'reference': str(reference)}}],
                 'nodes': [{'id': identity, 'tool': 'align/build-sr-index', 'params': {'threads': '1'},
                            'inputs': {'reference': ['input-1']}} for identity in ('step-1', 'step-2')]}
        backend = FixtureBackend()
        runner = engine.Engine(self.root, load_catalog(self.root), backend)
        policy = {'cpuBudget': 2, 'maxParallel': 2, 'stepCpus': {'step-1': 1, 'step-2': 1}}
        result = runner.execute(runner.prepare(graph, self.root, resource_policy=policy))
        self.assertTrue(result['success'], result)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(sorted(node['referenceIndex']['action'] for node in result['nodes']), ['built', 'reused'])

    def test_native_backend_scratch_environment_does_not_expand_bridge_schema(self):
        folder = self.root / 'backend-step'; folder.mkdir()
        temporary = self.root / 'backend-temp'; temporary.mkdir()
        backend = engine.NativeBackend(self.root)
        from types import SimpleNamespace
        process = SimpleNamespace(stdout=[json.dumps({'success': True})], wait=lambda **kwargs: 0, poll=lambda: 0)
        observed = {}
        def spawn(*args, **kwargs):
            observed.update(kwargs)
            return process
        request = {'app_root': str(self.root), 'pack_folder': str(self.root / 'packs/example-1.0.0'),
                   'pack_sha256': 'a' * 64, 'workflow_id': 'process', 'output_folder': str(folder),
                   'values': {}, 'cancel_file': str(folder / 'cancel'), 'temporary_folder': str(temporary)}
        with patch.object(backend, '_spawn', side_effect=spawn), patch.object(backend, '_release'):
            self.assertTrue(backend.run(request, lambda item: None, threading.Event())['success'])
        saved = json.loads((folder / 'bridge-request.json').read_text())
        self.assertNotIn('temporary_folder', saved)
        self.assertEqual({key: observed['env'][key] for key in ('TMP', 'TEMP', 'TMPDIR')},
                         dict.fromkeys(('TMP', 'TEMP', 'TMPDIR'), str(temporary)))

    def test_structural_resource_validation_retains_unavailable_settings_for_correction(self):
        policy = {'cpuBudget': 64, 'temporaryFolder': str(self.root / 'no-longer-present')}
        self.assertEqual(execution_resources.normalize(policy, check_environment=False)['cpuBudget'], 64)
        with self.assertRaises(ValueError):
            execution_resources.normalize(policy)

    def test_published_metagenomics_descriptors_require_fresh_adapter_verification(self):
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / 'scripts'))
        from prepare_kraken2_pack import definitions as kraken_definitions
        from prepare_bracken_pack import definitions as bracken_definitions
        for pack, definitions in (('kraken2', kraken_definitions), ('bracken', bracken_definitions)):
            _, metadata = definitions()
            for operation, contract in metadata['workflows'].items():
                with self.subTest(pack=pack, operation=operation):
                    tool = dict(contract, packId=pack, id=pack + '/' + operation)
                    self.assertIn('complete restart dependency inventory', recovery.unsupported_reason(tool))
        database = json.loads((root / 'tools/bracken/fixtures/database.json').read_text())
        classification = json.loads((root / 'tools/bracken/fixtures/classification.json').read_text())
        self.assertEqual(database['kind'], 'native-workbench-kraken2-database')
        self.assertIn('databaseRoot', database)
        self.assertTrue(database['brackenDistributions'][0]['path'])
        self.assertEqual(classification['report']['path'], 'expected.report.tsv')

    def test_imported_project_context_freezes_separately_in_results_methods_cwl_and_restart(self):
        context = self.project()
        plan = self.engine.prepare(self.graph(), self.root, project_metadata=context)
        result = self.engine.execute(plan)
        self.assertTrue(result['success'])
        self.assertEqual(plan['project'], context)
        self.assertEqual(result['project'], context)
        self.assertEqual(plan['references'], {})
        self.assertIn('Historical reference receipts', result['methods'])
        document = json.loads((Path(plan['folder']) / 'workflow.cwl').read_text())
        self.assertEqual(json.loads(document['$graph'][0]['nw:project']), context)
        review = self.engine.review_restart(plan['graph'], plan['folder'])
        restarted = self.engine.prepare(plan['graph'], self.root, restart_from=review)
        self.assertEqual(restarted['project'], context)
        self.assertEqual(set(self.actions(restarted['recovery']).values()), {'reuse'})

    def test_project_context_cannot_silently_reattribute_changed_or_new_inputs(self):
        for change in ('hash', 'binding', 'helper'):
            with self.subTest(change=change):
                context = self.project()
                if change == 'hash':
                    context['dependencies'][0]['sha256'] = '0' * 64
                elif change == 'binding':
                    context['dependencies'].pop()
                else:
                    context['validationTools'] = {'step-1': {}}
                with self.assertRaises(ValueError):
                    self.engine.prepare(self.graph(), self.root, project_metadata=context)
        self.assertEqual(list(self.root.glob('run-*')), [])

    def test_imported_preflight_helper_keeps_exact_pin_when_newer_helper_is_installed(self):
        make_pack(self.root, '1.0.0', identity='bam', executable='samtools')
        make_pack(self.root, '2.0.0', identity='bam', executable='samtools')
        catalog = load_catalog(self.root)
        operations = [catalog['tools']['example/process'], *catalog['toolVersions']['example/process']]
        for operation in operations:
            operation['ports'][0].update(type='bam', accepts=['file'], requiredState={'sort': 'coordinate'})
        self.engine = engine.Engine(self.root, catalog, self.backend)
        old = next(tool for tool in catalog['toolVersions']['bam/process'] if tool['packVersion'] == '1.0.0')
        helper = {'operation': old['id'], 'pin': engine.pin_for(old), 'executable': old['executables'][0]}
        context = self.project(); context['validationTools'] = dict.fromkeys(('step-1', 'step-2', 'step-3'), helper)
        plan = self.engine.prepare(self.graph(), self.root, project_metadata=context)
        self.assertEqual({node['validationTools']['samtools']['pin']['packVersion'] for node in plan['nodes']}, {'1.0.0'})
        self.assertEqual(self.engine._samtools_selection(catalog['tools']['example/process'])['pin']['packVersion'], '2.0.0')


if __name__ == '__main__':
    unittest.main()
