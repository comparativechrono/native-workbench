#!/usr/bin/env python3
"""Observe tester-reported native repaint, library navigation and Samples behavior.

Run against a disposable extraction with its own private Python. All temporal
frames read the displayed desktop before any PrintWindow capture. Finite samples
are bounded observations, not proof of zero flicker on other hardware.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_batch_windows import NativeList, scientific_truth
from check_deployment_ui_windows import (Keyboard, failed, finalize_report,
    passed, tree_hashes, unique_button, utc, verify_extracted)
from check_references_windows import PrivateHost, require, sha256, stop_process_tree, write_json
from check_scroll_frames_windows import DisplayFrames
from check_ui_patch_windows import PatchUI, clear_focused_edit, inside, pointer_click

LIMITS = [
    'Finite displayed-desktop samples cannot exclude shorter flashes between samples or validate other display hardware.',
    'Hosted restored windows and observed DPI only; representative PCs, high DPI, multiple monitors and physical trackpads remain untested.',
    'Tree overflow uses explicitly identified test-only packs imported through the normal validated importer; Starter categories are separately observed.',
    'Synthetic Starter batch truth is not a benchmark, clinical validation or biological QC pass threshold.',
]


class FeedbackUI(PatchUI):
    """Recognize only explicitly expected native common dialogs in this gate."""
    expected_dialog_titles = frozenset()

    @contextmanager
    def common_dialog(self, title):
        previous = self.expected_dialog_titles
        self.expected_dialog_titles = previous | {title}
        try:
            yield
        finally:
            self.expected_dialog_titles = previous

    def top_windows(self):
        """Snapshot owned captions without messaging a dialog being destroyed.

        GetWindowTextW reads another process's top-level caption from Windows;
        it does not use the strict WM_GETTEXT path needed for child edit values.
        Recheck liveness/visibility after reading before classifying a dialog.
        """
        rows = []
        for handle in self.windows():
            live = lambda: (self.user.IsWindow(ctypes.c_void_p(handle)) and
                            self.user.IsWindowVisible(handle))
            if not live():
                continue
            title, klass = ctypes.create_unicode_buffer(8192), ctypes.create_unicode_buffer(256)
            self.user.GetClassNameW(handle, klass, len(klass))
            self.user.GetWindowTextW(handle, title, len(title))
            if live():
                rows.append({'handle': handle, 'title': title.value, 'class': klass.value})
        return rows

    def wait(self, phase, predicate, seconds=30):
        self.progress(phase)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            require(self.process.poll() is None, 'Native desktop exited unexpectedly.')
            unexpected = [row for row in self.top_windows()
                          if row['class'] == '#32770' and row['title'] not in self.expected_dialog_titles]
            require(not unexpected, 'Unexpected native dialog: ' + json.dumps(unexpected))
            if predicate():
                return
            time.sleep(.1)
        # Preserve displayed pixels without asking the app to repair its paint.
        if self.main:
            self.screen_capture('feedback-wait-timeout.bmp', self.bounds(self.main))
            self.progress(phase + ' timed out', controls=self.controls())
        raise TimeoutError(phase)

    def close(self):
        """Require clean exit, recording a blocking dialog before cleanup."""
        try:
            if self.main and self.process.poll() is None:
                self.post(self.main, 0x0010)
                try:
                    require(self.process.wait(timeout=30) == 0, 'Native desktop did not close cleanly.')
                except Exception:
                    report = getattr(self, 'gate_report', None)
                    try:
                        rows = self.top_windows()
                        if report is not None:
                            report.setdefault('closeFailures', []).append({'windows': rows})
                        for index, row in enumerate(rows):
                            if report is not None:
                                visible_capture(self, report, 'feedback-close-failure-%d' % index, row['handle'])
                            else:
                                self.screen_capture('feedback-close-failure-%d.bmp' % index, self.bounds(row['handle']))
                    except Exception as capture_error:
                        if report is not None:
                            report.setdefault('failureCaptureErrors', []).append(str(capture_error))
                    raise
        finally:
            stop_process_tree(self.process)
            self.user.SetThreadDpiAwarenessContext(self.previous_dpi)
            log = self.root / 'user-data/desktop-host.stderr.txt'
            if log.is_file():
                shutil.copyfile(log, self.evidence / 'ui-desktop-host.stderr.txt')


@contextmanager
def observed_desktop(ui, report, scope):
    """Cleanup cannot replace the first failed assertion with a close timeout."""
    primary = None
    try:
        yield ui
    except Exception as error:
        primary = error
        report.setdefault('primaryFailures', []).append({
            'scope': scope, 'error': str(error), 'traceback': traceback.format_exc()})
        try:
            for index, owner in enumerate(ui.windows()):
                visible_capture(ui, report, scope + '-failure-%d' % index, owner)
        except Exception as capture_error:
            report.setdefault('failureCaptureErrors', []).append(str(capture_error))
        # Only the gate-owned disposable process is terminated after a failure.
        # Successful scenarios still require the ordinary clean-close contract.
        try:
            stop_process_tree(ui.process)
        except Exception as cleanup_error:
            report.setdefault('cleanupErrors', []).append(str(cleanup_error))
        raise
    finally:
        try:
            ui.close()
        except Exception as cleanup_error:
            if primary is None:
                raise
            report.setdefault('cleanupErrors', []).append(str(cleanup_error))


def validate_identities(args):
    for key in ('source_commit', 'gate_commit'):
        require(re.fullmatch('[0-9a-f]{40}', getattr(args, key)), 'Exact source/gate commits are required.')
    require(re.fullmatch('[0-9a-f]{64}', args.starter_sha256), 'Exact Starter SHA-256 is required.')
    require(args.app_root.resolve() not in args.report.resolve().parents,
            'Evidence must be outside the disposable application.')
    require(args.report.resolve() != args.starter_archive.resolve(), 'Evidence cannot replace the immutable archive.')


def normalized(raw):
    """BI_RGB's fourth byte is unused; exclude it without ignoring RGB changes."""
    value = bytearray(raw)
    value[3::4] = bytes(len(value) // 4)
    return bytes(value)


def black_blocks(raw, width, height, tile=8):
    """Detect a 16x16 nearly solid black region, not black text or selection.

    Four adjacent 8x8 tiles must each contain at least 61 RGB pixels below 16.
    A blue selection, ordinary glyph, caret or cursor cannot satisfy this by
    itself. This deliberately measures the reported black collapse flash, not
    arbitrary visual differences between legitimate expanded/collapsed frames.
    """
    require(len(raw) == width * height * 4, 'Unexpected pixel buffer size.')
    dark = set()
    for y in range(0, height - tile + 1, tile):
        for x in range(0, width - tile + 1, tile):
            count = 0
            for yy in range(y, y + tile):
                offset = (yy * width + x) * 4
                count += sum(max(raw[p:p + 3]) < 16 for p in range(offset, offset + tile * 4, 4))
            if count >= tile * tile - 3:
                dark.add((x, y))
    return [[x, y, x + tile * 2, y + tile * 2] for x, y in sorted(dark)
            if {(x + tile, y), (x, y + tile), (x + tile, y + tile)} <= dark]


def sample_frames(ui, report, name, rectangle, seconds, *, action=None, stable=None,
                  stable_after=0, observe=None):
    """Bounded capture with no target paint/erase, input or polling inside reads."""
    stream = DisplayFrames(ui, rectangle)
    row = {'name': name, 'rectangle': rectangle, 'requestedSeconds': seconds,
           'method': 'visible screen BitBlt with compositor timing aid; no PrintWindow or target repaint',
           'samples': [], 'captures': [], 'stableComparisonStartsSeconds': stable_after,
           'unexpectedStableFrames': 0, 'blackBlockFrames': 0}
    report.setdefault('temporal', []).append(row)
    saved = set()
    last_raw = None
    try:
        if action:
            action()
        start = time.perf_counter()
        while time.perf_counter() - start < seconds:
            stamp, raw, read_start = stream.read()
            rgb = normalized(raw)
            digest = hashlib.sha256(rgb).hexdigest()
            elapsed = stamp - start
            blocks = black_blocks(raw, stream.width, stream.height)
            differs = stable is not None and elapsed >= stable_after and rgb != stable
            sample = {'elapsedMs': round(elapsed * 1000, 3),
                      'readMs': round((stamp - read_start) * 1000, 3),
                      'rgbSha256': digest, 'blackBlocks': blocks,
                      'unexpectedStableDifference': differs}
            if observe:
                sample['observation'] = observe()
            row['samples'].append(sample)
            row['unexpectedStableFrames'] += int(differs)
            row['blackBlockFrames'] += bool(blocks)
            # Preserve every distinct unexpected frame, up to a bounded 32,
            # plus the first frame. All samples/counts remain in the report.
            if not saved or ((blocks or differs) and digest not in saved and len(saved) < 32):
                saved.add(digest)
                frame = stream.save(ui.evidence, name + '-frame-%03d.bmp' % len(row['samples']), raw)
                frame.update(dpi=ui.user.GetDpiForWindow(ui.main), method=row['method'])
                row['captures'].append(frame)
                report['captures'].append(frame)
            last_raw = raw
        require(last_raw is not None and len(row['samples']) >= 5, 'Too few displayed samples to establish temporal observation.')
        frame = stream.save(ui.evidence, name + '-last.bmp', last_raw)
        frame.update(dpi=ui.user.GetDpiForWindow(ui.main), method=row['method'])
        row['captures'].append(frame)
        report['captures'].append(frame)
        row.update(frames=len(row['samples']), elapsedSeconds=time.perf_counter() - start,
                   samplingComplete=True)
        return row
    finally:
        stream.close()


def visible_capture(ui, report, name, owner=None):
    frame, raw = ui.screen_capture(name + '.bmp', ui.bounds(owner or ui.main))
    frame['dpi'] = ui.user.GetDpiForWindow(owner or ui.main)
    report['captures'].append(frame)
    return raw


def window(ui, title):
    return next((row['handle'] for row in ui.top_windows()
                 if row['handle'] != ui.main and row['title'] == title), None)


def button(ui, owner, identity):
    control = ui.child(identity, owner)
    ui.wait('available native action ' + str(identity), lambda:
            control and ui.user.IsWindowVisible(control) and ui.user.IsWindowEnabled(control))
    top = ui.user.GetAncestor(control, 2)
    if ui.user.GetForegroundWindow() != top:
        ui.user.SetForegroundWindow(top)
        ui.wait('button owner in foreground', lambda: ui.user.GetForegroundWindow() == top)
    # A closing native dialog/async reply may temporarily cover or disable its
    # owner after IsWindowVisible has already changed. Wait for the same actual
    # hit-test contract as click_at, then retain that strict check at input time.
    observations, stable_since = [], None
    def ready():
        nonlocal stable_since
        row = pointer_state(ui, control)
        row['elapsedMs'] = round((time.monotonic() - started) * 1000, 3)
        observations.append(row)
        stable_since = (stable_since or time.monotonic()) if row['ready'] else None
        return stable_since is not None and time.monotonic() - stable_since >= .1
    started = time.monotonic()
    ui.wait('native action hit target settled ' + str(identity), ready, seconds=5)
    if hasattr(ui, 'gate_report'):
        ui.gate_report.setdefault('pointerReadiness', []).append({'controlId': identity, 'observations': observations})
    pointer_click(ui, control)


def pointer_state(ui, control):
    left, top, right, bottom = ui.bounds(control)
    x, y = (left + right) // 2, (top + bottom) // 2
    hit = ui.user.WindowFromPoint(wintypes.POINT(x, y))
    process = wintypes.DWORD()
    ui.user.GetWindowThreadProcessId(hit, ctypes.byref(process))
    area = ui.work_area()
    available = bool(ui.user.IsWindowVisible(control) and ui.user.IsWindowEnabled(control))
    owned = process.value == ui.process.pid
    expected = bool(hit == control or ui.user.IsChild(control, hit))
    visible = area[0] <= x < area[2] and area[1] <= y < area[3]
    return {'point': [x, y], 'hitWindow': hit, 'hitProcess': process.value,
            'expectedWindow': control, 'available': available, 'owned': owned,
            'expectedHit': expected, 'insideWorkArea': visible,
            'ready': available and owned and expected and visible}


def edit(ui, keys, control, value):
    pointer_click(ui, control)
    ui.wait('focused editable cell', lambda: keys.focus() == control)
    clear_focused_edit(ui, keys, control)
    keys.text(value)
    ui.wait('typed field value', lambda: ui.label(control) == value)


def combo_choices(ui, control):
    values = []
    for index in range(ui.send(control, 0x0146)):
        value = ctypes.create_unicode_buffer(4096)
        ui.send(control, 0x0148, index, ctypes.addressof(value))
        values.append(value.value)
    return values


def choose(ui, keys, control, value):
    choices = combo_choices(ui, control)
    require(value in choices, 'Expected native choice is missing: ' + value + ' / ' + str(choices))
    pointer_click(ui, control)
    keys.key(0x24)  # Home, then real navigation in the open dropdown.
    for _ in range(choices.index(value)):
        keys.key(0x28)
    keys.key(0x0D)
    ui.wait('native combo selection', lambda: ui.send(control, 0x0147) == choices.index(value))


def prepare_desktop(root, evidence, report):
    ui = FeedbackUI(root, evidence)
    ui.gate_report = report
    report['nativeGUILaunched'] = report['nativeWindowsExecuted'] = True
    require(inside(ui.initial_bounds, ui.initial_work_area), 'Unmodified startup window exceeds work area.')
    report.setdefault('startups', []).append({'bounds': ui.initial_bounds, 'workArea': ui.initial_work_area,
                         'dpi': ui.user.GetDpiForWindow(ui.main)})
    ui.wait('native desktop catalogue ready', lambda: ui.library().tools() and ui.user.IsWindowEnabled(ui.child(410)))
    setup = lambda: window(ui, 'Tool setup · Native Workbench')
    # A pristine extraction is required for reproducible state.
    ui.wait('fresh setup or available main window', lambda: setup() or ui.user.IsWindowEnabled(ui.child(417)))
    if setup():
        pointer_click(ui, unique_button(ui, setup(), 'Starter'))
        pointer_click(ui, unique_button(ui, setup(), 'Use Workbench'))
        ui.wait('setup dismissal completed', lambda: not setup() and ui.user.IsWindowEnabled(ui.child(417)))
    return ui


def run_button_observations(ui, report):
    keys = Keyboard(ui)
    search = ui.child(102)
    edit(ui, keys, search, 'Coordinate sort')
    ui.wait('one real SAMtools operation', lambda: len(ui.library().tools()) == 1)
    ui.click_at(*ui.library().first_tool_point(), expected=ui.child(104))
    ui.wait('standalone Run ready', lambda: ui.label(ui.child(113)) == 'Run tool' and ui.user.IsWindowEnabled(ui.child(113)))
    edit(ui, keys, ui.child(102), '')
    for width, height in [(960, 680), (1024, 728)]:
        ui.fit_window(width, height)
        time.sleep(.5)  # Natural settled baseline, no redraw request.
        run = ui.child(113)
        rect = ui.bounds(run)
        area = [rect[0] - 3, rect[1] - 3, rect[2] + 3, rect[3] + 3]
        require(inside(area, ui.work_area()), 'Run sampling rectangle clips the visible desktop.')
        park = ui.bounds(ui.child(101))
        ui.mouse(park[0] + 10, park[1] + 8)
        time.sleep(.5)
        stream = DisplayFrames(ui, area)
        try:
            _, idle_raw, _ = stream.read()
        finally:
            stream.close()
        idle = sample_frames(ui, report, 'run-%d-idle' % width, area, 6.4,
                             stable=normalized(idle_raw),
                             observe=lambda: {'enabled': bool(ui.user.IsWindowEnabled(run)), 'text': ui.label(run)})
        require(not idle['unexpectedStableFrames'] and not idle['blackBlockFrames'],
                'Displayed Run region changes during settled idle sampling.')
        require(all(s['observation'] == {'enabled': True, 'text': 'Run tool'} for s in idle['samples']),
                'Idle polling disables or changes the Run action.')
        ui.mouse((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        # Observe the transition before a hover reference is established;
        # normal theme animation is allowed but black-block flashes are not.
        transition = sample_frames(ui, report, 'run-%d-hover-transition' % width, area, .55)
        require(not transition['blackBlockFrames'], 'Black block while entering Run hover.')
        stream = DisplayFrames(ui, area)
        try:
            _, hover_raw, _ = stream.read()
        finally:
            stream.close()
        hover = sample_frames(ui, report, 'run-%d-hover-hold' % width, area, 6.4,
                              stable=normalized(hover_raw))
        require(not hover['unexpectedStableFrames'] and not hover['blackBlockFrames'],
                'Displayed Run region changes while hovering across idle polling intervals.')
        passed(report, 'run-temporal-%d' % width,
               'Run plus 3-pixel gutter remains stable in 6.4-second idle and hover holds at the observed restored size; finite screen samples only.')
        visible_capture(ui, report, 'run-settled-%d' % width)


def samples_blank_access(ui, report):
    button(ui, ui.main, 424)
    title, editor_title = 'Samples · Native Workbench', 'Sample table editor · Native Workbench'
    ui.wait('Samples available without an analysis graph', lambda: window(ui, title))
    owner = window(ui, title)
    require(ui.user.IsWindowEnabled(ui.child(815, owner)), 'New table is unavailable without a workflow.')
    button(ui, owner, 815)
    ui.wait('blank-workspace table editor', lambda: window(ui, editor_title))
    editor = window(ui, editor_title)
    require(NativeList(ui, ui.child(1601, editor)).count() == 1,
            'A blank workspace cannot create an independent sample table.')
    visible_capture(ui, report, 'samples-new-without-workflow', editor)
    button(ui, editor, 1615)
    ui.wait('unchanged new table cancelled', lambda: not window(ui, editor_title))
    button(ui, owner, 813)
    ui.wait('blank Samples closed', lambda: not window(ui, title))
    activate_main_after_modal(ui, report, 'blank Samples closed')
    passed(report, 'samples-without-workflow',
           'Samples and New table work from a fresh empty workspace; cancelling the untouched draft returns without creating an analysis.')


def caption_pointer_state(ui, point):
    """Require the actual exposed main caption, never a covered target."""
    x, y = point
    hit = ui.user.WindowFromPoint(wintypes.POINT(x, y))
    owner = wintypes.DWORD()
    ui.user.GetWindowThreadProcessId(hit, ctypes.byref(owner))
    left, top, right, bottom = ui.work_area()
    available = bool(ui.user.IsWindowVisible(ui.main) and ui.user.IsWindowEnabled(ui.main))
    exposed = hit == ui.main and owner.value == ui.process.pid and left <= x < right and top <= y < bottom
    # WM_NCHITTEST returns HTCAPTION=2 only for the draggable title area;
    # system menu, close/minimize/maximize buttons and borders are not accepted.
    hit_code = ui.send(ui.main, 0x0084, 0, (x & 0xffff) | ((y & 0xffff) << 16)) if exposed else None
    return {'point': point, 'hitWindow': hit, 'hitProcess': owner.value,
            'available': available, 'exposed': exposed, 'hitCode': hit_code,
            'ready': available and exposed and hit_code == 2}


def main_caption_rectangle(ui):
    class TitleBarInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcTitleBar', wintypes.RECT),
                    ('rgstate', wintypes.DWORD * 6)]
    ui.user.GetTitleBarInfo.argtypes = [wintypes.HWND, ctypes.POINTER(TitleBarInfo)]
    ui.user.GetTitleBarInfo.restype = wintypes.BOOL
    info = TitleBarInfo()
    info.cbSize = ctypes.sizeof(info)
    require(ui.user.GetTitleBarInfo(ui.main, ctypes.byref(info)), 'Cannot inspect the actual main caption.')
    box = info.rcTitleBar
    return [box.left, box.top, box.right, box.bottom]


def activate_main_after_modal(ui, report, phase):
    """One ordinary caption click at a known modal-close setup boundary.

    A hosted runner console can become foreground while the dialog is being
    destroyed. Recover only through an exposed owned caption; do not suppress
    foreign windows, inject focus or repair measured rendering scenarios.
    """
    ui.wait('main owner enabled after modal close', lambda:
            ui.user.IsWindowVisible(ui.main) and ui.user.IsWindowEnabled(ui.main), seconds=5)
    time.sleep(.15)  # Let the native modal destruction/owner activation finish.
    row = {'phase': phase, 'foregroundBefore': ui.user.GetForegroundWindow(),
           'mainWindow': ui.main, 'clicked': False, 'candidates': []}
    report.setdefault('modalActivationSetup', []).append(row)
    if row['foregroundBefore'] == ui.main:
        row['foregroundAfter'] = row['foregroundBefore']
        return
    require(not any(entry['handle'] != ui.main for entry in ui.top_windows()),
            'Another owned window is still open after the expected modal close.')
    visible_capture(ui, report, 'modal-activation-before')
    left, top, right, bottom = main_caption_rectangle(ui)
    row['captionBounds'] = [left, top, right, bottom]
    require(left < right and top < bottom, 'The native main caption has no usable area.')
    for fraction in (.25, .5, .75):
        point = [round(left + (right - left) * fraction), (top + bottom) // 2]
        state = caption_pointer_state(ui, point)
        row['candidates'].append(state)
        if not state['ready']:
            continue
        # Recheck immediately before genuine SendInput, without click_at's
        # SetForegroundWindow precondition that the runner refused earlier.
        confirmed = caption_pointer_state(ui, point)
        row['confirmation'] = confirmed
        require(confirmed['ready'], 'The exposed main caption changed before input.')
        ui.mouse(*point)
        ui.mouse(*point, 2)
        ui.mouse(*point, 4)
        row.update(clicked=True, clickPoint=point)
        ui.wait('real caption click activates main owner', lambda:
                ui.user.GetForegroundWindow() == ui.main, seconds=5)
        row['foregroundAfter'] = ui.user.GetForegroundWindow()
        visible_capture(ui, report, 'modal-activation-after')
        return
    raise AssertionError('No exposed owned main caption is available for ordinary activation.')


def tree_snapshot(tree, item):
    first, selected = tree.first_visible(), tree.selected()
    return {'item': tree.label(item), 'expanded': tree.expanded(item),
            'itemBounds': tree.rect(item), 'firstVisible': tree.label(first) if first else None,
            'firstVisibleHandle': first, 'nativeChildFirstVisibleHandle': tree.next(0, 5), 'selected': tree.label(selected) if selected else None,
            'selectedHandle': selected}


def triangle_point(ui, tree, item):
    """Read a visible row without EnsureVisible, which could mask the jump bug."""
    left, top, _, bottom = tree.rect(item)
    point = [left - round(10 * ui.user.GetDpiForWindow(ui.main) / 96), (top + bottom) // 2]
    bounds = tree.visible_bounds()
    require(bounds[0] < point[0] < bounds[2] and bounds[1] < point[1] < bounds[3],
            'Required triangle is not already visible; no EnsureVisible repair is permitted.')
    return point


def tree_transition(ui, keys, report, item, target, label, keyboard=False, retain_anchor=True):
    tree = ui.library()
    before = tree_snapshot(tree, item)
    bounds = tree.visible_bounds()
    rectangle = [bounds[0] + 2, bounds[1] + 2, bounds[2] - 2, bounds[3] - 2]
    require(before['expanded'] != target, 'Tree transition must change actual expansion.')
    if keyboard:
        # Selecting the heading is an explicit real pointer action, separated
        # from the later Left/Right transition. Its own selection can scroll.
        rect = tree.rect(item)
        ui.click_at(rect[0] + 8, (rect[1] + rect[3]) // 2, expected=tree.hwnd)
        ui.wait('heading keyboard focus', lambda: keys.focus() == tree.hwnd and tree.selected() == item)
        # App headings toggle on click: establish actual current state first.
        if tree.expanded(item) == target:
            keys.key(0x25 if target else 0x27)
            ui.wait('keyboard transition starting state', lambda: tree.expanded(item) != target)
        before = tree_snapshot(tree, item)
        action = lambda: keys.key(0x27 if target else 0x25)
    else:
        point = triangle_point(ui, tree, item)
        action = lambda: ui.click_at(*point, expected=tree.hwnd)
    row = sample_frames(ui, report, label, rectangle, .8, action=action)
    ui.wait('requested native category state', lambda: tree.expanded(item) == target)
    after = tree_snapshot(tree, item)
    row.update(before=before, after=after, input='real SendInput keyboard' if keyboard else 'real pointer triangle',
               noEnsureVisibleOrPaintRepair=True, retainAnchorRequired=retain_anchor)
    require(not row['blackBlockFrames'], 'Black collapse/expansion block was captured.')
    if retain_anchor:
        require(after['firstVisibleHandle'] == before['firstVisibleHandle'] and
                after['itemBounds'][1] == before['itemBounds'][1],
                'Expanding/collapsing an already visible heading changed its scroll anchor or moved it to the top.')
    if keyboard:
        require(after['selectedHandle'] == item, 'Keyboard category selection was lost.')
    else:
        require(after['selectedHandle'] == item, 'Triangle click lost the explicitly selected category.')
    return row


def tree_real_categories(ui, report):
    tree, keys = ui.library(), Keyboard(ui)
    roots = tree.roots()
    require(len(roots) >= 3, 'Expected real Starter categories are missing.')
    report['starterCategories'] = {tree.label(root): [tree.label(child) for child in tree.children(root)] for root in roots}
    # Clear only expansion chosen during the earlier filtered tool selection.
    for root in roots:
        if tree.expanded(root):
            ui.click_at(*triangle_point(ui, tree, root), expected=tree.hwnd)
            ui.wait('collapsed real category baseline', lambda root=root: not tree.expanded(root))
    for width, height in [(960, 680), (1024, 728)]:
        ui.fit_window(width, height)
        time.sleep(.4)
        # Open bottom to top, then close top to bottom. Each target is visible
        # before the action even when the already-open children overflow.
        for index, item in reversed(list(enumerate(roots[:3]))):
            tree_transition(ui, keys, report, item, True, 'starter-%d-expand-%d' % (width, index),
                            retain_anchor=True)
        for index, item in enumerate(roots[:3]):
            tree_transition(ui, keys, report, item, False, 'starter-%d-collapse-%d' % (width, index),
                            retain_anchor=True)
        visible_capture(ui, report, 'starter-categories-%d' % width)
        passed(report, 'starter-category-temporal-%d' % width,
               'Three real Starter headings expand/collapse by triangle with retained selection/anchor and no sampled 16×16 black block.')


def overflow_fixture(root, evidence, identity, category):
    binary = next((root / 'packs/bam-0.4.0').rglob('samtools.exe'))
    executable = binary.read_bytes()
    workflows = {'version-%02d' % n: {'ports': [], 'outputs': [{'id': 'version', 'type': 'metrics',
        'manifestOutputs': ['version']}], 'methods': 'Test-only library overflow fixture.'} for n in range(32)}
    schema = json.dumps({'schema': 1, 'category': category, 'workflows': workflows}).encode()
    manifest = ('[pack]\nformat=2\nid=%s\nversion=1.0.0\nname=%s\nplatform=windows-x86_64\n'
                '[tool:samtools]\npath=bin/samtools.exe\nversion=fixture\nsha256=%s\n'
                '[asset:workbench-schema]\npath=workbench-schema.json\nsha256=%s\n' %
                (identity, category, sha256(binary), hashlib.sha256(schema).hexdigest()))
    for operation in workflows:
        manifest += ('[workflow:%s]\nname=%s\ninputs=\noutputs=version\nsteps=run\n'
                     '[output:%s:version]\nlabel=Version\npath=version.txt\n'
                     '[step:%s:run]\nlabel=Version\nkind=exec\ntool=samtools\narg.0=--version\nstdout=version\n' %
                     (operation, operation, operation, operation))
    files = {'pack.ini': manifest.encode(), 'workbench-schema.json': schema,
             'bin/samtools.exe': executable,
             'licenses/TEST-FIXTURE.txt': b'Test-only unchanged Starter SAMtools wrapper. Never distributed as a product pack.\n'}
    envelope = {'schema': 1, 'id': identity, 'version': '1.0.0', 'packApi': 1,
                'minAppVersion': '0.11.0', 'platform': 'windows-x86_64',
                'manifestSha256': hashlib.sha256(files['pack.ini']).hexdigest(),
                'files': [{'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for path, data in files.items()]}
    archive = evidence / (identity + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('workbench-pack.json', json.dumps(envelope))
        for path, data in files.items():
            out.writestr('pack/' + path, data)
    return archive, envelope


def import_overflow(root, evidence, report):
    report['overflowFixtures'] = []
    original = tree_hashes(root / 'packs')
    host = PrivateHost(root, evidence, 'overflow-import', offline=True)
    try:
        host.call('init')
        for identity, category in [('tester-overflow-a', 'Gate overflow first'), ('tester-overflow-z', 'ZZ gate overflow tail')]:
            archive, envelope = overflow_fixture(root, evidence, identity, category)
            host.call('packs/import', {'path': str(archive)})
            deadline = time.monotonic() + 60
            while True:
                state = host.call('packs/status')['operation']
                if not state.get('active'):
                    require(state.get('success') and state.get('status') == 'completed', 'Normal fixture import failed: ' + json.dumps(state))
                    break
                require(time.monotonic() < deadline, 'Fixture import timed out.')
                time.sleep(.1)
            report['overflowFixtures'].append({'id': identity, 'category': category,
                'archive': archive.name, 'sha256': sha256(archive), 'inventory': envelope,
                'scope': 'Disposable gate extraction only; unchanged pinned SAMtools bytes; no scientific claim.'})
    finally:
        host.close()
    current = tree_hashes(root / 'packs')
    require(all(current.get(path) == digest for path, digest in original.items()), 'Fixture import modified existing packs.')


def wheel_heading_into_view(ui, tree, item, require_nonzero=False):
    """Prepare a visible heading using real wheel input, before observations.

    Wrapped descriptions make the number of rows per viewport variable. This
    setup cannot assume that opening three children leaves a later heading on
    screen. Measured expansion/collapse still uses no EnsureVisible or scroll
    repair, and retains the same anchor/pixel assertions.
    """
    bounds = tree.visible_bounds()
    for _ in range(100):
        row = tree.rect(item)
        center = (row[1] + row[3]) // 2
        nonzero = tree.first_visible() != tree.roots()[0]
        if bounds[1] + 4 < center < bounds[3] - 4 and (nonzero or not require_nonzero):
            return
        delta = 120 if center <= bounds[1] + 4 else -120
        ui.wheel(bounds[0] + 30, bounds[1] + 40, delta)
        time.sleep(.05)
    raise AssertionError('Actual wheel input could not establish a visible wrapped heading.')


def tree_overflow(ui, report):
    tree, keys = ui.library(), Keyboard(ui)
    roots = tree.roots()
    first = next(item for item in roots if tree.label(item) == 'Gate overflow first')
    tail = next(item for item in roots if tree.label(item) == 'ZZ gate overflow tail')
    for width, height in [(960, 680), (1024, 728)]:
        ui.fit_window(width, height)
        # Real wheel navigation establishes the top; no EnsureVisible messages.
        box = tree.visible_bounds()
        for _ in range(35):
            ui.wheel(box[0] + 30, box[1] + 40, 120)
        time.sleep(.2)
        # Tail is opened before the first overflow section to keep its heading
        # initially visible. Its children retain enough content below the
        # collapse target that scroll clamping is not necessary.
        if not tree.expanded(tail):
            tree_transition(ui, keys, report, tail, True, 'overflow-%d-tail-open' % width)
        preceding = next((item for item in roots[:roots.index(first)]
                          if len(tree.children(item)) >= 3), None)
        require(preceding is not None, 'Need a real preceding category for a nonzero wheel anchor.')
        if not tree.expanded(preceding):
            tree_transition(ui, keys, report, preceding, True,
                            'overflow-%d-preceding' % width)
        if not tree.expanded(first):
            wheel_heading_into_view(ui, tree, first)
            tree_transition(ui, keys, report, first, True, 'overflow-%d-first-open' % width)
        require(ui.scroll_info(tree.viewport())['nMax'] + 1 > ui.scroll_info(tree.viewport())['nPage'],
                'Overflow fixture did not create genuine native scrolling.')
        # Establish a real nonzero viewport with the target already visible;
        # variable-height descriptions may need more than one wheel notch.
        wheel_heading_into_view(ui, tree, first, require_nonzero=True)
        before = tree_snapshot(tree, first)
        require(before['firstVisibleHandle'] != roots[0], 'Wheel did not leave the tree top.')
        triangle_point(ui, tree, first)
        for cycle in range(4):
            tree_transition(ui, keys, report, first, False, 'overflow-%d-collapse-%d' % (width, cycle))
            tree_transition(ui, keys, report, first, True, 'overflow-%d-expand-%d' % (width, cycle))
        tree_transition(ui, keys, report, first, False, 'overflow-%d-key-left' % width, keyboard=True)
        tree_transition(ui, keys, report, first, True, 'overflow-%d-key-right' % width, keyboard=True)
        visible_capture(ui, report, 'overflow-scrolled-%d' % width)
        passed(report, 'overflow-anchor-temporal-%d' % width,
               'Genuinely scrolled multi-category tree retains first-visible anchor/heading row across pointer and real keyboard transitions; no sampled 16×16 black block.')


def methods_and_missing_input(ui, report):
    require(ui.label(ui.child(115)) == 'Methods', 'Separate Methods action is missing.')
    ui.click_button(115)
    ui.wait('separate planned Methods dialog', lambda: window(ui, 'Planned methods'))
    owner = window(ui, 'Planned methods')
    body = ui.label(ui.child(105, owner))
    report['methods'] = {'title': ui.label(owner), 'text': body,
                          'textSha256': hashlib.sha256(body.encode()).hexdigest()}
    require('samtools 1.24 (pack bam 0.4.0)' in body.lower() and
            'coordinate sort' in body.lower() and len(body) > 100,
            'Methods does not expose the selected scientific operation.')
    require('Readiness' not in ui.label(owner), 'Methods remains hidden under readiness.')
    visible_capture(ui, report, 'separate-planned-methods', owner)
    button(ui, owner, 2)
    ui.wait('planned Methods closed', lambda: not window(ui, 'Planned methods'))
    passed(report, 'separate-methods', 'Separate Methods action opens the selected SAMtools operation draft without a readiness wrapper.')
    ui.click_button(113)
    ui.wait('Run still reviews missing input', lambda: window(ui, 'Review and run'))
    owner = window(ui, 'Review and run')
    body = ui.label(ui.child(105, owner))
    require(any(token in body.lower() for token in ('missing', 'required', 'choose', 'select')),
            'Run no longer gives actionable missing-input guidance.')
    require(ui.label(ui.child(1, owner)) != 'Run analysis', 'Incomplete tool permits analysis execution.')
    report['missingInputRun'] = {'title': ui.label(owner), 'text': body,
                                 'confirmation': ui.label(ui.child(1, owner))}
    visible_capture(ui, report, 'run-missing-input-guidance', owner)
    button(ui, owner, 2)
    ui.wait('missing-input review closed', lambda: not window(ui, 'Review and run'))
    require(not (ui.root / 'user-data/runs.json').exists() or not json.loads(
        (ui.root / 'user-data/runs.json').read_text()), 'Invalid Run unexpectedly recorded an analysis.')
    passed(report, 'run-missing-input', 'Run retains actionable missing-input review and does not offer execution for an incomplete tool.')


def confirm(ui, title):
    with ui.common_dialog(title):
        ui.wait(title, lambda: window(ui, title))
        pointer_click(ui, unique_button(ui, window(ui, title), 'Yes'))
        ui.wait(title + ' closed', lambda: not window(ui, title))


def samples_roundtrip(ui, root, evidence, report):
    keys = Keyboard(ui)
    # This is the existing native File menu command, not backend state injection.
    # The separate workflow regression gate exercises the menu pointer itself.
    ui.post(ui.main, 0x0111, 302)
    ui.wait('bundled Starter graph loaded', lambda: 'Starter example' in ui.label(ui.child(101)))
    button(ui, ui.main, 424)
    title, editor_title = 'Samples · Native Workbench', 'Sample table editor · Native Workbench'
    ui.wait('Samples opened', lambda: window(ui, title))
    samples = window(ui, title)
    button(ui, samples, 815)
    ui.wait('new native table editor', lambda: window(ui, editor_title))
    owner = window(ui, editor_title)
    grid = NativeList(ui, ui.child(1601, owner))
    ui.wait('new blank row', lambda: grid.count() == 1 and ui.user.IsWindowEnabled(ui.child(1603, owner)))
    require(combo_choices(ui, ui.child(1602, owner)) == ['sample_id', 'read1', 'read2', 'reference'],
            'New table did not offer the documented editable columns.')

    def cell(column, value, row=0):
        grid.click(row)
        choose(ui, keys, ui.child(1602, owner), column)
        edit(ui, keys, ui.child(1603, owner), value)
        index = combo_choices(ui, ui.child(1602, owner)).index(column)
        ui.wait('complete edited cell retained', lambda: grid.text(row, index) == value)

    fixture = root / 'examples/starter'
    values = {'sample_id': 'nativeCreated', 'read1': str(fixture / 'reads1.fastq'),
              'read2': str(fixture / 'reads2.fastq'), 'reference': str(fixture / 'reference.fa')}
    for column, value in values.items():
        cell(column, value)
    button(ui, owner, 1608)
    ui.wait('second editable row added', lambda: grid.count() == 2)
    cell('sample_id', 'temporaryRow', 1)
    button(ui, owner, 1609)
    confirm(ui, 'Remove sample row')
    ui.wait('row removed without altering retained row', lambda: grid.count() == 1 and grid.text(0) == 'nativeCreated')
    button(ui, owner, 1610)
    ui.wait('Add column dialog', lambda: window(ui, 'Add column'))
    modal = window(ui, 'Add column')
    edit(ui, keys, ui.child(105, modal), 'temporary_note')
    button(ui, modal, 1)
    ui.wait('new metadata column', lambda: 'temporary_note' in combo_choices(ui, ui.child(1602, owner)))
    cell('temporary_note', 'text stays text')
    button(ui, owner, 1611)
    ui.wait('Rename column dialog', lambda: window(ui, 'Rename column'))
    modal = window(ui, 'Rename column')
    edit(ui, keys, ui.child(105, modal), 'retained_note')
    button(ui, modal, 1)
    ui.wait('renamed metadata preserves value', lambda: combo_choices(ui, ui.child(1602, owner))[-1] == 'retained_note'
            and grid.text(0, 4) == 'text stays text')
    button(ui, owner, 1612)
    confirm(ui, 'Remove sample column')
    ui.wait('temporary metadata removed', lambda: len(combo_choices(ui, ui.child(1602, owner))) == 4)
    visible_capture(ui, report, 'samples-created-edited-table', owner)

    destination = evidence / 'saved table with spaces.tsv'
    button(ui, owner, 1613)
    picker_title = 'Save a new sample table'
    with ui.common_dialog(picker_title):
        ui.wait('native Save As cancellation picker', lambda: window(ui, picker_title))
        keys.key(0x1B)
        ui.wait('native Save As cancelled', lambda: not window(ui, picker_title))
    require(grid.count() == 1 and grid.text(0) == 'nativeCreated' and not destination.exists(),
            'Cancelling Save As lost the complete editor draft or wrote the target.')
    button(ui, owner, 1613)
    with ui.common_dialog(picker_title):
        ui.wait('native Save As picker', lambda: window(ui, picker_title))
        picker = window(ui, picker_title)
        keys.key(0x4E, 0x12)  # Alt+N: documented File name field shortcut.
        filename = keys.focus()
        require(ui.label(filename, True).lower() == 'edit', 'Save As did not focus its native filename edit.')
        clear_focused_edit(ui, keys, filename)
        keys.text(str(destination))
        ui.wait('actual selected save filename', lambda: ui.label(filename) == str(destination))
        button(ui, picker, 1)
        ui.wait('complete new table saved', lambda: not window(ui, picker_title) and destination.is_file()
                and 'Saved as a new table' in ui.label(ui.child(1616, owner)))
    with destination.open(encoding='utf-8-sig', newline='') as stream:
        saved = list(csv.DictReader(stream, delimiter='\t'))
    require(saved == [values], 'Saved TSV differs from the complete edited table.')
    saved_hash = sha256(destination)
    report['savedNativeTable'] = {'path': destination.name, 'sha256': saved_hash,
                                  'rows': saved, 'realNativeSaveAs': True}
    button(ui, owner, 1614)
    ui.wait('Use table returns to Samples', lambda: not window(ui, editor_title))
    rows = NativeList(ui, ui.child(808, samples))
    ui.wait('used complete native row', lambda: rows.count() == 1 and rows.text(0) == 'nativeCreated')
    button(ui, samples, 813)
    ui.wait('Samples closed', lambda: not window(ui, title))
    button(ui, ui.main, 424)
    ui.wait('Samples reopened', lambda: window(ui, title))
    samples = window(ui, title)
    edit(ui, keys, ui.child(801, samples), str(destination))
    button(ui, samples, 803)
    rows = NativeList(ui, ui.child(808, samples))
    ui.wait('saved table reopened through import', lambda: rows.count() == 1 and rows.text(0) == 'nativeCreated'
            and ui.user.IsWindowEnabled(ui.child(816, samples)))
    passed(report, 'samples-create-edit-save-reopen',
           'Native row/cell/column add, rename and remove roundtrip through the real Save As picker and reloads the exact complete TSV.')

    button(ui, samples, 816)
    ui.wait('existing table editor', lambda: window(ui, editor_title))
    owner = window(ui, editor_title)
    grid = NativeList(ui, ui.child(1601, owner))
    ui.wait('full imported editor row', lambda: grid.count() == 1 and grid.text(0) == 'nativeCreated')
    cell('sample_id', 'discardThisChange')
    button(ui, owner, 1615)
    confirm(ui, 'Discard sample table changes')
    ui.wait('cancelled editor closed', lambda: not window(ui, editor_title))
    require(rows.count() == 1 and rows.text(0) == 'nativeCreated' and sha256(destination) == saved_hash,
            'Cancelling an edited draft modified imported data or original saved bytes.')
    bad = evidence / 'invalid-samples.csv'
    bad.write_bytes(b'sample_id,read1\nduplicate,a\nduplicate,b\n')
    edit(ui, keys, ui.child(801, samples), str(bad))
    button(ui, samples, 803)
    with ui.common_dialog('Native Workbench'):
        ui.wait('failed sample import message', lambda: window(ui, 'Native Workbench'))
        failure = window(ui, 'Native Workbench')
        report['rejectedImportMessage'] = '\n'.join(row['text'] for row in ui.controls(failure))
        require(any(word in report['rejectedImportMessage'].lower() for word in ('duplicate', 'unique')),
                'Import did not explain the deliberately duplicated sample identity.')
        visible_capture(ui, report, 'samples-invalid-import', failure)
        pointer_click(ui, unique_button(ui, failure, 'OK'))
        ui.wait('failed import returns to existing table', lambda: not window(ui, 'Native Workbench')
                and ui.user.IsWindowEnabled(ui.child(816, samples)))
    require(rows.count() == 1 and rows.text(0) == 'nativeCreated' and sha256(destination) == saved_hash,
            'Failed sample import discarded the previously loaded table or changed its source bytes.')
    passed(report, 'samples-cancel-and-invalid-import',
           'Discarding edited draft changes and rejecting a duplicate-ID import retain the loaded row and original saved file bytes.')

    button(ui, samples, 817)
    ui.wait('packaged synthetic example editor', lambda: window(ui, editor_title))
    owner = window(ui, editor_title)
    grid = NativeList(ui, ui.child(1601, owner))
    ui.wait('complete synthetic sample row', lambda: grid.count() == 1 and grid.text(0) == 'starter')
    require('synthetic' in '\n'.join(row['text'] for row in ui.controls(owner)).lower(),
            'Example editor lacks its synthetic-training explanation.')
    require([grid.text(0, n) for n in range(1, 4)] == [str(fixture / name) for name in ('reads1.fastq', 'reads2.fastq', 'reference.fa')],
            'Example row does not refer to the bundled exact Starter data.')
    visible_capture(ui, report, 'samples-bundled-example', owner)
    button(ui, owner, 1614)
    ui.wait('synthetic table applied', lambda: not window(ui, editor_title) and rows.count() == 1 and rows.text(0) == 'starter')
    targets = NativeList(ui, ui.child(804, samples))
    ui.wait('sample input mapping targets', lambda: targets.count() >= 3)
    labels = [targets.text(index) for index in range(targets.count())]
    report['exampleMappingTargets'] = labels
    for fragment, column in [('read1', 'read1'), ('read2', 'read2'), ('reference', 'reference'), ('step-1 · Sample name', 'sample_id')]:
        choices = [index for index, text in enumerate(labels) if fragment.lower() in text.lower()]
        require(len(choices) == 1, 'Ambiguous native sample mapping: ' + fragment + ' / ' + str(labels))
        targets.click(choices[0])
        choose(ui, keys, ui.child(805, samples), column)
        ui.wait('explicit sample column mapping', lambda: targets.text(choices[0], 1) == column)
    output = evidence / 'native sample results'
    output.mkdir()
    edit(ui, keys, ui.child(810, samples), str(output))
    button(ui, samples, 807)
    ui.wait('reviewed one-sample native batch valid', lambda: rows.count() == 1 and rows.text(0, 1) == 'Valid'
            and ui.user.IsWindowEnabled(ui.child(812, samples)))
    require(not list(output.iterdir()), 'Preview created a run before explicit Queue.')
    visible_capture(ui, report, 'samples-example-preview', samples)
    passed(report, 'samples-example-preview',
           'Included one-sample synthetic table matches packaged data and previews valid only after explicit read/reference/sample mappings, without executing.')
    queue_path = root / 'user-data/run-queue.json'
    previous = {row['job_id'] for row in json.loads(queue_path.read_text()).get('jobs', [])} if queue_path.exists() else set()
    button(ui, samples, 812)
    queue_title = 'Analysis queue · Native Workbench'
    ui.wait('native queue opens', lambda: window(ui, queue_title))
    queue = window(ui, queue_title)

    def added_job():
        jobs = [job for job in json.loads(queue_path.read_text())['jobs'] if job['job_id'] not in previous] if queue_path.exists() else []
        return jobs[0] if len(jobs) == 1 and jobs[0]['status'] != 'preparing' else None

    ui.wait('one sample frozen but paused', lambda: added_job() is not None)
    job = added_job()
    require(job['status'] == 'queued' and not (Path(job['folder']) / 'run.json').exists(),
            'Native sample was started before the explicit Start queued action.')
    button(ui, queue, 904)
    ui.wait('native sample scientific workflow completed', lambda: added_job()['status'] in
            ('completed', 'failed', 'cancelled', 'interrupted'), seconds=240)
    job = added_job()
    report['nativeSampleScience'] = scientific_truth(root, job)
    plan = json.loads((Path(job['folder']) / 'plan.json').read_text())
    record = json.loads((Path(job['folder']) / 'run.json').read_text())
    require(plan['batch']['sampleId'] == 'starter' and record['batch'] == plan['batch'],
            'Native example sample identity was not frozen into execution provenance.')
    sam = Path(record['outputs']['step-1::sam']['files']['sam']).read_text()
    require(any('SM:starter' in line for line in sam.splitlines() if line.startswith('@RG')),
            'Explicit native sample name mapping did not reach the actual alignment.')
    listing = NativeList(ui, ui.child(901, queue))
    ui.wait('native queue completion and idle controls', lambda:
            listing.count() == 1 and listing.text(0, 2) == 'completed' and
            '1 completed.' in ui.label(ui.child(908, queue)) and
            ui.user.IsWindowEnabled(ui.child(113)) and not ui.user.IsWindowEnabled(ui.child(114)))
    report['nativeQueueCompletion'] = {'rowStatus': listing.text(0, 2),
        'notice': ui.label(ui.child(908, queue)),
        'runEnabled': bool(ui.user.IsWindowEnabled(ui.child(113))),
        'cancelEnabled': bool(ui.user.IsWindowEnabled(ui.child(114)))}
    report['nativeSampleScience']['sampleId'] = 'starter'
    visible_capture(ui, report, 'samples-example-completed', queue)
    passed(report, 'samples-example-native-science',
           'Explicit Queue then Start produces 202 proper-pair alignments and the known starter:1351 G>A homozygous SNP with sample/CWL/output provenance.')
    button(ui, queue, 909)
    ui.wait('native Queue closed', lambda: not window(ui, queue_title))
    button(ui, samples, 813)
    ui.wait('Samples closed after scientific check', lambda: not window(ui, title))


def run(args, report):
    require(os.name == 'nt', 'Native Windows unavailable; this gate cannot pass here.')
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(),
            'Run using the exact extracted Starter private interpreter.')
    require(sha256(args.starter_archive) == args.starter_sha256, 'Wrong exact Starter archive.')
    report['archive'] = {'name': args.starter_archive.name, 'sha256': args.starter_sha256,
                         'bytes': args.starter_archive.stat().st_size,
                         'extractedFilesVerified': verify_extracted(args.starter_archive, root)}
    report['appVersion'] = json.loads((root / 'manifest.json').read_text())['version']
    require(report['appVersion'] == args.app_version, 'Unexpected candidate application version.')
    original_core = {name: sha256(root / name) for name in ('NativeWorkbench.exe', 'WorkbenchBridge.exe')}
    ui = prepare_desktop(root, evidence, report)
    with observed_desktop(ui, report, 'feedback'):
        samples_blank_access(ui, report)
        run_button_observations(ui, report)
        tree_real_categories(ui, report)
        methods_and_missing_input(ui, report)
        samples_roundtrip(ui, root, evidence, report)
    import_overflow(root, evidence, report)
    ui = prepare_desktop(root, evidence, report)
    with observed_desktop(ui, report, 'overflow'):
        tree_overflow(ui, report)
    require({name: sha256(root / name) for name in original_core} == original_core,
            'Gate modified packaged application executables.')
    report['archive']['postGateExtractedFilesVerified'] = verify_extracted(args.starter_archive, root)
    report['nativeGUIObservationsCompleted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app-root', 'starter-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--gate-commit')
    parser.add_argument('--starter-sha256', '--asset-sha256', dest='starter_sha256', required=True)
    parser.add_argument('--asset-name')
    parser.add_argument('--app-version', default='0.16.1')
    args = parser.parse_args()
    args.gate_commit = args.gate_commit or args.source_commit
    if args.asset_name:
        require(args.asset_name == args.starter_archive.name, 'Declared asset name differs from exact archive.')
    validate_identities(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'tester-feedback-native', 'sourceCommit': args.source_commit,
              'gateCommit': args.gate_commit, 'gateSha256': sha256(__file__),
              'platform': platform.platform(), 'startedUtc': utc(), 'checks': [], 'scenarios': [],
              'captures': [], 'skips': [], 'limits': LIMITS,
              'nativeWindowsExecuted': False, 'nativeGUILaunched': False,
              'nativeGUIValidated': False, 'nativeGUIObservationsCompleted': False, 'success': False}
    report['helperSha256'] = {name: sha256(Path(__file__).parent / name) for name in (
        'check_batch_windows.py', 'check_deployment_ui_windows.py', 'check_references_windows.py',
        'check_scroll_frames_windows.py', 'check_ui_patch_windows.py',
        'check_workspace_ui_windows.py', 'native_tree.py')}
    try:
        run(args, report)
    except Exception as error:
        failed(report, 'gate-completion', str(error))
        report['failure'], report['traceback'] = str(error), traceback.format_exc()
    finally:
        report['finishedUtc'] = utc()
        finalize_report(report)
        write_json(args.report, report)
    print(json.dumps({'success': report['success'], 'passed': report['passed'],
                      'failed': report['failed'], 'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
