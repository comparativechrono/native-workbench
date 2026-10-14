#!/usr/bin/env python3
"""Real IQ-TREE scientific/guard tests; native Windows and explicit Linux reference.

python tests/test_iqtree_pack.py --pack <installed pack> --report <report.json>
Linux additionally requires --binary <pinned official Linux IQ-TREE executable>.
No mutation of the installed pack is performed; all runtime files are temporary.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'packs/iqtree-1.0.0'
BINARY = ROOT / 'build/iqtree-inputs/linux/iqtree-3.1.4-Linux/bin/iqtree3'
REPORT = None
MUSCLE_ARCHIVE = None
MUSCLE_BINARY = ROOT / 'build/iqtree-inputs/muscle-linux-x86.v5.3'
MUSCLE_EVIDENCE = []
sys.dont_write_bytecode = True
EXECUTIONS = []
NATIVE_CHECKS = []


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(path.rglob('*')) if p.is_file()}


def fasta(path):
    rows = {}
    for line in path.read_text().splitlines():
        if line.startswith('>'):
            identity = line[1:].split()[0]
            rows[identity] = ''
        elif line:
            rows[identity] += line
    return rows


def independent_newick(path):
    # Independent stack-based reader of original-identifier Newick; it does not
    # use the adapter's tree summary as the scientific assertion oracle.
    tokens = re.findall(r"'(?:''|[^'])*'|[^\s(),:;]+|[(),:;]", path.read_text())
    stack, leaves, groups, support = [[]], [], [], []
    at = 0
    while at < len(tokens):
        tok = tokens[at]
        at += 1
        if tok == '(':
            stack.append([])
        elif tok == ')':
            group = set().union(*stack.pop())
            groups.append(group)
            stack[-1].append(group)
            if tokens[at] not in (':', ',', ')', ';'):
                support.append([float(x) for x in tokens[at].split('/')])
                at += 1
        elif tok == ':':
            float(tokens[at])
            at += 1
        elif tok in (',', ';'):
            continue
        else:
            name = tok[1:-1].replace("''", "'") if tok.startswith("'") else tok
            leaves.append(name)
            stack[-1].append({name})
    universe = set(leaves)
    pairs = set()
    for group in groups:
        for side in (group, universe - group):
            if len(side) == 2:
                pairs.add(frozenset(side))
    return leaves, pairs, support


class IQTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PACK.is_dir():
            raise RuntimeError('Prepare or import the IQ-TREE pack first.')
        cls.adapter = PACK / 'adapter.py'
        cls.python = PACK / 'bin/python.exe' if os.name == 'nt' else Path(sys.executable)
        if not cls.python.is_file() or not BINARY.is_file():
            raise RuntimeError('Missing private Windows runtime or explicit pinned Linux reference binary.')
        cls.before = inventory(PACK)
        if os.name == 'nt' and (not MUSCLE_ARCHIVE or not MUSCLE_ARCHIVE.is_file()):
            raise RuntimeError('Native chain regression requires --muscle-archive with the pinned published MUSCLE0.5.2 pack ZIP')
        spec = importlib.util.spec_from_file_location('installed_iqtree_adapter', cls.adapter)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    @classmethod
    def tearDownClass(cls):
        if inventory(PACK) != cls.before:
            raise AssertionError('Installed pack files changed during scientific checks.')

    def setUp(self):
        parent = ROOT / 'build/iqtree-test-runs'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='iqtree scientific spaces ', dir=parent)
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, datatype='nucleotide', model='MFP', support='none', source=None, threads=2, extra=(), success=True):
        out = self.directory / ('run ' + str(len(list(self.directory.glob('run *')))))
        out.mkdir()
        source = source or PACK / 'fixtures' / (datatype + '.afa')
        cmd = [str(self.python), '-I', '-B', '-X', 'utf8', str(self.adapter), '--alignment', str(source), '--run', str(out), '--datatype', 'DNA' if datatype == 'nucleotide' else 'AA', '--model', model,
            '--support', support, '--threads', str(threads), '--seed', '42']
        if os.name != 'nt':
            cmd += ['--reference-binary', str(BINARY)]
        cmd += list(extra)
        before = sha(source)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=240)
        EXECUTIONS.append({'datatype': datatype, 'model': model, 'support': support, 'threads': threads, 'returncode': result.returncode, 'expectedSuccess': success, 'stdout': result.stdout, 'stderr': result.stderr})
        self.assertEqual(sha(source), before, 'Input was changed')
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((out / 'inferred-tree.nwk').exists())
        return out, result

    def assert_fixture(self, out, support_count=0, expected_stats=(800, 300, 210)):
        columns, variable, informative = expected_stats
        leaves, pairs, support = independent_newick(out / 'inferred-tree.nwk')
        self.assertCountEqual(leaves, ['alpha1', 'alpha2', 'beta1', 'beta2', 'gamma1', 'gamma2'])
        self.assertEqual(pairs, {frozenset([p + '1', p + '2']) for p in ('alpha', 'beta', 'gamma')})
        self.assertEqual(len(support), 3 if support_count else 0)
        for values in support:
            self.assertEqual(len(values), support_count)
            self.assertTrue(all(95 <= x <= 100 for x in values))
        report = (out / 'iqtree-report.txt').read_text()
        self.assertIn('6 sequences with ' + str(columns), report)
        self.assertIn('Number of parsimony informative sites: ' + str(informative), report)
        actual = json.loads((out / 'model-selection.json').read_text())
        self.assertEqual(actual['alignment']['taxa'], 6)
        self.assertEqual(actual['alignment']['columns'], columns)
        self.assertEqual(actual['alignment']['variableColumnsIgnoringAmbiguity'], variable)
        self.assertEqual(actual['alignment']['parsimonyInformativeColumnsIgnoringAmbiguity'], informative)
        provenance = json.loads((out / 'analysis-provenance.json').read_text())
        self.assertTrue(provenance['inputUnchanged'])
        self.assertEqual(provenance['status'], 'completed')
        self.assertEqual(provenance['executableSha256'], sha(BINARY))
        return actual, provenance

    def test_01_manifest_and_upstream_identity(self):
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read(PACK / 'pack.ini', encoding='utf-8')
        self.assertEqual(config['pack']['id'], 'iqtree')
        for section in config.sections():
            if section.startswith(('tool:', 'asset:')):
                self.assertEqual(sha(PACK / config[section]['path']), config[section]['sha256'])
        with (PACK / 'bin/iqtree3.exe').open('rb') as stream:
            self.assertEqual(stream.read(2), b'MZ')
        result = subprocess.run([str(BINARY), '--version'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('3.1.4', result.stdout)
        expected = '43c9bf3b0dc5e7d88c183a2582369d22c9d692b7585350038769334bb6fd9aed' if os.name == 'nt' else '4ba12225d8f52a727b5e6fa172d300cd9302510730ea763795b2bd7a6ed4a834'
        self.assertEqual(sha(BINARY), expected, 'Scientific executable is not the pinned official build')
        lock = json.loads((PACK / 'licenses/input-lock.json').read_text())
        self.assertEqual(lock['iqtreeCommit'], '63c330d90dd02241dbbbaf1e9f9e9cc6dadbd1de')
        self.assertIn('libiomp5md.dll', json.loads((PACK / 'licenses/windows-imports.json').read_text())['iqtree3.exe'])
        self.assertNotIn('import site', (PACK / 'bin/python313._pth').read_text())

    def test_02_dna_modelfinder_known_topology_default_threads(self):
        out, _ = self.run_tool()
        actual, provenance = self.assert_fixture(out)
        self.assertEqual(actual['selectedModel'], 'JC')
        self.assertEqual(actual['criterion'], 'BIC')
        self.assertEqual(provenance['threads'], 2)
        self.assertEqual(provenance['supportReplicates'], 0)
        self.assertNotIn('-B', provenance['argv'])

    def test_03_protein_modelfinder_known_topology(self):
        out, _ = self.run_tool('protein')
        actual, provenance = self.assert_fixture(out)
        self.assertEqual(actual['criterion'], 'BIC')
        self.assertIn('ModelFinder', (out / 'iqtree-report.txt').read_text())
        self.assertEqual(provenance['datatype'], 'AA')

    def test_04_real_ufboot_and_sh_alrt_replicates(self):
        for datatype, model, method, count in [('nucleotide', 'GTR+G4', 'both', 2), ('protein', 'LG+G4', 'ufboot', 1), ('nucleotide', 'HKY+G4', 'sh-alrt', 1)]:
            with self.subTest(datatype=datatype, method=method):
                out, _ = self.run_tool(datatype, model, method)
                _, provenance = self.assert_fixture(out, count)
                self.assertEqual(provenance['supportReplicates'], 1000)
                self.assertEqual(provenance['ufbootBNNI'], method != 'sh-alrt')
                if method in ('both', 'ufboot'):
                    self.assertIn('1000 replicates', (out / 'iqtree-report.txt').read_text())
                    self.assertIn('-bnni', provenance['argv'])
                if method in ('both', 'sh-alrt'):
                    self.assertIn('-alrt', provenance['argv'])

    def test_05_upstream_direct_agrees_with_adapter(self):
        out, _ = self.run_tool(model='JC', threads=1)
        staged = out / 'iqtree-work/alignment.fa'
        direct = self.directory / 'direct upstream spaces'
        direct.mkdir()
        result = subprocess.run([str(BINARY), '-s', str(staged), '-st', 'DNA', '-m', 'JC', '-T', '1', '-seed', '42', '--prefix', str(direct / 'truth'), '-keep-ident'], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((direct / 'truth.treefile').read_text(), (out / 'iqtree-work/analysis.treefile').read_text())
        self.assert_fixture(out)

    def test_06_taxon_names_are_safe_and_restored(self):
        rows = fasta(PACK / 'fixtures/nucleotide.afa')
        names = ["alpha'1", 'beta:two', 'gamma(one)', '-flag', 'semi;name', 'sample_6']
        source = self.directory / 'input spaces.afa'
        source.write_text(''.join('>' + name + ' full description\n' + seq + '\n' for name, seq in zip(names, rows.values())))
        out, _ = self.run_tool(source=source, model='JC')
        leaves, _, _ = independent_newick(out / 'inferred-tree.nwk')
        self.assertCountEqual(leaves, names)
        provenance = json.loads((out / 'analysis-provenance.json').read_text())
        self.assertEqual([x['originalId'] for x in provenance['taxonMapping']], names)
        self.assertNotIn('alpha', (out / 'iqtree-work/alignment.fa').read_text())

    def test_07_malformed_alignment_guards(self):
        rows = fasta(PACK / 'fixtures/nucleotide.afa')
        base = list(rows.items())
        cases = {
            'few': base[:3],
            'unequal': base[:5] + [(base[5][0], base[5][1][:-1])],
            'identical': [(name, base[0][1]) for name, _ in base],
            'empty': base[:5] + [(base[5][0], '')],
            'unknown': base[:5] + [(base[5][0], 'N' * 800)],
            'invalid': base[:5] + [(base[5][0], base[5][1][:-1] + '*')],
            'duplicate': base[:5] + [(base[0][0], base[5][1])],
            'uninformative': [(name, 'A' * (25 + n) + 'C' + 'A' * (774 - n)) for n, (name, _) in enumerate(base)]}
        for name, records in cases.items():
            with self.subTest(name=name):
                source = self.directory / (name + '.afa')
                source.write_text(''.join('>' + k + '\n' + v + '\n' for k, v in records))
                _, result = self.run_tool(source=source, success=False)
                self.assertIn('IQ-TREE pack:', result.stderr)

    def test_08_options_and_shell_arguments_rejected(self):
        for model, extra in [('GTR+G4;echo', ()), ('LG+G4', ()), ('MFP', ('--replicates', '999')), ('MFP', ('--threads', '0')), ('MFP', ('--seed', '-1')), ('MFP', ('--seed', '1;echo')), ('MFP', ('--replicates', '10001'))]:
            with self.subTest(model=model, extra=extra):
                self.run_tool(model=model, extra=extra, success=False)

    def test_09_explicit_protein_datatype_and_normalizations(self):
        source = self.directory / 'dna-looking-protein.afa'
        source.write_bytes((PACK / 'fixtures/nucleotide.afa').read_bytes())
        out, _ = self.run_tool('protein', 'LG+G4', source=source)
        provenance = json.loads((out / 'analysis-provenance.json').read_text())
        self.assertEqual(provenance['datatype'], 'AA')
        self.assertIn('800 amino-acid sites', (out / 'iqtree-report.txt').read_text())
        rows = fasta(PACK / 'fixtures/nucleotide.afa')
        source2 = self.directory / 'rna lower gaps.afa'
        source2.write_text(''.join('>' + k + '\n' + v.lower().replace('t', 'u') + '.\n' for k, v in rows.items()))
        out2, _ = self.run_tool(source=source2, model='JC')
        staged = fasta(out2 / 'iqtree-work/alignment.fa')
        self.assertEqual(list(staged.values()), [v + '-' for v in rows.values()])
        self.assertEqual(json.loads((out2 / 'model-selection.json').read_text())['alignment']['columns'], 801)

    def test_10_installed_check_declarations(self):
        declarations = json.loads((PACK / 'workbench-checks.json').read_text())
        self.assertEqual(len(declarations['checks']), 4)
        for item in declarations['checks']:
            params = item['params']
            out, _ = self.run_tool(item['workflow'].removeprefix('infer-'), params.get('model', 'MFP'), params.get('support', 'none'))
            files = {'tree': 'inferred-tree.nwk', 'report': 'iqtree-report.txt', 'model': 'model-selection.json', 'provenance': 'analysis-provenance.json', 'log': 'iqtree.log'}
            for expectation in item['expect']:
                # Match released pack_checks._read_check_text: decode actual bytes,
                # not read_text(), which hides Windows CRLF regressions.
                content = (out / files[expectation['output']]).read_bytes().decode('utf-8')
                for fragment in expectation['contains']:
                    self.assertIn(fragment, content, item['id'] + ': missing ' + fragment)
            NATIVE_CHECKS.append({'id': item['id'], 'success': True})

    def test_11_actual_muscle_alignment_to_tree(self):
        if os.name == 'nt':
            self.assertEqual(sha(MUSCLE_ARCHIVE), 'c07d3e398f48df683926c0970ef77c3b7d2bdab6426b80c80186f2360ed25258')
            folder = self.directory / 'muscle native tool'
            folder.mkdir()
            with zipfile.ZipFile(MUSCLE_ARCHIVE) as archive:
                for name in ('muscle.exe', 'libomp.dll'):
                    (folder / name).write_bytes(archive.read('pack/bin/' + name))
            executable = folder / 'muscle.exe'
        else:
            executable = MUSCLE_BINARY
            lock = json.loads((PACK / 'licenses/input-lock.json').read_text())
            expected = next(x['sha256'] for x in lock['inputs'] if x['filename'] == executable.name)
            self.assertEqual(sha(executable), expected)
        for datatype, flag, model in [('nucleotide', '-nt', 'JC'), ('protein', '-amino', 'LG+G4')]:
            aligned = self.directory / (datatype + ' real MUSCLE.afa')
            source = PACK / 'fixtures' / (datatype + '.afa')
            command = [str(executable), '-super5', str(source), '-output', str(aligned), flag, '-threads', '1', '-perturb', '0', '-perm', 'none']
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({k: v.replace('-', '') for k, v in fasta(aligned).items()}, fasta(source))
            out, _ = self.run_tool(datatype, model, source=aligned)
            matrix = list(fasta(aligned).values())
            self.assertEqual(len({len(x) for x in matrix}), 1)
            observed = [Counter(x for x in column if x != '-') for column in zip(*matrix)]
            stats = (len(matrix[0]), sum(len(c) > 1 for c in observed), sum(sum(n >= 2 for n in c.values()) >= 2 for c in observed))
            self.assert_fixture(out, expected_stats=stats)
            MUSCLE_EVIDENCE.append({'datatype': datatype, 'muscleExecutableSha256': sha(executable), 'muscleArchiveSha256': sha(MUSCLE_ARCHIVE) if MUSCLE_ARCHIVE else None,
                'method': 'Super5, explicit alphabet, threads1, perturb0, permnone', 'alignmentSha256': sha(aligned), 'alignmentResiduesPreserved': True, 'alignmentColumns': stats[0], 'variableColumns': stats[1], 'informativeColumns': stats[2], 'iqtreeKnownTopologyPassed': True})

    def test_12_windows_path_guard_and_unicode_input(self):
        source = self.directory / 'selected input é.afa'
        source.write_bytes((PACK / 'fixtures/nucleotide.afa').read_bytes())
        out, _ = self.run_tool(source=source, model='JC')
        self.assert_fixture(out)
        if os.name == 'nt':
            destination = self.directory / 'results é'
            destination.mkdir()
            result = subprocess.run([str(self.python), '-I', '-B', '-X', 'utf8', str(self.adapter), '--alignment', str(source), '--run', str(destination), '--datatype', 'DNA', '--model', 'JC'], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ASCII', result.stderr)
            self.assertEqual(list(destination.iterdir()), [])

    def test_13_deep_newick_parser_does_not_recurse(self):
        names = {'T' + str(i).zfill(6): 'taxon' + str(i) for i in range(1, 1201)}
        tokens = list(names)
        tree = '(' * 1199 + tokens[0] + ':0.1,' + tokens[1] + ':0.1)'
        for token in tokens[2:]:
            tree += ':0.1,' + token + ':0.1)'
        result = self.mod.tree_evidence(tree + ';', names)
        self.assertEqual(len(result['taxa']), 1200)
        self.assertEqual(result['nontrivialBipartitions'], [])
        self.assertEqual(result['bipartitionSummary'], 'omitted-above-256-taxa-use-full-Newick')
        self.assertLess(len(json.dumps(result)), 30000)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=PACK)
    parser.add_argument('--binary', type=Path, help='Explicit developer Linux reference executable; omit on native Windows')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--muscle-archive', type=Path, help='Required on Windows: unchanged published MUSCLE0.5.2 pack ZIP')
    parser.add_argument('--muscle-binary', type=Path, help='Linux only: pinned official MUSCLE5.3 executable')
    args = parser.parse_args()
    PACK = args.pack.resolve()
    MUSCLE_ARCHIVE = args.muscle_archive.resolve() if args.muscle_archive else None
    MUSCLE_BINARY = args.muscle_binary.resolve() if args.muscle_binary else MUSCLE_BINARY.resolve()
    BINARY = (args.binary.resolve() if args.binary else PACK / 'bin/iqtree3.exe' if os.name == 'nt' else BINARY.resolve())
    if os.name == 'nt' and args.binary:
        parser.error('Windows checks must run the installed pack executable, not an external replacement.')
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IQTreeTests))
    import configparser
    identity = configparser.ConfigParser(interpolation=None)
    identity.read(PACK / 'pack.ini', encoding='utf-8')
    evidence = {'schema': 1, 'packId': 'iqtree', 'packVersion': identity['pack']['version'], 'toolVersion': '3.1.4', 'nativeWindowsExecuted': os.name == 'nt',
        'scientificExecutablesExecuted': True, 'platform': sys.platform, 'pythonVersion': sys.version, 'packManifestSha256': sha(PACK / 'pack.ini'),
        'scientificBinarySha256': sha(BINARY), 'installedAdapterSha256': sha(PACK / 'adapter.py'), 'testSourceSha256': sha(Path(__file__)),
        'testsRun': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'success': result.wasSuccessful(),
        'seconds': round(time.monotonic() - started, 3), 'installationCheckDeclarations': NATIVE_CHECKS, 'executions': EXECUTIONS, 'muscleIntegration': MUSCLE_EVIDENCE,
        'scope': 'Synthetic known topology, model/columns, actual support, direct upstream agreement, input/pack immutability and validation guards; no GUI, large-tree performance or clinical claim.'}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({k: v for k, v in evidence.items() if k not in ('executions', 'pythonVersion')}, indent=2))
    sys.exit(not result.wasSuccessful())
