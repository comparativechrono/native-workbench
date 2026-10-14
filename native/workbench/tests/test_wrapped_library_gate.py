"""Portable failures/oracles for the exact native wrapped-library gate."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location('wrapped_library_gate',
    Path(__file__).resolve().parents[1] / 'scripts/check_wrapped_library_windows.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def image(width=30, height=8):
    result = bytearray(b'\xff\xff\xff\0' * width * height)
    for y in range(2, 6):
        for x in range(3, 27, 3):
            start = (y * width + x) * 4
            result[start:start + 4] = bytes([62, 44, 32, 0])
    return result


def bold(raw, width=30):
    result = bytearray(raw)
    for start in range(0, len(raw) - 4, 4):
        if min(raw[start:start + 3]) < 225 and (start // 4) % width < width - 1:
            result[start + 4:start + 8] = raw[start:start + 4]
    return result


class WrappedLibraryGateTests(unittest.TestCase):
    def test_font_oracle_rejects_regular_title_and_bold_description(self):
        regular = image(height=10)
        strong = bold(regular)
        gate.require_glyph_style(strong, strong, regular)
        gate.require_glyph_style(regular, regular, strong)
        with self.assertRaisesRegex(AssertionError, 'clipped, missing, misplaced'):
            gate.require_glyph_style(regular, strong, regular)
        with self.assertRaisesRegex(AssertionError, 'clipped, missing, misplaced'):
            gate.require_glyph_style(strong, regular, strong)

    def test_clipped_or_blank_text_cannot_hide_in_white_margin(self):
        expected = bold(image(height=10))
        blank = b'\xff\xff\xff\0' * (len(expected) // 4)
        with self.assertRaises(AssertionError):
            gate.require_glyph_style(blank, expected, image(height=10))
        clipped = bytearray(expected)
        clipped[30 * 4 * 4:] = blank[30 * 4 * 4:]
        with self.assertRaises(AssertionError):
            gate.require_glyph_style(clipped, expected, image(height=10))

    def test_unused_alpha_does_not_change_visible_glyph_comparison(self):
        actual, expected = bold(image(height=10)), bold(image(height=10))
        actual[3::4] = bytes([255]) * (len(actual) // 4)
        self.assertEqual(gate.glyph_error(actual, expected)['fraction'], 0)

    def test_style_requires_distinguishable_wrong_weight_control(self):
        expected = bold(image(height=10))
        with self.assertRaisesRegex(AssertionError, 'distinguish'):
            gate.require_glyph_style(expected, expected, expected)

    def test_invalid_capture_lengths_and_crops_fail_closed(self):
        with self.assertRaises(AssertionError):
            gate.glyph_error(bytes(9), bytes(9))
        with self.assertRaises(AssertionError):
            gate.crop(bytes(16), 2, 2, [-1, 0, 2, 2])
        with self.assertRaises(AssertionError):
            gate.intersect([0, 0, 2, 2], [3, 3, 4, 4])

    def test_word_wrap_preserves_words_and_splits_oversized_tokens(self):
        self.assertEqual(gate.wrap_text('one two three', 7, len), ['one two', 'three'])
        self.assertEqual(gate.wrap_text('abcdefghi end', 4, len), ['abcd', 'efgh', 'i', 'end'])
        self.assertEqual(gate.wrap_text('a\u0001', 4, len), ['a\u0001'])
        self.assertEqual(gate.wrap_text('😀😀😀', 2, len), ['😀😀', '😀'])
        with self.assertRaises(AssertionError):
            gate.wrap_text('W', 1, lambda text: len(text) * 2)

    def test_fixture_exercises_maximum_valid_description(self):
        self.assertEqual(len(gate.LONG_DESCRIPTION), 2048)
        self.assertTrue(gate.LONG_DESCRIPTION.endswith('FINAL LONG DESCRIPTION ANSWER'))
        self.assertLessEqual(len(gate.TOKEN_NAME), 100)
        self.assertGreater(len(gate.TOKEN_DESCRIPTION.split()[0]), 100)

    def test_failed_or_unfinished_gate_never_passes(self):
        report = {'nativeGUIObservationsCompleted': True,
                  'scenarios': [{'status': 'pass'}, {'status': 'failed'}]}
        gate.finalize_report(report)
        self.assertFalse(report['success'])
        report = {'nativeGUIObservationsCompleted': False, 'scenarios': [{'status': 'pass'}]}
        gate.finalize_report(report)
        self.assertFalse(report['success'])

    def test_partial_boundary_lines_do_not_count_as_complete_text(self):
        self.assertEqual(gate.complete_line_range(10, 5, 20, 10, 110), (0, 5))
        self.assertEqual(gate.complete_line_range(10, 5, 20, 11, 109), (1, 4))
        self.assertEqual(gate.complete_line_range(-80, 8, 20, 0, 70), (4, 7))
        self.assertEqual(gate.complete_line_range(90, 2, 20, 0, 80), (0, 0))
        with self.assertRaises(AssertionError):
            gate.complete_line_range(0, 2, 0, 0, 80)

    def test_coverage_requires_every_line_not_just_top_and_bottom(self):
        def row(title, description):
            return {'titleLines': ['title'], 'descriptionLines': ['a', 'b', 'c', 'd'],
                'blocks': [{'label': 'title', 'completeLineIndices': title},
                           {'label': 'description', 'completeLineIndices': description}]}
        observations = [row([0], [0]), row([], [3])]
        with self.assertRaisesRegex(AssertionError, 'never visibly validated'):
            gate.line_coverage(observations, require_complete=True)
        observations.append(row([], [1, 2]))
        result = gate.line_coverage(observations, require_complete=True)
        self.assertEqual(result['covered'], {'title': [0], 'description': [0, 1, 2, 3]})
        observations[-1]['descriptionLines'].append('unexpected reflow')
        with self.assertRaisesRegex(AssertionError, 'Wrapping changed'):
            gate.line_coverage(observations, require_complete=True)

    def test_visible_pane_intersects_oversized_child_with_actual_parent(self):
        tree = gate.NativeTree.__new__(gate.NativeTree)
        tree.hwnd = 4
        def client(hwnd, pointer):
            pointer._obj.right = 180
            pointer._obj.bottom = 900 if hwnd == 4 else 400
            return True
        def screen(hwnd, pointer):
            pointer._obj.x = 100
            pointer._obj.y = -200 if hwnd == 4 else 50
            return True
        tree.user = SimpleNamespace(GetClientRect=client, ClientToScreen=screen,
            GetParent=lambda hwnd: 9, GetDlgCtrlID=lambda hwnd: 430)
        self.assertEqual(tree.viewport(), 9)
        self.assertEqual(tree.client_bounds(), [100, -200, 280, 700])
        self.assertEqual(tree.visible_bounds(), [100, 50, 280, 450])
        tree.rect = lambda item: [120, -180, 800, 600]
        tree.send = lambda *args: 1
        self.assertEqual(tree.point(1), (160, 250))
        # A native coarse scrollbar can live beyond the clipping parent. Its
        # absence may widen the child's client, never the visible text column.
        def wider_client(hwnd, pointer):
            client(hwnd, pointer)
            pointer._obj.right = 197 if hwnd == 4 else 180
            return True
        tree.user.GetClientRect = wider_client
        self.assertEqual(tree.client_bounds(), [100, -200, 297, 700])
        self.assertEqual(tree.visible_bounds(), [100, 50, 280, 450])
        self.assertEqual(tree.point(1), (160, 250))

    def test_first_visible_uses_real_clipped_rows_without_scroll_repair(self):
        tree = gate.NativeTree.__new__(gate.NativeTree)
        tree.visible_bounds = lambda: [100, 50, 280, 450]
        rows = {10: [120, -120, 270, -20], 11: [120, -20, 270, 50],
                12: [120, 50, 270, 300], 13: [120, 300, 270, 600]}
        calls = []
        def next_item(item=0, relation=0):
            calls.append((item, relation))
            self.assertIn(relation, (5, 6))
            return 10 if relation == 5 else item + 1 if item < 13 else 0
        tree.next = next_item
        tree.rect = lambda item: rows[item]
        self.assertEqual(tree.first_visible(), 12)
        self.assertEqual(calls, [(0, 5), (10, 6), (11, 6)])
        tree.visible_bounds = lambda: [100, 299, 280, 450]
        self.assertEqual(tree.first_visible(), 12)  # A genuinely visible one-pixel strip counts.

    def test_tall_native_row_click_is_clipped_to_actual_visible_client(self):
        tree = gate.NativeTree.__new__(gate.NativeTree)
        tree.hwnd = 4
        tree.send = lambda *args: 1
        tree.rect = lambda item: [120, -200, 900, 900]
        def client(hwnd, pointer):
            pointer._obj.right, pointer._obj.bottom = 180, 400
            return True
        def screen(hwnd, pointer):
            pointer._obj.x, pointer._obj.y = 100, 50
            return True
        tree.user = SimpleNamespace(GetClientRect=client, ClientToScreen=screen, GetParent=lambda hwnd: 0)
        self.assertEqual(tree.point(1), (160, 250))
        tree.rect = lambda item: [120, 500, 900, 900]
        with self.assertRaisesRegex(AssertionError, 'no usable visible'):
            tree.point(1)


if __name__ == '__main__':
    unittest.main()
