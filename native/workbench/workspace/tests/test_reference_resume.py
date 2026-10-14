"""Durable resumable reference transfers with adversarial HTTP entity behavior."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_manager import ReferenceManager, ReferenceError, ReferencePaused, ReferenceCancelled
from reference_provider import ReferenceHTTPError
from reference_transfer import file_lease
from test_reference_manager import Provider


class RangeResponse(io.BytesIO):
    def __init__(self, provider, url, offset, code, headers):
        super().__init__(provider.data[url][offset:])
        self.provider, self.url, self.code, self.headers = provider, url, code, headers
        self.amount = 0
    def getcode(self):
        return self.code
    def geturl(self):
        return self.url
    def read(self, count=-1):
        if self.provider.fail_after is not None and self.amount >= self.provider.fail_after:
            raise OSError('simulated dropped connection')
        block = super().read(min(count, 257))
        self.amount += len(block)
        if block and self.provider.callback:
            self.provider.callback()
        return block


class RangeProvider(Provider):
    def __init__(self):
        super().__init__()
        self.plain = b'>chromosome1\n' + ''.join(random.Random(33).choices('ACGT', k=100000)).encode() + b'\n'
        self.add('genome', self.plain)
        self.requests = []; self.fail_after = None; self.behavior = 'valid'
        self.no_validator = False
    def open_url(self, url, cancel=None, headers=None):
        if self.fail_network:
            raise AssertionError('offline operation attempted network')
        self.requests.append(deepcopy(headers))
        total = len(self.data[url]); offset = 0; code = 200
        result = {'ETag': '"entity-one"', 'Last-Modified': 'Mon, 05 Oct 2026 00:00:00 GMT'}
        if self.no_validator:
            result = {}
        if headers:
            if self.behavior == '416':
                raise ReferenceHTTPError(416, url)
            offset = int(headers['Range'][6:-1]); code = 206
            result['Content-Range'] = f'bytes {offset}-{total - 1}/{total}'
            if self.behavior == 'wrong_offset':
                result['Content-Range'] = f'bytes {offset + 1}-{total - 1}/{total}'
            if self.behavior == 'wrong_total':
                result['Content-Range'] = f'bytes {offset}-{total}/{total + 1}'
            if self.behavior == 'changed_etag':
                result['ETag'] = '"entity-two"'
            if self.behavior == 'ignored':
                offset = 0; code = 200; result.pop('Content-Range')
        result['Content-Length'] = str(total - offset)
        return RangeResponse(self, url, offset, code, result)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'Workbench'; self.root.mkdir()
        self.dest = Path(self.temp.name) / 'Reference data'; self.dest.mkdir()
        self.provider = RangeProvider(); self.manager = ReferenceManager(self.root, self.provider)
    def tearDown(self):
        self.temp.cleanup()
    def download(self, **kwargs):
        selection = self.manager.discover(116, 'test_species')['discovery']['selection_id']
        return self.manager.download(selection, ['genome'], str(self.dest), **kwargs)
    def pause(self):
        ready_before = self.manager.snapshot()['local']
        folders_before = list(self.dest.iterdir())
        self.provider.callback = self.manager.pause
        with self.assertRaises(ReferencePaused):
            self.download()
        self.provider.callback = None
        pending = self.manager.snapshot()['pending']
        self.assertEqual(len(pending), 1); self.assertEqual(pending[0]['status'], 'paused')
        self.assertEqual(self.manager.snapshot()['local'], ready_before); self.assertEqual(list(self.dest.iterdir()), folders_before)
        self.assertGreater(pending[0]['bytes'], 0)
        return pending[0]
    def complete(self, manager, identity):
        result = manager.resume(identity)
        self.assertEqual(result['pending'], [])
        file = result['local'][-1]['files'][0]
        self.assertEqual(Path(file['path']).read_bytes(), self.provider.plain)
        self.assertEqual(file['sha256'], hashlib.sha256(self.provider.plain).hexdigest())
        self.assertEqual(file['compressed_sha256'], hashlib.sha256(self.provider.data[file['source_url']]).hexdigest())
        return file
    def test_pause_reopen_offline_snapshot_and_resume_verified_offset(self):
        pending = self.pause()
        self.provider.fail_network = True
        reopened = ReferenceManager(self.root, self.provider)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(reopened.snapshot()['pending'], self.manager.snapshot()['pending'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.provider.fail_network = False
        self.complete(reopened, pending['id'])
        self.assertEqual(self.provider.requests[-1], {'Range': f'bytes={pending["bytes"]}-', 'If-Range': '"entity-one"'})
    def test_network_interruption_retains_progress_then_resumes(self):
        self.provider.fail_after = 500
        with self.assertRaisesRegex(ReferenceError, 'interrupted'):
            self.download()
        pending = self.manager.snapshot()['pending'][0]
        self.assertEqual(pending['status'], 'interrupted'); self.assertEqual(self.manager.snapshot()['local'], [])
        self.provider.fail_after = None
        self.complete(ReferenceManager(self.root, self.provider), pending['id'])
    def test_cancel_retains_original_cleanup_contract(self):
        cancel = threading.Event(); self.provider.callback = cancel.set
        with self.assertRaises(ReferenceCancelled):
            self.download(cancel=cancel)
        self.assertEqual(self.manager.snapshot()['pending'], [])
        self.assertEqual(self.manager.snapshot()['local'], [])
        self.assertEqual(list(self.dest.iterdir()), [])
    def test_cancel_resume_discards_existing_progress(self):
        pending = self.pause(); cancel = threading.Event(); cancel.set()
        with self.assertRaises(ReferenceCancelled):
            self.manager.resume(pending['id'], cancel=cancel)
        self.assertEqual(self.manager.snapshot()['pending'], [])
    def test_discard_is_offline_and_cannot_escape_job_root(self):
        pending = self.pause(); self.provider.fail_network = True
        self.assertEqual(self.manager.discard(pending['id'])['pending'], [])
        for identity in ('../outside', 'x'*32, '', None):
            with self.assertRaises(ReferenceError):
                self.manager.discard(identity)
    def test_ignored_range_restarts_without_duplicate_prefix(self):
        pending = self.pause(); self.provider.behavior = 'ignored'
        self.complete(self.manager, pending['id'])
        self.assertIsNotNone(self.provider.requests[-1])
    def test_changed_or_invalid_range_and_416_restart_full(self):
        for behavior in ('wrong_offset', 'wrong_total', 'changed_etag', '416'):
            with self.subTest(behavior=behavior):
                pending = self.pause(); self.provider.behavior = behavior
                self.complete(self.manager, pending['id'])
                self.assertIsNone(self.provider.requests[-1])
                self.provider.behavior = 'valid'
    def test_no_strong_validator_forces_safe_full_restart(self):
        self.provider.no_validator = True
        pending = self.pause(); self.complete(self.manager, pending['id'])
        self.assertIsNone(self.provider.requests[-1])
    def test_equal_length_modified_prefix_rejected_before_network(self):
        pending = self.pause(); folder = self.manager._job_path(pending['id'])
        path = folder / 'genome.gz'; data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        calls = len(self.provider.requests)
        with self.assertRaisesRegex(ReferenceError, 'prefix has changed'):
            self.manager.resume(pending['id'])
        self.assertEqual(len(self.provider.requests), calls); self.assertEqual(self.manager.snapshot()['local'], [])
    def test_crash_uncheckpointed_suffix_is_not_trusted(self):
        pending = self.pause(); path = self.manager._job_path(pending['id']) / 'genome.gz'
        with path.open('ab') as stream:
            stream.write(b'uncommitted crash suffix')
        self.complete(ReferenceManager(self.root, self.provider), pending['id'])
        self.assertEqual(self.provider.requests[-1]['Range'], f'bytes={pending["bytes"]}-')
    def test_discovery_pin_tampering_and_damaged_json_not_resumed(self):
        pending = self.pause(); folder = self.manager._job_path(pending['id'])
        doc = json.loads((folder / 'job.json').read_text()); doc['files'][0]['url'] += 'changed'
        (folder / 'job.json').write_text(json.dumps(doc))
        calls = len(self.provider.requests)
        self.assertFalse(self.manager.snapshot()['pending'][0]['resumable'])
        with self.assertRaisesRegex(ReferenceError, 'pin has changed'):
            self.manager.resume(pending['id'])
        self.assertEqual(calls, len(self.provider.requests))
        self.manager.discard(pending['id'])
    def test_md5_provider_checksum_is_enforced(self):
        raw = self.provider.data[self.provider.files[-1]['url']]
        self.provider.files[-1]['checksum'] = {'algorithm': 'md5', 'value': hashlib.md5(raw).hexdigest()}
        result = self.download(); self.assertEqual(result['local'][0]['files'][0]['validation']['provider_md5'], 'passed')
        self.provider.files[-1]['checksum']['value'] = '0'*32
        with self.assertRaisesRegex(ReferenceError, 'MD5 checksum'):
            self.download()
    def test_concurrent_transfer_lease_and_stale_inode(self):
        self.manager.data.mkdir(parents=True)
        with file_lease(self.manager.data / '_transfer.lease'):
            with self.assertRaisesRegex(ReferenceError, 'Another Workbench'):
                self.download()
        self.assertEqual(len(self.download()['local']), 1)
    def test_os_lease_recovers_after_abrupt_process_death(self):
        self.manager.data.mkdir(parents=True)
        lock = self.manager.data / '_transfer.lease'
        code = 'import sys,time;sys.path.insert(0,sys.argv[1]);from reference_transfer import file_lease;from pathlib import Path\nwith file_lease(Path(sys.argv[2])):\n print("locked",flush=True);time.sleep(30)'
        child = subprocess.Popen([sys.executable, '-c', code, str(Path(__file__).resolve().parents[1]), str(lock)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            with self.assertRaisesRegex(ReferenceError, 'Another Workbench'):
                with file_lease(lock):
                    self.fail('lease must exclude live owner')
            child.kill(); child.wait(timeout=5)
            with file_lease(lock):
                pass
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            child.stdout.close()
    def _child(self, code, *args):
        command = [sys.executable, '-c', 'import sys,os;sys.path[:0]=sys.argv[1:3];' + code,
                   str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent), *map(str, args)]
        return subprocess.run(command, capture_output=True, text=True, timeout=15)
    def test_actual_process_death_during_checkpoint_replace_recovers(self):
        pending = self.pause()
        code = "from reference_manager import ReferenceManager;import reference_manager as rm;from test_reference_resume import RangeProvider;manager=ReferenceManager(sys.argv[3],RangeProvider());original=rm.os.replace;rm.os.replace=lambda src,dst: os._exit(72) if str(dst).endswith('job.json') else original(src,dst);manager.resume(sys.argv[4])"
        child = self._child(code, self.root, pending['id'])
        self.assertEqual(child.returncode, 72, child.stderr)
        folder = self.manager._job_path(pending['id'])
        self.assertTrue(any(p.name.startswith('_write-') for p in folder.iterdir()))
        self.assertTrue(self.manager.snapshot()['pending'][0]['resumable'])
        self.complete(ReferenceManager(self.root, self.provider), pending['id'])
    def _crash_publication(self):
        code = "from reference_manager import ReferenceManager;from test_reference_resume import RangeProvider;manager=ReferenceManager(sys.argv[3],RangeProvider());manager._write_library=lambda doc:os._exit(73);selection=manager.discover(116,'test_species')['discovery']['selection_id'];manager.download(selection,['genome'],sys.argv[4])"
        child = self._child(code, self.root, self.dest)
        self.assertEqual(child.returncode, 73, child.stderr)
        pending = self.manager.snapshot()['pending'][0]
        self.assertEqual(self.manager.snapshot()['local'], [])
        self.assertEqual(len([p for p in self.dest.iterdir() if p.name.startswith('ref-')]), 1)
        return pending
    def test_actual_process_death_after_publication_rename_registers_verified_orphan(self):
        pending = self._crash_publication(); self.provider.fail_network = True
        self.complete(ReferenceManager(self.root, self.provider), pending['id'])
    def test_discard_cleans_proven_owned_unregistered_publication(self):
        pending = self._crash_publication(); self.provider.fail_network = True
        self.manager.discard(pending['id'])
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(self.manager.snapshot()['pending'], [])
    def test_malformed_file_identity_is_bounded_in_offline_snapshot(self):
        from reference_manager import _json_bytes
        pending = self.pause(); folder = self.manager._job_path(pending['id'])
        doc = json.loads((folder / 'job.json').read_text()); doc['files'][0]['id'] = []
        pin = _json_bytes({key: doc[key] for key in ('id', 'selection', 'files', 'destination')})
        (folder / 'pin.json').write_bytes(pin); doc['pin_sha256'] = hashlib.sha256(pin).hexdigest()
        (folder / 'job.json').write_text(json.dumps(doc))
        self.assertFalse(self.manager.snapshot()['pending'][0]['resumable'])
        with self.assertRaisesRegex(ReferenceError, 'invalid files'):
            self.manager.resume(pending['id'])
        self.manager.discard(pending['id'])
    def test_symlink_checkpoint_or_prefix_is_not_followed(self):
        pending = self.pause(); folder = self.manager._job_path(pending['id'])
        original = folder / 'genome.gz'; saved = self.root / 'saved.gz'; original.rename(saved)
        try:
            original.symlink_to(saved)
        except OSError:
            original.write_bytes(saved.read_bytes()); self.skipTest('Symlink privilege unavailable')
        before = saved.read_bytes()
        self.assertFalse(self.manager.snapshot()['pending'][0]['resumable'])
        with self.assertRaisesRegex(ReferenceError, 'links or junctions'):
            self.manager.resume(pending['id'])
        self.assertEqual(saved.read_bytes(), before)
        original.unlink(); original.write_bytes(before); self.manager.discard(pending['id'])


if __name__ == '__main__':
    unittest.main()
