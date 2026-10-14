"""Unchanged released Workbench 0.6.0 contracts for optional analysis packs.

This suite executes neither scientific programs nor the native importer. Its
archive test uses the released Python pack manager with a checked copy callback
for folder publication. Separate native scientific gates remain necessary.

Run in a fresh process with --report FILE. Configuration:
  NW_EXPANSION_PACK_IDS: comma-separated selection; default all four packs
  NW_EXPANSION_STARTER_ZIP: exact released 0.6.0 starter ZIP
  NW_EXPANSION_TEMP_DIR: disposable application parent
  NW_EXPANSION_<ID>_VERSION: expected version, default 1.0.0
  NW_EXPANSION_<ID>_ARCHIVE: exact installable pack ZIP
  NW_EXPANSION_<ID>_PACK_DIR: optional prepared/installed pack folder; if absent,
    graph tests use a fresh extraction of the exact archive
  NW_EXPANSION_MUSCLE_ARCHIVE: pinned 0.5.2 ZIP, required for IQ-TREE
  NW_EXPANSION_FEATURECOUNTS_ARCHIVE: pinned 1.0.0 ZIP, required for DESeq2
  NW_EXPANSION_KALLISTO_ARCHIVE: pinned 1.0.1 ZIP, required for DESeq2

Only selected-pack cases enter the suite; missing selected prerequisites fail
CLI execution. Ordinary repository test discovery can skip unavailable builds.
No network requests, replacement dependency metadata or edited core are used.
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
WORK = SOURCE / 'build/next-contracts'
SUPPORTED = ('snpeff', 'deseq2', 'mosdepth', 'iqtree')
SELECTED = tuple(x.strip() for x in os.environ.get('NW_EXPANSION_PACK_IDS', ','.join(SUPPORTED)).split(',') if x.strip())
if not SELECTED or len(set(SELECTED)) != len(SELECTED) or set(SELECTED) - set(SUPPORTED):
    raise ValueError('NW_EXPANSION_PACK_IDS must select distinct supported pack IDs: ' + ','.join(SUPPORTED))
VERSIONS = {identity: os.environ.get('NW_EXPANSION_' + identity.upper() + '_VERSION', '1.0.0') for identity in SELECTED}
STARTER = Path(os.environ.get('NW_EXPANSION_STARTER_ZIP', SOURCE / 'build/gatk-downloads/starter.zip')).resolve()
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
TEMP_ROOT = Path(os.environ.get('NW_EXPANSION_TEMP_DIR', WORK / 'applications')).resolve()
ARCHIVES = {identity: Path(os.environ.get('NW_EXPANSION_' + identity.upper() + '_ARCHIVE',
            WORK / ('native-workbench-pack-' + identity + '-' + version + '.zip'))).resolve()
            for identity, version in VERSIONS.items()}
PACK_DIRS = {identity: Path(os.environ['NW_EXPANSION_' + identity.upper() + '_PACK_DIR']).resolve()
             for identity in SELECTED if 'NW_EXPANSION_' + identity.upper() + '_PACK_DIR' in os.environ}
DEPENDENCIES = {
    'muscle': ('0.5.2', 'c07d3e398f48df683926c0970ef77c3b7d2bdab6426b80c80186f2360ed25258'),
    'featurecounts': ('1.0.0', 'f3319b6a8b13c30bc31b782008b0283c7688c739da2dd77cf5ab80859ccff4c2'),
    'kallisto': ('1.0.1', '641cd1f2b05e0951b1f8a58f45d6308ca6206bf86bf90fb74d0daa2860f5eecd'),
}
NEEDED_DEPENDENCIES = (['muscle'] if 'iqtree' in SELECTED else []) + (['featurecounts', 'kallisto'] if 'deseq2' in SELECTED else [])
DEPENDENCY_ARCHIVES = {identity: Path(os.environ.get('NW_EXPANSION_' + identity.upper() + '_ARCHIVE',
    WORK / ('dependencies/native-workbench-pack-' + identity + '-' + DEPENDENCIES[identity][0] + '.zip'))).resolve()
    for identity in NEEDED_DEPENDENCIES}
OPERATIONS = {
    'snpeff': {'build-database', 'annotate', 'annotate-local', 'filter-impact'},
    'deseq2': {'counts', 'featurecounts', 'kallisto'},
    'mosdepth': {'coverage', 'targets'},
    'iqtree': {'infer-nucleotide', 'infer-protein'},
}
EVIDENCE = {
    'schema': 1, 'applicationVersion': '0.6.0', 'expectedPackVersions': VERSIONS,
    'testHost': sys.platform, 'pythonVersion': sys.version.split()[0],
    'nativeWindowsExecuted': False, 'scientificExecutablesExecuted': False,
    'nativeImporterExecuted': False,
    'scope': 'Released-app graph contracts and Python archive import; checked copy callback substitutes native folder publication.',
    'typingLimitations': {
        'deseq2': 'Released count and abundance products are metrics. Their statistical/file roles, sample identities and suitability require the separately tested adapter.',
        'snpeff': 'Local database ZIPs are generic files. Database assembly/annotation identity and reference compatibility require the separately tested adapter.',
        'mosdepth': 'Compressed per-base and region depth products use generic file types; they are not ordinary BED intervals.',
        'iqtree': 'Newick trees are generic files. Core sequence types establish aligned nucleotide/protein roles; scientific suitability also requires adapter validation.',
    },
}
EVIDENCE['typingLimitations'] = {key: value for key, value in EVIDENCE['typingLimitations'].items() if key in SELECTED}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def files_below(root):
    return {path.relative_to(root).as_posix(): sha(path) for path in Path(root).rglob('*') if path.is_file()}


def checked_copy(source, destination):
    source, destination = Path(source), Path(destination)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    if source.stat().st_size != destination.stat().st_size or sha(source) != sha(destination):
        raise RuntimeError('Fixture copy differs: ' + str(destination))
    shutil.copystat(source, destination)
    return str(destination)


def extract_pack(archive_path, destination, identity, version):
    """Assemble a disposable graph fixture from an immutable pack ZIP."""
    with zipfile.ZipFile(archive_path) as archive:
        envelope = json.loads(archive.read('workbench-pack.json'))
        if (envelope['id'], envelope['version']) != (identity, version):
            raise RuntimeError('Unexpected dependency/selected archive identity: ' + str(archive_path))
        names = [member.filename for member in archive.infolist() if member.filename.endswith('/pack.ini')]
        if len(names) != 1:
            raise RuntimeError('Expected exactly one archive manifest')
        prefix = names[0][:-len('pack.ini')]
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            relative = member.filename[len(prefix):]
            if not relative or '\\' in relative or ':' in relative or relative.startswith('/') or any(x in ('', '.', '..') for x in relative.split('/')):
                raise RuntimeError('Unsafe pack fixture archive path')
            target = destination.joinpath(*relative.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    if sha(destination / 'pack.ini') != envelope['manifestSha256']:
        raise RuntimeError('Extracted manifest differs from archive envelope')
    return envelope


class ExpansionPipelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [STARTER, *ARCHIVES.values(), *DEPENDENCY_ARCHIVES.values(), *[x / 'pack.ini' for x in PACK_DIRS.values()]]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            message = 'Recover/build the selected pack and dependency archives first: ' + '; '.join(missing)
            if __name__ != '__main__':
                raise unittest.SkipTest(message)
            raise RuntimeError(message)
        if sha(STARTER) != STARTER_SHA:
            raise RuntimeError('Released starter hash differs; edited core cannot establish released compatibility.')
        for identity, archive in DEPENDENCY_ARCHIVES.items():
            if sha(archive) != DEPENDENCIES[identity][1]:
                raise RuntimeError('Published dependency hash differs: ' + identity)
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='expansion-contract-', dir=TEMP_ROOT)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        with zipfile.ZipFile(STARTER) as archive:
            archive.extractall(cls.root)
        cls.app = cls.root / 'native-workbench'
        cls.pack_folders = {}
        for identity, version in VERSIONS.items():
            destination = cls.app / 'packs' / (identity + '-' + version)
            if identity in PACK_DIRS:
                shutil.copytree(PACK_DIRS[identity], destination, copy_function=checked_copy)
            else:
                extract_pack(ARCHIVES[identity], destination, identity, version)
            cls.pack_folders[identity] = destination
        for identity, archive in DEPENDENCY_ARCHIVES.items():
            version = DEPENDENCIES[identity][0]
            extract_pack(archive, cls.app / 'packs' / (identity + '-' + version), identity, version)
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
        cls.operations = {}
        cls.checks = {}
        for identity, version in VERSIONS.items():
            operations = {tool['workflowId']: tool for tool in cls.tools.values()
                          if tool.get('packId') == identity and tool.get('packVersion') == version}
            if set(operations) != OPERATIONS[identity]:
                raise RuntimeError('Unexpected supported operations for ' + identity + ': ' + repr(set(operations)))
            cls.operations[identity] = operations
            manifest = cls.modules['catalog'].load_pack(cls.pack_folders[identity] / 'pack.ini')
            cls.checks[identity] = json.loads((cls.pack_folders[identity] / manifest['assets']['workbench-checks']['path']).read_text(encoding='utf-8'))['checks']
        cls.engine = cls.modules['engine'].Engine(cls.app, cls.catalog)
        cls.addClassCleanup(cls.engine.backend.shutdown)

    @staticmethod
    def graph(name):
        return {'schema': 1, 'name': name, 'nodes': [], 'sources': []}

    def select(self, pack, workflow):
        return next(tool for tool in self.tools.values() if tool.get('packId') == pack and tool.get('workflowId') == workflow)

    @staticmethod
    def port(tool, identity):
        return next(port for port in tool['ports'] if port['id'] == identity)

    @staticmethod
    def product(tool, identity):
        return next(product for product in tool['outputs'] if product['id'] == identity)

    @staticmethod
    def kind(tool, kind, outputs=False):
        return next(item for item in tool['outputs' if outputs else 'ports'] if item['type'] == kind)

    @staticmethod
    def ref(node, product):
        return node['id'] + '::' + product['id']

    def add_node(self, graph, tool, bindings=None, params=None, label=None):
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
        fixtures = self.checks.get(tool.get('packId'), [])
        fixture = next((case for case in fixtures if case['workflow'] == tool['workflowId']), None)
        if fixture:
            values.update(fixture.get('params', {}))
        values.update(params or {})
        node = {'id': 'step-' + str(len(graph['nodes']) + 1), 'tool': tool['id'], 'inputs': inputs, 'params': values}
        if label:
            node['label'] = label
        graph['nodes'].append(node)
        return node

    def assert_valid(self, graph):
        review = self.engine.validate(graph, check_files=False)
        self.assertTrue(review['valid'], review)
        return review

    def assert_invalid(self, graph, message=None):
        review = self.engine.validate(graph, check_files=False)
        self.assertFalse(review['valid'], review)
        if message:
            self.assertTrue(any(message in error['message'] for error in review['errors']), review)
        return review

    def reject_type(self, tool, port, wrong_type):
        graph = self.graph('Reject incompatible biological input')
        node = self.add_node(graph, tool)
        source = next(source for source in graph['sources'] if source['id'] == node['inputs'][port['id']][0])
        source['type'] = wrong_type
        self.assert_invalid(graph, wrong_type + ' cannot feed ')

    def save_and_review(self, graph):
        self.assert_valid(graph)
        saved = self.engine.save_pipeline(graph)
        self.assertTrue(all('files' not in source for source in saved['sources']))
        for node in saved['nodes']:
            self.assertEqual(node['pin'], self.modules['engine'].pin_for(self.tools[node['tool']]))
        methods = self.engine.methods(graph)
        self.assertIn('Planned methods', methods)
        for node in graph['nodes']:
            if node.get('label'):
                self.assertIn(node['label'], methods)
        invalid = copy.deepcopy(saved)
        invalid['nodes'][0]['pin']['manifestSha256'] = '0' * 64
        self.assert_invalid(invalid, 'original pack')
        return {'tools': [node['tool'] for node in graph['nodes']], 'ranks': self.engine.rank_groups(graph),
                'savedPins': [node['pin'] for node in saved['nodes']], 'namedMethodsProvenance': True,
                'changedSavedManifestRejected': True}

    def test_released_application_and_dependency_bytes_are_verified(self):
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
        EVIDENCE['dependencies'] = {identity: {'version': DEPENDENCIES[identity][0], 'archiveSha256': sha(archive)}
                                    for identity, archive in DEPENDENCY_ARCHIVES.items()}

    def test_every_selected_operation_is_discoverable_and_has_scientific_assertions(self):
        EVIDENCE['installedInventory'] = self.modules['verify_installation'].check_packs(self.app, self.catalog)
        evidence = []
        for identity, operations in self.operations.items():
            checks = self.checks[identity]
            self.assertTrue(checks)
            self.assertTrue(all(case.get('expect') for case in checks))
            self.assertEqual({case['workflow'] for case in checks}, OPERATIONS[identity],
                             'Every exposed operation needs a scientific installation assertion.')
            for workflow, tool in operations.items():
                with self.subTest(pack=identity, operation=workflow):
                    self.assertTrue(tool.get('methodsDescription'))
                    self.assertTrue(tool.get('citations'))
                    graph = self.graph('Standalone ' + identity + ' ' + workflow)
                    self.add_node(graph, tool)
                    self.assert_valid(graph)
            evidence.append({'id': identity, 'version': VERSIONS[identity],
                             'manifestSha256': sha(self.pack_folders[identity] / 'pack.ini'),
                             'operations': sorted(operations), 'scientificChecksDeclared': len(checks)})
        EVIDENCE['selectedPacks'] = evidence

    def test_tool_presets_are_distinct_from_pipeline_saves_and_pin_original_bytes(self):
        tested = []
        for identity, operations in self.operations.items():
            for workflow, tool in operations.items():
                with self.subTest(pack=identity, operation=workflow):
                    graph = self.graph('One operation is a tool preset')
                    node = self.add_node(graph, tool)
                    preset = self.engine.save_preset(node)
                    self.assertEqual(preset['kind'], 'tool-preset')
                    self.assertEqual(preset['pin'], self.modules['engine'].pin_for(tool))
                    self.assertNotIn('inputs', preset)
                    with self.assertRaisesRegex(ValueError, 'at least two connected tools'):
                        self.engine.save_pipeline(graph)
                    node['pin'] = copy.deepcopy(preset['pin'])
                    node['pin']['manifestSha256'] = '0' * 64
                    self.assert_invalid(graph, 'original pack')
                    tested.append(tool['id'])
        EVIDENCE['presetAndOriginalPinContracts'] = tested

    def test_exact_archives_import_once_without_changing_existing_files(self):
        root = self.root / 'offline import with spaces'
        (root / 'packs').mkdir(parents=True)
        for identity in ('align', 'bam', 'variants'):
            row = next(row for row in self.catalog['packs'] if row['id'] == identity)
            shutil.copytree(self.app / row['folder'], root / row['folder'], copy_function=checked_copy)
        starter_files = files_below(root / 'packs')
        calls = []

        def copy_publication(source):
            manifest = self.modules['catalog'].load_pack(Path(source) / 'pack.ini')
            destination = root / 'packs' / (manifest['id'] + '-' + manifest['version'])
            calls.append((manifest['id'], manifest['version']))
            shutil.copytree(source, destination, copy_function=checked_copy)
            return {'success': True, 'folder': str(destination)}

        manager = self.modules['pack_manager'].PackManager(root, copy_publication)
        imported = []
        for identity, archive in ARCHIVES.items():
            with zipfile.ZipFile(archive) as handle:
                envelope = json.loads(handle.read('workbench-pack.json'))
            self.assertEqual((envelope['id'], envelope['version']), (identity, VERSIONS[identity]))
            result = manager.import_archive(archive)
            self.assertTrue(result['success'])
            self.assertFalse(result['publisherVerified'])
            folder = root / 'packs' / (identity + '-' + VERSIONS[identity])
            self.assertEqual(sha(folder / 'pack.ini'), envelope['manifestSha256'])
            receipt = root / 'user-data/pack-receipts' / (identity + '-' + VERSIONS[identity] + '.json')
            self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['manifestSha256'], envelope['manifestSha256'])
            imported_files, graph_files = files_below(folder), files_below(self.pack_folders[identity])
            payload_changes = {
                'onlyImported': {key: imported_files[key] for key in imported_files.keys() - graph_files.keys()},
                'onlyGraphCopy': {key: graph_files[key] for key in graph_files.keys() - imported_files.keys()},
                'changed': {key: {'imported': imported_files[key], 'graphCopy': graph_files[key]}
                            for key in imported_files.keys() & graph_files.keys() if imported_files[key] != graph_files[key]},
            }
            if any(payload_changes.values()):
                EVIDENCE.setdefault('unexpectedArchivePayloadDifferences', {})[identity] = payload_changes
            self.assertFalse(any(payload_changes.values()), 'Exact graph-tested payload differs: ' + json.dumps(payload_changes))
            before = files_below(root)
            count = len(calls)
            with self.assertRaisesRegex(ValueError, 'already installed'):
                manager.import_archive(archive)
            self.assertEqual(len(calls), count, 'Duplicate reached publication callback.')
            after = files_below(root)
            changes = {'added': {key: after[key] for key in after.keys() - before.keys()},
                       'removed': {key: before[key] for key in before.keys() - after.keys()},
                       'changed': {key: {'before': before[key], 'after': after[key]}
                                   for key in before.keys() & after.keys() if before[key] != after[key]}}
            if any(changes.values()):
                EVIDENCE.setdefault('unexpectedDuplicateImportChanges', {})[identity] = changes
            self.assertFalse(any(changes.values()), 'Installed files/receipts changed: ' + json.dumps(changes))
            imported.append({'id': identity, 'version': VERSIONS[identity], 'archiveSha256': sha(archive),
                             'manifestSha256': envelope['manifestSha256'], 'archiveMatchesGraphPayload': True,
                             'duplicateVersionRejected': True, 'installedFilesAndReceiptsUnchanged': True,
                             'publisherVerified': False})
        self.assertEqual({relative: sha(root / 'packs' / relative) for relative in starter_files}, starter_files)
        catalog = self.modules['catalog'].load_catalog(root)
        self.assertFalse(catalog.get('errors'), catalog)
        self.assertEqual({pack['id'] for pack in catalog['packs']}, {'align', 'bam', 'variants'} | set(SELECTED))
        EVIDENCE['offlineStaticImports'] = imported
        EVIDENCE['starterPackFilesPreserved'] = len(starter_files)

    def case_iqtree_muscle_alignments_branch_into_explicit_phylogenetic_models(self):
        results = []
        for alphabet, alternative in (('nucleotide', 'GTR+G4'), ('protein', 'LG+G4')):
            muscle = next(tool for tool in self.tools.values() if tool.get('packId') == 'muscle'
                          and any(product['type'] == 'msa-' + alphabet for product in tool['outputs'])
                          and 'super5' not in tool['workflowId'])
            tree = self.operations['iqtree']['infer-' + alphabet]
            alignment = self.port(tree, 'alignment')
            self.assertEqual(alignment['type'], 'msa-' + alphabet)
            self.assertEqual(alignment['accepts'], ['msa-' + alphabet])
            self.assertEqual(alignment['requiredState']['compression'], 'none')
            graph = self.graph('Compare phylogenetic models for one ' + alphabet + ' alignment')
            aligned = self.add_node(graph, muscle, label='Align homologous ' + alphabet + ' sequences')
            bindings = {'alignment': [self.ref(aligned, self.kind(muscle, 'msa-' + alphabet, outputs=True))]}
            self.add_node(graph, tree, bindings, {'model': 'MFP', 'support': 'none'}, 'Select the substitution model')
            self.add_node(graph, tree, bindings, {'model': alternative, 'support': 'both', 'replicates': 1000}, 'Compare the specified substitution model')
            self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1']}, {'rank': 2, 'nodes': ['step-2', 'step-3']}])
            evidence = self.save_and_review(graph)
            self.assertEqual(self.product(tree, 'tree')['type'], 'file')
            evidence['alphabet'] = alphabet
            results.append(evidence)
        EVIDENCE['alignmentToPhylogenyGraphs'] = results

    def case_iqtree_unaligned_and_wrong_alphabet_inputs_are_rejected(self):
        rejected = []
        for alphabet, other in (('nucleotide', 'protein'), ('protein', 'nucleotide')):
            tool = self.operations['iqtree']['infer-' + alphabet]
            incoming = self.port(tool, 'alignment')
            for wrong in ('fasta-' + alphabet, 'msa-' + other, 'reads'):
                self.reject_type(tool, incoming, wrong)
                rejected.append(wrong + ' -> ' + incoming['type'])
            graph = self.graph('Reject invalid support replicate count')
            self.add_node(graph, tool, params={'support': 'both', 'replicates': 999})
            self.assert_invalid(graph)
        EVIDENCE['phylogenyTypeGuards'] = {'rejected': rejected, 'supportReplicateLowerBoundEnforced': True}

    def case_mosdepth_prepared_bam_branches_to_whole_genome_and_target_coverage(self):
        prepare = self.select('bam', 'prepare')
        coverage = self.operations['mosdepth']['coverage']
        targets = self.operations['mosdepth']['targets']
        graph = self.graph('Shared prepared BAM with genome and target coverage')
        first = self.add_node(graph, prepare, label='Prepare one alignment')
        output = self.kind(prepare, 'bam', outputs=True)
        branches = []
        for tool, label in ((coverage, 'Whole-alignment coverage'), (targets, 'Target-region coverage')):
            alignment = self.kind(tool, 'bam')
            self.assertEqual(alignment['requiredState']['sort'], 'coordinate')
            self.assertEqual(set(alignment['accepts']), {'bam', 'bam-rna'})
            branches.append(self.add_node(graph, tool, {alignment['id']: [self.ref(first, output)]}, label=label))
        report = self.tools['builtin/report']
        self.add_node(graph, report, {'metrics': [self.ref(node, self.product(tool, 'summary'))
                      for node, tool in zip(branches, (coverage, targets))]}, label='Compare separately attributed coverage summaries')
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1']},
                         {'rank': 2, 'nodes': ['step-2', 'step-3']}, {'rank': 3, 'nodes': ['step-4']}])
        EVIDENCE['coverageBranchesGraph'] = self.save_and_review(graph)
        parameter_ids = {parameter['id'] for tool in (coverage, targets) for parameter in tool['params']}
        self.assertFalse(parameter_ids & {'baseq', 'base-quality', 'min-baseq'}, 'Upstream mosdepth does not implement base-quality filtering.')

    def case_mosdepth_order_guards_and_pack_owned_bam_preflight(self):
        name_sort = self.select('bam', 'name-sort')
        selected = copy.deepcopy(self.catalog)
        selected['tools'] = {tool['id']: tool for tool in self.operations['mosdepth'].values()}
        selected['toolVersions'] = {identity: [tool] for identity, tool in selected['tools'].items()}
        selected['packs'] = [pack for pack in selected['packs'] if pack['id'] == 'mosdepth']
        engine = self.modules['engine'].Engine(self.app, selected)
        try:
            for tool in self.operations['mosdepth'].values():
                incoming = self.kind(tool, 'bam')
                graph = self.graph('Reject known queryname order for coverage')
                first = self.add_node(graph, name_sort)
                self.add_node(graph, tool, {incoming['id']: [self.ref(first, self.kind(name_sort, 'bam', outputs=True))]})
                self.assert_invalid(graph, 'sort=coordinate')
                self.reject_type(tool, incoming, 'vcf')
                helper = engine._samtools_selection(tool)
                self.assertEqual(helper['executable']['id'], 'samtools')
                self.assertEqual(helper['pin'], self.modules['engine'].pin_for(tool))
        finally:
            engine.backend.shutdown()
        EVIDENCE['coverageGuards'] = {'querynameOrderRejected': True, 'unrelatedVcfRejected': True,
                                      'bamPreflightHelperOwnedByPack': True}

    def case_snpeff_shared_local_database_and_variant_calls_have_explicit_provenance(self):
        build = self.operations['snpeff']['build-database']
        annotate = self.operations['snpeff']['annotate']
        filtering = self.operations['snpeff']['filter-impact']
        local = self.operations['snpeff']['annotate-local']
        caller = self.select('variants', 'call')
        graph = self.graph('Local database and called variants feed two annotation branches')
        database = self.add_node(graph, build, label='Build the selected reference annotation database')
        called = self.add_node(graph, caller, label='Call variants from the prepared BAM')
        bindings = {self.port(annotate, 'database')['id']: [self.ref(database, self.product(build, 'database'))],
                    self.kind(annotate, 'vcf')['id']: [self.ref(called, self.kind(caller, 'vcf', outputs=True))]}
        first = self.add_node(graph, annotate, bindings, label='Annotate consequences')
        second = self.add_node(graph, annotate, bindings, label='Repeat with the same declared database')
        self.add_node(graph, filtering, {self.kind(filtering, 'vcf')['id']: [self.ref(first, self.kind(annotate, 'vcf', outputs=True))]}, label='Select records with the chosen impact')
        self.add_node(graph, local, {self.port(local, 'variants')['id']: [self.ref(second, self.kind(annotate, 'vcf', outputs=True))]}, label='Add the selected local VCF annotations')
        self.assertEqual(self.product(build, 'database')['type'], 'file')
        self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1', 'step-2']},
                         {'rank': 2, 'nodes': ['step-3', 'step-4']}, {'rank': 3, 'nodes': ['step-5', 'step-6']}])
        EVIDENCE['localVariantAnnotationGraph'] = self.save_and_review(graph)

    def case_snpeff_ordinary_variant_types_and_filters_do_not_claim_pass(self):
        for workflow in ('annotate', 'annotate-local', 'filter-impact'):
            tool = self.operations['snpeff'][workflow]
            incoming = self.port(tool, 'variants')
            self.assertEqual(incoming['type'], 'vcf')
            for wrong in ('bam', 'file'):
                self.reject_type(tool, incoming, wrong)
            output = self.kind(tool, 'vcf', outputs=True)
            self.assertEqual(output.get('propagateStateFrom'), incoming['id'])
            self.assertNotEqual(output.get('state', {}).get('selection'), 'PASS-only')
        EVIDENCE['annotationTypeGuards'] = {'bamRejected': True, 'genericFileRejectedAtOrdinaryVcfPort': True,
                                           'consequenceSelectionDoesNotInventPassState': True}

    def case_deseq2_four_sample_counting_or_quantification_fans_in_in_named_order(self):
        results = []
        for operation, source_pack, source_workflow, output_id in (
                ('featurecounts', 'featurecounts', 'count-paired', 'counts'),
                ('kallisto', 'kallisto', 'index-quant-paired', 'abundance')):
            producer = self.select(source_pack, source_workflow)
            analysis = self.operations['deseq2'][operation]
            counts = self.port(analysis, 'counts')
            self.assertEqual(counts['type'], 'metrics')
            self.assertEqual(counts['min'], 4)
            self.assertEqual(counts['max'], 64, 'Released 0.6.0 supports at most 64 file sources per port.')
            self.assertEqual(len(counts['fields']), 1)
            self.assertEqual(counts['fields'][0]['type'], 'files')
            graph = self.graph('Four biological samples feed a differential expression comparison')
            nodes = [self.add_node(graph, producer, params={'strandness': '0'} if source_pack == 'featurecounts' else {},
                                   label='Sample ' + str(i + 1) + ' ' + source_pack) for i in range(4)]
            product = self.product(producer, output_id)
            references = [self.ref(node, product) for node in nodes]
            self.add_node(graph, analysis, {'counts': references}, label='Compare the explicit biological groups')
            self.assertEqual(self.engine.rank_groups(graph), [{'rank': 1, 'nodes': ['step-1', 'step-2', 'step-3', 'step-4']},
                                                             {'rank': 2, 'nodes': ['step-5']}])
            evidence = self.save_and_review(graph)
            files = ['/results/sample-' + str(index + 1) + '/' + output_id + '.tsv' for index in range(4)]
            produced = {ref: {'manifestOutputs': product['manifestOutputs'],
                              'files': {product['manifestOutputs'][0]: path}} for ref, path in zip(references, files)}
            values = self.engine._resolve_values({'tool': analysis, 'inputs': {'counts': references}, 'params': {}}, {}, produced)
            self.assertEqual(values[counts['manifestInputs'][0]].splitlines(), files)
            evidence.update(inputOrderPreserved=True, workflow=operation, incomingCounts=references,
                            metadataBindingsExcludedFromSavedPipeline=True)
            results.append(evidence)
        EVIDENCE['differentialExpressionGraphs'] = results

    def case_deseq2_replication_cardinality_required_comparison_and_types_are_enforced(self):
        for workflow, tool in self.operations['deseq2'].items():
            self.reject_type(tool, self.port(tool, 'counts'), 'bam-rna')
            self.reject_type(tool, self.port(tool, 'counts'), 'vcf')
            for required in ('numerator', 'denominator'):
                parameter = next(parameter for parameter in tool['params'] if parameter['id'] == required)
                self.assertEqual(parameter.get('default', ''), '', 'Condition identities must be supplied by the user.')
                graph = self.graph('Require an explicit differential expression contrast')
                node = self.add_node(graph, tool)
                node['params'].pop(required, None)
                self.assert_invalid(graph)
            if workflow == 'counts':
                continue
            graph = self.graph('Enforce four distinct selected abundance files')
            node = self.add_node(graph, tool)
            self.assert_valid(graph)
            insufficient = copy.deepcopy(graph)
            insufficient['nodes'][0]['inputs']['counts'] = node['inputs']['counts'][:3]
            self.assert_invalid(insufficient, 'needs 4')
            duplicate = copy.deepcopy(graph)
            duplicate['nodes'][0]['inputs']['counts'][1] = duplicate['nodes'][0]['inputs']['counts'][0]
            self.assert_invalid(duplicate, 'cannot be connected twice')
        EVIDENCE['differentialExpressionGuards'] = {'minimumFourSelectedFiles': True,
            'duplicateConnectionRejected': True, 'contrastLabelsRequired': True,
            'bamAndVcfRejected': True, 'biologicalReplicationAndRawCountSuitabilityRequireAdapter': True}


for _identity in SELECTED:
    for _name, _method in list(vars(ExpansionPipelineContracts).items()):
        if _name.startswith('case_' + _identity + '_'):
            setattr(ExpansionPipelineContracts, 'test_' + _name.removeprefix('case_'), _method)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExpansionPipelineContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), testSourceSha256=sha(__file__),
                    success=result.wasSuccessful() and result.testsRun > 0 and not result.skipped)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if EVIDENCE['success'] else 1)
