"""Portable evidence guards; these are not Windows UI acceptance tests."""
import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('ui_patch_gate',
    Path(__file__).resolve().parents[1] / 'scripts/check_ui_patch_windows.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class UIPatchGateTests(unittest.TestCase):
    def test_observation_completion_never_becomes_application_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = ['gate.py', '--app-root', str(root / 'app'), '--starter-archive', str(root / 'input.zip'),
                    '--report', str(root / 'evidence/observation.json'), '--source-commit', '1' * 40,
                    '--gate-commit', '2' * 40, '--starter-sha256', 'a' * 64,
                    '--resize-only', '--resize-observation-only']
            def completed(unused_args, report):
                report['nativeGUIObservationsCompleted'] = True
                report['scenarios'].append({'status': 'pass'})
            with patch('sys.argv', args), patch.object(gate, 'run_resize_only', side_effect=completed):
                self.assertEqual(gate.main(), 0)
            report = json.loads((root / 'evidence/observation.json').read_text())
            self.assertTrue(report['success'])
            self.assertTrue(report['diagnosticCompleted'])
            self.assertFalse(report['nativeGUIValidated'])
            self.assertEqual(report['kind'], 'native-ui-resize-observation-only')
            with patch('sys.argv', args + ['--expect-known-resize-defect']), patch.object(gate, 'run_resize_only') as run:
                with self.assertRaises(AssertionError):
                    gate.main()
                run.assert_not_called()

    def test_resize_tool_readiness_requires_visible_owned_actual_hit(self):
        state = {'hit': 7, 'process': 12, 'visible': True, 'enabled': True}
        def owner(handle, output):
            output._obj.value = state['process']
        ui = SimpleNamespace(process=SimpleNamespace(pid=12), work_area=lambda: [0, 0, 1024, 728],
            user=SimpleNamespace(WindowFromPoint=lambda point: state['hit'],
                GetWindowThreadProcessId=owner, IsWindowVisible=lambda h: state['visible'],
                IsWindowEnabled=lambda h: state['enabled'], IsChild=lambda parent, child: False))
        self.assertTrue(gate.resize_tool_pointer_ready(ui, 7, [97, 238]))
        for key, value in [('hit', 5), ('process', 99), ('visible', False), ('enabled', False)]:
            previous = state[key]
            state[key] = value
            with self.subTest(key=key):
                self.assertFalse(gate.resize_tool_pointer_ready(ui, 7, [97, 238]))
            state[key] = previous
        self.assertFalse(gate.resize_tool_pointer_ready(ui, 7, [1024, 238]))

    def test_resize_source_witness_requires_distinct_source_pixels(self):
        self.assertEqual(gate.resize_pixel_state(b'old', b'new', b'old'), 'source-geometry')
        self.assertEqual(gate.resize_pixel_state(b'new', b'new', b'old'), 'target')
        self.assertEqual(gate.resize_pixel_state(b'blank', b'new', b'old'), 'other')
        self.assertEqual(gate.resize_pixel_state(b'unchanged', b'unchanged', b'unchanged'), 'target')
        self.assertEqual(gate.resize_pixel_state(b'wrong', b'unchanged', b'unchanged'), 'other')

    def test_resize_gate_keeps_pre_compositor_latency_separate_from_asserted_frames(self):
        good = {'samplingComplete': True, 'targetSeen': True, 'immediateNonTargetFrames': 1,
                'postCompositorSourceFrames': 0, 'postCompositorNonTargetFrames': 0}
        gate.require_resize_outcome([good])
        for change in [{'postCompositorSourceFrames': 1, 'postCompositorNonTargetFrames': 1},
                       {'postCompositorNonTargetFrames': 1}, {'targetSeen': False},
                       {'samplingComplete': False}]:
            with self.subTest(change=change), self.assertRaises(AssertionError):
                gate.require_resize_outcome([dict(good, **change)])

    def test_resize_negative_control_does_not_turn_unrelated_or_unrecovered_errors_into_passes(self):
        known = {'samplingComplete': True, 'targetSeen': True,
                 'postCompositorSourceFrames': 1, 'postCompositorNonTargetFrames': 2}
        gate.require_resize_outcome([known], True)
        for rows in [[], [dict(known, samplingComplete=False)], [dict(known, targetSeen=False)],
                     [dict(known, postCompositorSourceFrames=0)],
                     [dict(known, postCompositorSourceFrames=0, postCompositorNonTargetFrames=0)]]:
            with self.subTest(rows=rows), self.assertRaises(AssertionError):
                gate.require_resize_outcome(rows, True)

    def test_resize_regions_crop_real_rgb_and_ignore_only_unused_fourth_byte(self):
        raw = b''.join(bytes([i, i + 10, i + 20, 200]) for i in range(12))
        self.assertEqual(gate.region_bytes(raw, [10, 20, 14, 23], [11, 21, 13, 23]),
                         b''.join(bytes([i, i + 10, i + 20, 0]) for i in [5, 6, 9, 10]))
        with self.assertRaises(AssertionError):
            gate.region_bytes(raw, [10, 20, 14, 23], [9, 21, 13, 23])

    def test_resize_only_cli_requires_archive_and_source_identities_without_updater(self):
        args = SimpleNamespace(resize_only=True, source_commit='1' * 40,
                               gate_commit='2' * 40, starter_sha256='a' * 64)
        gate.validate_identities(args)
        args.starter_sha256 = gate.BASELINE_SHA
        with self.assertRaises(AssertionError):
            gate.validate_identities(args)

    def test_resize_destinations_cannot_replace_immutable_input(self):
        root = Path.cwd()
        args = SimpleNamespace(app_root=root / 'app', starter_archive=root / 'input.zip',
                               report=root / 'evidence' / 'resize.json')
        gate.validate_resize_destinations(args)
        for report in [root / 'app' / 'resize.json', root / 'input.zip']:
            args.report = report
            with self.assertRaises(AssertionError):
                gate.validate_resize_destinations(args)

    def test_candidate_inventory_growth_requires_matching_verified_transaction_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {'schema_version': 2, 'ownership': 'core', 'pack_management': 'independent',
                        'interface': 'native-win32', 'requires_browser': False,
                        'transport': 'anonymous-pipes', 'manifest_includes_itself': False,
                        'version': gate.TARGET_VERSION, 'files': []}

            def add_file(name):
                data = ('fixture ' + name).encode()
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                manifest['files'].append({'path': name, 'bytes': len(data),
                                          'sha256': hashlib.sha256(data).hexdigest()})

            for name in ['NativeWorkbench.exe', 'WorkbenchBridge.exe', 'workspace/desktop_host.py'] + [
                    'workspace/fixture_%d.py' % i for i in range(84)]:
                add_file(name)
            self.assertEqual(gate.verify_candidate_core(root, manifest), 87)
            for name in ['workspace/sample_table_editor.py', 'examples/starter/samples.csv',
                         'examples/starter/samples-README.txt']:
                add_file(name)
            expected = gate.verify_candidate_core(root, manifest)
            self.assertEqual(expected, 90)
            transaction = {'status': 'installed', 'version': gate.TARGET_VERSION,
                           'files_verified': expected, 'packs_changed': False}
            gate.verify_core_transaction(transaction, expected)
            for change in [{'files_verified': 87}, {'files_verified': 89}, {'files_verified': 91},
                           {'files_verified': '90'}, {'status': 'already-installed'},
                           {'version': '0.16.0'}, {'packs_changed': True}]:
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    gate.verify_core_transaction(dict(transaction, **change), expected)
            (root / 'workspace/sample_table_editor.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Frozen input differs'):
                gate.verify_candidate_core(root, manifest)

    def test_rejects_missing_or_unpinned_candidate_identities(self):
        good = dict(source_commit='1' * 40, gate_commit='2' * 40,
                    starter_sha256='a' * 64, update_sha256='b' * 64)
        gate.validate_identities(SimpleNamespace(**good))
        for key, bad in [('source_commit', 'HEAD'), ('gate_commit', '2' * 39),
                         ('starter_sha256', gate.BASELINE_SHA), ('update_sha256', 'unknown')]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                gate.validate_identities(SimpleNamespace(**dict(good, **{key: bad})))

    def test_clipped_old_window_fails_even_when_its_controls_fit_its_own_bounds(self):
        self.assertFalse(gate.inside([0, 0, 1040, 728], [0, 0, 1024, 728]))
        self.assertTrue(gate.inside([0, 0, 1024, 728], [0, 0, 1024, 728]))
        self.assertFalse(gate.inside([0, 0, 960, 769], [0, 0, 1024, 728]))
        self.assertTrue(gate.inside([-960, 0, 0, 680], [-1024, 0, 0, 728]))

    def test_overlapping_fixed_buttons_are_not_accepted_as_touching_edges(self):
        self.assertFalse(gate.overlaps([0, 0, 100, 30], [100, 0, 200, 30]))
        self.assertTrue(gate.overlaps([0, 0, 101, 30], [100, 0, 200, 30]))

    def test_initial_window_measurement_does_not_reposition_the_app(self):
        ui = gate.PatchUI.__new__(gate.PatchUI)
        ui.main = 7
        ui.bounds = lambda handle: [40, 20, 1000, 700]
        ui.work_area = lambda: [0, 0, 1024, 728]
        with patch.object(gate.NativeUI, 'fit_window') as fit:
            ui.fit_window(960, 680)
            fit.assert_not_called()
            self.assertEqual(ui.initial_bounds, [40, 20, 1000, 700])
            ui.fit_window(1024, 728)
            fit.assert_called_once_with(1024, 728)

    def test_real_pointer_click_keeps_hit_target_guard(self):
        calls = []
        ui = SimpleNamespace(bounds=lambda handle: [20, 30, 120, 70],
                             click_at=lambda x, y, **kw: calls.append((x, y, kw)))
        gate.pointer_click(ui, 5)
        self.assertEqual(calls, [(70, 50, {'expected': 5})])

    def test_cli_rejects_bad_identity_before_creating_report_or_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = ['gate.py']
            for name in ('app-root', 'baseline-archive', 'update-root', 'starter-archive',
                         'update-archive', 'work', 'report'):
                args += ['--' + name, str(root / name)]
            args += ['--source-commit', 'HEAD', '--gate-commit', '1' * 40,
                     '--starter-sha256', 'a' * 64, '--update-sha256', 'b' * 64]
            with patch('sys.argv', args), patch.object(gate, 'run') as run:
                with self.assertRaises(AssertionError):
                    gate.main()
                run.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_failed_scope_cannot_become_success_when_observations_finish(self):
        report = {'nativeGUIObservationsCompleted': True,
                  'scenarios': [{'status': 'pass'}, {'status': 'failed'}]}
        gate.finalize_report(report)
        self.assertEqual((report['passed'], report['failed']), (1, 1))
        self.assertFalse(report['success'])
        self.assertFalse(report['nativeGUIValidated'])


if __name__ == '__main__':
    unittest.main()
