"""Released 0.6.0 graph and offline-import contracts for the October 2026 packs.

This suite executes no scientific programs and no native Windows importer. It
copies the released starter and selected packs into disposable applications.
The import test substitutes a Python folder-copy callback for native publication.

Configuration (paths can be absolute; defaults are local development locations):
  NW_POPULAR_STARTER_ZIP: immutable released 0.6.0 starter ZIP
  NW_POPULAR_PACK_DIR: directory containing <id>-<version> pack folders
  NW_POPULAR_ARCHIVE_DIR: directory containing the five installable pack ZIPs
  NW_POPULAR_STAR_ARCHIVE: immutable published STAR 1.0.0 ZIP
  NW_POPULAR_TEMP_DIR: writable parent for disposable test applications
  NW_POPULAR_<ID>_VERSION: expected version, default 1.0.0 for each new pack
  NW_POPULAR_<ID>_PACK_DIR: override one prepared pack's full folder path
  NW_POPULAR_<ID>_ARCHIVE: override one installable pack ZIP path

Run in a fresh process, for example:
  python3 tests/test_popular_pipeline.py --report /tmp/popular-contracts.json
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
WORK = SOURCE.parent / 'popular-build'
STARTER = Path(os.environ.get('NW_POPULAR_STARTER_ZIP', WORK / 'validation/native-workbench-0.6.0-starter-windows.zip')).resolve()
PACK_ROOT = Path(os.environ.get('NW_POPULAR_PACK_DIR', SOURCE / 'packs')).resolve()
ARCHIVES = Path(os.environ.get('NW_POPULAR_ARCHIVE_DIR', WORK / 'releases')).resolve()
STAR_ARCHIVE = Path(os.environ.get('NW_POPULAR_STAR_ARCHIVE', WORK / 'integration/dependencies/native-workbench-pack-star-1.0.0.zip')).resolve()
TEMP_ROOT = Path(os.environ.get('NW_POPULAR_TEMP_DIR', WORK / 'integration')).resolve()
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
STAR_SHA = 'edbeefff1c1149b632407f50a8a28847989a34eaa004752b43680fb6e29e4877'
PACK_VERSIONS = {identity: os.environ.get('NW_POPULAR_' + identity.upper() + '_VERSION', '1.0.0')
                 for identity in ('fastqc', 'multiqc', 'featurecounts', 'bedtools', 'blast')}
PACK_DIRS = {identity: Path(os.environ.get('NW_POPULAR_' + identity.upper() + '_PACK_DIR',
                                         PACK_ROOT / (identity + '-' + version))).resolve()
             for identity, version in PACK_VERSIONS.items()}
ARCHIVE_OVERRIDES = {identity: Path(os.environ['NW_POPULAR_' + identity.upper() + '_ARCHIVE']).resolve()
                     for identity in PACK_VERSIONS if 'NW_POPULAR_' + identity.upper() + '_ARCHIVE' in os.environ}
EVIDENCE = {
    'schema': 1, 'applicationVersion': '0.6.0',
    'testHost': sys.platform, 'pythonVersion': sys.version.split()[0],
    'nativeWindowsExecuted': False, 'scientificExecutablesExecuted': False,
    'nativeImporterExecuted': False, 'expectedPackVersions': PACK_VERSIONS,
    'scope': 'Released-app graph contracts and Python archive import; a copy callback substitutes native folder publication.',
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def files_below(root):
    return {path.relative_to(root).as_posix(): sha(path)
            for path in Path(root).rglob('*') if path.is_file()}


class PopularPipelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [STARTER, STAR_ARCHIVE] + [folder / 'pack.ini' for folder in PACK_DIRS.values()]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise unittest.SkipTest('Build packs and recover the published dependencies first: ' + '; '.join(missing))
        if sha(STARTER) != STARTER_SHA or sha(STAR_ARCHIVE) != STAR_SHA:
            raise RuntimeError('Released dependency ZIP hash differs; do not substitute an unverified application or STAR pack.')
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='contract-', dir=TEMP_ROOT)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        with zipfile.ZipFile(STARTER) as archive:
            archive.extractall(cls.root)
        cls.app = cls.root / 'native-workbench'
        for identity, version in PACK_VERSIONS.items():
            folder = identity + '-' + version
            shutil.copytree(PACK_DIRS[identity], cls.app / 'packs' / folder)
        # Extract only the existing pack payload. Its immutable ZIP is checked
        # above; the Python importer itself is exercised separately below.
        with zipfile.ZipFile(STAR_ARCHIVE) as archive:
            envelope = json.loads(archive.read('workbench-pack.json'))
            if (envelope['id'], envelope['version']) != ('star', '1.0.0'):
                raise RuntimeError('Wrong STAR dependency identity')
            manifest_members = [name for name in archive.namelist() if name.endswith('/pack.ini')]
            if len(manifest_members) != 1:
                raise RuntimeError('Expected one STAR manifest')
            prefix = manifest_members[0][:-len('pack.ini')]
            destination = cls.app / 'packs/star-1.0.0'
            for member in archive.infolist():
                if member.is_dir() or not member.filename.startswith(prefix):
                    continue
                target = destination / member.filename[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
        sys.path.insert(0, str(cls.app / 'workspace'))
        cls.addClassCleanup(lambda: sys.path.remove(str(cls.app / 'workspace')))
        cls.modules = {}
        for name in ('catalog', 'engine', 'pack_security', 'pack_manager', 'verify_installation', 'app_version'):
            module = importlib.import_module(name)
            if Path(module.__file__).resolve().parent != cls.app / 'workspace':
                raise RuntimeError('Use a fresh process; another application module was already imported: ' + name)
            cls.modules[name] = module
        if cls.modules['app_version'].APP_VERSION != '0.6.0':
            raise RuntimeError('This gate requires the released 0.6.0 application.')
        cls.catalog = cls.modules['catalog'].load_catalog(cls.app)
        if cls.catalog.get('errors'):
            raise RuntimeError('Pack discovery failed: ' + repr(cls.catalog['errors']))
        cls.tools = cls.catalog['tools']
        for identity, version in PACK_VERSIONS.items():
            if not any(tool.get('packId') == identity and tool.get('packVersion') == version
                       for tool in cls.tools.values()):
                raise RuntimeError('Expected current pack is absent: ' + identity + ' ' + version)
        cls.engine = cls.modules['engine'].Engine(cls.app, cls.catalog)
        cls.addClassCleanup(cls.engine.backend.shutdown)

    def select(self, pack, predicate=lambda tool: True):
        version = '1.0.0' if pack == 'star' else PACK_VERSIONS[pack]
        matches = [tool for tool in self.tools.values() if tool.get('packId') == pack
                   and tool.get('packVersion') == version and predicate(tool)]
        self.assertTrue(matches, 'Missing required workflow in ' + pack)
        return sorted(matches, key=lambda tool: tool['id'])[0]

    @staticmethod
    def port(tool, kind):
        return next(port for port in tool['ports'] if port['type'] == kind)

    @staticmethod
    def product(tool, kind):
        return next(output for output in tool['outputs'] if output['type'] == kind)

    @staticmethod
    def graph(name):
        return {'schema': 1, 'name': name, 'nodes': [], 'sources': []}

    def add_node(self, graph, tool, bindings=None, params=None, label=None):
        identity = 'step-' + str(len(graph['nodes']) + 1)
        inputs = {}
        for port in tool['ports']:
            if port['id'] in (bindings or {}):
                inputs[port['id']] = bindings[port['id']]
            elif port.get('min', 1):
                refs = []
                for _ in range(port.get('min', 1)):
                    source_id = 'input-' + str(len(graph['sources']) + 1)
                    # Graph-only paths: they are never prepared or executed.
                    files = {field: '/contract-only/' + source_id + '-' + field for field in port['manifestInputs']}
                    graph['sources'].append({'id': source_id, 'label': port['label'], 'type': port['type'], 'files': files})
                    refs.append(source_id)
                inputs[port['id']] = refs
        values = {param['id']: param['default'] for param in tool['params'] if param.get('default', '') != ''}
        values.update(params or {})
        node = {'id': identity, 'tool': tool['id'], 'inputs': inputs, 'params': values}
        if label:
            node['label'] = label
        graph['nodes'].append(node)
        return node

    def assert_valid(self, graph):
        review = self.engine.validate(graph, check_files=False)
        self.assertTrue(review['valid'], review)
        return review

    def assert_bad_type(self, tool, port, wrong_type):
        graph = self.graph('Reject incompatible scientific input')
        params = {param['id']: '0' for param in tool['params'] if param['id'] in ('strandness', 'strandedness')}
        node = self.add_node(graph, tool, params=params)
        source = next(source for source in graph['sources'] if source['id'] == node['inputs'][port['id']][0])
        source['type'] = wrong_type
        review = self.engine.validate(graph, check_files=False)
        self.assertFalse(review['valid'])
        self.assertTrue(any(wrong_type + ' cannot feed ' in error['message'] for error in review['errors']), review)

    def fastqc_zip(self, tool):
        pack = self.modules['catalog'].load_pack(self.app / tool['packFolder'] / 'pack.ini')
        outputs = {output['id']: output for output in pack['workflows'][tool['workflowId']]['outputs']}
        return next(output for output in tool['outputs'] if output['type'] == 'metrics'
                    and any(outputs[identity]['path'].endswith('.zip') for identity in output['manifestOutputs']))

    def test_released_application_bytes_are_unmodified(self):
        verified = []
        with zipfile.ZipFile(STARTER) as archive:
            for member in archive.infolist():
                relative = member.filename.removeprefix('native-workbench/')
                if member.is_dir() or not (relative.startswith('workspace/') or relative == 'WorkbenchBridge.exe'):
                    continue
                self.assertEqual(sha(self.app / relative), hashlib.sha256(archive.read(member)).hexdigest(), relative)
                verified.append(relative)
        self.assertIn('workspace/engine.py', verified)
        self.assertIn('WorkbenchBridge.exe', verified)
        EVIDENCE['releasedApplicationFilesVerified'] = verified
        EVIDENCE['starterSha256'] = STARTER_SHA
        EVIDENCE['starDependencySha256'] = STAR_SHA

    def test_pack_integrity_and_declared_scientific_assertions(self):
        EVIDENCE['installedInventory'] = self.modules['verify_installation'].check_packs(self.app, self.catalog)
        inspected = []
        for row in self.catalog['packs']:
            if row['id'] not in PACK_VERSIONS or row['version'] != PACK_VERSIONS[row['id']]:
                continue
            pack = self.modules['catalog'].load_pack(self.app / row['folder'] / 'pack.ini')
            for asset in ('workbench-schema', 'workbench-checks'):
                self.assertIn(asset, pack['assets'])
            spec = json.loads((self.app / row['folder'] / pack['assets']['workbench-checks']['path']).read_text())
            self.assertGreater(len(spec['checks']), 0)
            self.assertTrue(all(case.get('expect') for case in spec['checks']))
            inspected.append({'id': row['id'], 'version': row['version'], 'manifestSha256': row['manifestSha256'],
                              'scientificChecksDeclared': len(spec['checks'])})
        self.assertEqual({row['id'] for row in inspected}, set(PACK_VERSIONS))
        EVIDENCE['newPacks'] = inspected

    def test_fastqc_sibling_branches_merge_into_multiqc_with_provenance(self):
        fastqc = self.select('fastqc', lambda tool: any(p['type'] == 'reads' for p in tool['ports']))
        multiqc = self.select('multiqc', lambda tool: tool['workflowId'] == 'aggregate')
        product = self.fastqc_zip(fastqc)
        incoming = self.port(multiqc, 'metrics')
        self.assertEqual(len(product['manifestOutputs']), 1)
        self.assertGreaterEqual(incoming['max'], 2)
        graph = self.graph('Read quality branches and a shared report')
        first = self.add_node(graph, fastqc, label='Quality sample A')
        second = self.add_node(graph, fastqc, label='Quality sample B')
        refs = [node['id'] + '::' + product['id'] for node in (first, second)]
        report = self.add_node(graph, multiqc, {incoming['id']: refs}, label='Combined quality report')
        self.assert_valid(graph)
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1', 'step-2']},
                                                         {'rank': 2, 'nodes': ['step-3']}])
        saved = self.engine.save_pipeline(graph)
        for node in saved['nodes']:
            self.assertEqual(node['pin'], self.modules['engine'].pin_for(self.tools[node['tool']]))
        self.assertEqual(saved['nodes'][2]['inputs'][incoming['id']], refs)
        self.assertTrue(all('files' not in source for source in saved['sources']))
        methods = self.engine.methods(graph)
        for label in ('Quality sample A', 'Quality sample B', 'Combined quality report', product['label']):
            self.assertIn(label, methods)
        self.assertIn('Planned methods', methods)
        invalid = copy.deepcopy(graph)
        invalid['nodes'][2]['inputs'][incoming['id']] = [refs[0], refs[0]]
        review = self.engine.validate(invalid, check_files=False)
        self.assertFalse(review['valid'])
        self.assertTrue(any('cannot be connected twice' in error['message'] for error in review['errors']), review)
        EVIDENCE['qualityMergeGraph'] = {'tools': [node['tool'] for node in graph['nodes']],
                                        'ranks': self.engine.rank_groups(graph), 'incoming': report['inputs'],
                                        'savedPins': [node['pin'] for node in saved['nodes']],
                                        'duplicateConnectionRejected': True}

    def test_star_alignment_fans_out_to_counting_and_reporting(self):
        star = self.select('star', lambda tool: tool['workflowId'] == 'rna-paired')
        counts = self.select('featurecounts', lambda tool: tool['workflowId'] == 'count-paired')
        multiqc = self.select('multiqc', lambda tool: tool['workflowId'] == 'aggregate')
        alignment = self.product(star, 'bam-rna')
        incoming = self.port(counts, 'bam-rna')
        self.assertEqual(incoming.get('requiredState', {}).get('pairing'), 'paired')
        self.assertEqual(len(alignment['manifestOutputs']), len(incoming['manifestInputs']))
        strand = next(param for param in counts['params'] if param['id'] in ('strandness', 'strandedness'))
        self.assertEqual(strand.get('default', ''), '', 'Library strandedness must not be guessed.')
        graph = self.graph('Compare RNA count filters and report both branches')
        first = self.add_node(graph, star)
        second = self.add_node(graph, counts, {incoming['id']: [first['id'] + '::' + alignment['id']]},
                               {strand['id']: '0', 'mapq': '0'}, label='Counts at MAPQ zero')
        third = self.add_node(graph, counts, {incoming['id']: [first['id'] + '::' + alignment['id']]},
                              {strand['id']: '0', 'mapq': '20'}, label='Counts at MAPQ twenty')
        star_summary = next(output for output in star['outputs'] if output['type'] == 'metrics' and 'summary' in output['id'])
        count_summary = next(output for output in counts['outputs'] if output['type'] == 'metrics' and 'summary' in output['id'])
        report_port = self.port(multiqc, 'metrics')
        self.add_node(graph, multiqc, {report_port['id']: [first['id'] + '::' + star_summary['id'],
                                                         second['id'] + '::' + count_summary['id'],
                                                         third['id'] + '::' + count_summary['id']]})
        self.assert_valid(graph)
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1']},
                                                         {'rank': 2, 'nodes': ['step-2', 'step-3']},
                                                         {'rank': 3, 'nodes': ['step-4']}])
        self.engine.save_pipeline(graph)
        omitted = copy.deepcopy(graph)
        del omitted['nodes'][1]['params'][strand['id']]
        self.assertFalse(self.engine.validate(omitted, check_files=False)['valid'])
        wrong_pairing = self.graph('Reject single RNA alignment for paired counting')
        single = self.select('star', lambda tool: tool['workflowId'] == 'rna-single')
        single_node = self.add_node(wrong_pairing, single)
        self.add_node(wrong_pairing, counts, {incoming['id']: [single_node['id'] + '::' + self.product(single, 'bam-rna')['id']]},
                      {strand['id']: '0'})
        pairing_review = self.engine.validate(wrong_pairing, check_files=False)
        self.assertFalse(pairing_review['valid'])
        self.assertTrue(any('pairing=paired' in error['message'] for error in pairing_review['errors']), pairing_review)
        EVIDENCE['rnaCountingReportingGraph'] = {'tools': [node['tool'] for node in graph['nodes']],
                                               'ranks': self.engine.rank_groups(graph),
                                               'explicitStrandednessRequired': True,
                                               'singleIntoPairedRejected': True}

    def test_bedtools_extracted_sequences_feed_nucleotide_blast_only(self):
        extract = self.select('bedtools', lambda tool: tool['workflowId'] == 'getfasta')
        blastn = self.select('blast', lambda tool: tool['workflowId'] == 'blastn')
        fasta = self.product(extract, 'fasta-nucleotide')
        query = next(port for port in blastn['ports'] if port['id'] == 'query')
        self.assertIn('fasta-nucleotide', query['accepts'])
        graph = self.graph('Extract genomic intervals and search local nucleotide sequences')
        first = self.add_node(graph, extract)
        self.add_node(graph, blastn, {query['id']: [first['id'] + '::' + fasta['id']]})
        self.assert_valid(graph)
        self.engine.save_pipeline(graph)
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1']}, {'rank': 2, 'nodes': ['step-2']}])
        blastp = self.select('blast', lambda tool: tool['workflowId'] == 'blastp')
        self.assert_bad_type(blastp, next(port for port in blastp['ports'] if port['id'] == 'query'), 'fasta-nucleotide')
        self.assert_bad_type(blastn, query, 'fasta-protein')
        EVIDENCE['intervalSequenceSearchGraph'] = {'tools': [extract['id'], blastn['id']],
                                                 'nucleotideProteinConfusionRejected': True}

    def test_unrelated_biological_types_are_rejected(self):
        fastqc = self.select('fastqc', lambda tool: any(p['type'] == 'reads' for p in tool['ports']))
        counts = self.select('featurecounts', lambda tool: tool['workflowId'] == 'count-paired')
        multiqc = self.select('multiqc', lambda tool: tool['workflowId'] == 'aggregate')
        bedtools = self.select('bedtools', lambda tool: tool['workflowId'] == 'getfasta')
        for tool, port, wrong in ((fastqc, self.port(fastqc, 'reads'), 'fasta-nucleotide'),
                                  (counts, self.port(counts, 'bam-rna'), 'bam'),
                                  (multiqc, self.port(multiqc, 'metrics'), 'bam-rna'),
                                  (bedtools, self.port(bedtools, 'bed'), 'vcf')):
            with self.subTest(tool=tool['id'], wrong=wrong):
                self.assert_bad_type(tool, port, wrong)
        EVIDENCE['incompatibleInputsRejected'] = ['FASTA to read QC', 'DNA BAM to RNA counting',
                                                 'RNA BAM to report aggregation', 'VCF to BED-only intervals']

    def test_saved_manifest_pins_cannot_silently_change(self):
        fastqc = self.select('fastqc', lambda tool: any(p['type'] == 'reads' for p in tool['ports']))
        multiqc = self.select('multiqc', lambda tool: tool['workflowId'] == 'aggregate')
        graph = self.graph('Pin quality tools')
        first = self.add_node(graph, fastqc)
        self.add_node(graph, multiqc, {self.port(multiqc, 'metrics')['id']: [first['id'] + '::' + self.fastqc_zip(fastqc)['id']]})
        saved = self.engine.save_pipeline(graph)
        saved['nodes'][0]['pin']['manifestSha256'] = '0' * 64
        review = self.engine.validate(saved, check_files=False)
        self.assertFalse(review['valid'])
        self.assertTrue(any('original pack' in error['message'] for error in review['errors']), review)
        EVIDENCE['changedSavedManifestRejected'] = True

    def test_offline_archives_import_once_and_preserve_existing_bytes(self):
        manager_module = self.modules['pack_manager']
        catalog_module = self.modules['catalog']
        root = self.root / 'offline import with spaces'
        (root / 'packs').mkdir(parents=True)
        starters = [row for row in self.catalog['packs'] if row['id'] in {'align', 'bam', 'variants'}]
        self.assertEqual({row['id'] for row in starters}, {'align', 'bam', 'variants'})
        for row in starters:
            shutil.copytree(self.app / row['folder'], root / row['folder'])
        starter_bytes = files_below(root / 'packs')
        calls = []

        def copy_publication(source):
            pack = catalog_module.load_pack(Path(source) / 'pack.ini')
            destination = root / 'packs' / (pack['id'] + '-' + pack['version'])
            calls.append((pack['id'], pack['version']))
            shutil.copytree(source, destination)
            return {'success': True, 'folder': str(destination)}

        manager = manager_module.PackManager(root, copy_publication)
        selected = {}
        candidates = sorted(set(ARCHIVES.glob('*.zip')) | set(ARCHIVE_OVERRIDES.values()))
        for candidate in candidates:
            with zipfile.ZipFile(candidate) as archive:
                if 'workbench-pack.json' not in archive.namelist():
                    continue
                envelope = json.loads(archive.read('workbench-pack.json'))
            if envelope['id'] in PACK_VERSIONS and envelope['version'] == PACK_VERSIONS[envelope['id']]:
                if envelope['id'] in ARCHIVE_OVERRIDES and candidate != ARCHIVE_OVERRIDES[envelope['id']]:
                    continue
                self.assertNotIn(envelope['id'], selected, 'Multiple archives claim the same expected pack version.')
                selected[envelope['id']] = (candidate, envelope)
        self.assertEqual(set(selected), set(PACK_VERSIONS), 'All five exact-version installable ZIPs are required.')
        imported = []
        for identity, (archive, envelope) in sorted(selected.items()):
            result = manager.import_archive(archive)
            self.assertTrue(result['success'])
            self.assertFalse(result['publisherVerified'])
            folder = root / 'packs' / (identity + '-' + envelope['version'])
            receipt = root / 'user-data/pack-receipts' / (identity + '-' + envelope['version'] + '.json')
            before = files_below(root)
            calls_before = len(calls)
            with self.assertRaisesRegex(ValueError, 'already installed'):
                manager.import_archive(archive)
            self.assertEqual(len(calls), calls_before, 'Duplicate reached the folder publication callback.')
            after = files_below(root)
            changes = {'packId': identity,
                       'added': {key: after[key] for key in after.keys() - before.keys()},
                       'removed': {key: before[key] for key in before.keys() - after.keys()},
                       'changed': {key: {'before': before[key], 'after': after[key]}
                                   for key in before.keys() & after.keys() if before[key] != after[key]}}
            if any(changes[key] for key in ('added', 'removed', 'changed')):
                EVIDENCE.setdefault('unexpectedDuplicateImportChanges', []).append(changes)
            self.assertEqual(after, before, 'Installed files or receipts changed: ' + json.dumps(changes))
            self.assertEqual(sha(folder / 'pack.ini'), envelope['manifestSha256'])
            self.assertEqual(json.loads(receipt.read_text())['manifestSha256'], envelope['manifestSha256'])
            graph_pack_folder = self.app / 'packs' / (identity + '-' + envelope['version'])
            self.assertEqual(files_below(folder), files_below(graph_pack_folder),
                             'Pack ZIP payload differs from the graph-tested pack folder.')
            imported.append({'id': identity, 'version': envelope['version'], 'archiveSha256': sha(archive),
                             'manifestSha256': envelope['manifestSha256'], 'duplicateVersionRejected': True,
                             'receiptAndInstalledBytesUnchanged': True})
        catalog = catalog_module.load_catalog(root)
        self.assertFalse(catalog.get('errors'), catalog)
        self.assertEqual({pack['id'] for pack in catalog['packs']}, {'align', 'bam', 'variants'} | set(PACK_VERSIONS))
        self.assertEqual({relative: sha(root / 'packs' / relative) for relative in starter_bytes}, starter_bytes)
        EVIDENCE['offlineStaticImports'] = imported
        EVIDENCE['starterPackFilesPreserved'] = len(starter_bytes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PopularPipelineContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), testSourceSha256=sha(__file__),
                    success=result.wasSuccessful() and result.testsRun > 0 and not result.skipped)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if EVIDENCE['success'] else 1)
