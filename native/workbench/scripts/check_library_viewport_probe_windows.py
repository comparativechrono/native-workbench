#!/usr/bin/env python3
"""Diagnose a frozen native library viewport without assigning acceptance.

First replay actual overflow-category clicks and wheel input, preserving the
first failed geometry and displayed pixels. Only then run explicitly labelled
native first-visible/redraw/style experiments in this disposable process.
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
from check_tester_feedback_windows import (import_overflow, observed_desktop,
    prepare_desktop, triangle_point, validate_identities, visible_capture)
from check_wrapped_library_windows import Rows


def inventory(tree):
    rows, top = [], 0
    for root in tree.roots():
        for item in [root] + (tree.children(root) if tree.expanded(root) else []):
            height = tree.item_height(item)
            rows.append({'handle': item, 'label': tree.label(item), 'globalTop': top,
                         'height': height, 'category': item == root})
            top += height
    return rows


def snapshot(ui, tree, report, name, rows, *, experiment=False):
    """Only query raw rectangles; never call visible_bounds or EnsureVisible."""
    child, parent = tree.client_bounds(), tree.client_bounds(tree.viewport())
    state = ui.scroll_info(tree.viewport())
    value = {'action': name, 'diagnosticMutation': experiment,
             'treeClient': child, 'viewportClient': parent,
             'treeWindow': ui.bounds(tree.hwnd), 'viewportWindow': ui.bounds(tree.viewport()),
             'treeStyle': ui.user.GetWindowLongPtrW(tree.hwnd, -16),
             'treeVisible': bool(ui.user.IsWindowVisible(tree.hwnd)),
             'scrollInfo': state, 'nativeFirstVisible': tree.next(0, 5),
             'selected': tree.selected(), 'rows': [],
             'intersectionExists': max(child[0], parent[0]) < min(child[2], parent[2]) and
                                   max(child[1], parent[1]) < min(child[3], parent[3]),
             'childCoversViewport': child[0] <= parent[0] and child[1] <= parent[1] and
                                    child[2] >= parent[2] and child[3] >= parent[3]}
    candidates = [row for row in rows if row['globalTop'] <= state['nPos']]
    value['expectedAnchor'] = candidates[-1]['handle'] if candidates else 0
    for row in rows:
        result = {'handle': row['handle'], 'globalTop': row['globalTop']}
        for key, text in [('fullRow', False), ('textRow', True)]:
            try:
                result[key] = tree.rect(row['handle'], text)
            except Exception as error:
                result[key + 'Error'] = str(error)
        value['rows'].append(result)
    report.setdefault('observations', []).append(value)
    print(json.dumps({key: value[key] for key in ('action', 'diagnosticMutation', 'treeClient',
        'viewportClient', 'scrollInfo', 'nativeFirstVisible', 'selected', 'expectedAnchor',
        'intersectionExists', 'childCoversViewport')}), flush=True)
    return value


def replay(ui, tree, report):
    ui.fit_window(960, 680)
    time.sleep(.3)
    roots = tree.roots()
    first = next(item for item in roots if tree.label(item) == 'Gate overflow first')
    tail = next(item for item in roots if tree.label(item) == 'ZZ gate overflow tail')
    preceding = next(item for item in roots[:roots.index(first)] if len(tree.children(item)) >= 3)
    require(not any(tree.expanded(item) for item in roots),
            'Fresh overflow diagnostic must start with collapsed categories.')
    rows = inventory(tree)
    report['inventories'] = [{'phase': 'collapsed', 'rows': rows}]
    snapshot(ui, tree, report, 'collapsed baseline', rows)
    box = tree.visible_bounds()
    for _ in range(35):
        ui.wheel(box[0] + 30, box[1] + 40, 120)
    for name, item in [('tail', tail), ('preceding', preceding)]:
        ui.click_at(*triangle_point(ui, tree, item), expected=tree.hwnd)
        ui.wait('probe expanded ' + name, lambda item=item: tree.expanded(item))
        rows = inventory(tree)
        report['inventories'].append({'phase': 'expanded ' + name, 'rows': rows})
        snapshot(ui, tree, report, 'real triangle expanded ' + name, rows)
    visible_capture(ui, report, 'viewport-before-wheel')
    report['replay'] = {'target': first, 'preceding': preceding, 'tail': tail,
                        'blankReproduced': False, 'headingReached': False}
    # Match the failing gate's actual wheel loop, but inspect the raw geometry
    # after every event so an empty intersection does not destroy the evidence.
    box = tree.visible_bounds()
    for step in range(100):
        state = snapshot(ui, tree, report, 'before real wheel %d' % step, rows)
        if not state['intersectionExists']:
            report['replay'].update(blankReproduced=True, firstFailureObservation=len(report['observations']) - 1)
            visible_capture(ui, report, 'viewport-first-blank-before-experiments')
            return rows, state
        rectangle = tree.rect(first)
        center = (rectangle[1] + rectangle[3]) // 2
        if box[1] + 4 < center < box[3] - 4:
            report['replay']['headingReached'] = True
            visible_capture(ui, report, 'viewport-heading-reached')
            return rows, state
        ui.wheel(box[0] + 30, box[1] + 40, 120 if center <= box[1] + 4 else -120)
        time.sleep(.05)
    state = snapshot(ui, tree, report, 'wheel limit reached', rows)
    report['replay']['wheelLimitReached'] = True
    visible_capture(ui, report, 'viewport-wheel-limit')
    return rows, state


def experiments(ui, tree, report, rows, failure):
    """Mutations below are diagnostic only, after the immutable failure capture."""
    original_style = ui.user.GetWindowLongPtrW(tree.hwnd, -16)
    ui.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    ui.user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    selected = failure['selected']
    anchor = failure['expectedAnchor']
    alternate = next((row['handle'] for row in rows if row['handle'] not in (anchor, selected)), 0)
    targets = [('expected anchor', anchor), ('selected item', selected), ('other unselected item', alternate)]
    report['experiments'] = []
    report['experimentDesign'] = ('Ordered stateful native-message observations, not isolated factorial trials. '
        'Each result refers only to its immediately preceding and following snapshots; '
        'an already-positioned target cannot establish that a message moved the native origin.')
    for no_scroll in (True, False):
        for redraw in (True, False):
            prefix = 'NOSCROLL=%s redraw=%s' % (no_scroll, redraw)
            try:
                # Explicitly vary only the documented TreeView style and
                # redraw contract. No app source, item text or height changes.
                style = original_style | 0x2000 if no_scroll else original_style & ~0x2000
                ui.user.SetWindowLongPtrW(tree.hwnd, -16, style)
                ui.send(tree.hwnd, 0x000B, int(redraw))  # WM_SETREDRAW.
                snapshot(ui, tree, report, prefix + ' before messages', rows, experiment=True)
                for label, item in targets:
                    if not item:
                        continue
                    before = len(report['observations']) - 1
                    outcome = ui.send(tree.hwnd, 0x110B, 5, item)  # TVM_SELECTITEM/TVGN_FIRSTVISIBLE.
                    snapshot(ui, tree, report, prefix + ' FIRSTVISIBLE ' + label, rows, experiment=True)
                    report['experiments'].append({'styleNoScroll': no_scroll, 'redraw': redraw,
                        'targetKind': label, 'target': item, 'nativeReturn': outcome,
                        'beforeObservation': before, 'afterObservation': len(report['observations']) - 1})
                ui.send(tree.hwnd, 0x000B, 1)
                snapshot(ui, tree, report, prefix + ' after redraw enabled', rows, experiment=True)
            finally:
                ui.send(tree.hwnd, 0x000B, 1)
                ui.user.SetWindowLongPtrW(tree.hwnd, -16, original_style)
                snapshot(ui, tree, report, prefix + ' after original style restored', rows, experiment=True)
    report['experimentsCompleted'] = True


def run(args, report):
    require(os.name == 'nt', 'Native Windows is required for this diagnostic.')
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(),
            'Use the exact packaged private Python.')
    require(sha256(args.starter_archive) == args.starter_sha256, 'Wrong exact Starter archive.')
    report['archive'] = {'name': args.starter_archive.name, 'sha256': args.starter_sha256,
        'bytes': args.starter_archive.stat().st_size, 'extractedFilesVerified': verify_extracted(args.starter_archive, root)}
    require(json.loads((root / 'manifest.json').read_text())['version'] == args.app_version,
            'Wrong application version.')
    import_overflow(root, evidence, report)
    ui = prepare_desktop(root, evidence, report)
    with observed_desktop(ui, report, 'viewport-probe'):
        ui.user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        ui.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        tree = Rows(ui.user, ui.send, ui.process.pid, ui.child(104))
        require(tree.viewport() != tree.hwnd, 'This diagnostic requires the bounded viewport implementation.')
        rows, state = replay(ui, tree, report)
        experiments(ui, tree, report, rows, state)
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
    report = {'schema': 1, 'kind': 'native-viewport-diagnostic-not-acceptance',
        'sourceCommit': args.source_commit, 'gateCommit': args.gate_commit,
        'gateSha256': sha256(__file__), 'platform': platform.platform(), 'startedUtc': utc(),
        'captures': [], 'nativeWindowsExecuted': False, 'nativeGUILaunched': False,
        'nativeGUIValidated': False, 'diagnosticCompleted': False, 'success': False,
        'limits': ['A frozen exact application is observed through actual category clicks and wheel input.',
                   'The first failure screenshot precedes all diagnostic style/redraw/first-visible mutations.',
                   'Native message experiments are diagnostic only; completion is not GUI acceptance.',
                   'No application bytes, catalogue text or item heights are modified.']}
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
    print(json.dumps({'diagnosticCompleted': report['diagnosticCompleted'],
                      'nativeGUIValidated': False, 'report': str(args.report)}), flush=True)
    return 0 if report['diagnosticCompleted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
