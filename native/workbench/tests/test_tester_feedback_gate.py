"""Portable tests for temporal failure oracles; no Windows acceptance claim."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('tester_feedback_gate',
    Path(__file__).resolve().parents[1] / 'scripts/check_tester_feedback_windows.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def pixels(width=40, height=32, color=(255, 255, 255, 0)):
    return bytearray(bytes(color) * width * height)


def paint(raw, x, y, width, height, color, stride=40):
    for yy in range(y, y + height):
        for xx in range(x, x + width):
            offset = (yy * stride + xx) * 4
            raw[offset:offset + 4] = bytes(color)


class FeedbackGateTests(unittest.TestCase):
    def fake_ui(self, title='Remove sample row'):
        ui = gate.FeedbackUI.__new__(gate.FeedbackUI)
        ui.process = SimpleNamespace(poll=lambda: None)
        ui.progress = lambda *args, **kwargs: None
        ui.windows = lambda: [4]
        ui.label = lambda handle, klass=False: '#32770' if klass else title
        ui.controls = lambda owner: []
        ui.top_windows = lambda: [{'handle': 4, 'title': title, 'class': '#32770'}]
        return ui

    def test_destroyed_caption_is_not_requeried_as_an_unexpected_dialog(self):
        ui = gate.FeedbackUI.__new__(gate.FeedbackUI)
        alive = [True]
        ui.windows = lambda: [4]
        def caption(handle, text, size):
            text.value = 'Remove sample row'
            alive[0] = False  # Destruction raced the caption snapshot.
        ui.user = SimpleNamespace(IsWindow=lambda handle: alive[0], IsWindowVisible=lambda handle: True,
            GetClassNameW=lambda handle, text, size: setattr(text, 'value', '#32770'),
            GetWindowTextW=caption)
        ui.label = lambda *args: self.fail('Top-level captions must not send WM_GETTEXT')
        self.assertEqual(ui.top_windows(), [])

    def test_live_visible_common_caption_is_preserved_in_snapshot(self):
        ui = gate.FeedbackUI.__new__(gate.FeedbackUI)
        ui.windows = lambda: [4]
        ui.user = SimpleNamespace(IsWindow=lambda handle: True, IsWindowVisible=lambda handle: True,
            GetClassNameW=lambda handle, text, size: setattr(text, 'value', '#32770'),
            GetWindowTextW=lambda handle, text, size: setattr(text, 'value', 'Real error'))
        self.assertEqual(ui.top_windows(), [{'handle': 4, 'class': '#32770', 'title': 'Real error'}])

    def test_expected_native_confirmation_is_allowed_only_in_its_context(self):
        ui = self.fake_ui()
        with ui.common_dialog('Remove sample row'):
            ui.wait('expected confirmation', lambda: True)
        with self.assertRaisesRegex(AssertionError, 'Unexpected native dialog'):
            ui.wait('unplanned confirmation', lambda: True)

    def test_allowing_delete_does_not_allow_another_native_error(self):
        ui = self.fake_ui('Unexpected application failure')
        with ui.common_dialog('Remove sample row'):
            with self.assertRaisesRegex(AssertionError, 'Unexpected application failure'):
                ui.wait('expected confirmation', lambda: True)

    def test_failed_dialog_scope_does_not_leave_future_dialogs_permitted(self):
        ui = self.fake_ui()
        with self.assertRaises(ValueError):
            with ui.common_dialog('Remove sample row'):
                raise ValueError('failed interaction')
        self.assertEqual(ui.expected_dialog_titles, frozenset())

    def test_primary_assertion_is_retained_if_cleanup_also_fails(self):
        ui = SimpleNamespace(windows=lambda: [], process=object(),
                             close=lambda: (_ for _ in ()).throw(RuntimeError('cleanup failed')))
        report = {}
        with patch.object(gate, 'stop_process_tree') as stop:
            with self.assertRaisesRegex(AssertionError, 'original failure'):
                with gate.observed_desktop(ui, report, 'scenario'):
                    raise AssertionError('original failure')
            stop.assert_called_once_with(ui.process)
        self.assertEqual(report['primaryFailures'][0]['error'], 'original failure')
        self.assertEqual(report['cleanupErrors'], ['cleanup failed'])

    def test_reported_black_rectangle_is_rejected_by_pixel_oracle(self):
        raw = pixels()
        paint(raw, 8, 8, 24, 16, (0, 0, 0, 99))
        self.assertIn([8, 8, 24, 24], gate.black_blocks(raw, 40, 32))

    def test_text_caret_and_blue_native_selection_are_not_black_blocks(self):
        raw = pixels()
        paint(raw, 0, 0, 40, 18, (180, 70, 10, 0))  # BGR selection, not near black.
        paint(raw, 1, 1, 2, 24, (0, 0, 0, 0))       # Caret or thin letter stem.
        for x in range(8, 35, 5):
            paint(raw, x, 20, 2, 8, (0, 0, 0, 0))
        self.assertEqual(gate.black_blocks(raw, 40, 32), [])

    def test_unused_alpha_is_ignored_but_real_rgb_changes_remain(self):
        first, second = bytes([20, 30, 40, 0]), bytes([20, 30, 40, 255])
        self.assertEqual(gate.normalized(first), gate.normalized(second))
        self.assertNotEqual(gate.normalized(first), gate.normalized(bytes([20, 30, 41, 0])))

    def test_truncated_frame_cannot_pass_as_empty_black_detection(self):
        with self.assertRaises(AssertionError):
            gate.black_blocks(bytes(100), 40, 32)

    def test_gate_rejects_unpinned_identity_and_evidence_inside_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(source_commit='1' * 40, gate_commit='2' * 40,
                starter_sha256='a' * 64, app_root=root / 'app', report=root / 'evidence/result.json',
                starter_archive=root / 'starter.zip')
            gate.validate_identities(args)
            args.gate_commit = 'HEAD'
            with self.assertRaises(AssertionError):
                gate.validate_identities(args)
            args.gate_commit = '2' * 40
            args.report = root / 'app/evidence.json'
            with self.assertRaises(AssertionError):
                gate.validate_identities(args)

    def test_main_window_is_not_mistaken_for_same_title_error_dialog(self):
        ui = SimpleNamespace(main=1, top_windows=lambda: [
            {'handle': handle, 'title': 'Native Workbench', 'class': '#32770'} for handle in [1, 2]])
        self.assertEqual(gate.window(ui, 'Native Workbench'), 2)

    def test_failed_temporal_scope_cannot_become_success(self):
        report = {'nativeGUIObservationsCompleted': True,
                  'scenarios': [{'status': 'pass'}, {'status': 'failed'}]}
        gate.finalize_report(report)
        self.assertFalse(report['success'])
        self.assertEqual(report['failed'], 1)

    def test_pointer_readiness_never_accepts_an_overlay_from_another_process(self):
        def pid(handle, target):
            target._obj.value = 99
        ui = SimpleNamespace(bounds=lambda h: [10, 10, 90, 40], work_area=lambda: [0, 0, 100, 100],
            process=SimpleNamespace(pid=42), user=SimpleNamespace(WindowFromPoint=lambda p: 7,
                GetWindowThreadProcessId=pid, IsWindowVisible=lambda h: True, IsWindowEnabled=lambda h: True,
                IsChild=lambda parent, child: True))
        state = gate.pointer_state(ui, 7)
        self.assertFalse(state['ready'])
        self.assertFalse(state['owned'])

    def test_pointer_readiness_requires_the_enabled_expected_surface(self):
        def pid(handle, target):
            target._obj.value = 42
        ui = SimpleNamespace(bounds=lambda h: [10, 10, 90, 40], work_area=lambda: [0, 0, 100, 100],
            process=SimpleNamespace(pid=42), user=SimpleNamespace(WindowFromPoint=lambda p: 7,
                GetWindowThreadProcessId=pid, IsWindowVisible=lambda h: True, IsWindowEnabled=lambda h: True,
                IsChild=lambda parent, child: False))
        self.assertTrue(gate.pointer_state(ui, 7)['ready'])
        ui.user.IsWindowEnabled = lambda h: False
        self.assertFalse(gate.pointer_state(ui, 7)['ready'])

    def caption_ui(self):
        foreground, clicks = [99], []
        def pid(handle, pointer):
            pointer._obj.value = 42 if handle == 7 else 99
        def mouse(x, y, flags=0):
            clicks.append((x, y, flags))
            if flags == 4:
                foreground[0] = 7
        def wait(phase, predicate, **kwargs):
            self.assertTrue(predicate(), phase)
        ui = SimpleNamespace(main=7, process=SimpleNamespace(pid=42),
            work_area=lambda: [0, 0, 1000, 800], mouse=mouse, wait=wait,
            top_windows=lambda: [{'handle': 7}], send=lambda *args: 2,
            user=SimpleNamespace(WindowFromPoint=lambda point: 7,
                GetWindowThreadProcessId=pid, GetForegroundWindow=lambda: foreground[0],
                IsWindowVisible=lambda handle: True, IsWindowEnabled=lambda handle: True))
        return ui, foreground, clicks

    def test_caption_activation_rejects_foreign_overlay_and_caption_buttons(self):
        ui, _, _ = self.caption_ui()
        self.assertTrue(gate.caption_pointer_state(ui, [250, 15])['ready'])
        ui.user.WindowFromPoint = lambda point: 99
        ui.send = lambda *args: self.fail('Do not hit-test behind a foreign overlay.')
        self.assertFalse(gate.caption_pointer_state(ui, [250, 15])['ready'])
        ui.user.WindowFromPoint = lambda point: 7
        ui.send = lambda *args: 20  # HTCLOSE is not a safe activation point.
        self.assertFalse(gate.caption_pointer_state(ui, [250, 15])['ready'])
        ui.send = lambda *args: 2
        ui.user.IsWindowEnabled = lambda handle: False
        self.assertFalse(gate.caption_pointer_state(ui, [250, 15])['ready'])

    def test_modal_activation_uses_real_caption_input_and_records_ownership(self):
        ui, foreground, clicks = self.caption_ui()
        report = {}
        with patch.object(gate, 'main_caption_rectangle', return_value=[0, 0, 1000, 30]), \
                patch.object(gate, 'visible_capture'), patch.object(gate.time, 'sleep'):
            gate.activate_main_after_modal(ui, report, 'Samples closed')
            self.assertEqual(clicks, [(250, 15, 0), (250, 15, 2), (250, 15, 4)])
            row = report['modalActivationSetup'][0]
            self.assertEqual((row['foregroundBefore'], row['foregroundAfter']), (99, 7))
            self.assertTrue(row['confirmation']['ready'])
            self.assertTrue(row['clicked'])
            gate.activate_main_after_modal(ui, report, 'already foreground')
            self.assertFalse(report['modalActivationSetup'][1]['clicked'])
            self.assertEqual(len(clicks), 3)

    def test_modal_activation_fails_without_exposed_caption_or_with_owned_dialog(self):
        ui, _, clicks = self.caption_ui()
        ui.user.WindowFromPoint = lambda point: 99
        with patch.object(gate, 'main_caption_rectangle', return_value=[0, 0, 1000, 30]), \
                patch.object(gate, 'visible_capture'), patch.object(gate.time, 'sleep'):
            with self.assertRaisesRegex(AssertionError, 'No exposed owned main caption'):
                gate.activate_main_after_modal(ui, {}, 'Samples closed')
            ui.top_windows = lambda: [{'handle': 7}, {'handle': 12}]
            with self.assertRaisesRegex(AssertionError, 'Another owned window'):
                gate.activate_main_after_modal(ui, {}, 'Samples closed')
        self.assertEqual(clicks, [])


if __name__ == '__main__':
    unittest.main()
