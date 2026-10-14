"""GATK graph/import contracts against the unchanged released Workbench 0.6.0.

No scientific executable or native Windows importer runs in this suite. The
archive importer uses a Python copy callback for publication; native execution
and the GATK boundary adapter have separate scientific/regression gates.

Configuration:
  NW_GATK_STARTER_ZIP: SHA-pinned released 0.6.0 starter ZIP
  NW_GATK_PACK_DIR: prepared GATK pack folder, default packs/gatk-1.0.0
  NW_GATK_ARCHIVE: installable ZIP with the same payload as the prepared pack
  NW_GATK_VERSION: expected numeric pack version, default 1.0.0
  NW_GATK_TEMP_DIR: writable parent for disposable applications

Run in a fresh Python process, optionally with --report /path/to/report.json.
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
WORK = SOURCE.parent / 'gatk-build'
VERSION = os.environ.get('NW_GATK_VERSION', '1.0.0')
STARTER = Path(os.environ.get('NW_GATK_STARTER_ZIP', WORK / 'downloads/native-workbench-0.6.0-starter-windows.zip')).resolve()
PACK = Path(os.environ.get('NW_GATK_PACK_DIR', SOURCE / ('packs/gatk-' + VERSION))).resolve()
ARCHIVE = Path(os.environ.get('NW_GATK_ARCHIVE', WORK / ('releases/native-workbench-pack-gatk-' + VERSION + '.zip'))).resolve()
TEMP_ROOT = Path(os.environ.get('NW_GATK_TEMP_DIR', WORK / 'integration')).resolve()
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
OPERATIONS = {
    'mark-duplicates', 'bqsr', 'haplotypecaller-vcf', 'haplotypecaller-gvcf',
    'combine-gvcfs', 'genotype-gvcfs', 'select-variants', 'variant-filtration',
    'validate-variants',
}
EVIDENCE = {
    'schema': 1, 'applicationVersion': '0.6.0', 'packId': 'gatk',
    'packVersion': VERSION, 'testHost': sys.platform,
    'pythonVersion': sys.version.split()[0],
    'nativeWindowsExecuted': False, 'scientificExecutablesExecuted': False,
    'nativeImporterExecuted': False,
    'scope': 'Released-app graph contracts and Python archive import; copy callback substitutes native folder publication.',
    'gvcfTypingLimitation': 'Released 0.6.0 represents GATK gVCFs as generic file products. Ordinary VCF ports reject them, but role validation for other generic files belongs to the separately tested pack adapter.',
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


def checked_stream_copy(source, destination):
    """Copy fixtures without filesystem fast-copy/offload, checking every byte.

    The managed test filesystem produced truncated/temporary large-file copies
    with copy2. This changes fixture transport only; exact payload and duplicate
    immutability assertions below remain unchanged, including unexpected files.
    """
    source, destination = Path(source), Path(destination)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
    if source.stat().st_size != destination.stat().st_size or sha(source) != sha(destination):
        raise RuntimeError('Fixture copy differs: ' + str(destination))
    shutil.copystat(source, destination)
    return str(destination)


class GatkPipelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [str(path) for path in (STARTER, PACK / 'pack.ini', ARCHIVE) if not path.is_file()]
        if missing:
            raise unittest.SkipTest('Recover released app and prepare/package GATK first: ' + '; '.join(missing))
        if sha(STARTER) != STARTER_SHA:
            raise RuntimeError('Released starter hash differs; do not substitute edited application bytes.')
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='gatk-contract-', dir=TEMP_ROOT)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        with zipfile.ZipFile(STARTER) as archive:
            archive.extractall(cls.root)
        cls.app = cls.root / 'native-workbench'
        cls.pack_folder = cls.app / 'packs' / ('gatk-' + VERSION)
        shutil.copytree(PACK, cls.pack_folder, copy_function=checked_stream_copy)
        EVIDENCE['graphPackManifestSha256'] = sha(cls.pack_folder / 'pack.ini')
        sys.path.insert(0, str(cls.app / 'workspace'))
        cls.addClassCleanup(lambda: sys.path.remove(str(cls.app / 'workspace')))
        cls.modules = {}
        for name in ('catalog', 'engine', 'pack_security', 'pack_manager', 'verify_installation', 'app_version'):
            module = importlib.import_module(name)
            if Path(module.__file__).resolve().parent != cls.app / 'workspace':
                raise RuntimeError('Use a fresh process; another app module is already imported: ' + name)
            cls.modules[name] = module
        if cls.modules['app_version'].APP_VERSION != '0.6.0':
            raise RuntimeError('This gate requires the released 0.6.0 application.')
        cls.catalog = cls.modules['catalog'].load_catalog(cls.app)
        if cls.catalog.get('errors'):
            raise RuntimeError('Pack discovery failed: ' + repr(cls.catalog['errors']))
        cls.tools = cls.catalog['tools']
        cls.operations = {tool['workflowId']: tool for tool in cls.tools.values()
                          if tool.get('packId') == 'gatk' and tool.get('packVersion') == VERSION}
        if set(cls.operations) != OPERATIONS:
            raise RuntimeError('Expected exact supported GATK operations: ' + repr(set(cls.operations)))
        cls.engine = cls.modules['engine'].Engine(cls.app, cls.catalog)
        cls.addClassCleanup(cls.engine.backend.shutdown)

    @staticmethod
    def graph(name):
        return {'schema': 1, 'name': name, 'nodes': [], 'sources': []}

    @staticmethod
    def port(tool, kind):
        return next(port for port in tool['ports'] if port['type'] == kind)

    @staticmethod
    def product(tool, kind):
        return next(output for output in tool['outputs'] if output['type'] == kind)

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
                    files = {field: '/contract-only/' + source_id + '-' + field for field in port['manifestInputs']}
                    graph['sources'].append({'id': source_id, 'label': port['label'], 'type': port['type'], 'files': files})
                    refs.append(source_id)
                inputs[port['id']] = refs
        values = {param['id']: param['default'] for param in tool['params'] if param.get('default', '') != ''}
        if any(param['id'] == 'sample' for param in tool['params']):
            values['sample'] = 'SAMPLE_A'
        values.update(params or {})
        node = {'id': identity, 'tool': tool['id'], 'inputs': inputs, 'params': values}
        if label:
            node['label'] = label
        graph['nodes'].append(node)
        return node

    def connect(self, node, output):
        return node['id'] + '::' + output['id']

    def assert_valid(self, graph):
        review = self.engine.validate(graph, check_files=False)
        self.assertTrue(review['valid'], review)
        return review

    def assert_invalid(self, graph, message):
        review = self.engine.validate(graph, check_files=False)
        self.assertFalse(review['valid'], review)
        self.assertTrue(any(message in error['message'] for error in review['errors']), review)
        return review

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

    def test_all_operations_are_individually_discoverable_with_checks(self):
        EVIDENCE['installedInventory'] = self.modules['verify_installation'].check_packs(self.app, self.catalog)
        manifest = self.modules['catalog'].load_pack(self.pack_folder / 'pack.ini')
        self.assertEqual(set(manifest['workflows']), OPERATIONS)
        checks_path = self.pack_folder / manifest['assets']['workbench-checks']['path']
        spec = json.loads(checks_path.read_text())
        self.assertTrue(spec['checks'])
        self.assertTrue(all(case.get('expect') for case in spec['checks']))
        self.assertEqual({case['workflow'] for case in spec['checks']}, OPERATIONS,
                         'Every exposed operation needs a declared scientific installation check.')
        for operation, tool in self.operations.items():
            with self.subTest(operation=operation):
                self.assertTrue(tool.get('methodsDescription'), 'Every operation needs its own planned methods.')
                self.assertTrue(tool.get('citations'), 'Upstream methods attribution must be retained.')
                graph = self.graph('Standalone ' + operation)
                self.add_node(graph, tool)
                self.assert_valid(graph)
                self.assertEqual(len(graph['nodes']), 1)
        # The native installation gate restricts its catalogue to the candidate
        # pack. Merely declaring an unused SAMtools executable in pack.ini does
        # not expose it to the released engine's BAM preflight selection.
        selected = copy.deepcopy(self.catalog)
        selected['tools'] = {tool['id']: tool for tool in self.operations.values()}
        selected['toolVersions'] = {key: [tool] for key, tool in selected['tools'].items()}
        selected['packs'] = [row for row in selected['packs'] if row['id'] == 'gatk' and row['version'] == VERSION]
        engine = self.modules['engine'].Engine(self.app, selected)
        try:
            for operation in ('mark-duplicates', 'bqsr', 'haplotypecaller-vcf', 'haplotypecaller-gvcf'):
                tool = self.operations[operation]
                helper = engine._samtools_selection(tool)
                self.assertEqual(helper['executable']['id'], 'samtools')
                self.assertEqual(helper['pin'], self.modules['engine'].pin_for(tool))
        finally:
            engine.backend.shutdown()
        EVIDENCE['operations'] = sorted(self.operations)
        EVIDENCE['scientificChecksDeclared'] = len(spec['checks'])
        EVIDENCE['bamPreflightHelperOwnedByPack'] = True

    def test_preparation_and_two_sample_joint_genotyping_have_explicit_branches(self):
        mark = self.operations['mark-duplicates']
        bqsr = self.operations['bqsr']
        call = self.operations['haplotypecaller-gvcf']
        combine = self.operations['combine-gvcfs']
        genotype = self.operations['genotype-gvcfs']
        select = self.operations['select-variants']
        filtering = self.operations['variant-filtration']
        graph = self.graph('Two germline samples with shared references and joint genotyping')
        marked = []
        for label in ('Sample A duplicate marking', 'Sample B duplicate marking'):
            marked.append(self.add_node(graph, mark, label=label))
        recalibrated = []
        for index, node in enumerate(marked):
            recalibrated.append(self.add_node(graph, bqsr,
                {self.port(bqsr, 'bam')['id']: [self.connect(node, self.product(mark, 'bam'))]},
                params={'sample': 'SAMPLE_A' if index == 0 else 'SAMPLE_B'},
                label='Sample ' + ('A' if index == 0 else 'B') + ' recalibration'))
        calls = []
        for index, node in enumerate(recalibrated):
            calls.append(self.add_node(graph, call,
                {self.port(call, 'bam')['id']: [self.connect(node, self.product(bqsr, 'bam'))]},
                params={'sample': 'SAMPLE_A' if index == 0 else 'SAMPLE_B'},
                label='Sample ' + ('A' if index == 0 else 'B') + ' reference-confidence calls'))
        # Share exactly one reference source across all reference-dependent steps.
        shared_reference = None
        for node in graph['nodes']:
            tool = self.tools[node['tool']]
            for port in tool['ports']:
                if port['type'] == 'reference':
                    shared_reference = shared_reference or node['inputs'][port['id']][0]
                    node['inputs'][port['id']] = [shared_reference]
        merge_port = next(port for port in combine['ports'] if port['id'] == 'gvcfs')
        self.assertEqual(merge_port['type'], 'file')
        self.assertEqual(len(merge_port['fields']), 1)
        self.assertEqual(merge_port['fields'][0]['type'], 'files', 'Fan-in must expand actual files.')
        self.assertEqual(merge_port['min'], 2)
        self.assertEqual(merge_port['max'], 32)
        gvcf_product = next(output for output in call['outputs'] if output['id'] == 'gvcf')
        references = [self.connect(node, gvcf_product) for node in calls]
        combined = self.add_node(graph, combine, {merge_port['id']: references}, label='Combine the two gVCFs')
        genotyped = self.add_node(graph, genotype,
            {'gvcf': [self.connect(combined, next(output for output in combine['outputs'] if output['id'] == 'gvcf'))]},
            label='Jointly genotype both samples')
        variant = self.product(genotype, 'vcf')
        for tool, label in ((select, 'Select a variant subset'), (filtering, 'Annotate chosen variant filters')):
            self.add_node(graph, tool, {self.port(tool, 'vcf')['id']: [self.connect(genotyped, variant)]}, label=label)
        for node in graph['nodes']:
            for port in self.tools[node['tool']]['ports']:
                if port['type'] == 'reference':
                    node['inputs'][port['id']] = [shared_reference]
        used = {ref for node in graph['nodes'] for refs in node['inputs'].values() for ref in refs}
        graph['sources'] = [source for source in graph['sources'] if source['id'] in used]
        self.assert_valid(graph)
        expected = [
            {'rank': 1, 'nodes': ['step-1', 'step-2']},
            {'rank': 2, 'nodes': ['step-3', 'step-4']},
            {'rank': 3, 'nodes': ['step-5', 'step-6']},
            {'rank': 4, 'nodes': ['step-7']},
            {'rank': 5, 'nodes': ['step-8']},
            {'rank': 6, 'nodes': ['step-9', 'step-10']},
        ]
        self.assertEqual(self.engine.rank_groups(graph), expected)
        saved = self.engine.save_pipeline(graph)
        self.assertEqual(saved['nodes'][6]['inputs'][merge_port['id']], references)
        self.assertTrue(all('files' not in source for source in saved['sources']))
        for node in saved['nodes']:
            self.assertEqual(node['pin'], self.modules['engine'].pin_for(self.tools[node['tool']]))
            self.assertNotIn('sample', node['params'], 'Reusable pipelines must not carry a specimen SM binding.')
        preset = self.engine.save_preset(calls[0])
        self.assertNotIn('sample', preset['params'])
        self.assertNotIn('inputs', preset)
        methods = self.engine.methods(graph)
        self.assertIn('Planned methods', methods)
        for node in graph['nodes']:
            self.assertIn(node['label'], methods)
        for name in ('HaplotypeCaller', 'CombineGVCFs', 'GenotypeGVCFs'):
            self.assertIn(name, methods)
        # File-list resolution must preserve the two distinct upstream files.
        produced = {
            ref: {'manifestOutputs': gvcf_product['manifestOutputs'],
                  'files': {gvcf_product['manifestOutputs'][0]: '/results/sample-' + str(index) + '.g.vcf'}}
            for index, ref in enumerate(references)
        }
        values = self.engine._resolve_values(
            {'tool': combine, 'inputs': {merge_port['id']: references}, 'params': {}}, {}, produced)
        self.assertEqual(values[merge_port['manifestInputs'][0]].splitlines(),
                         ['/results/sample-0.g.vcf', '/results/sample-1.g.vcf'])
        EVIDENCE['jointGenotypingGraph'] = {'tools': [node['tool'] for node in graph['nodes']],
            'ranks': expected, 'incomingGvcfs': references, 'savedPins': [node['pin'] for node in saved['nodes']],
            'fileListResolutionPreserved': True, 'namedMethodsProvenance': True}

    def test_gvcfs_and_ordinary_variant_calls_are_not_interchangeable(self):
        call_g = self.operations['haplotypecaller-gvcf']
        gvcf = next(output for output in call_g['outputs'] if output['id'] == 'gvcf')
        self.assertEqual(gvcf['type'], 'file', 'Released core cannot safely represent a gVCF as ordinary VCF.')
        self.assertIn('gvcf', gvcf['label'].lower())
        rejected = []
        for operation in ('bqsr', 'select-variants', 'variant-filtration', 'validate-variants'):
            tool = self.operations[operation]
            graph = self.graph('Reject reference-confidence blocks as ordinary variant calls')
            first = self.add_node(graph, call_g)
            self.add_node(graph, tool, {self.port(tool, 'vcf')['id']: [self.connect(first, gvcf)]})
            self.assert_invalid(graph, 'file cannot feed vcf')
            rejected.append(operation)
        statistics = next(tool for tool in self.tools.values() if tool.get('packId') == 'variants'
                          and tool.get('workflowId') == 'statistics')
        graph = self.graph('Reject gVCF into existing BCFtools statistics')
        first = self.add_node(graph, call_g)
        self.add_node(graph, statistics, {self.port(statistics, 'vcf')['id']: [self.connect(first, gvcf)]})
        self.assert_invalid(graph, 'file cannot feed vcf')
        call_v = self.operations['haplotypecaller-vcf']
        for operation, port_id in (('genotype-gvcfs', 'gvcf'), ('combine-gvcfs', 'gvcfs')):
            tool = self.operations[operation]
            graph = self.graph('Reject ordinary VCF as reference-confidence input')
            first = self.add_node(graph, call_v)
            refs = [self.connect(first, self.product(call_v, 'vcf'))]
            if operation == 'combine-gvcfs':
                second = self.add_node(graph, call_v)
                refs.append(self.connect(second, self.product(call_v, 'vcf')))
            self.add_node(graph, tool, {port_id: refs})
            self.assert_invalid(graph, 'vcf cannot feed file')
        EVIDENCE['variantKindsNotInterchangeable'] = {'gvcfRejectedBy': rejected + ['variants/statistics'],
            'ordinaryVcfRejectedBy': ['genotype-gvcfs', 'combine-gvcfs'],
            'genericFileRoleCheckRequiresAdapter': True}

    def test_rna_inputs_and_known_bad_alignment_order_are_rejected(self):
        for operation in ('mark-duplicates', 'bqsr', 'haplotypecaller-vcf', 'haplotypecaller-gvcf'):
            tool = self.operations[operation]
            incoming = self.port(tool, 'bam')
            graph = self.graph('Reject RNA alignment for DNA GATK operation')
            node = self.add_node(graph, tool)
            source = next(source for source in graph['sources'] if source['id'] == node['inputs'][incoming['id']][0])
            source['type'] = 'bam-rna'
            self.assert_invalid(graph, 'bam-rna cannot feed bam')
        caller = self.operations['haplotypecaller-vcf']
        self.assertEqual(self.port(caller, 'bam')['requiredState']['sort'], 'coordinate')
        name_sort = next(tool for tool in self.tools.values() if tool.get('packId') == 'bam'
                         and tool.get('workflowId') == 'name-sort')
        graph = self.graph('Reject query-name sorting before coordinate traversal')
        first = self.add_node(graph, name_sort)
        self.add_node(graph, caller, {self.port(caller, 'bam')['id']: [self.connect(first, self.product(name_sort, 'bam'))]})
        self.assert_invalid(graph, 'sort=coordinate')
        marked = self.product(self.operations['mark-duplicates'], 'bam')
        self.assertEqual(marked['state'].get('duplicates'), 'marked')
        self.assertEqual(marked['state'].get('sort'), 'coordinate')
        recalibrated = self.product(self.operations['bqsr'], 'bam')
        self.assertNotIn('duplicates', recalibrated['state'], 'BQSR must not claim it marked previously unmarked inputs.')
        self.assertNotIn('mateFixed', marked['state'], 'Duplicate marking does not establish SAMtools fixmate provenance.')
        EVIDENCE['alignmentContracts'] = {'rnaToDnaRejected': True, 'querynameToCallerRejected': True,
            'duplicateMarkingStateTruthful': True, 'bqsrDoesNotInventDuplicateMarking': True}

    def test_fan_in_cardinality_duplicate_sources_and_saved_pins_are_enforced(self):
        combine = self.operations['combine-gvcfs']
        graph = self.graph('Guard gVCF merge inputs')
        node = self.add_node(graph, combine)
        self.assert_valid(graph)
        port = next(port for port in combine['ports'] if port['id'] == 'gvcfs')
        one = copy.deepcopy(graph)
        one['nodes'][0]['inputs'][port['id']] = one['nodes'][0]['inputs'][port['id']][:1]
        self.assert_invalid(one, 'needs 2')
        duplicate = copy.deepcopy(graph)
        refs = duplicate['nodes'][0]['inputs'][port['id']]
        refs[1] = refs[0]
        self.assert_invalid(duplicate, 'cannot be connected twice')
        genotype = self.operations['genotype-gvcfs']
        self.add_node(graph, genotype, {'gvcf': [self.connect(node, next(output for output in combine['outputs'] if output['id'] == 'gvcf'))]})
        saved = self.engine.save_pipeline(graph)
        saved['nodes'][0]['pin']['manifestSha256'] = '0' * 64
        self.assert_invalid(saved, 'original pack')
        EVIDENCE['fanInGuards'] = {'minimumTwoSources': True, 'duplicateConnectionRejected': True,
                                  'changedSavedManifestRejected': True}

    def test_offline_archive_matches_graph_payload_and_duplicate_is_immutable(self):
        with zipfile.ZipFile(ARCHIVE) as archive:
            envelope = json.loads(archive.read('workbench-pack.json'))
        self.assertEqual((envelope['id'], envelope['version']), ('gatk', VERSION))
        root = self.root / 'offline import with spaces'
        (root / 'packs').mkdir(parents=True)
        for identity in ('align', 'bam', 'variants'):
            row = next(row for row in self.catalog['packs'] if row['id'] == identity)
            shutil.copytree(self.app / row['folder'], root / row['folder'], copy_function=checked_stream_copy)
        starter_files = files_below(root / 'packs')
        calls = []

        def copy_publication(source):
            manifest = self.modules['catalog'].load_pack(Path(source) / 'pack.ini')
            destination = root / 'packs' / (manifest['id'] + '-' + manifest['version'])
            calls.append((manifest['id'], manifest['version']))
            shutil.copytree(source, destination, copy_function=checked_stream_copy)
            return {'success': True, 'folder': str(destination)}

        manager = self.modules['pack_manager'].PackManager(root, copy_publication)
        result = manager.import_archive(ARCHIVE)
        self.assertTrue(result['success'])
        self.assertFalse(result['publisherVerified'])
        folder = root / 'packs' / ('gatk-' + VERSION)
        self.assertEqual(sha(folder / 'pack.ini'), envelope['manifestSha256'])
        imported_files, graph_files = files_below(folder), files_below(self.pack_folder)
        payload_changes = {
            'onlyImported': {key: imported_files[key] for key in imported_files.keys() - graph_files.keys()},
            'onlyGraphCopy': {key: graph_files[key] for key in graph_files.keys() - imported_files.keys()},
            'changed': {key: {'imported': imported_files[key], 'graphCopy': graph_files[key]}
                        for key in imported_files.keys() & graph_files.keys() if imported_files[key] != graph_files[key]},
        }
        if any(payload_changes.values()):
            EVIDENCE['unexpectedArchivePayloadDifferences'] = payload_changes
        self.assertFalse(any(payload_changes.values()),
                         'Archive differs from exact disposable graph-tested payload: ' + json.dumps(payload_changes))
        before = files_below(root)
        call_count = len(calls)
        with self.assertRaisesRegex(ValueError, 'already installed'):
            manager.import_archive(ARCHIVE)
        self.assertEqual(len(calls), call_count, 'Duplicate reached the publication callback.')
        after = files_below(root)
        changes = {
            'added': {key: after[key] for key in after.keys() - before.keys()},
            'removed': {key: before[key] for key in before.keys() - after.keys()},
            'changed': {key: {'before': before[key], 'after': after[key]}
                        for key in before.keys() & after.keys() if before[key] != after[key]},
        }
        if any(changes.values()):
            EVIDENCE['unexpectedDuplicateImportChanges'] = changes
        self.assertFalse(any(changes.values()), 'Duplicate modified installed files or receipts: ' + json.dumps(changes))
        self.assertEqual({relative: sha(root / 'packs' / relative) for relative in starter_files}, starter_files)
        catalog = self.modules['catalog'].load_catalog(root)
        self.assertFalse(catalog.get('errors'), catalog)
        self.assertEqual({pack['id'] for pack in catalog['packs']}, {'align', 'bam', 'variants', 'gatk'})
        EVIDENCE['offlineStaticImport'] = {'archiveSha256': sha(ARCHIVE),
            'manifestSha256': envelope['manifestSha256'], 'archiveMatchesGraphPayload': True,
            'duplicateVersionRejected': True, 'installedFilesAndReceiptsUnchanged': True,
            'starterPackFilesPreserved': len(starter_files), 'publisherVerified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GatkPipelineContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), testSourceSha256=sha(__file__),
                    success=result.wasSuccessful() and result.testsRun > 0 and not result.skipped)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if EVIDENCE['success'] else 1)
