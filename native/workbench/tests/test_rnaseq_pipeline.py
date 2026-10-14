"""RNA pack graph and offline archive contracts against the released 0.6.0 app.

Run this separately with NW_RNASEQ_APP_ROOT pointing to an extracted 0.6.0
starter plus the new packs, and NW_RNASEQ_ARCHIVE_DIR pointing to their ZIPs.
Set NW_RNASEQ_STAR_VERSION / NW_RNASEQ_KALLISTO_VERSION when testing upgrades.
The released Python modules are tested, not edited application source. No
scientific executable or native Windows importer is exercised by this suite.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1]
WORK = SOURCE.parent
APP = Path(os.environ.get('NW_RNASEQ_APP_ROOT', WORK / 'rna-build/validation-app/native-workbench')).resolve()
ARCHIVES = Path(os.environ.get('NW_RNASEQ_ARCHIVE_DIR', WORK / 'rna-build/releases')).resolve()
STARTER = Path(os.environ.get('NW_RNASEQ_STARTER_ZIP', WORK / 'release-0.6.0/native-workbench-0.6.0-starter-windows.zip')).resolve()
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
PACK_VERSIONS = {'star': os.environ.get('NW_RNASEQ_STAR_VERSION', '1.0.0'),
                 'kallisto': os.environ.get('NW_RNASEQ_KALLISTO_VERSION', '1.0.0')}
EVIDENCE = {'schema': 1, 'applicationVersion': '0.6.0', 'nativeWindowsExecuted': False,
            'scientificExecutablesExecuted': False, 'nativeImporterExecuted': False,
            'expectedPackVersions': PACK_VERSIONS,
            'scope': 'Released-app graph contracts and Python archive import; copy callback substitutes native folder publication.'}


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


class RnaSeqPipelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (APP / 'workspace/engine.py').is_file():
            raise unittest.SkipTest('Assemble the released RNA validation app and set NW_RNASEQ_APP_ROOT.')
        # Refuse a surrounding unittest invocation that already imported another
        # application's modules. This evidence must concern released 0.6.0.
        sys.path.insert(0, str(APP / 'workspace'))
        cls.modules = {}
        for name in ('catalog', 'engine', 'pack_security', 'pack_manager', 'verify_installation', 'app_version'):
            module = importlib.import_module(name)
            if Path(module.__file__).resolve().parent != APP / 'workspace':
                raise RuntimeError('Run this suite in a fresh process: wrong imported module ' + name)
            cls.modules[name] = module
        if cls.modules['app_version'].APP_VERSION != '0.6.0':
            raise RuntimeError('This contract gate requires the released 0.6.0 application.')
        cls.catalog = cls.modules['catalog'].load_catalog(APP)
        if cls.catalog.get('errors'):
            raise RuntimeError('Pack discovery failed: ' + repr(cls.catalog['errors']))
        for pack_id in ('star', 'kallisto', 'bam'):
            if not any(tool.get('packId') == pack_id for tool in cls.catalog['tools'].values()):
                raise RuntimeError('Required pack is absent: ' + pack_id)
        for pack_id, version in PACK_VERSIONS.items():
            if not any(tool.get('packId') == pack_id and tool.get('packVersion') == version
                       for tool in cls.catalog['tools'].values()):
                raise RuntimeError('Expected current pack version is absent: ' + pack_id + ' ' + version)
        cls.tools = cls.catalog['tools']
        cls.engine = cls.modules['engine'].Engine(APP, cls.catalog)

    @classmethod
    def tearDownClass(cls):
        backend = getattr(cls.engine, 'backend', None)
        if backend is not None and hasattr(backend, 'shutdown'):
            backend.shutdown()

    def select(self, pack, predicate):
        matches = [tool for tool in self.tools.values() if tool.get('packId') == pack
                   and tool.get('packVersion') == PACK_VERSIONS[pack] and predicate(tool)]
        self.assertTrue(matches, 'Missing required workflow contract in ' + pack)
        return sorted(matches, key=lambda tool: tool['id'])[0]

    @staticmethod
    def port(tool, kind):
        return next(port for port in tool.get('ports', []) if port['type'] == kind)

    @staticmethod
    def defaults(tool):
        result = {}
        for param in tool.get('params', []):
            value = param.get('default', '')
            if not value and param.get('binding'):
                value = 'validation'
            if value != '':
                result[param['id']] = value
        return result

    def add_node(self, graph, tool, bindings=None):
        identity = 'step-' + str(len(graph['nodes']) + 1)
        inputs = {}
        for port in tool['ports']:
            if port['id'] in (bindings or {}):
                inputs[port['id']] = bindings[port['id']]
            elif port.get('min', 1):
                source_id = 'input-' + str(len(graph['sources']) + 1)
                # This suite assesses declared graph contracts. Synthetic local
                # paths are deliberately never prepared or scientifically run.
                files = {field: '/contract-only/' + source_id + '-' + field
                         for field in port['manifestInputs']}
                graph['sources'].append({'id': source_id, 'label': port['label'], 'type': port['type'], 'files': files})
                inputs[port['id']] = [source_id]
        node = {'id': identity, 'tool': tool['id'], 'inputs': inputs, 'params': self.defaults(tool)}
        graph['nodes'].append(node)
        return node

    def paired_star(self):
        return self.select('star', lambda t: t['workflowId'] == 'rna-paired')

    def paired_kallisto(self, indexed):
        return self.select('kallisto', lambda t: any(p['type'] == 'pair' for p in t['ports'])
                           and any(p['type'] == 'index' for p in t['ports']) == indexed)

    def test_application_contract_files_match_published_starter(self):
        self.assertEqual(sha(STARTER), STARTER_SHA, 'Published starter ZIP bytes differ.')
        members = ['workspace/' + name + '.py' for name in self.modules]
        members += ['WorkbenchBridge.exe', 'workspace/pack_checks.py']
        with zipfile.ZipFile(STARTER) as archive:
            for relative in members:
                expected = hashlib.sha256(archive.read('native-workbench/' + relative)).hexdigest()
                self.assertEqual(sha(APP / relative), expected, relative + ' differs from released 0.6.0')
        EVIDENCE['releasedApplicationFilesVerified'] = members
        EVIDENCE['starterSha256'] = STARTER_SHA

    def test_new_pack_inventory_and_scientific_checks_are_declared(self):
        EVIDENCE['installedInventory'] = self.modules['verify_installation'].check_packs(APP, self.catalog)
        checked = []
        for row in self.catalog['packs']:
            if row['id'] not in PACK_VERSIONS or row['version'] != PACK_VERSIONS[row['id']]:
                continue
            pack = self.modules['catalog'].load_pack(APP / row['folder'] / 'pack.ini')
            for asset in ('workbench-schema', 'workbench-checks'):
                self.assertIn(asset, pack['assets'])
            spec = json.loads((APP / row['folder'] / pack['assets']['workbench-checks']['path']).read_text())
            self.assertGreater(len(spec['checks']), 0)
            self.assertTrue(all(case.get('expect') for case in spec['checks']))
            checked.append({'id': row['id'], 'version': row['version'], 'manifestSha256': row['manifestSha256'],
                            'scientificChecksDeclared': len(spec['checks'])})
        self.assertEqual({row['id'] for row in checked}, {'star', 'kallisto'})
        EVIDENCE['newPacks'] = checked

    def test_kallisto_index_connects_to_quantification_and_saved_pins(self):
        index = self.select('kallisto', lambda t: any(o['type'] == 'index' for o in t['outputs'])
                            and not any(p['type'] in {'reads', 'pair'} for p in t['ports']))
        quant = self.paired_kallisto(indexed=True)
        product = next(o for o in index['outputs'] if o['type'] == 'index')
        port = self.port(quant, 'index')
        self.assertEqual(len(product['manifestOutputs']), len(port['manifestInputs']))
        graph = {'schema': 1, 'name': 'Index transcripts then quantify fragments', 'nodes': [], 'sources': []}
        first = self.add_node(graph, index)
        self.add_node(graph, quant, {port['id']: [first['id'] + '::' + product['id']]})
        review = self.engine.validate(graph, check_files=False)
        self.assertTrue(review['valid'], review)
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1']}, {'rank': 2, 'nodes': ['step-2']}])
        saved = self.engine.save_pipeline(graph)
        for node in saved['nodes']:
            self.assertEqual(node['pin'], self.modules['engine'].pin_for(self.tools[node['tool']]))
        self.assertTrue(all('files' not in source for source in saved['sources']))
        methods = self.engine.methods(graph)
        self.assertIn('kallisto', methods.lower())
        self.assertIn(index['name'], methods)
        self.assertIn(quant['name'], methods)
        EVIDENCE['indexQuantificationGraph'] = {'tools': [index['id'], quant['id']], 'savedPins': [n['pin'] for n in saved['nodes']]}

    def test_shared_reads_make_star_and_kallisto_same_rank_siblings(self):
        star, kallisto = self.paired_star(), self.paired_kallisto(indexed=False)
        graph = {'schema': 1, 'name': 'RNA alignment and abundance branches', 'nodes': [], 'sources': []}
        first = self.add_node(graph, star)
        shared = first['inputs'][self.port(star, 'pair')['id']]
        self.add_node(graph, kallisto, {self.port(kallisto, 'pair')['id']: shared})
        review = self.engine.validate(graph, check_files=False)
        self.assertTrue(review['valid'], review)
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1', 'step-2']}])
        self.assertEqual(len(self.engine.save_pipeline(graph)['nodes']), 2)
        methods = self.engine.methods(graph)
        self.assertIn('star', methods.lower())
        self.assertIn('kallisto', methods.lower())
        EVIDENCE['sharedReadBranches'] = {'tools': [star['id'], kallisto['id']], 'ranks': self.engine.rank_groups(graph)}

    def test_star_rna_alignments_cannot_enter_dna_preparation_or_calling(self):
        star = self.paired_star()
        rna = [output for output in star['outputs'] if output['type'] in {'sam-rna', 'bam-rna'}]
        self.assertEqual({output['type'] for output in rna}, {'sam-rna', 'bam-rna'})
        for consumer in (self.tools['bam/prepare'], self.tools['variants/call']):
            incoming = next(port for port in consumer['ports'] if port['type'] in {'bam', 'sam'})
            for output in rna:
                with self.subTest(type=output['type'], consumer=consumer['id']):
                    graph = {'schema': 1, 'name': 'Reject RNA as a DNA alignment', 'nodes': [], 'sources': []}
                    alignment = self.add_node(graph, star)
                    bindings = {incoming['id']: ['step-1::' + output['id']]}
                    for port in consumer['ports']:
                        if port['type'] == 'reference':
                            bindings[port['id']] = alignment['inputs'][self.port(star, 'reference')['id']]
                    self.add_node(graph, consumer, bindings)
                    review = self.engine.validate(graph, check_files=False)
                    self.assertFalse(review['valid'])
                    self.assertTrue(any(output['type'] + ' cannot feed ' in error['message'] for error in review['errors']), review)
        EVIDENCE['rnaIntoDnaRejected'] = sorted(output['type'] for output in rna)
        EVIDENCE['dnaConsumersRejected'] = ['bam/prepare', 'variants/call']

    def test_offline_archive_import_duplicate_receipt_and_original_bytes(self):
        manager_module = self.modules['pack_manager']
        catalog_module = self.modules['catalog']
        imported = []
        with tempfile.TemporaryDirectory(prefix='rnaseq-static-import-') as temporary:
            root = Path(temporary) / 'app with spaces'
            (root / 'packs').mkdir(parents=True)
            starters = [row for row in self.catalog['packs'] if row['id'] in {'align', 'bam', 'variants'}]
            self.assertEqual({row['id'] for row in starters}, {'align', 'bam', 'variants'})
            for row in starters:
                shutil.copytree(APP / row['folder'], root / row['folder'])
            starter_bytes = {path.relative_to(root).as_posix(): sha(path)
                             for path in (root / 'packs').rglob('*') if path.is_file()}
            callback_count = 0

            def copy_publication(source):
                nonlocal callback_count
                callback_count += 1
                pack = catalog_module.load_pack(Path(source) / 'pack.ini')
                destination = root / 'packs' / (pack['id'] + '-' + pack['version'])
                shutil.copytree(source, destination)
                return {'success': True, 'folder': str(destination)}

            manager = manager_module.PackManager(root, copy_publication)
            archives = []
            for candidate in sorted(ARCHIVES.glob('*.zip')):
                with zipfile.ZipFile(candidate) as archive:
                    if 'workbench-pack.json' not in archive.namelist():
                        continue
                    envelope = json.loads(archive.read('workbench-pack.json'))
                if envelope['id'] in PACK_VERSIONS and envelope['version'] == PACK_VERSIONS[envelope['id']]:
                    archives.append((candidate, envelope))
            self.assertEqual({entry['id'] for _, entry in archives}, {'star', 'kallisto'}, 'Both RNA pack archives are required.')
            for archive, envelope in archives:
                result = manager.import_archive(archive)
                self.assertTrue(result['success'])
                self.assertFalse(result['publisherVerified'])
                folder = root / 'packs' / (envelope['id'] + '-' + envelope['version'])
                receipt = root / 'user-data/pack-receipts' / (envelope['id'] + '-' + envelope['version'] + '.json')
                before = {path.relative_to(root).as_posix(): sha(path) for path in root.rglob('*') if path.is_file()}
                calls_before = callback_count
                with self.assertRaisesRegex(ValueError, 'already installed'):
                    manager.import_archive(archive)
                self.assertEqual(callback_count, calls_before, 'Duplicate reached native publication callback.')
                self.assertEqual({path.relative_to(root).as_posix(): sha(path) for path in root.rglob('*') if path.is_file()}, before)
                self.assertEqual(sha(folder / 'pack.ini'), envelope['manifestSha256'])
                self.assertEqual(json.loads(receipt.read_text())['manifestSha256'], envelope['manifestSha256'])
                imported.append({'id': envelope['id'], 'version': envelope['version'], 'archiveSha256': sha(archive),
                                 'duplicateVersionRejected': True, 'receiptAndInstalledBytesUnchanged': True})
            catalog = catalog_module.load_catalog(root)
            self.assertFalse(catalog.get('errors'), catalog)
            self.assertEqual({pack['id'] for pack in catalog['packs']}, {'align', 'bam', 'variants', 'star', 'kallisto'})
            self.assertEqual({relative: sha(root / relative) for relative in starter_bytes}, starter_bytes)
        EVIDENCE['offlineStaticImports'] = imported
        EVIDENCE['starterPackFilesPreserved'] = len(starter_bytes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RnaSeqPipelineContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), success=result.wasSuccessful() and result.testsRun > 0 and not result.skipped)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if EVIDENCE['success'] else 1)
