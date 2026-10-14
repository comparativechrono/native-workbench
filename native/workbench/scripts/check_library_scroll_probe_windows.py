#!/usr/bin/env python3
"""Diagnose native integral-row scrolling on one exact disposable Starter.

This is an observation probe, not an acceptance gate. Documented native scroll
messages and pointer input inspect whether the TreeView can expose the inside
of a row taller than its client area. No row/layout mutation or paint repair.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_deployment_ui_windows import utc, verify_extracted
from check_references_windows import require, sha256, write_json
from check_tester_feedback_windows import observed_desktop, prepare_desktop, validate_identities, visible_capture
from check_wrapped_library_windows import (Rows, TextReference, client_box, filter_to, import_fixture,
    TOKEN_NAME, TOKEN_DESCRIPTION, LONG_NAME, LONG_DESCRIPTION)


def scrollbar(ui, tree):
    class ScrollBarInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcScrollBar', wintypes.RECT),
                    ('dxyLineButton', ctypes.c_int), ('xyThumbTop', ctypes.c_int),
                    ('xyThumbBottom', ctypes.c_int), ('reserved', ctypes.c_int),
                    ('rgstate', wintypes.DWORD * 6)]
    ui.user.GetScrollBarInfo.argtypes = [wintypes.HWND, wintypes.LONG, ctypes.POINTER(ScrollBarInfo)]
    value = ScrollBarInfo()
    value.cbSize = ctypes.sizeof(value)
    require(ui.user.GetScrollBarInfo(tree.hwnd, -5, ctypes.byref(value)), 'Cannot inspect native vertical scrollbar.')
    box = value.rcScrollBar
    return {'bounds': [box.left, box.top, box.right, box.bottom],
            'lineButton': value.dxyLineButton, 'thumbTop': value.xyThumbTop,
            'thumbBottom': value.xyThumbBottom, 'states': list(value.rgstate)}


def snapshot(ui, tree, item, group, name):
    time.sleep(.15)  # Observe normal completion; never ask the application to repaint.
    row = {'action': name, 'scrollInfo': ui.scroll_info(tree.hwnd),
           'client': client_box(ui, tree.hwnd), 'firstVisible': tree.next(0, 5),
           'selected': tree.selected(), 'targetHandle': item, 'scrollbar': scrollbar(ui, tree)}
    try:
        row['targetRow'] = tree.rect(item, False)
        row['targetTextRect'] = tree.rect(item)
        top = row['targetRow'][1] + group['contentTopOffset']
        bottom = row['targetRow'][1] + group['contentBottomOffset']
        row['targetContent'] = [top, bottom]
        row['firstLineFullyVisible'] = row['client'][1] <= top and top + group['titleLineHeight'] <= row['client'][3]
        row['lastLineFullyVisible'] = row['client'][1] <= bottom - group['descriptionLineHeight'] and bottom <= row['client'][3]
    except Exception as error:
        row['rowQueryError'] = str(error)
    group['observations'].append(row)
    print(json.dumps({'probe': group['name'], 'action': name,
                      'position': row['scrollInfo']['nPos'], 'row': row.get('targetRow'),
                      'firstVisible': row['firstVisible'], 'lastLineVisible': row.get('lastLineFullyVisible')}), flush=True)
    return row


def observe_action(ui, tree, item, group, name, action):
    try:
        action()
        return snapshot(ui, tree, item, group, name)
    except Exception as error:
        # A failed pointer hit or query is evidence, never permission to inject
        # a click behind an overlay or to treat missing data as a passed check.
        group.setdefault('actionErrors', []).append({'action': name, 'error': str(error),
                                                     'traceback': traceback.format_exc()})
        return None


def probe_case(ui, tree, reference, report, name, query, title, description):
    filter_to(ui, tree, query)
    require(len(tree.tools()) == 1, 'Probe requires exactly one filtered native tool.')
    item = tree.tools()[0]
    ui.user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    ui.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    ui.user.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    dpi = ui.user.GetDpiForWindow(tree.hwnd)
    px = lambda value: round(value * dpi / 96)
    client = client_box(ui, tree.hwnd)
    width = client[2] - client[0] - ui.send(tree.hwnd, 0x1106) * 2 - px(4) - px(6)
    if not ui.user.GetWindowLongPtrW(tree.hwnd, -16) & 0x00200000:
        width -= ui.user.GetSystemMetricsForDpi(2, dpi)
    title_lines = reference.lines(title, width, 700)
    description_lines = reference.lines(description, width, 400)
    group = {'name': name, 'title': title, 'descriptionCharacters': len(description),
        'observations': [], 'dpi': dpi, 'textWidth': width, 'titleLines': len(title_lines),
        'descriptionLines': len(description_lines), 'titleLineHeight': reference.line_heights[700],
        'descriptionLineHeight': reference.line_heights[400], 'contentTopOffset': px(6),
        'contentBottomOffset': px(6) + len(title_lines) * reference.line_heights[700] + px(3) +
            len(description_lines) * reference.line_heights[400]}
    report['cases'].append(group)
    send = lambda command, position=0: ui.send(tree.hwnd, 0x0115, command | (position << 16))
    observe_action(ui, tree, item, group, 'WM_VSCROLL SB_TOP initial', lambda: send(6))
    visible_capture(ui, report, name + '-initial')
    point = (client[0] + 30, client[1] + 40)
    for number, delta in enumerate([-120, -120, -120, 120]):
        observe_action(ui, tree, item, group, 'real wheel %d delta %d' % (number, delta), lambda delta=delta: ui.wheel(*point, delta))
    for label, command in [('SB_TOP', 6), ('SB_LINEDOWN first', 1), ('SB_LINEDOWN second', 1),
                           ('SB_LINEUP', 0), ('SB_PAGEDOWN', 3), ('SB_PAGEUP', 2), ('SB_BOTTOM', 7)]:
        observe_action(ui, tree, item, group, 'WM_VSCROLL ' + label, lambda command=command: send(command))
    state = ui.scroll_info(tree.hwnd)
    maximum = max(state['nMin'], state['nMax'] - state['nPage'] + 1)
    require(maximum <= 65535, 'Diagnostic thumb positions exceed documented WM_VSCROLL message range.')
    targets = sorted({min(maximum, state['nMin'] + step) for step in (1, 2)} | {maximum // 2, maximum})
    for target in targets:
        observe_action(ui, tree, item, group, 'reset SB_TOP before thumb %d' % target, lambda: send(6))
        observe_action(ui, tree, item, group, 'SB_THUMBTRACK %d' % target, lambda target=target: send(5, target))
        observe_action(ui, tree, item, group, 'SB_THUMBPOSITION %d' % target, lambda target=target: send(4, target))
        observe_action(ui, tree, item, group, 'SB_ENDSCROLL after thumb %d' % target, lambda: send(8))
    ui.user.SetScrollInfo.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.POINTER(ui.ScrollInfo), wintypes.BOOL]
    for target in targets:
        send(6)
        value = ui.ScrollInfo()
        value.cbSize, value.fMask, value.nPos = ctypes.sizeof(value), 0x4, target
        observe_action(ui, tree, item, group, 'SetScrollInfo SIF_POS %d no repaint' % target,
                       lambda value=value: ui.user.SetScrollInfo(tree.hwnd, 1, ctypes.byref(value), False))
        observe_action(ui, tree, item, group, 'SB_THUMBPOSITION after SetScrollInfo %d' % target,
                       lambda target=target: send(4, target))
    # Actual scrollbar pointer actions use observed native geometry and the
    # existing foreground/ownership hit guard. They are not synthetic WM_NOTIFY.
    send(6)
    bar = scrollbar(ui, tree)
    left, top, right, bottom = bar['bounds']
    if right > left and bottom > top and not bar['states'][0] & (0x8000 | 0x10000):
        x = (left + right) // 2
        arrow = (x, bottom - max(2, bar['lineButton'] // 2))
        observe_action(ui, tree, item, group, 'real scrollbar down arrow', lambda: ui.click_at(*arrow, expected=tree.hwnd))
        bar = scrollbar(ui, tree)
        page_top, page_bottom = top + bar['thumbBottom'] + 2, bottom - bar['lineButton'] - 2
        if page_bottom > page_top:
            observe_action(ui, tree, item, group, 'real scrollbar page down',
                           lambda: ui.click_at(x, (page_top + page_bottom) // 2, expected=tree.hwnd))
        send(6)
        bar = scrollbar(ui, tree)
        start = (x, top + (bar['thumbTop'] + bar['thumbBottom']) // 2)
        finish = (x, bottom - bar['lineButton'] - max(2, (bar['thumbBottom'] - bar['thumbTop']) // 2))
        def drag_thumb():
            hit = ui.user.WindowFromPoint(wintypes.POINT(*start))
            owner = wintypes.DWORD()
            ui.user.GetWindowThreadProcessId(hit, ctypes.byref(owner))
            area = ui.work_area()
            require(owner.value == ui.process.pid and (hit == tree.hwnd or ui.user.IsChild(tree.hwnd, hit)) and
                    area[0] <= start[0] < area[2] and area[1] <= start[1] < area[3] and
                    area[0] <= finish[0] < area[2] and area[1] <= finish[1] < area[3],
                    'Observed scrollbar drag target is not an unobscured application surface.')
            ui.drag(start, finish)
        observe_action(ui, tree, item, group, 'real scrollbar thumb drag to bottom', drag_thumb)
    else:
        group['pointerScrollbarUnavailable'] = bar
    snapshot(ui, tree, item, group, 'final native state')
    visible_capture(ui, report, name + '-final')
    group['observationsComplete'] = True


def run(args, report):
    require(os.name == 'nt', 'Native Windows is required for this diagnostic.')
    root = args.app_root.resolve()
    require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(), 'Use the exact packaged private Python.')
    require(sha256(args.starter_archive) == args.starter_sha256, 'Wrong exact Starter archive.')
    report['archive'] = {'name': args.starter_archive.name, 'sha256': args.starter_sha256,
        'bytes': args.starter_archive.stat().st_size, 'extractedFilesVerified': verify_extracted(args.starter_archive, root)}
    require(json.loads((root / 'manifest.json').read_text())['version'] == args.app_version, 'Wrong application version.')
    evidence = args.report.resolve().parent
    import_fixture(root, evidence, report)
    ui = prepare_desktop(root, evidence, report)
    with observed_desktop(ui, report, 'scroll-probe'):
        reference = None
        try:
            ui.fit_window(1024, 728)
            tree = Rows(ui.user, ui.send, ui.process.pid, ui.child(104))
            reference = TextReference(ui, tree.hwnd)
            probe_case(ui, tree, reference, report, 'oversized-token', 'BoundaryToken', TOKEN_NAME, TOKEN_DESCRIPTION)
            probe_case(ui, tree, reference, report, 'maximum-description', 'FINAL LONG DESCRIPTION ANSWER', LONG_NAME, LONG_DESCRIPTION)
            visible_capture(ui, report, 'scroll-probe-final-desktop')
        finally:
            if reference is not None:
                reference.close()
    report['archive']['postProbeExtractedFilesVerified'] = verify_extracted(args.starter_archive, root)
    report['diagnosticCompleted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app-root', 'starter-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('source-commit', 'gate-commit', 'starter-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--app-version', default='0.16.1')
    args = parser.parse_args()
    validate_identities(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'integral-row-scroll-diagnostic-not-acceptance',
        'sourceCommit': args.source_commit, 'gateCommit': args.gate_commit, 'gateSha256': sha256(__file__),
        'platform': platform.platform(), 'startedUtc': utc(), 'cases': [], 'captures': [],
        'nativeWindowsExecuted': False, 'nativeGUILaunched': False, 'nativeGUIValidated': False,
        'diagnosticCompleted': False, 'success': False,
        'limits': ['Observation of documented scroll messages and actual pointer input on one disposable frozen application.',
                   'Diagnostic completion is not acceptance; no typography or usability pass is assigned.',
                   'No source, row height, row contents, layout or application paint repair is changed by this probe.']}
    report['helperSha256'] = {name: sha256(Path(__file__).parent / name) for name in (
        'check_wrapped_library_windows.py', 'check_tester_feedback_windows.py',
        'check_workspace_ui_windows.py', 'native_tree.py')}
    try:
        run(args, report)
    except Exception as error:
        report.update(failure=str(error), traceback=traceback.format_exc())
    finally:
        report['success'] = report['diagnosticCompleted']
        report['nativeGUIValidated'] = False
        report['finishedUtc'] = utc()
        write_json(args.report, report)
    print(json.dumps({'diagnosticCompleted': report['diagnosticCompleted'], 'nativeGUIValidated': False,
                      'report': str(args.report)}), flush=True)
    return 0 if report['diagnosticCompleted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
