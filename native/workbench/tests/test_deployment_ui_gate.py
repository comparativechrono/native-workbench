"""Portable evidence-integrity checks; these do not simulate Windows UI passes."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('deployment_ui_gate',
    Path(__file__).resolve().parents[1] / 'scripts/check_deployment_ui_windows.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class DeploymentUIGateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def archive(self, members):
        path = self.root / 'input.zip'
        with zipfile.ZipFile(path, 'w') as zipped:
            for name, content in members.items():
                zipped.writestr(name, content)
        return path

    def test_flat_published_updater_layout_verifies_launcher_and_private_runtime(self):
        members = {'UpdateWorkbench.exe': b'published launcher', 'runtime/python/python.exe': b'private runtime'}
        archive = self.archive(members)
        extraction = self.root / 'updater'
        for name, content in members.items():
            path = extraction / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.assertEqual(gate.verify_extracted(archive, extraction), 2)
        (extraction / 'UpdateWorkbench.exe').write_bytes(b'changed launcher!!')
        with self.assertRaisesRegex(AssertionError, 'Extraction differs'):
            gate.verify_extracted(archive, extraction)

    def test_starter_root_is_stripped_once_and_missing_file_is_rejected(self):
        archive = self.archive({'native-workbench/NativeWorkbench.exe': b'app', 'native-workbench/manifest.json': b'{}'})
        extraction = self.root / 'starter'
        extraction.mkdir()
        (extraction / 'NativeWorkbench.exe').write_bytes(b'app')
        (extraction / 'manifest.json').write_bytes(b'{}')
        self.assertEqual(gate.verify_extracted(archive, extraction), 2)
        (extraction / 'manifest.json').unlink()
        with self.assertRaisesRegex(AssertionError, 'Extraction differs'):
            gate.verify_extracted(archive, extraction)

    def test_archive_traversal_is_rejected_before_reading_outside_extraction(self):
        archive = self.archive({'../outside.exe': b'untrusted'})
        with self.assertRaisesRegex(AssertionError, 'Unsafe archived path'):
            gate.verify_extracted(archive, self.root / 'updater')

    def test_snapshot_detects_addition_deletion_and_content_change(self):
        folder = self.root / 'saved'
        folder.mkdir()
        path = folder / 'settings.json'
        path.write_text('{"packVersion":"0.4.0"}', encoding='utf-8')
        baseline = gate.tree_hashes(folder)
        path.write_text('{"packVersion":"0.4.1"}', encoding='utf-8')
        self.assertNotEqual(gate.tree_hashes(folder), baseline)
        path.unlink()
        self.assertNotEqual(gate.tree_hashes(folder), baseline)
        (folder / 'other.json').write_text('{}', encoding='utf-8')
        self.assertNotEqual(gate.tree_hashes(folder), baseline)

    def test_preservation_diagnostics_distinguish_added_deleted_and_changed_files(self):
        self.assertEqual(gate.tree_difference({'retained': 'same', 'edited': 'old', 'deleted': 'gone'},
                                             {'retained': 'same', 'edited': 'new', 'added': 'new-file'}),
                         {'added': {'before': None, 'after': 'new-file'},
                          'deleted': {'before': 'gone', 'after': None},
                          'edited': {'before': 'old', 'after': 'new'}})

    def test_preservation_permits_only_the_exact_legacy_session_lock_addition(self):
        before = {'user-data/saved.json': 'unchanged', 'external/reference.fa': 'unchanged-reference'}
        after = dict(before, **{'user-data/session.lock': hashlib.sha256(b'\0').hexdigest()})
        self.assertEqual(gate.verify_preserved(before, after)['existingFiles'], 2)
        for bad in [dict(after, **{'user-data/session.lock': hashlib.sha256(b'').hexdigest()}),
                    dict(after, **{'user-data/saved.json': 'changed'}),
                    dict(after, **{'user-data/unexpected.json': 'new'}),
                    {'user-data/saved.json': 'unchanged'}]:
            with self.assertRaisesRegex(AssertionError, 'changed existing files'):
                gate.verify_preserved(before, bad)

    def test_message_box_button_uses_observed_label_and_ownership_not_id_one(self):
        # Exact regression shape from the Windows Server 2022 warning: OK has
        # ID 2, while the folder picker's separate confirmation has ID 1.
        controls = [{'id': 2, 'class': 'Button', 'text': 'OK', 'hwnd': 201},
                    {'id': 65535, 'class': 'Static', 'text': 'Warning', 'hwnd': 202}]
        enabled = {201}
        ui = SimpleNamespace(windows=lambda: [100], controls=lambda owner: controls,
                             user=SimpleNamespace(IsWindowVisible=lambda hwnd: True,
                                                  IsWindowEnabled=lambda hwnd: hwnd in enabled))
        self.assertEqual(gate.unique_button(ui, 100, 'OK'), 201)
        with self.assertRaisesRegex(AssertionError, 'gate-owned'):
            gate.unique_button(ui, 999, 'OK')
        enabled.clear()
        with self.assertRaisesRegex(AssertionError, 'one visible enabled'):
            gate.unique_button(ui, 100, 'OK')
        enabled.update((201, 203))
        controls.append({'id': 1, 'class': 'Button', 'text': '&OK', 'hwnd': 203})
        with self.assertRaisesRegex(AssertionError, 'one visible enabled'):
            gate.unique_button(ui, 100, 'OK')

    def test_completed_observations_retain_failed_requirement_and_incomplete_runs_cannot_pass(self):
        report = {'nativeGUIObservationsCompleted': True,
                  'scenarios': [{'status': 'pass'}, {'status': 'failed'}, {'status': 'pass'}]}
        gate.finalize_report(report)
        self.assertTrue(report['nativeGUIObservationsCompleted'])
        self.assertFalse(report['success'])
        self.assertFalse(report['nativeGUIValidated'])
        self.assertEqual((report['passed'], report['failed'], report['blocked']), (2, 1, 0))
        report['scenarios'] = [{'status': 'pass'}]
        report['nativeGUIObservationsCompleted'] = False
        gate.finalize_report(report)
        self.assertFalse(report['success'])
        report['nativeGUIObservationsCompleted'] = True
        gate.finalize_report(report)
        self.assertTrue(report['success'])

    def test_cli_rejects_input_overlap_before_creating_a_report_or_running_windows(self):
        bundle = self.root / 'immutable-kit'
        bundle.mkdir()
        sentinel = bundle / 'retained.txt'
        sentinel.write_bytes(b'immutable')
        app, updater, work = self.root / 'app-copy', bundle / 'updater', self.root / 'work'
        archive = self.root / 'starter.zip'
        archive.write_bytes(b'published-archive-sentinel')
        defaults = {'app-root': app, 'baseline-archive': self.root / 'baseline.zip',
                    'update-root': updater, 'starter-archive': archive,
                    'update-archive': self.root / 'update.zip', 'work': work,
                    'report': self.root / 'evidence' / 'report.json', 'bundle-root': bundle,
                    'source-commit': gate.SOURCE_COMMIT, 'gate-commit': 'a' * 40}
        cases = [
            {'report': bundle / 'new-evidence' / 'report.json'},
            {'work': bundle / 'new-work'},
            {'app-root': bundle / 'native-workbench'},
            {'report': app / 'new-evidence' / 'report.json'},
            {'report': updater / 'new-evidence' / 'report.json'},
            {'report': archive},
            {'report': work / 'new-evidence' / 'report.json'},
        ]
        before = gate.tree_hashes(self.root)
        for changes in cases:
            values = dict(defaults, **changes)
            argv = ['gate.py'] + [part for name, value in values.items()
                                  for part in ('--' + name, str(value))]
            with self.subTest(changes=changes), patch('sys.argv', argv), patch.object(gate, 'run') as run:
                with self.assertRaises(AssertionError):
                    gate.main()
                run.assert_not_called()
                self.assertEqual(gate.tree_hashes(self.root), before)
                self.assertEqual(sorted(path.relative_to(self.root).as_posix()
                                        for path in self.root.rglob('*') if path.is_dir()), ['immutable-kit'])


if __name__ == '__main__':
    unittest.main()
