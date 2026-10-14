"""Kraken2/Bracken contracts against the unchanged released Workbench 0.6.0.

No scientific executable or native importer runs. The released Python archive
manager publishes through a checked copy callback. Native installation and real
Kraken2-to-Bracken execution have separate gates.

Run in a fresh Python process: python tests/test_metagenomics_pipeline.py
  --report FILE

Configuration:
  NW_METAGENOMICS_PACK_IDS: kraken2, bracken, or both (default both)
  NW_METAGENOMICS_STARTER_ZIP: SHA-pinned released 0.6.0 starter ZIP
  NW_METAGENOMICS_TEMP_DIR: disposable applications parent
  NW_METAGENOMICS_<ID>_VERSION: selected pack version; default 1.0.0
  NW_METAGENOMICS_<ID>_ARCHIVE: exact selected installable ZIP
  NW_METAGENOMICS_<ID>_PACK_DIR: optional graph-tested prepared/installed folder;
    absent means extract the exact selected archive
  NW_METAGENOMICS_FASTP_ARCHIVE: exact published fastp 0.4.1 ZIP
    (needed when Kraken2 is selected)
  NW_METAGENOMICS_KRAKEN2_ARCHIVE, _VERSION, _SHA256: mandatory pinned Kraken2
    dependency for Bracken-only gates; version defaults to 1.0.0

The primary disposable app contains only starter and selected packs, proving
standalone discovery/import without optional dependencies. A second disposable
app adds pinned dependencies for graph connections. Both-selected gates exercise
both proposed payloads; Bracken-only gates exercise its selected payload with a
previously frozen Kraken2 dependency. No downloads or core edits are performed.
Missing prerequisites fail CLI execution; ordinary test discovery can skip an
unbuilt optional pack. A skipped CLI run never succeeds.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager


SOURCE = Path(__file__).resolve().parents[1]
WORK = SOURCE / 'build/metagenomics-contracts'
SUPPORTED = ('kraken2', 'bracken')
SELECTED = tuple(value.strip() for value in os.environ.get(
    'NW_METAGENOMICS_PACK_IDS', ','.join(SUPPORTED)).split(',') if value.strip())
if not SELECTED or len(set(SELECTED)) != len(SELECTED) or set(SELECTED) - set(SUPPORTED):
    raise ValueError('NW_METAGENOMICS_PACK_IDS must select distinct supported IDs: ' + ','.join(SUPPORTED))
VERSIONS = {identity: os.environ.get('NW_METAGENOMICS_' + identity.upper() + '_VERSION', '1.0.0')
            for identity in SELECTED}
STARTER = Path(os.environ.get('NW_METAGENOMICS_STARTER_ZIP', SOURCE / 'build/gatk-downloads/starter.zip')).resolve()
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
TEMP_ROOT = Path(os.environ.get('NW_METAGENOMICS_TEMP_DIR', WORK / 'applications')).resolve()
ARCHIVES = {identity: Path(os.environ.get('NW_METAGENOMICS_' + identity.upper() + '_ARCHIVE',
            WORK / ('native-workbench-pack-' + identity + '-' + version + '.zip'))).resolve()
            for identity, version in VERSIONS.items()}
PACK_DIRS = {identity: Path(os.environ['NW_METAGENOMICS_' + identity.upper() + '_PACK_DIR']).resolve()
             for identity in SELECTED if 'NW_METAGENOMICS_' + identity.upper() + '_PACK_DIR' in os.environ}
DEPENDENCIES = {}
if 'kraken2' in SELECTED:
    DEPENDENCIES['fastp'] = ('0.4.1', '93c32ccd506bb61eed0e901f83f025fed183557587cc5378ad0d40771db4a8cc')
if 'bracken' in SELECTED and 'kraken2' not in SELECTED:
    DEPENDENCIES['kraken2'] = (os.environ.get('NW_METAGENOMICS_KRAKEN2_VERSION', '1.0.0'),
                                os.environ.get('NW_METAGENOMICS_KRAKEN2_SHA256', ''))
DEPENDENCY_ARCHIVES = {identity: Path(os.environ.get('NW_METAGENOMICS_' + identity.upper() + '_ARCHIVE',
    WORK / ('dependencies/native-workbench-pack-' + identity + '-' + details[0] + '.zip'))).resolve()
    for identity, details in DEPENDENCIES.items()}
OPERATIONS = {
    'kraken2': {'register-database', 'prepare-archive', 'classify-single', 'classify-paired'},
    'bracken': {'estimate', 'estimate-external'},
}
EVIDENCE = {
    'schema': 1, 'applicationVersion': '0.6.0', 'expectedPackVersions': VERSIONS,
    'testHost': sys.platform, 'pythonVersion': sys.version.split()[0],
    'nativeWindowsExecuted': False, 'scientificExecutablesExecuted': False,
    'nativeImporterExecuted': False,
    'scope': 'Released-app graph contracts and Python archive import; checked copy callback substitutes native folder publication.',
    'typingLimitation': 'Released 0.6.0 uses generic file ports for local database manifests, classification records and Bracken distributions. Graph acceptance does not validate resource identity, report hashes, read length, count units or scientific suitability; the separately tested adapters must validate them.',
}


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


class MetagenomicsPipelineContracts(unittest.TestCase):
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
            if re.fullmatch(r'[0-9a-f]{64}', DEPENDENCIES[identity][1]) is None:
                raise RuntimeError('An exact published dependency SHA-256 is required: ' + identity)
            if sha(archive) != DEPENDENCIES[identity][1]:
                raise RuntimeError('Published dependency hash differs: ' + identity)
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='metagenomics-contract-', dir=TEMP_ROOT)
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
        chain_root = cls.root / 'connected application with spaces'
        with zipfile.ZipFile(STARTER) as archive:
            archive.extractall(chain_root)
        cls.chain_app = chain_root / 'native-workbench'
        for identity, version in VERSIONS.items():
            shutil.copytree(cls.pack_folders[identity], cls.chain_app / 'packs' / (identity + '-' + version),
                            copy_function=checked_copy)
        for identity, archive in DEPENDENCY_ARCHIVES.items():
            version = DEPENDENCIES[identity][0]
            extract_pack(archive, cls.chain_app / 'packs' / (identity + '-' + version), identity, version)
        cls.chain_catalog = cls.modules['catalog'].load_catalog(cls.chain_app)
        if cls.chain_catalog.get('errors'):
            raise RuntimeError('Connection fixture discovery failed: ' + repr(cls.chain_catalog['errors']))
        cls.chain_engine = cls.modules['engine'].Engine(cls.chain_app, cls.chain_catalog)
        cls.addClassCleanup(cls.chain_engine.backend.shutdown)

    @contextmanager
    def connections(self):
        """Keep independently installed tool operations separate from dependencies."""
        engine, catalog, tools = self.engine, self.catalog, self.tools
        self.engine, self.catalog, self.tools = self.chain_engine, self.chain_catalog, self.chain_catalog['tools']
        try:
            yield
        finally:
            self.engine, self.catalog, self.tools = engine, catalog, tools

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
            tool = self.tools[node['tool']]
            for port in tool['ports']:
                for reference in node['inputs'].get(port['id'], []):
                    if '::' in reference:
                        producer, output = reference.split('::', 1)
                        previous = next(item for item in graph['nodes'] if item['id'] == producer)
                        product = self.product(self.tools[previous['tool']], output)
                        self.assertIn(previous.get('label', self.tools[previous['tool']]['name']) + ' → ' + product['label'], methods)
                    else:
                        source = next(item for item in graph['sources'] if item['id'] == reference)
                        self.assertIn(source['label'], methods)
        diagram = self.engine.diagram({'graph': graph})
        self.assertTrue(diagram.startswith('<svg '))
        self.assertIn('Pipeline dependency graph', diagram)
        for node in graph['nodes']:
            for port_id, references in node['inputs'].items():
                for reference in references:
                    self.assertIn(reference + ' → ' + node['id'] + ':' + port_id, diagram)
        invalid = copy.deepcopy(saved)
        invalid['nodes'][0]['pin']['manifestSha256'] = '0' * 64
        self.assert_invalid(invalid, 'original pack')
        return {'tools': [node['tool'] for node in graph['nodes']], 'ranks': self.engine.rank_groups(graph),
                'savedPins': [node['pin'] for node in saved['nodes']], 'namedMethodsProvenance': True,
                'inputBindings': {node['id']: node['inputs'] for node in graph['nodes']},
                'diagramEdgesRetainNamedSources': True, 'plannedMethods': methods,
                'changedSavedManifestRejected': True}

    def test_released_application_and_dependency_bytes_are_verified(self):
        verified = []
        with zipfile.ZipFile(STARTER) as archive:
            for member in archive.infolist():
                relative = member.filename.removeprefix('native-workbench/')
                if member.is_dir() or not (relative.startswith('workspace/') or relative == 'WorkbenchBridge.exe'):
                    continue
                for app in (self.app, self.chain_app):
                    self.assertEqual(sha(app / relative), hashlib.sha256(archive.read(member)).hexdigest(), relative)
                verified.append(relative)
        self.assertIn('workspace/engine.py', verified)
        self.assertIn('WorkbenchBridge.exe', verified)
        EVIDENCE['releasedApplicationFilesVerified'] = verified
        EVIDENCE['starterSha256'] = STARTER_SHA
        EVIDENCE['dependencies'] = {identity: {'version': DEPENDENCIES[identity][0], 'archiveSha256': sha(archive)}
                                    for identity, archive in DEPENDENCY_ARCHIVES.items()}
        EVIDENCE['separateConnectionApplication'] = True
        for identity, version in VERSIONS.items():
            self.assertEqual(files_below(self.pack_folders[identity]),
                             files_below(self.chain_app / 'packs' / (identity + '-' + version)))

    def test_every_selected_operation_is_discoverable_and_has_scientific_assertions(self):
        EVIDENCE['installedInventory'] = self.modules['verify_installation'].check_packs(self.app, self.catalog)
        self.assertEqual({pack['id'] for pack in self.catalog['packs']}, {'align', 'bam', 'variants'} | set(SELECTED),
                         'Standalone application must not depend on another optional pack.')
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

    def case_kraken2_preprocessing_and_database_outputs_keep_sources_and_branches_explicit(self):
        with self.connections():
            register = self.select('kraken2', 'register-database')
            prepare = self.select('kraken2', 'prepare-archive')
            preprocessing = self.select('fastp', 'paired')
            single = self.select('kraken2', 'classify-single')
            paired = self.select('kraken2', 'classify-paired')
            results = []
            for database_tool in (register, prepare):
                graph = self.graph('One local database and cleaned reads feed separate classification branches')
                database = self.add_node(graph, database_tool, label='Prepare the explicitly selected local database')
                reads = self.add_node(graph, preprocessing, params={'adapter1': 'AGATCGGAAGAGC', 'adapter2': 'AGATCGGAAGAGC'},
                                      label='Filter paired reads and retain surviving unpaired reads')
                output = self.product(database_tool, 'database')
                self.assertEqual(output['type'], 'file')
                shared_database = self.ref(database, output)
                branches = []
                for tool, product_id, label in (
                        (paired, 'trimmed', 'Classify cleaned read pairs as fragments'),
                        (single, 'unpaired1', 'Classify surviving unpaired read 1 observations')):
                    read_port = self.port(tool, 'reads')
                    product = self.product(preprocessing, product_id)
                    self.assertEqual(read_port['type'], product['type'])
                    branch = self.add_node(graph, tool,
                        {'database': [shared_database], 'reads': [self.ref(reads, product)]}, label=label)
                    self.assertEqual(self.product(tool, 'classification')['type'], 'file')
                    self.assertEqual(self.product(tool, 'report')['type'], 'metrics')
                    branches.append((branch, tool))
                report = self.tools['builtin/report']
                self.add_node(graph, report, {'metrics': [self.ref(node, self.product(tool, 'report'))
                    for node, tool in branches]}, label='Review separately attributed Kraken reports')
                self.assertEqual(self.engine.rank_groups(graph),
                    [{'rank': 1, 'nodes': ['step-1', 'step-2']},
                     {'rank': 2, 'nodes': ['step-3', 'step-4']}, {'rank': 3, 'nodes': ['step-5']}])
                evidence = self.save_and_review(graph)
                evidence.update(databaseOperation=database_tool['workflowId'],
                                retainedOrphansAreSeparateObservations=True,
                                reportAggregation='separate-sections-no-pooled-statistics')
                results.append(evidence)
            EVIDENCE['preprocessingAndLocalDatabaseGraphs'] = results

    def case_kraken2_atomic_pairs_and_biological_types_are_enforced(self):
        rejected = []
        for workflow, allowed, wrong_types in (
                ('classify-single', 'reads', ('pair', 'bam', 'fasta-nucleotide', 'file')),
                ('classify-paired', 'pair', ('reads', 'bam', 'fasta-nucleotide', 'file'))):
            tool = self.operations['kraken2'][workflow]
            incoming = self.port(tool, 'reads')
            self.assertEqual(incoming['type'], allowed)
            self.assertEqual(incoming['accepts'], [allowed])
            self.assertEqual(incoming['manifestInputs'], ['reads'] if allowed == 'reads' else ['reads1', 'reads2'])
            self.assertEqual(incoming['min'], 1)
            self.assertEqual(incoming['max'], 1)
            for wrong in wrong_types:
                self.reject_type(tool, incoming, wrong)
                rejected.append(wrong + ' -> ' + workflow)
            self.reject_type(tool, self.port(tool, 'database'), 'metrics')
            graph = self.graph('A read pair remains a single named input group')
            node = self.add_node(graph, tool)
            node['inputs']['reads'].append(node['inputs']['reads'][0])
            self.assert_invalid(graph, 'cannot be connected twice')
        EVIDENCE['classificationTypeGuards'] = {
            'rejected': rejected, 'atomicReadPairCardinality': True,
            'ordinaryMetricsCannotFeedDatabase': True,
            'fastqRecordsPairIdentityAndDatabaseFormatRequireAdapter': True,
        }

    def case_bracken_standalone_inputs_support_species_and_genus_comparison(self):
        results = []
        for workflow in ('estimate', 'estimate-external'):
            tool = self.operations['bracken'][workflow]
            graph = self.graph('Compare species and genus abundance from the same declared evidence')
            species = self.add_node(graph, tool, params={'level': 'S'}, label='Estimate species abundance')
            genus = self.add_node(graph, tool, bindings=copy.deepcopy(species['inputs']),
                                  params={'level': 'G'}, label='Estimate genus abundance')
            report = self.tools['builtin/report']
            self.add_node(graph, report, {'metrics': [self.ref(node, self.product(tool, 'abundance'))
                for node in (species, genus)]}, label='Review ranks as separate abundance tables')
            self.assertEqual(self.engine.rank_groups(graph),
                [{'rank': 1, 'nodes': ['step-1', 'step-2']}, {'rank': 2, 'nodes': ['step-3']}])
            evidence = self.save_and_review(graph)
            evidence.update(workflow=workflow, sameExplicitInputSources=True,
                            reportAggregation='separate-sections-no-pooled-statistics')
            results.append(evidence)
        EVIDENCE['independentAbundanceGraphs'] = results

    def case_bracken_role_types_and_external_provenance_choices_are_enforced(self):
        estimate = self.operations['bracken']['estimate']
        external = self.operations['bracken']['estimate-external']
        for incoming in ('classification', 'database'):
            self.assertEqual(self.port(estimate, incoming)['type'], 'file')
            for wrong in ('metrics', 'reads', 'bam'):
                self.reject_type(estimate, self.port(estimate, incoming), wrong)
        self.assertEqual(self.port(external, 'report')['type'], 'metrics')
        self.assertEqual(self.port(external, 'distribution')['type'], 'file')
        for wrong in ('reads', 'bam', 'file'):
            self.reject_type(external, self.port(external, 'report'), wrong)
        for parameter_id in ('database-label', 'database-release', 'external-confirmation'):
            parameter = next(item for item in external['params'] if item['id'] == parameter_id)
            self.assertEqual(parameter.get('default', ''), '', 'External provenance must be supplied explicitly.')
            graph = self.graph('External report provenance requires an explicit declaration')
            node = self.add_node(graph, external)
            node['params'].pop(parameter_id, None)
            self.assert_invalid(graph)
        graph = self.graph('Generic types cannot prove classification/database identities agree')
        node = self.add_node(graph, estimate)
        node['inputs']['classification'], node['inputs']['database'] = node['inputs']['database'], node['inputs']['classification']
        self.assert_valid(graph)
        for tool in (estimate, external):
            graph = self.graph('Reject an unsupported taxonomic rank')
            self.add_node(graph, tool, params={'level': 'strain'})
            self.assert_invalid(graph)
        EVIDENCE['abundanceTypeAndProvenanceGuards'] = {
            'reportAndClassificationRolesHaveDifferentCoreTypes': True,
            'externalDatabaseLabelReleaseAndConfirmationRequired': True,
            'unsupportedRankRejected': True,
            'genericFileSwapAcceptedByGraphAndRequiresRuntimeRejection': True,
        }

    def case_bracken_real_kraken_result_fans_out_with_shared_database_identity(self):
        with self.connections():
            classification = self.select('kraken2', 'classify-paired')
            estimate = self.select('bracken', 'estimate')
            graph = self.graph('One Kraken paired classification feeds species and genus estimates')
            kraken = self.add_node(graph, classification, label='Classify paired fragments against the selected database')
            database_refs = kraken['inputs']['database']
            source = next(item for item in graph['sources'] if item['id'] == database_refs[0])
            source['label'] = 'Shared versioned Kraken database and Bracken distributions'
            product = self.product(classification, 'classification')
            self.assertEqual(product['type'], 'file')
            self.assertEqual(self.port(estimate, 'classification')['type'], 'file')
            bindings = {'classification': [self.ref(kraken, product)], 'database': database_refs}
            branches = [self.add_node(graph, estimate, bindings=copy.deepcopy(bindings), params={'level': level}, label=label)
                        for level, label in (('S', 'Estimate species abundances'), ('G', 'Estimate genus abundances'))]
            self.add_node(graph, self.tools['builtin/report'], {'metrics': [self.ref(node, self.product(estimate, 'abundance'))
                for node in branches]}, label='Review species and genus results without pooling')
            self.assertEqual(self.engine.rank_groups(graph),
                [{'rank': 1, 'nodes': ['step-1']}, {'rank': 2, 'nodes': ['step-2', 'step-3']},
                 {'rank': 3, 'nodes': ['step-4']}])
            evidence = self.save_and_review(graph)
            produced_path = '/contract-only/results/kraken/classification-record.json'
            resolved = self.engine._resolve_values(
                {'tool': estimate, 'inputs': branches[0]['inputs'], 'params': branches[0]['params']},
                {item['id']: item for item in graph['sources']},
                {self.ref(kraken, product): {'manifestOutputs': product['manifestOutputs'],
                                            'files': {product['manifestOutputs'][0]: produced_path}}})
            self.assertEqual(resolved[self.port(estimate, 'classification')['manifestInputs'][0]], produced_path)
            evidence.update(classificationPathResolvedFromNamedProducer=True,
                            sameExplicitDatabaseSource=True, actualScientificProgramsExecuted=False)
            EVIDENCE['krakenToBrackenGraph'] = evidence


for _identity in SELECTED:
    for _name, _method in list(vars(MetagenomicsPipelineContracts).items()):
        if _name.startswith('case_' + _identity + '_'):
            setattr(MetagenomicsPipelineContracts, 'test_' + _name.removeprefix('case_'), _method)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MetagenomicsPipelineContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), testSourceSha256=sha(__file__),
                    success=result.wasSuccessful() and result.testsRun > 0 and not result.skipped)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if EVIDENCE['success'] else 1)
