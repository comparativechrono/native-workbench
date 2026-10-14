"""Regression checks for exact installed versions across graph and UI paths."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import CatalogError, load_catalog, resolve_tool
from desktop_model import DesktopModel
from engine import Engine, pin_for


def make_pack(root, version, identity='example', executable='worker', tool_version=None):
    folder = root / 'packs' / (identity + '-' + version)
    (folder / 'bin').mkdir(parents=True)
    payload = (identity + version).encode()
    (folder / 'bin/worker.exe').write_bytes(payload)
    (folder / 'licenses').mkdir()
    (folder / 'licenses/notice.txt').write_text('Synthetic test fixture; no executable software.')
    text = f'''[pack]
format=2
id={identity}
version={version}
name=Example {version}
platform=windows-x86_64
[tool:{executable}]
path=bin/worker.exe
version={tool_version or version}
sha256={hashlib.sha256(payload).hexdigest()}
[workflow:process]
name=Process {version}
description=Version-specific processing {version}.
inputs=source,threshold
outputs=result
steps=run
[input:process:source]
label=Source {version}
type=file
[input:process:threshold]
label=Threshold {version}
type=integer
min=1
max={3 if version=='1.0.0' else 9}
default=2
[output:process:result]
label=Result {version}
path=result.dat
[step:process:run]
label=Process
kind=exec
tool={executable}
stdout=result
arg.0={{input:source}}
arg.1={{input:threshold}}
'''
    (folder / 'pack.ini').write_text(text)
    return folder


class RecordingBackend:
    def __init__(self):
        self.requests = []

    def run(self, request, event, cancel):
        self.requests.append(copy.deepcopy(request))
        folder = Path(request['output_folder'])
        (folder / 'result.dat').write_text(Path(request['pack_folder']).name)
        return {'success': True, 'folder': str(folder)}

    def inspect_alignment(self, executable, filename, cancel):
        return '@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:20\n'


class ExactPackVersions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workbench-versions-')
        self.root = Path(self.tmp.name)
        self.old_folder = make_pack(self.root, '1.0.0')
        self.new_folder = make_pack(self.root, '2.0.0')
        self.catalog = load_catalog(self.root)
        self.new, self.old = self.catalog['toolVersions']['example/process']
        self.source = self.root / 'input.dat'
        self.source.write_text('input')
        self.backend = RecordingBackend()
        self.engine = Engine(self.root, self.catalog, backend=self.backend)

    def tearDown(self):
        self.tmp.cleanup()

    def graph(self):
        return {'schema': 1, 'name': 'Two versions', 'sources': [
            {'id': 'input-1', 'type': 'file', 'files': {'source': str(self.source)}}], 'nodes': [
            {'id': 'step-1', 'tool': 'example/process', 'pin': pin_for(self.old),
             'params': {'threshold': '3'}, 'inputs': {'source': ['input-1']}},
            {'id': 'step-2', 'tool': 'example/process', 'pin': pin_for(self.new),
             'params': {'threshold': '8'}, 'inputs': {'source': ['step-1::result']}}]}

    def test_latest_for_new_steps_exact_old_and_new_in_same_dag(self):
        self.assertEqual(resolve_tool(self.catalog, 'example/process'), self.new)
        graph = self.graph()
        self.assertTrue(self.engine.validate(graph)['ok'])
        saved = self.engine.save_pipeline(graph)
        self.assertEqual([n['pin'] for n in saved['nodes']], [pin_for(self.old), pin_for(self.new)])
        methods = self.engine.methods(graph)
        self.assertIn('pack example 1.0.0', methods)
        self.assertIn('pack example 2.0.0', methods)
        plan = self.engine.prepare(graph, self.root)
        self.assertEqual([n['tool']['packVersion'] for n in plan['nodes']], ['1.0.0', '2.0.0'])
        result = self.engine.execute(plan)
        self.assertTrue(result['success'], result)
        self.assertEqual([Path(r['pack_folder']).name for r in self.backend.requests], ['example-1.0.0', 'example-2.0.0'])
        record = json.loads((Path(plan['folder']) / 'run.json').read_text())
        self.assertEqual([n['pin']['packVersion'] for n in record['nodes']], ['1.0.0', '2.0.0'])

    def test_ui_inspector_connections_presets_and_reload_keep_exact_version(self):
        model = DesktopModel(self.root, self.catalog)
        state = model.dispatch('load_graph', {'graph': self.graph(), 'template': False})
        self.assertEqual(state['inspector']['tool']['packVersion'], '1.0.0')
        self.assertEqual(state['inspector']['params'][0]['max'], 3)
        self.assertEqual(state['nodes'][1]['inputs'][0]['refs'][0]['name'], 'Result 1.0.0')
        preset = self.engine.save_preset(model.graph['nodes'][0])
        self.assertEqual(preset['pin'], pin_for(self.old))
        model.dispatch('apply_preset', {'nodeId': 'step-1', 'preset': preset})
        with self.assertRaises(ValueError):
            model.dispatch('apply_preset', {'nodeId': 'step-2', 'preset': preset})
        model.update_catalog(load_catalog(self.root))
        self.assertEqual(model.graph['nodes'][0]['pin'], pin_for(self.old))
        state = model.dispatch('add_tool', {'toolId': 'example/process', 'pin': pin_for(self.old)})
        self.assertEqual(state['inspector']['tool']['packVersion'], '1.0.0')
        state = model.dispatch('add_tool', {'toolId': 'example/process'})
        self.assertEqual(state['inspector']['tool']['packVersion'], '2.0.0')

    def test_bad_or_missing_exact_pins_fail_without_latest_fallback(self):
        for pin in ({}, {'packVersion': '1.0.0'}, dict(pin_for(self.old), manifestSha256='0'*64),
                    dict(pin_for(self.old), packVersion='7.0.0'), dict(pin_for(self.old), packId='wrong')):
            with self.subTest(pin=pin):
                with self.assertRaises(CatalogError):
                    resolve_tool(self.catalog, 'example/process', pin)
                graph = self.graph(); graph['nodes'][0]['pin'] = pin
                self.assertFalse(self.engine.validate(graph)['ok'])
                with self.assertRaises(ValueError): self.engine.prepare(graph, self.root)
                with self.assertRaises(ValueError): self.engine.save_preset(graph['nodes'][0])
        legacy = pin_for(self.old); legacy.pop('packId')
        self.assertEqual(resolve_tool(self.catalog, 'example/process', legacy), self.old)
        self.old_folder.rename(self.root / 'retired-pack')
        updated = load_catalog(self.root)
        with self.assertRaises(CatalogError): resolve_tool(updated, 'example/process', pin_for(self.old))
        model = DesktopModel(self.root, updated)
        state = model.dispatch('load_graph', {'graph': self.graph(), 'template': False})
        self.assertFalse(state['review']['valid'])
        self.assertEqual(state['inspector']['tool']['name'], 'Unavailable tool')

    def test_manifest_tampering_after_freeze_rejected(self):
        plan = self.engine.prepare(self.graph(), self.root)
        with (self.old_folder / 'pack.ini').open('a') as stream: stream.write('\n; changed\n')
        result = self.engine.execute(plan)
        self.assertFalse(result['success'])
        self.assertEqual(self.backend.requests, [])

    def test_missing_pack_template_load_preserves_graph_settings_and_blocks_run(self):
        saved = self.engine.save_pipeline(self.graph())
        # A different computer has neither version installed.
        empty = self.root / 'another-installation'; empty.mkdir()
        model = DesktopModel(empty, load_catalog(empty))
        state = model.dispatch('load_graph', {'graph': saved, 'template': True})
        self.assertEqual(state['graph']['nodes'], saved['nodes'])
        self.assertEqual([node['inputs'] for node in state['graph']['nodes']],
                         [node['inputs'] for node in saved['nodes']])
        self.assertTrue(all(node['unavailable'] for node in state['nodes']))
        self.assertTrue(state['inspector']['unavailable'])
        self.assertEqual(state['inspector']['missingPin'], pin_for(self.old))
        self.assertIn('exact saved tool version', state['inspector']['missingReason'])
        self.assertIn('Manage tools', state['notice'])
        self.assertFalse(state['review']['valid'])
        with self.assertRaisesRegex(ValueError, 'exact saved tool version'):
            model.engine.prepare(state['graph'], empty)
        # Installing a compatible pack later must restore the original fields,
        # without replacing the saved threshold or changing the original pin.
        make_pack(empty, '1.0.0'); make_pack(empty, '2.0.0')
        recovered = model.update_catalog(load_catalog(empty))
        self.assertEqual(recovered['graph']['nodes'], saved['nodes'])
        self.assertEqual(recovered['inspector']['params'][0]['value'], '3')
        self.assertEqual(recovered['inspector']['tool']['packVersion'], '1.0.0')

    def test_malformed_and_unsupported_folders_are_isolated(self):
        invalid = self.root / 'packs/broken-1.0.0'; invalid.mkdir()
        (invalid / 'pack.ini').write_text('[pack]\nformat=999\n')
        unsupported = make_pack(self.root, '3.0.0')
        path = unsupported / 'pack.ini'
        path.write_text(path.read_text().replace('platform=windows-x86_64', 'platform=linux-x86_64'))
        catalog = load_catalog(self.root)
        self.assertEqual(len(catalog['errors']), 2)
        self.assertEqual(catalog['tools']['example/process']['packVersion'], '2.0.0')
        self.assertEqual(resolve_tool(catalog, 'example/process', pin_for(self.old)), self.old)

    def test_empty_application_keeps_reporting_and_legacy_catalogues_resolve(self):
        empty = self.root / 'empty'; empty.mkdir()
        self.assertEqual(set(load_catalog(empty)['tools']), {'builtin/report'})
        legacy = {'tools': {'example/process': self.old}}
        self.assertEqual(resolve_tool(legacy, 'example/process', pin_for(self.old)), self.old)
        with self.assertRaises(CatalogError): resolve_tool(legacy, 'example/process', pin_for(self.new))

    def test_incompatible_or_malformed_receipt_isolates_only_affected_version(self):
        receipts = self.root / 'user-data/pack-receipts'; receipts.mkdir(parents=True)
        path = receipts / 'example-2.0.0.json'
        receipt = {'schema': 1, 'id': 'example', 'version': '2.0.0', 'packApi': 1,
                   'minAppVersion': '0.6.0', 'platform': 'windows-x86_64', 'manifestSha256': self.new['manifestSha256']}
        path.write_text(json.dumps(receipt))
        self.assertEqual(load_catalog(self.root)['tools']['example/process'], self.new)
        for changes in ({'minAppVersion': '99.0.0'}, {'packApi': 2}, {'packApi': True},
                        {'platform': 'linux-x86_64'}, {'manifestSha256': '0'*64}, {'unexpected': 1}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps(dict(receipt, **changes)))
                catalog = load_catalog(self.root)
                self.assertEqual(catalog['tools']['example/process'], self.old)
                self.assertEqual(len(catalog['errors']), 1)
                with self.assertRaises(CatalogError): resolve_tool(catalog, 'example/process', pin_for(self.new))
        path.write_text('{"schema":1,"schema":1}')
        self.assertEqual(len(load_catalog(self.root)['errors']), 1)

    def test_helper_selection_is_deterministic_prefers_owner_and_remains_pinned(self):
        make_pack(self.root, '1.0.0', 'samtools', 'samtools', '1.9')
        make_pack(self.root, '2.0.0', 'samtools', 'samtools', '1.24')
        catalog = load_catalog(self.root)
        engine = Engine(self.root, catalog)
        selection = engine._samtools_selection(self.old)
        self.assertEqual(selection['executable']['version'], '1.24')
        older = catalog['toolVersions']['samtools/process'][1]
        self.assertEqual(engine._samtools_selection(older)['pin'], pin_for(older))
        node = {'tool': self.old, 'validationTools': {'samtools': selection}}
        make_pack(self.root, '3.0.0', 'samtools', 'samtools', '1.99')
        engine = Engine(self.root, load_catalog(self.root))
        selected_path = engine._samtools(node)
        self.assertEqual(selected_path.parent.parent.name, 'samtools-2.0.0')
        self.assertEqual(node['validationTools']['samtools'], selection)
        selected_path.write_text('tampered helper')
        with self.assertRaises(ValueError): engine._samtools(node)

    def test_header_helper_is_frozen_in_plan_and_recorded_in_execution(self):
        make_pack(self.root, '2.0.0', 'samtools', 'samtools', '1.24')
        catalog = load_catalog(self.root)
        owner = resolve_tool(catalog, 'example/process', pin_for(self.old))
        owner['ports'][0].update(type='bam', accepts=['sam','bam'], requiredState={'sort':'coordinate'})
        graph = self.graph(); graph['nodes'] = graph['nodes'][:1]
        graph['sources'][0]['type'] = 'sam'
        self.source.write_text('@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:20\n')
        engine = Engine(self.root, catalog, backend=self.backend)
        plan = engine.prepare(graph, self.root)
        selected = plan['nodes'][0]['validationTools']['samtools']
        self.assertEqual(selected['executable']['version'], '1.24')
        result = engine.execute(plan)
        self.assertTrue(result['success'], result)
        record = json.loads((Path(plan['folder']) / 'run.json').read_text())
        self.assertEqual(record['nodes'][0]['preflight']['validationTools']['samtools'], selected)


if __name__ == '__main__':
    unittest.main()
