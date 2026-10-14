"""Engine filesystem boundaries under an emulated MAX_PATH policy.

These source regressions use real files and execution plans, but the scientific
backend and Windows path limit are simulated. Native Windows gates are separate.
No user attachment paths or data are used here.
"""
from __future__ import annotations

import builtins
from contextlib import ExitStack, contextmanager
import copy
import errno
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
import engine
from catalog import load_catalog
from test_pack_versions import make_pack


class PhysicalPath(type(Path())):
    """Marks an explicit I/O-path conversion in the cross-platform fixture."""


@contextmanager
def ordinary_paths_limited():
    """Reject long ordinary I/O; converted paths still reach the real disk."""
    physical = engine._io_path

    def io_path(value):
        return PhysicalPath(physical(value))

    def check(value):
        if isinstance(value, int):
            return
        text = os.fsdecode(value)
        if len(text) >= 260 and not isinstance(value, PhysicalPath) and not text.startswith('\\\\?\\'):
            failure = FileNotFoundError(errno.ENOENT, 'Simulated ordinary Windows MAX_PATH limit', text)
            failure.winerror = 206
            raise failure

    def checked(function, positions=(0,)):
        def wrapper(*args, **kwargs):
            for position in positions:
                check(args[position])
            return function(*args, **kwargs)
        return wrapper

    def predicate(function):
        def wrapper(value, *args, **kwargs):
            try:
                check(value)
            except FileNotFoundError:
                return False
            return function(value, *args, **kwargs)
        return wrapper

    with ExitStack() as stack:
        stack.enter_context(patch.object(engine, '_io_path', io_path))
        stack.enter_context(patch.object(Path, 'stat', checked(Path.stat)))
        stack.enter_context(patch.object(Path, 'mkdir', checked(Path.mkdir)))
        stack.enter_context(patch.object(builtins, 'open', checked(builtins.open)))
        stack.enter_context(patch.object(io, 'open', checked(io.open)))
        stack.enter_context(patch.object(os, 'replace', checked(os.replace, (0, 1))))
        stack.enter_context(patch.object(os.path, 'samefile', checked(os.path.samefile, (0, 1))))
        for name in ('isfile', 'isdir', 'exists', 'islink'):
            stack.enter_context(patch.object(os.path, name, predicate(getattr(os.path, name))))
        yield


class NativeLikeBackend:
    def __init__(self, outside=None):
        self.requests = []
        self.outside = outside

    def run(self, request, event, cancel):
        self.requests.append(copy.deepcopy(request))
        folder = self.outside or Path(request['output_folder']) / 'analysis-native-output'
        engine._io_path(folder).mkdir(parents=True, exist_ok=True)
        value = engine._io_path(request['values']['source']).read_bytes()
        engine._io_path(folder / 'result.dat').write_bytes(value + b'\nprocessed')
        return {'success': True, 'folder': str(folder), 'message': 'Synthetic native backend completed.'}


class EnginePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workbench-paths-')
        self.root = Path(self.tmp.name)
        make_pack(self.root, '1.0.0')
        self.catalog = load_catalog(self.root)
        # A narrow synthetic metric-producing operation gives the same real
        # engine chain and report readers as ordinary pack outputs.
        operations = [self.catalog['tools']['example/process'], *self.catalog['toolVersions']['example/process']]
        for operation in operations:
            operation['ports'][0]['accepts'] = ['file', 'metrics']
            operation['outputs'][0]['type'] = 'metrics'
        self.source = self.root / 'input.txt'
        self.source.write_text('fixture data', encoding='utf-8')
        self.parent = self.root / ('output-' + 'x' * 150) / ('results-' + 'y' * 110)
        engine._io_path(self.parent).mkdir(parents=True)
        self.backend = NativeLikeBackend()
        self.engine = engine.Engine(self.root, self.catalog, backend=self.backend)

    def tearDown(self):
        self.tmp.cleanup()

    def graph(self):
        return {'schema': 1, 'name': 'Long output chain',
                'sources': [{'id': 'input-1', 'type': 'file', 'label': 'Fixture', 'files': {'source': str(self.source)}}],
                'nodes': [
                    {'id': 'step-1', 'tool': 'example/process', 'inputs': {'source': ['input-1']}, 'params': {}},
                    {'id': 'step-2', 'tool': 'example/process', 'inputs': {'source': ['step-1::result']}, 'params': {}},
                    {'id': 'step-3', 'tool': 'builtin/report', 'inputs': {'metrics': ['step-1::result', 'step-2::result']}, 'params': {}}]}

    def test_successful_backend_long_outputs_are_hashed_consumed_and_reported(self):
        with ordinary_paths_limited():
            plan = self.engine.prepare(self.graph(), self.parent)
            result = self.engine.execute(plan)
            self.assertTrue(result['success'], result)
            self.assertEqual([node['status'] for node in result['nodes']], ['success'] * 3)
            produced = result['outputs']['step-1::result']
            output_path = next(iter(produced['files'].values()))
            self.assertGreater(len(output_path), 260)
            self.assertFalse(Path(output_path).is_file(), 'Fixture must reproduce a false missing-file check for ordinary paths')
            self.assertTrue(engine._io_path(output_path).is_file())
            self.assertEqual(next(iter(produced['sha256'].values())), hashlib.sha256(b'fixture data\nprocessed').hexdigest())
            self.assertEqual(self.backend.requests[1]['values']['source'], output_path)
            for request in self.backend.requests:
                self.assertIsInstance(request['output_folder'], str)
                self.assertFalse(request['output_folder'].startswith('\\\\?\\'))
            for output in result['outputs'].values():
                for path in output['files'].values():
                    self.assertFalse(path.startswith('\\\\?\\'), 'I/O namespace must not leak into provenance')
            folder = Path(plan['folder'])
            record = json.loads(engine._io_path(folder / 'run.json').read_text())
            self.assertEqual(record['status'], 'success')
            reports = [path for output in result['outputs'].values() for path in output['files'].values() if path.endswith('.html')]
            self.assertTrue(reports)
            report = engine._io_path(reports[0]).read_text()
            self.assertEqual(report.count('<section>'), 2)
            self.assertIn('fixture data\nprocessed\nprocessed', report)
            self.assertTrue(engine._io_path(folder / 'methods-completed.txt').is_file())

    def test_frozen_plan_and_upstream_hash_protections_are_not_weakened(self):
        with ordinary_paths_limited():
            plan = self.engine.prepare(self.graph(), self.parent)
            modified = copy.deepcopy(plan)
            modified['nodes'][0]['params']['threshold'] = '3'
            with self.assertRaisesRegex(ValueError, 'frozen execution plan'):
                self.engine.execute(modified)
            self.source.write_text('changed fixture', encoding='utf-8')
            result = self.engine.execute(plan)
            self.assertFalse(result['success'])
            self.assertIn('external input changed', result['nodes'][0]['message'])
            self.assertEqual(result['nodes'][1]['status'], 'blocked')
            self.assertEqual(self.backend.requests, [])

    def test_result_containment_and_manifest_checks_are_not_weakened(self):
        with ordinary_paths_limited():
            plan = self.engine.prepare(self.graph(), self.parent)
            self.backend.outside = self.parent / 'escape'
            result = self.engine.execute(plan)
            self.assertFalse(result['success'])
            self.assertIn("outside this step's private folder", result['nodes'][0]['message'])
            manifest = self.root / 'packs/example-1.0.0/pack.ini'
            manifest.write_text(manifest.read_text() + '\n# changed\n')
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                self.engine.prepare(self.graph(), self.parent)

    def test_long_sequence_and_interval_readers_use_the_same_io_boundary(self):
        files = {
            'sequence.fa': b'>chr1\nACGTACGT\n',
            'targets.bed': b'chr1\t1\t5\n',
            'resource.vcf.gz': gzip.compress(b'##fileformat=VCFv4.2\n##INFO=<ID=AF,Number=A,Type=Float,Description="Frequency">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'),
            'ids.txt.gz': gzip.compress(b'alpha\nbeta\n')}
        for name, data in files.items():
            engine._io_path(self.parent / name).write_bytes(data)
        cancel = threading.Event()
        with ordinary_paths_limited():
            fasta = self.parent / 'sequence.fa'
            self.assertEqual(engine._fasta_dictionary(fasta)[0][:2], ('chr1', 8))
            sequence = engine._sequence_evidence(fasta, 'fasta-nucleotide', ['fasta-nucleotide'], {}, cancel)
            self.assertEqual(sequence['records'], 1)
            bed = engine._bed_evidence(self.parent / 'targets.bed', {'referenceBounds': True}, [('chr1', 8, '')], cancel)
            self.assertEqual(bed['records'], 1)
            vcf = engine._vcf_header_evidence(self.parent / 'resource.vcf.gz', {'requiredInfoFields': [{'id': 'AF', 'number': 'A', 'type': 'Float'}]}, cancel)
            self.assertEqual(vcf['check'], 'VCF-INFO-header')
            ids = engine._sequence_evidence(self.parent / 'ids.txt.gz', 'id-list', ['id-list'], {}, cancel)
            self.assertEqual(ids['records'], 2)
            self.assertEqual(engine._ordinary(fasta), fasta.resolve())

    def test_hardlink_input_identity_remains_rejected_at_long_paths(self):
        first, second = self.parent / 'first.fa', self.parent / 'second.fa'
        engine._io_path(first).write_text('>chr1\nACGT\n')
        os.link(engine._io_path(first), engine._io_path(second))
        tool = {'ports': [{'fields': [{'id': 'first', 'label': 'First file'},
                                     {'id': 'second', 'label': 'Second file', 'differentFrom': 'first'}]}]}
        with ordinary_paths_limited():
            with self.assertRaisesRegex(ValueError, 'must be a different file'):
                engine._check_distinct_files(tool, {'first': str(first), 'second': str(second)})

    def test_symbolic_input_and_output_ancestors_remain_rejected(self):
        target = self.parent / 'nested'
        engine._io_path(target).mkdir()
        engine._io_path(target / 'input.fa').write_text('>chr1\nACGT\n')
        alias = self.root / 'aliased-results'
        alias.symlink_to(engine._io_path(self.parent), target_is_directory=True)
        with ordinary_paths_limited():
            with self.assertRaisesRegex(ValueError, 'symbolic links or junctions'):
                engine._ordinary(alias / 'nested/input.fa')
            with self.assertRaisesRegex(ValueError, 'symbolic links or junctions'):
                self.engine.prepare(self.graph(), alias / 'nested')

    def test_windows_helper_imports_work_in_package_style_without_workspace_sys_path(self):
        code = '''
import sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import workspace.engine as engine
# Exercise the Windows-only lazy import branch without pretending to perform
# Windows filesystem operations on this host.
engine.os = SimpleNamespace(name="nt")
engine._io_path(sys.argv[1])
path = engine._display_path(r"\\\\?\\C:\\fixture\\file.txt")
assert str(path) == r"C:\\fixture\\file.txt", str(path)
'''
        result = subprocess.run([sys.executable, '-I', '-c', code, str(WORKSPACE.parent)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main(verbosity=2)
