#!/usr/bin/env python3
"""Validate wrapped library text on the exact installed native Windows desktop.

The synthetic, offline fixture is imported through the ordinary pack importer.
Displayed BitBlt pixels are compared with independently rasterized Win32 text;
no application drawing hook, injected notification or PrintWindow is used.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import sys
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_deployment_ui_windows import (Keyboard, failed, finalize_report, passed,
    tree_hashes, utc, verify_extracted)
from check_references_windows import PrivateHost, require, sha256, write_json
from check_tester_feedback_windows import (observed_desktop, prepare_desktop,
    validate_identities, visible_capture)
from native_tree import NativeTree

CATEGORY = 'Wrapped library validation category with a deliberately complete heading'
NAME = 'SAMtools wrapped library demonstration with a complete multi-line tool name'
DESCRIPTION = ('Measure this synthetic training fixture without shortening its explanation. '
               'Every word must stay visible in the tool library, including FINAL DESCRIPTION ANSWER.')
LONG_NAME = 'SAMtools extended description reachability demonstration'
LONG_DESCRIPTION = ('Synthetic complete description words remain readable while scrolling. ' * 32)[:2048 - len(' FINAL LONG DESCRIPTION ANSWER')] + ' FINAL LONG DESCRIPTION ANSWER'
TOKEN_NAME = 'SAMtools ' + 'LongUnbrokenName' * 5
TOKEN_DESCRIPTION = 'BoundaryToken' * 19 + ' END TOKEN ANSWER'

LIMITS = [
    'Observed hosted Windows DPI and two restored viewport sizes only; representative PCs/high DPI/multiple monitors/physical trackpads remain separate.',
    'Pixel comparisons cover the identified fixture and real SAMtools guidance, with actual screenshots retained for independent visual review.',
    'Synthetic local pack wraps unchanged Starter SAMtools; this is UI validation, not a scientific or performance claim.',
    'Hover observation is finite; style inspection also requires native tooltip suppression.',
]


def fixture_pack(root, evidence):
    binary = next((root / 'packs/bam-0.4.0').rglob('samtools.exe'))
    rows = [('wrapped', NAME, DESCRIPTION), ('extended', LONG_NAME, LONG_DESCRIPTION),
            ('token', TOKEN_NAME, TOKEN_DESCRIPTION)]
    schema = json.dumps({'schema': 1, 'category': CATEGORY, 'workflows': {
        identity: {'ports': [], 'outputs': [{'id': 'version', 'type': 'metrics',
            'manifestOutputs': ['version']}], 'methods': 'Synthetic wrapped-library UI fixture.'}
        for identity, _, _ in rows}}).encode()
    manifest = ('[pack]\nformat=2\nid=wrapped-library-gate\nversion=1.0.0\n'
                'name=Wrapped library validation\nplatform=windows-x86_64\n'
                '[tool:samtools]\npath=bin/samtools.exe\nversion=fixture\nsha256=' + sha256(binary) + '\n'
                '[asset:workbench-schema]\npath=workbench-schema.json\nsha256=' + hashlib.sha256(schema).hexdigest() + '\n')
    for identity, name, description in rows:
        manifest += (f'[workflow:{identity}]\nname={name}\ndescription={description}\ninputs=\noutputs=version\nsteps=run\n'
                     f'[output:{identity}:version]\nlabel=Version\npath=version.txt\n'
                     f'[step:{identity}:run]\nlabel=Version\nkind=exec\ntool=samtools\narg.0=--version\nstdout=version\n')
    files = {'pack.ini': manifest.encode(), 'workbench-schema.json': schema,
             'bin/samtools.exe': binary.read_bytes(),
             'licenses/TEST-FIXTURE.txt': b'Test-only wrapper of unchanged Starter SAMtools, not distributed.\n'}
    envelope = {'schema': 1, 'id': 'wrapped-library-gate', 'version': '1.0.0',
        'packApi': 1, 'minAppVersion': '0.11.0', 'platform': 'windows-x86_64',
        'manifestSha256': hashlib.sha256(files['pack.ini']).hexdigest(),
        'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in files.items()]}
    path = evidence / 'wrapped-library-fixture.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr('workbench-pack.json', json.dumps(envelope))
        for name, data in files.items():
            zipped.writestr('pack/' + name, data)
    return path, rows


def import_fixture(root, evidence, report):
    before = tree_hashes(root / 'packs')
    archive, rows = fixture_pack(root, evidence)
    host = PrivateHost(root, evidence, 'wrapped-library-import', offline=True)
    try:
        host.call('init')
        host.call('packs/import', {'path': str(archive)})
        deadline = time.monotonic() + 60
        while True:
            state = host.call('packs/status')['operation']
            if not state.get('active'):
                require(state.get('success') and state.get('status') == 'completed', 'Offline fixture import failed.')
                break
            require(time.monotonic() < deadline, 'Offline fixture import timed out.')
            time.sleep(.1)
    finally:
        host.close()
    after = tree_hashes(root / 'packs')
    require(all(after.get(name) == digest for name, digest in before.items()), 'Fixture import changed existing pack bytes.')
    report['fixture'] = {'archive': archive.name, 'sha256': sha256(archive), 'category': CATEGORY,
                        'operations': [{'id': identity, 'name': name, 'description': description}
                                       for identity, name, description in rows],
                        'originalPackFilesUnchanged': len(before)}


def intersect(first, second):
    result = [max(first[0], second[0]), max(first[1], second[1]),
              min(first[2], second[2]), min(first[3], second[3])]
    require(result[0] < result[2] and result[1] < result[3], 'Text has no visible intersection.')
    return result


def crop(raw, width, height, box):
    left, top, right, bottom = box
    require(len(raw) == width * height * 4 and 0 <= left < right <= width and
            0 <= top < bottom <= height, 'Invalid pixel crop.')
    return b''.join(raw[(y * width + left) * 4:(y * width + right) * 4] for y in range(top, bottom))


def glyph_error(actual, expected):
    """Measure displayed text, ignoring BI_RGB alpha and near-white background.

    Exact drawing may differ by a few anti-aliasing levels. A pixel is wrong
    when any RGB channel differs by more than 24; denominator is the union of
    actual/reference ink so a huge blank margin cannot hide missing text.
    """
    require(len(actual) == len(expected) and len(actual) % 4 == 0, 'Invalid glyph image sizes.')
    ink = wrong = 0
    for start in range(0, len(actual), 4):
        a, b = actual[start:start + 3], expected[start:start + 3]
        if min(a) < 225 or min(b) < 225:
            ink += 1
            wrong += any(abs(x - y) > 24 for x, y in zip(a, b))
    require(ink >= 30, 'Too little visible text to validate its style.')
    return {'inkPixels': ink, 'differentPixels': wrong, 'fraction': wrong / ink}


def require_glyph_style(actual, expected, wrong_weight):
    correct, alternate = glyph_error(actual, expected), glyph_error(actual, wrong_weight)
    require(correct['fraction'] <= .04, 'Displayed text is clipped, missing, misplaced or drawn differently: ' + str(correct))
    require(alternate['fraction'] >= correct['fraction'] + .08,
            'Visible text does not distinguish required font weight from the incorrect alternative.')
    return {'requiredWeight': correct, 'wrongWeightControl': alternate}


def wrap_text(text, width, measure):
    """Independent word-fit oracle, splitting long tokens without dropping text."""
    lines, line = [], ''
    for word in text.split():
        if line and measure(line + ' ' + word) <= width:
            line += ' ' + word
            continue
        if line:
            lines.append(line)
            line = ''
        while word and measure(word) > width:
            length = 1
            while length < len(word) and measure(word[:length + 1]) <= width:
                length += 1
            require(measure(word[:length]) <= width, 'One glyph cannot fit the visible text column.')
            lines.append(word[:length])
            word = word[length:]
        line = word
    if line:
        lines.append(line)
    return lines


class Rows(NativeTree):
    def rect(self, item, text=True):
        size = ctypes.sizeof(wintypes.RECT)
        payload = int(item).to_bytes(ctypes.sizeof(ctypes.c_void_p), 'little').ljust(size, b'\0')
        raw = self._buffer(payload, size, lambda address: self.send(self.hwnd, 0x1104, int(text), address))
        value, origin = wintypes.RECT.from_buffer_copy(raw), wintypes.POINT()
        require(self.user.ClientToScreen(self.hwnd, ctypes.byref(origin)), 'Cannot locate native row.')
        return [value.left + origin.x, value.top + origin.y, value.right + origin.x, value.bottom + origin.y]


def client_box(ui, hwnd):
    rect, origin = wintypes.RECT(), wintypes.POINT()
    require(ui.user.GetClientRect(hwnd, ctypes.byref(rect)) and
            ui.user.ClientToScreen(hwnd, ctypes.byref(origin)), 'Cannot locate native library client area.')
    return [origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom]


class TextReference:
    """Rasterize the expected font contract at the actual observed window DPI.

    HFONT handles returned by another process's WM_GETFONT are process-private
    GDI objects. Create independent expected fonts here; the displayed-pixel
    comparison, including wrong-weight controls, establishes their actual use.
    """
    def __init__(self, ui, hwnd):
        self.ui, self.fonts = ui, {}
        self.screen = self.dc = self.old_font = 0
        u, g = ui.user, ui.gdi
        class LogFont(ctypes.Structure):
            _fields_ = [(name, wintypes.LONG) for name in ('height', 'width', 'escapement', 'orientation', 'weight')] + [
                (name, ctypes.c_ubyte) for name in ('italic', 'underline', 'strike', 'charset', 'outprecision',
                                                   'clipprecision', 'quality', 'pitch')] + [('face', wintypes.WCHAR * 32)]
        class Metrics(ctypes.Structure):
            _fields_ = [(name, wintypes.LONG) for name in ('height', 'ascent', 'descent', 'internal', 'external',
                'average', 'maximum', 'weight', 'overhang', 'aspectx', 'aspecty')] + [
                (name, wintypes.WCHAR) for name in ('first', 'last', 'default', 'breakchar')] + [
                (name, ctypes.c_ubyte) for name in ('italic', 'underline', 'strike', 'pitch', 'charset')]
        g.CreateFontIndirectW.argtypes, g.CreateFontIndirectW.restype = [ctypes.POINTER(LogFont)], wintypes.HFONT
        g.GetTextMetricsW.argtypes = [wintypes.HDC, ctypes.POINTER(Metrics)]
        g.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.SIZE)]
        g.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
        g.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        g.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        try:
            self.screen = u.GetDC(None)
            require(self.screen, 'Cannot acquire a display DC for the independent font reference.')
            self.dc = g.CreateCompatibleDC(self.screen)
            require(self.dc, 'Cannot create the independent reference DC.')
            dpi = u.GetDpiForWindow(hwnd)
            require(dpi > 0, 'Cannot read the actual native library DPI.')
            font = LogFont(height=-((14 * dpi + 48) // 96), charset=1, quality=5, face='Segoe UI')
            self.identity = {'face': font.face, 'height': font.height, 'quality': font.quality,
                'charset': font.charset, 'observedDpi': dpi,
                'source': 'Independent expected Segoe UI 14-logical-pixel font contract; not a cross-process GDI handle.'}
            for weight in (400, 700):
                font.weight = weight
                self.fonts[weight] = g.CreateFontIndirectW(ctypes.byref(font))
                require(self.fonts[weight], 'Cannot create independent font reference.')
            self.old_font = g.SelectObject(self.dc, self.fonts[400])
            require(self.old_font, 'Cannot select independent reference font.')
            self.line_heights = {}
            for weight in (400, 700):
                g.SelectObject(self.dc, self.fonts[weight])
                metrics = Metrics()
                require(g.GetTextMetricsW(self.dc, ctypes.byref(metrics)), 'Cannot read reference font line height.')
                self.line_heights[weight] = metrics.height
            self.line_height = self.line_heights[400]
            g.SetBkMode(self.dc, 1)
        except Exception:
            self.close()
            raise

    def measure(self, text, weight):
        self.ui.gdi.SelectObject(self.dc, self.fonts[weight])
        size = wintypes.SIZE()
        require(self.ui.gdi.GetTextExtentPoint32W(self.dc, text, len(text), ctypes.byref(size)), 'Cannot measure reference text.')
        return size.cx

    def lines(self, text, width, weight):
        return wrap_text(text, width, lambda value: self.measure(value, weight))

    def raster(self, lines, width, weight, color, line_height=None):
        line_height = line_height or self.line_heights[weight]
        height = max(1, len(lines)) * line_height
        g = self.ui.gdi
        bitmap = g.CreateCompatibleBitmap(self.screen, width, height)
        previous = g.SelectObject(self.dc, bitmap)
        try:
            require(g.PatBlt(self.dc, 0, 0, width, height, 0x00FF0062), 'Cannot clear reference raster.')  # WHITENESS
            g.SelectObject(self.dc, self.fonts[weight])
            g.SetTextColor(self.dc, color[0] | color[1] << 8 | color[2] << 16)
            for index, line in enumerate(lines):
                require(g.TextOutW(self.dc, 0, index * line_height, line, len(line)), 'Cannot draw reference text.')
            g.SelectObject(self.dc, previous)
            header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
            info, pixels = ctypes.create_string_buffer(header + bytes(1024)), ctypes.create_string_buffer(width * height * 4)
            require(g.GetDIBits(self.dc, bitmap, 0, height, pixels, info, 0) == height, 'Cannot read reference raster.')
            return pixels.raw, height
        finally:
            g.SelectObject(self.dc, previous)
            g.DeleteObject(bitmap)

    def close(self):
        if self.dc and self.old_font:
            self.ui.gdi.SelectObject(self.dc, self.old_font)
        for font in self.fonts.values():
            if font:
                self.ui.gdi.DeleteObject(font)
        if self.dc:
            self.ui.gdi.DeleteDC(self.dc)
        if self.screen:
            self.ui.user.ReleaseDC(None, self.screen)
        self.screen = self.dc = self.old_font = 0
        self.fonts.clear()


def filter_to(ui, tree, query, count=1):
    ui.set_text(ui.child(102), query)
    ui.wait('wrapped library search ' + query[:45], lambda: len(tree.tools()) == count and
            all(query.casefold() in tree.label(item).casefold() for item in tree.tools()) and
            ui.user.IsWindowVisible(tree.hwnd) and ui.user.IsWindowEnabled(tree.hwnd))
    time.sleep(.25)  # Let the ordinary asynchronous search update reach the compositor.


def hover_no_tooltip(ui, tree, item, report, name):
    u = ui.user
    u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
    style = u.GetWindowLongPtrW(tree.hwnd, -16)
    require(style & 0x80, 'Native tree has not disabled tooltip behavior.')  # TVS_NOTOOLTIPS
    rect = intersect(tree.rect(item, False), tree.visible_bounds())
    ui.mouse(rect[0] + min(50, (rect[2] - rect[0]) // 2), (rect[1] + rect[3]) // 2)
    samples, start = [], time.monotonic()
    while time.monotonic() - start < 2:
        tooltip = ui.send(tree.hwnd, 0x1119)  # TVM_GETTOOLTIPS.
        popups = [row for row in ui.top_windows() if row['class'].casefold() == 'tooltips_class32']
        visible = bool(tooltip and u.IsWindowVisible(tooltip))
        samples.append({'elapsedMs': round((time.monotonic() - start) * 1000, 3),
                        'treeTooltipVisible': visible, 'visibleTooltipWindows': len(popups)})
        require(not visible and not popups, 'Hovering the wrapped library displayed a tooltip.')
        time.sleep(.05)
    report.setdefault('hoverObservations', []).append({'name': name, 'style': style, 'samples': samples})
    visible_capture(ui, report, name + '-hover')


def complete_line_range(top, count, height, viewport_top, viewport_bottom):
    """Only wholly visible line boxes count toward complete-text coverage."""
    require(count >= 0 and height > 0 and viewport_top < viewport_bottom, 'Invalid line geometry.')
    first = max(0, min(count, (viewport_top - top + height - 1) // height))
    end = max(first, min(count, (viewport_bottom - top) // height))
    return first, end


def line_coverage(rows, require_complete=False):
    require(rows, 'No displayed text observations were retained.')
    expected = {label: rows[0][label + 'Lines'] for label in ('title', 'description')}
    covered = {label: set() for label in expected}
    for row in rows:
        require(all(row[label + 'Lines'] == lines for label, lines in expected.items()),
                'Wrapping changed during coverage of a fixed-width row.')
        for block in row['blocks']:
            label = block['label']
            indices = set(block['completeLineIndices'])
            require(indices <= set(range(len(expected[label]))), 'Invalid visible line index.')
            covered[label].update(indices)
    missing = {label: sorted(set(range(len(lines))) - covered[label]) for label, lines in expected.items()}
    if require_complete:
        require(not any(missing.values()), 'Some complete title/description lines were never visibly validated: ' + str(missing))
    return {'covered': {label: sorted(indices) for label, indices in covered.items()}, 'missing': missing}


def wheel_line_into_view(ui, tree, item, offset, line_height):
    """Reveal a line using ordinary wheel input, never EnsureVisible or repair."""
    client = tree.visible_bounds()
    for _ in range(100):
        top = tree.rect(item, False)[1] + offset
        if client[1] <= top and top + line_height <= client[3]:
            return
        ui.wheel(client[0] + 30, client[1] + 40, 120 if top < client[1] else -120)
        time.sleep(.05)
    raise AssertionError('Native wheel input could not reveal a complete wrapped text line.')


def check_row(ui, tree, item, reference, title, description, report, name):
    require(tree.selected() != item, 'Raster fixture must be an unselected row; expected colours are not selection colours.')
    # Parking the pointer outside the tree removes hover paint from the glyph oracle.
    search = ui.bounds(ui.child(102))
    ui.mouse(search[0] + 4, search[1] + 4)
    time.sleep(.2)
    client, row = tree.visible_bounds(), tree.rect(item, False)
    scale = ui.user.GetDpiForWindow(ui.main) / 96
    px = lambda n: round(n * scale)
    # Contract: draw within the visible column, even if the native child is
    # wider so its own coarse scrollbar is clipped outside the pixel viewport.
    style = ui.user.GetWindowLongPtrW(tree.hwnd, -16)
    indent = ui.send(tree.hwnd, 0x1106)  # TVM_GETINDENT.
    drawing_client = tree.client_bounds()
    text_left = drawing_client[0] + indent * (2 if tree.next(item, 3) else 1) + px(4)
    ui.user.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    scrollbar = ui.user.GetSystemMetricsForDpi(2, ui.user.GetDpiForWindow(ui.main))
    # A pixel viewport's client already reserves its own scrollbar. The
    # historical direct TreeView reserves space while its scrollbar is hidden.
    reserve = 0 if tree.viewport() != tree.hwnd or style & 0x00200000 else scrollbar
    width = client[2] - text_left - px(6) - reserve
    require(width >= 50, 'Text column is too narrow to validate.')
    title_lines, description_lines = reference.lines(title, width, 700), reference.lines(description, width, 400)
    needed = px(6) + len(title_lines) * reference.line_heights[700] + (px(3) if description else 0) + len(description_lines) * reference.line_heights[400] + px(6)
    require(row[3] - row[1] >= needed, 'Native row is shorter than the complete wrapped title and description.')
    viewport_geometry = None
    if tree.viewport() != tree.hwnd:
        viewport = tree.client_bounds(tree.viewport())
        logical_rows = [item for category in tree.roots()
                        for item in [category] + (tree.children(category) if tree.expanded(category) else [])]
        maximum_row = max(tree.item_height(item) for item in logical_rows)
        require(drawing_client[0] <= viewport[0] and drawing_client[1] <= viewport[1] and
                drawing_client[2] >= viewport[2] and drawing_client[3] >= viewport[3],
                'Native backing tree does not cover its complete clipping viewport.')
        require(drawing_client[3] - drawing_client[1] <= viewport[3] - viewport[1] + maximum_row,
                'Native backing tree exceeds its viewport-plus-largest-row height bound.')
        viewport_geometry = {'viewportClient': viewport, 'nativeChildClient': drawing_client,
                             'largestNativeVisibleRowHeight': maximum_row,
                             'scrollInfo': ui.scroll_info(tree.viewport())}
    capture, actual = ui.screen_capture(name + '-displayed.bmp', client)
    report['captures'].append(capture)
    observations = {'name': name, 'title': title, 'description': description,
        'client': client, 'row': row, 'textColumn': [text_left, width], 'requiredHeight': needed,
        'titleLines': title_lines, 'descriptionLines': description_lines,
        'font': reference.identity, 'lineHeights': reference.line_heights, 'viewportGeometry': viewport_geometry, 'blocks': []}
    report.setdefault('renderedRows', []).append(observations)
    y = row[1] + px(6)
    for label, lines, weight, color in [('title', title_lines, 700, (32, 44, 62)),
                                      ('description', description_lines, 400, (98, 112, 132))]:
        if not lines:
            continue
        line_height = reference.line_heights[weight]
        block = [text_left, y, text_left + width, y + len(lines) * line_height]
        first_line, end_line = complete_line_range(block[1], len(lines), line_height, client[1], client[3])
        if first_line < end_line:
            visible = [block[0], block[1] + first_line * line_height, block[2], block[1] + end_line * line_height]
            require(client[0] <= visible[0] < visible[2] <= client[2], 'Wrapped text exceeds the visible horizontal column.')
            required, height = reference.raster(lines, width, weight, color)
            alternate, _ = reference.raster(lines, width, 400 if weight == 700 else 700, color, line_height)
            measured = crop(actual, client[2] - client[0], client[3] - client[1],
                            [visible[0] - client[0], visible[1] - client[1], visible[2] - client[0], visible[3] - client[1]])
            clipping = [visible[0] - block[0], visible[1] - block[1], visible[2] - block[0], visible[3] - block[1]]
            required_visible = crop(required, width, height, clipping)
            alternate_visible = crop(alternate, width, height, clipping)
            block_observation = {'label': label, 'visible': visible, 'expectedWeight': weight,
                                 'completeLineIndices': list(range(first_line, end_line))}
            observations['blocks'].append(block_observation)
            for kind, pixels in [('required', required_visible), ('wrong-weight', alternate_visible)]:
                w, h = visible[2] - visible[0], visible[3] - visible[1]
                path = ui.evidence / (name + '-' + label + '-' + kind + '.bmp')
                header = struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, len(pixels), 0, 0, 0, 0)
                path.write_bytes(struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54) + header + pixels)
                block_observation[kind + 'Reference'] = {'path': path.name, 'sha256': sha256(path), 'width': w, 'height': h,
                    'method': 'Independent validator GDI raster; not an application screenshot.'}
            block_observation.update(requiredError=glyph_error(measured, required_visible),
                                     wrongWeightError=glyph_error(measured, alternate_visible))
            block_observation.update(require_glyph_style(measured, required_visible, alternate_visible))
        y = block[3] + (px(3) if label == 'title' and description else 0)
    require(observations['blocks'], 'No text block was actually compared.')
    return observations


def check_complete_row(ui, tree, item, reference, title, description, report, name):
    """Validate every glyph line across overlapping visible scroll positions."""
    padding = round(6 * ui.user.GetDpiForWindow(ui.main) / 96)
    gap = round(3 * ui.user.GetDpiForWindow(ui.main) / 96)
    wheel_line_into_view(ui, tree, item, padding, reference.line_heights[700])
    group = {'name': name, 'observations': [], 'complete': False,
             'input': 'Real wheel input between captures; no EnsureVisible or forced repaint.'}
    report.setdefault('completeRows', []).append(group)
    rows = []
    for index in range(100):
        row = check_row(ui, tree, item, reference, title, description, report, name + '-view-%02d' % index)
        rows.append(row)
        group['observations'].append(row['name'])
        coverage = line_coverage(rows)
        group.update(coverage)
        if not any(coverage['missing'].values()):
            line_coverage(rows, require_complete=True)
            group['complete'] = True
            return rows[0], rows[-1]
        if coverage['missing']['title']:
            offset = padding + coverage['missing']['title'][0] * reference.line_heights[700]
            line_height = reference.line_heights[700]
        else:
            offset = padding + len(row['titleLines']) * reference.line_heights[700] + gap + coverage['missing']['description'][0] * reference.line_heights[400]
            line_height = reference.line_heights[400]
        wheel_line_into_view(ui, tree, item, offset, line_height)
    raise AssertionError('Complete text coverage exceeded its bounded observation limit.')


def exercise(root, evidence, report):
    ui = prepare_desktop(root, evidence, report)
    with observed_desktop(ui, report, 'wrapped-library'):
        reference = None
        try:
            keys = Keyboard(ui)
            tree = Rows(ui.user, ui.send, ui.process.pid, ui.child(104))
            reference = TextReference(ui, tree.hwnd)
            # Configure documented pointer-sized style query once, before row comparisons.
            ui.user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            ui.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            for width, height in [(960, 680), (1024, 728)]:
                ui.fit_window(width, height)
                filter_to(ui, tree, 'complete multi-line tool name')
                item, category = tree.tools()[0], tree.roots()[0]
                require(tree.label(item) == NAME + '\n' + DESCRIPTION,
                        'Native accessibility text does not retain the complete title and description.')
                check_complete_row(ui, tree, category, reference, CATEGORY, '', report, 'category-%d' % width)
                row, last = check_complete_row(ui, tree, item, reference, NAME, DESCRIPTION, report, 'wrapped-%d' % width)
                require(len(row['titleLines']) >= 2 and len(row['descriptionLines']) >= 2, 'Fixture did not actually require wrapping.')
                hover_no_tooltip(ui, tree, item, report, 'wrapped-%d' % width)
                passed(report, 'wrapped-text-%d' % width,
                       'Complete multi-line title/category use bold text; description uses regular text; displayed glyphs match required weights and no tooltip appears.')
            filter_to(ui, tree, 'BoundaryToken')
            item = tree.tools()[0]
            check_complete_row(ui, tree, item, reference, TOKEN_NAME, TOKEN_DESCRIPTION, report, 'unbroken-token')
            passed(report, 'unbroken-token', 'Oversized name/description tokens wrap within the actual column without dropping or clipping their ends.')
            filter_to(ui, tree, 'FINAL LONG DESCRIPTION ANSWER')
            item = tree.tools()[0]
            before = ui.scroll_info(tree.viewport())
            first, last = check_complete_row(ui, tree, item, reference, LONG_NAME, LONG_DESCRIPTION, report, 'long-description')
            client = tree.visible_bounds()
            require(first['row'][3] - first['row'][1] > client[3] - client[1], 'Maximum-length fixture did not exceed the viewport.')
            require(ui.scroll_info(tree.viewport())['nPos'] > before['nPos'] and last['row'][1] < client[1],
                    'Long row did not scroll through its own content.')
            # Click an actual lower description line, not an offscreen row midpoint.
            bottom = last['blocks'][-1]['visible']
            ui.click_at(bottom[0] + 10, bottom[3] - reference.line_height // 2, expected=tree.hwnd)
            ui.wait('lower description line selects standalone tool', lambda: any(
                c['class'].lower() == 'edit' and c['text'] == LONG_NAME for c in ui.controls(ui.child(118))))
            passed(report, 'long-description-reachable',
                   'Every line of a maximum-length valid description is visibly validated through scrolling, and clicking its lower line opens the tool.')
            filter_to(ui, tree, 'complete multi-line tool name')
            item, category = tree.tools()[0], tree.roots()[0]
            # Selection via description line must retain the same standalone operation.
            normal_content = next(record['requiredHeight'] for record in report['renderedRows'] if record['name'].startswith('wrapped-1024-view-')) - round(6 * ui.user.GetDpiForWindow(ui.main) / 96)
            wheel_line_into_view(ui, tree, item, normal_content - reference.line_height, reference.line_height)
            row = tree.rect(item, False)
            description_y = row[1] + normal_content - reference.line_height // 2
            ui.click_at(row[0] + 80, description_y, expected=tree.hwnd)
            ui.wait('wrapped description selects tool', lambda: tree.selected() == item and any(
                c['class'].lower() == 'edit' and c['text'] == NAME for c in ui.controls(ui.child(118))))
            # Opening a standalone tool temporarily disables editable controls
            # while its host reply arrives. Establish keyboard focus separately
            # on the already selected row, after that operation has completed.
            ui.wait('wrapped tool ready for keyboard navigation', lambda:
                    ui.user.IsWindowEnabled(tree.hwnd) and tree.selected() == item)
            navigation = {'treeWindow': tree.hwnd, 'categoryHandle': category,
                          'itemHandle': item, 'focusBeforeRefocus': keys.focus(),
                          'selectedBeforeRefocus': tree.selected()}
            report['navigationInput'] = navigation
            wheel_line_into_view(ui, tree, item, normal_content - reference.line_height, reference.line_height)
            row = tree.rect(item, False)
            # Move horizontally from the selection click so the user's focus
            # click cannot be mistaken for the second half of a double click.
            refocus = [row[0] + 60, row[1] + normal_content - reference.line_height // 2]
            navigation['refocusPointer'] = refocus
            ui.click_at(*refocus, expected=tree.hwnd)
            ui.wait('selected wrapped row has actual keyboard focus', lambda:
                    keys.focus() == tree.hwnd and tree.selected() == item)
            navigation.update(focusBeforeHome=keys.focus(), selectedBeforeHome=tree.selected(),
                              selectedLabelBeforeHome=tree.label(tree.selected()))
            # Real keyboard input to focused tree, no injected selection notification.
            keys.key(0x24)
            navigation.update(focusImmediatelyAfterHome=keys.focus(),
                              selectedImmediatelyAfterHome=tree.selected())
            ui.wait('keyboard Home selects category', lambda: tree.selected() == category)
            navigation.update(focusAfterHome=keys.focus(), selectedAfterHome=tree.selected(),
                              selectedLabelAfterHome=tree.label(tree.selected()))
            keys.key(0x25)
            ui.wait('keyboard Left collapses wrapped category', lambda: not tree.expanded(category))
            keys.key(0x27)
            ui.wait('keyboard Right expands wrapped category', lambda: tree.expanded(category))
            keys.key(0x28)
            ui.wait('keyboard Down selects wrapped child', lambda: tree.selected() == item)
            passed(report, 'wrapped-navigation', 'Pointer on lower text and native Home/Left/Right/Down navigate the variable-height rows and preserve selection.')
            ui.click_button(411)
            ui.wait('workflow mode ready', lambda: ui.user.IsWindowVisible(ui.child(117)))
            filter_to(ui, tree, 'complete multi-line tool name')
            item = tree.tools()[0]
            before_nodes = ui.send(ui.child(106), 0x1004)
            wheel_line_into_view(ui, tree, item, normal_content - reference.line_height, reference.line_height)
            row = tree.rect(item, False)
            start = (row[0] + 80, row[1] + normal_content - reference.line_height // 2)
            canvas = ui.bounds(ui.child(117))
            ui.drag(start, (canvas[0] + 100, canvas[1] + 100))
            ui.wait('wrapped description drag adds one workflow node', lambda: ui.send(ui.child(106), 0x1004) == before_nodes + 1)
            time.sleep(.3)
            require(ui.send(ui.child(106), 0x1004) == before_nodes + 1, 'Wrapped row drag duplicated workflow nodes.')
            visible_capture(ui, report, 'wrapped-workflow-drag')
            ui.click_button(410)
            ui.wait('standalone tool retained after workflow', lambda: any(c['class'].lower() == 'edit' and c['text'] == NAME
                    for c in ui.controls(ui.child(118))))
            passed(report, 'wrapped-workflow-drag', 'Dragging a lower description line adds exactly one node; Tools mode keeps its standalone settings.')
            filter_to(ui, tree, 'FASTA lookup index')
            item = tree.tools()[0]
            label = tree.label(item)
            require('SAMtools' in label and 'not an aligner index' in label and 'not a prerequisite' in label,
                    'Real SAMtools displayDescription guidance is missing from the visible library text.')
            title, description = label.split('\n', 1)
            check_complete_row(ui, tree, item, reference, title, description, report, 'samtools-fai-guidance')
            visible_capture(ui, report, 'wrapped-final-desktop')
            passed(report, 'real-samtools-guidance', 'The existing FASTA lookup operation retains its complete display description and required font weights.')
        finally:
            if reference is not None:
                reference.close()


def run(args, report):
    require(os.name == 'nt', 'Native Windows is required; this gate has no passing skip.')
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(), 'Use the exact packaged private interpreter.')
    require(sha256(args.starter_archive) == args.starter_sha256, 'Wrong exact Starter archive.')
    report['archive'] = {'name': args.starter_archive.name, 'sha256': args.starter_sha256,
        'bytes': args.starter_archive.stat().st_size, 'extractedFilesVerified': verify_extracted(args.starter_archive, root)}
    manifest = json.loads((root / 'manifest.json').read_text())
    require(manifest['version'] == args.app_version, 'Unexpected candidate version.')
    report['appVersion'] = manifest['version']
    import_fixture(root, evidence, report)
    exercise(root, evidence, report)
    report['archive']['postGateExtractedFilesVerified'] = verify_extracted(args.starter_archive, root)
    report['nativeGUIObservationsCompleted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app-root', 'starter-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--gate-commit', required=True)
    parser.add_argument('--starter-sha256', required=True)
    parser.add_argument('--app-version', default='0.16.1')
    args = parser.parse_args()
    validate_identities(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'wrapped-library-native', 'sourceCommit': args.source_commit,
        'gateCommit': args.gate_commit, 'gateSha256': sha256(__file__), 'platform': platform.platform(),
        'startedUtc': utc(), 'checks': [], 'scenarios': [], 'captures': [], 'skips': [], 'limits': LIMITS,
        'nativeWindowsExecuted': False, 'nativeGUILaunched': False, 'nativeGUIValidated': False,
        'nativeGUIObservationsCompleted': False, 'success': False}
    report['helperSha256'] = {name: sha256(Path(__file__).parent / name) for name in (
        'check_deployment_ui_windows.py', 'check_references_windows.py', 'check_tester_feedback_windows.py',
        'check_ui_patch_windows.py', 'check_workspace_ui_windows.py', 'native_tree.py')}
    try:
        run(args, report)
    except Exception as error:
        failed(report, 'wrapped-library-completion', str(error))
        report.update(failure=str(error), traceback=traceback.format_exc())
    finally:
        report['finishedUtc'] = utc()
        finalize_report(report)
        write_json(args.report, report)
    print(json.dumps({'success': report['success'], 'passed': report['passed'], 'failed': report['failed'],
                      'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
