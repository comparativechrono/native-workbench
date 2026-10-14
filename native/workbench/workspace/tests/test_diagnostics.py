"""Privacy boundary and real ZIP/filesystem tests; no scientific execution claims."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def fixture(self):
        return diagnostics.build_report(None, {
            'packs': [{'id': 'bam', 'version': '0.4.0', 'manifestSha256': 'a' * 64}],
            'tools': {'bam/sort': {}}, 'errors': [],
        }, run={'status': 'failed', 'nodes': [
            {'status': 'success', 'pin': {'packId': 'bam', 'packVersion': '0.4.0', 'manifestSha256': 'a' * 64}},
            {'status': 'failed', 'pin': {'packId': 'variants', 'packVersion': '0.4.0', 'manifestSha256': 'b' * 64}},
        ]}, readiness={'status': 'blocked', 'checks': [
            {'status': 'failed'}, {'status': 'passed'}, {'status': 'not_checked'},
        ]})

    def test_private_canaries_never_enter_review_or_any_zip_member(self):
        private = 'PRIVATE-PATIENT-CANARY-73'
        path = 'C:\\Users\\' + private + '\\sample.fastq'
        document = {
            'id': private, 'version': private, 'name': private, 'description': private,
            'folder': path, 'manifestSha256': private, 'message': private,
            'file': path, 'status': private, 'code': private,
            'command': ['tool.exe', path], 'settings': {private: private},
            'environment': {private: private}, 'url': 'https://' + private,
        }
        catalog = {'packs': [document], 'tools': {private: document}, 'errors': [document]}
        run = dict(document, nodes=[dict(document, pin=document)], performance=document)
        readiness = dict(document, checks=[document], outputFolder={'path': path})
        originals = copy.deepcopy((catalog, run, readiness))
        class UnreadableRoot:
            def __fspath__(self):
                raise AssertionError('App root must not be scanned')
        with mock.patch.dict(os.environ, {'PRIVATE_CANARY': private}), mock.patch.object(
                diagnostics, 'safe_system_identity', return_value={'architecture': private,
                    'os': {'name': private, 'release': private, 'version': private}}):
            report = diagnostics.build_report(UnreadableRoot(), catalog, run, readiness)
        review = diagnostics.preview_text(report)
        self.assertNotIn(private, review)
        self.assertNotIn(path, review)
        self.assertEqual(report['catalog']['packs'][0], {'id': 'third-party', 'version': None, 'manifestSha256': None})
        self.assertEqual(report['run']['status'], 'unknown')
        self.assertEqual(report['readiness']['statusCounts']['unknown'], 1)
        self.assertEqual((catalog, run, readiness), originals)
        with tempfile.TemporaryDirectory() as folder:
            artifact = diagnostics.export_report(report, folder)
            with zipfile.ZipFile(artifact) as archive:
                for item in archive.infolist():
                    self.assertNotIn(private, item.filename)
                    self.assertNotIn(private.encode(), archive.read(item))

    def test_cold_review_and_export_need_no_hostname_or_socket_calls(self):
        # A subprocess prevents the irreversible audit hook affecting unrelated
        # tests and catches cold-import/cache differences. Block platform.uname
        # as well: on Linux the old machine() call did not raise a socket event,
        # while Windows uname() calls socket.gethostname() before returning it.
        program = r'''
import json, platform, sys, tempfile, zipfile
sys.path.insert(0, sys.argv[1])
def reject_network(event, arguments):
    if event.startswith('socket.'):
        raise RuntimeError('Unexpected socket or hostname call: ' + event)
def reject_uname(*args, **kwargs):
    raise RuntimeError('platform.uname must not collect computer identity')
platform.uname = reject_uname
sys.addaudithook(reject_network)
import diagnostics
report = diagnostics.build_report(None, {'packs': [], 'tools': {}, 'errors': []})
preview = diagnostics.preview_text(report).encode('utf-8')
with tempfile.TemporaryDirectory() as destination:
    artifact = diagnostics.export_report(report, destination)
    with zipfile.ZipFile(artifact) as archive:
        assert archive.read('report.json') == preview
assert report['system']['os'] in ('Windows', 'Linux', 'macOS', 'other')
print(json.dumps({'success': True, 'architecture': report['system']['architecture']}))
'''
        result = subprocess.run([sys.executable, '-I', '-c', program, str(Path(diagnostics.__file__).parent)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['success'])

    def test_real_archive_matches_review_and_retains_failed_and_unchecked_states(self):
        report = self.fixture()
        self.assertEqual(report['run']['status'], 'failed')
        self.assertEqual([item['status'] for item in report['run']['steps']], ['success', 'failed'])
        self.assertEqual(report['readiness']['statusCounts']['not_checked'], 1)
        review = diagnostics.preview_text(report).encode()
        with tempfile.TemporaryDirectory() as folder:
            archive_path = diagnostics.export_report(report, folder)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {'report.json', 'README.txt', 'SHA256SUMS.txt'})
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('report.json'), review)
                self.assertEqual(json.loads(archive.read('report.json')), report)
                for line in archive.read('SHA256SUMS.txt').decode().splitlines():
                    digest, name = line.split('  ')
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
                self.assertTrue(all(not item.flag_bits & 1 for item in archive.infolist()))
            if os.name != 'nt':
                self.assertEqual(archive_path.stat().st_mode & 0o777, 0o600)

    def test_records_are_bounded_and_missing_measurements_are_not_zero(self):
        report = diagnostics.build_report(None, {'packs': [{}] * 600},
            {'nodes': [{}] * 900}, {'checks': [{'status': 'failed'}] * 5000})
        self.assertEqual(len(report['catalog']['packs']), 256)
        self.assertEqual(report['catalog']['omittedPackCount'], 344)
        self.assertEqual(len(report['run']['steps']), 256)
        self.assertEqual(report['run']['omittedStepCount'], 644)
        self.assertEqual(report['readiness']['checkCount'], 5000)
        self.assertEqual(report['readiness']['examinedCheckCount'], 4096)
        self.assertEqual(report['readiness']['omittedCheckCount'], 904)
        self.assertLess(len(diagnostics.preview_text(report).encode()), diagnostics.MAX_REPORT_BYTES)
        with mock.patch.object(diagnostics, '_memory_bytes', return_value=None), mock.patch.object(
                diagnostics.os, 'cpu_count', return_value=None):
            unknown = diagnostics.build_report(None, {})
        self.assertIsNone(unknown['system']['logicalCpuCount'])
        self.assertIsNone(unknown['system']['totalMemoryBytes'])

    def test_unknown_fields_and_tampered_reports_fail_before_creating_output(self):
        malicious = [
            lambda r: r.update({'../private.txt': 'PRIVATE'}),
            lambda r: r['run'].update({'command': 'PRIVATE'}),
            lambda r: r['system'].update({'hostname': 'PRIVATE'}),
            lambda r: r['catalog']['packs'][0].update({'id': 'patient-name'}),
            lambda r: r['catalog']['packs'][0].update({'version': '../../private'}),
            lambda r: r['catalog']['packs'][0].update({'manifestSha256': 'PRIVATE'}),
            lambda r: r['system'].update({'totalMemoryBytes': float('nan')}),
            lambda r: r['limits'].update({'automaticUpload': True}),
            lambda r: r['run'].update({'steps': r['run']['steps'] * 500}),
        ]
        with tempfile.TemporaryDirectory() as folder:
            for mutate in malicious:
                report = self.fixture()
                mutate(report)
                with self.assertRaises((ValueError, TypeError)):
                    diagnostics.export_report(report, folder)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unique_exports_are_thread_safe_and_collision_never_overwrites(self):
        report = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            with ThreadPoolExecutor(max_workers=4) as executor:
                paths = list(executor.map(lambda _: diagnostics.export_report(report, folder), range(12)))
            self.assertEqual(len(set(paths)), 12)
            with mock.patch.object(diagnostics.secrets, 'token_hex', return_value='0' * 32):
                first = diagnostics.export_report(report, folder)
                original = first.read_bytes()
                with self.assertRaises(FileExistsError):
                    diagnostics.export_report(report, folder)
                self.assertEqual(first.read_bytes(), original)

    def test_failed_write_removes_only_its_new_partial_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / 'analysis-result.vcf'
            existing.write_text('scientific result must remain unchanged')
            before = existing.read_bytes()
            with mock.patch.object(diagnostics.os, 'fsync', side_effect=OSError('simulated full disk')):
                with self.assertRaises(OSError):
                    diagnostics.export_report(self.fixture(), folder)
            self.assertEqual(list(Path(folder).iterdir()), [existing])
            self.assertEqual(existing.read_bytes(), before)

    def test_missing_or_file_destination_is_not_created_or_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'result'
            file.write_text('existing scientific output')
            for destination in (Path(folder) / 'missing', file):
                with self.assertRaises((OSError, ValueError)):
                    diagnostics.export_report(self.fixture(), destination)
            self.assertEqual(file.read_text(), 'existing scientific output')
            self.assertEqual(list(Path(folder).iterdir()), [file])

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink test; Windows junction test is separate')
    def test_symlink_destination_or_ancestor_cannot_redirect_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / 'real'
            real.mkdir()
            child = real / 'child'
            child.mkdir()
            link = root / 'link'
            link.symlink_to(real, target_is_directory=True)
            for destination in (link, link / 'child'):
                with self.assertRaises((ValueError, OSError)):
                    diagnostics.export_report(self.fixture(), destination)
            self.assertEqual(list(child.iterdir()), [])
            self.assertEqual(list(real.iterdir()), [child])

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows junction handling requires Windows')
    def test_windows_junction_destination_and_ancestor_cannot_redirect_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / 'real'
            real.mkdir()
            child = real / 'child'
            child.mkdir()
            link = root / 'link'
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(real)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for destination in (link, link / 'child'):
                    with self.assertRaises((OSError, ValueError)):
                        diagnostics.export_report(self.fixture(), destination)
                self.assertEqual(list(child.iterdir()), [])
                self.assertEqual(list(real.iterdir()), [child])
            finally:
                os.rmdir(link)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows extended-path IO requires Windows')
    def test_windows_long_destination_uses_extended_io_without_changing_display_path(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            while len(str(parent)) <= 300:
                parent /= 'nested-diagnostics-folder'
            diagnostics.filesystem_path(parent).mkdir(parents=True)
            try:
                result = diagnostics.export_report(self.fixture(), parent)
                self.assertEqual(result.parent, parent)
                self.assertFalse(str(result).startswith('\\\\?\\'))
                with zipfile.ZipFile(diagnostics.filesystem_path(result)) as archive:
                    self.assertEqual(json.loads(archive.read('report.json'))['run']['status'], 'failed')
            finally:
                import shutil
                shutil.rmtree(diagnostics.filesystem_path(Path(folder) / 'nested-diagnostics-folder'))


if __name__ == '__main__':
    unittest.main()
