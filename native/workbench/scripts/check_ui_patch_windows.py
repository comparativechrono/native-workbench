#!/usr/bin/env python3
"""Exact 0.16.1 native keyboard/layout and 0.16.0 updater regression gate.

Uses unchanged packaged candidate bytes and real Windows input. The existing
published deployment gate remains separate and unchanged. No policy changes.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import threading
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_090 import extract
from build_update_0160 import verify_inventory
from apply_core_update import core_inventory
from check_references_windows import PrivateHost, require, sha256, write_json
from check_update_090_windows import read_json, preserved_files, synthetic_reference
from check_update_0160_windows import local_reference_run
from check_workspace_ui_windows import NativeUI
from check_scroll_frames_windows import DisplayFrames, visible_bytes
from check_deployment_ui_windows import (Keyboard, capture, passed, failed,
    finalize_report, focus_observation, observe_close, tree_hashes,
    tree_difference, verify_extracted, verify_preserved, unique_button,
    validate_destinations, updater_scenario, utc)

BASELINE_SHA = 'f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073'
TARGET_VERSION = '0.16.1'
LIMITS = [
    'Exact published 0.16.0 to candidate 0.16.1 update only.',
    'Synthetic local reference and saved-state fixtures, not clinical or realistic-workload acceptance.',
    'Observed hosted desktop sizes and DPI only; no high-DPI/transition, multiple-monitor or physical-trackpad acceptance.',
    'Representative PCs and institutional security/approval remain external checks.',
    'Scientific hosts deny Python socket operations, not OS-level network access.'
]


def validate_identities(args):
    for name in ('source_commit', 'gate_commit'):
        require(re.fullmatch('[0-9a-f]{40}', getattr(args, name)), 'Exact source/gate commit required.')
    for name in (('starter_sha256',) if getattr(args, 'resize_only', False)
                 else ('starter_sha256', 'update_sha256')):
        require(re.fullmatch('[0-9a-f]{64}', getattr(args, name)), 'Exact candidate archive SHA-256 required.')
    require(args.starter_sha256 != BASELINE_SHA, 'Candidate must differ from the published baseline.')


def verify_candidate_core(root, manifest):
    """Count only the validated inventory from the already verified Starter."""
    require(manifest.get('version') == TARGET_VERSION, 'Unexpected candidate target manifest.')
    inventory = core_inventory(manifest)
    verify_inventory(root, inventory.values())
    return len(inventory)


def verify_core_transaction(transaction, expected_files):
    require(transaction.get('status') == 'installed' and transaction.get('version') == TARGET_VERSION and
            type(transaction.get('files_verified')) is int and transaction['files_verified'] == expected_files and
            transaction.get('packs_changed') is False,
            'Packaged launcher did not finish a verified core update.')


def inside(inner, outer):
    return (outer[0] <= inner[0] < inner[2] <= outer[2] and
            outer[1] <= inner[1] < inner[3] <= outer[3])


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def pointer_click(ui, control):
    left, top, right, bottom = ui.bounds(control)
    ui.click_at((left + right) // 2, (top + bottom) // 2, expected=control)


def clear_focused_edit(ui, keys, control):
    """Use standard single-line Edit keys and observe selection before deletion."""
    require(keys.focus() == control and ui.user.IsWindowEnabled(control),
            'Keyboard replacement requires the already-focused available edit.')
    length = len(ui.label(control).encode('utf-16-le')) // 2
    require(length < 65536, 'Keyboard fixture exceeds EM_GETSEL packed range.')
    keys.key(0x24)  # Home.
    ui.wait('native keyboard Home places caret at start', lambda:
            keys.focus() == control and ui.send(control, 0x00B0) == 0)
    keys.key(0x23, 0x10)  # Shift+End.
    ui.wait('native keyboard selection spans edit', lambda:
            keys.focus() == control and ui.send(control, 0x00B0) == (length << 16))
    keys.key(0x08)
    ui.wait('native keyboard edit cleared', lambda:
            keys.focus() == control and not ui.label(control))
    return {'controlId': ui.user.GetDlgCtrlID(control), 'originalUtf16Length': length,
            'homeSelection': [0, 0], 'fullSelection': [0, length],
            'emptyAfterBackspace': True, 'focusRetained': True, 'pointerIntervention': False}


def retain_keyboard_focus(ui, keys, control, seconds=2.4):
    """Passively sample across the normal two-second queue-poll interval."""
    started, samples = time.monotonic(), 0
    while time.monotonic() - started < seconds:
        require(keys.focus() == control and ui.user.IsWindowEnabled(control),
                'Background activity displaced or disabled the focused control: ' +
                str(ui.user.GetDlgCtrlID(control)))
        samples += 1
        time.sleep(.02)
    return {'controlId': ui.user.GetDlgCtrlID(control), 'samples': samples,
            'durationSeconds': time.monotonic() - started,
            'focusRetained': True, 'enabledThroughoutSamples': True,
            'inputOrRefocusDuringObservation': False,
            'limit': 'Sampled observations across the normal poll interval; exact poll count is not instrumented.'}


class PatchUI(NativeUI):
    def fit_window(self, width, height):
        # NativeUI normally resizes immediately. Record real startup geometry
        # before any driver repositioning, so a driver cannot repair the defect.
        if not hasattr(self, 'initial_bounds'):
            self.initial_bounds = self.bounds(self.main)
            self.initial_work_area = self.work_area()
            return
        super().fit_window(width, height)


class ResizeFrames(DisplayFrames):
    def immediate(self):
        """First read has neither pacing nor compositor synchronization."""
        started = time.perf_counter()
        require(self.ui.gdi.BitBlt(self.memory, 0, 0, self.width, self.height,
                                  self.dc, self.rectangle[0], self.rectangle[1], 0x00CC0020),
                'Could not read immediate resize pixels.')
        require(self.ui.gdi.GdiFlush(), 'Could not finish immediate resize read.')
        self.last_read = time.perf_counter()
        return self.last_read, ctypes.string_at(self.pixels, self.size), started


def resize_pixel_state(actual, target, source):
    """A source match is evidence only where source and target visibly differ."""
    if actual == target:
        return 'target'
    if source != target and actual == source:
        return 'source-geometry'
    return 'other'


def require_resize_outcome(rows, expect_defect=False):
    """Negative control requires a specific reproduced defect and recovery."""
    require(rows and all(row['samplingComplete'] and row['targetSeen'] for row in rows),
            'Resize sampling did not complete with observed target recovery.')
    stale = sum(row['postCompositorSourceFrames'] for row in rows)
    wrong = sum(row['postCompositorNonTargetFrames'] for row in rows)
    if expect_defect:
        require(stale > 0, 'The exact old-package source-geometry defect was not reproduced.')
    else:
        require(wrong == 0, 'Displayed resize regions retained old or incomplete geometry after compositor completion.')


def resize_regions(ui, rectangle):
    """Compare static text and fixed buttons; omit carets, library and status."""
    left, top, right, bottom = rectangle
    buttons = {113, 115, 415, 416, 402, 403, 112, 414}
    result = []
    for control in ui.controls():
        if not ui.user.IsWindowVisible(control['hwnd']):
            continue
        identity, klass = control['id'], control['class']
        if not ((klass == 'Static' and identity not in (119, 430)) or
                (klass == 'Button' and identity in buttons)):
            continue
        a, b, c, d = control['bounds']
        region = [max(left + 8, a - 1), max(top + 32, b - 1),
                  min(right - 8, c + 1), min(bottom - 8, d + 1)]
        if region[2] > region[0] and region[3] > region[1]:
            result.append({'controlId': identity, 'class': klass, 'rectangle': region})
    require(len(result) >= 8, 'Too few static/control regions for visible resize evidence.')
    return result


def region_bytes(raw, canvas, rectangle):
    left, top, right, bottom = canvas
    a, b, c, d = rectangle
    require(left <= a < c <= right and top <= b < d <= bottom,
            'Resize comparison region is outside the captured desktop.')
    width = right - left
    spans = [(((y - top) * width + a - left) * 4,
              ((y - top) * width + c - left) * 4) for y in range(b, d)]
    return visible_bytes(raw, spans)


def resize_tool_pointer_ready(ui, control, point):
    """The catalogue can answer while its asynchronous tree refresh is hidden."""
    x, y = point
    hit = ui.user.WindowFromPoint(wintypes.POINT(x, y))
    owner = wintypes.DWORD()
    ui.user.GetWindowThreadProcessId(hit, ctypes.byref(owner))
    left, top, right, bottom = ui.work_area()
    return bool(ui.user.IsWindowVisible(control) and ui.user.IsWindowEnabled(control) and
                left <= x < right and top <= y < bottom and owner.value == ui.process.pid and
                (hit == control or ui.user.IsChild(control, hit)))


def resize_observation_bursts(ui, stream, references, group, save):
    """Observe during resize calls; completion is not a pixel acceptance pass."""
    canvas = group['canvas']
    client, origin = wintypes.RECT(), wintypes.POINT()
    require(ui.user.GetClientRect(ui.main, ctypes.byref(client)) and
            ui.user.ClientToScreen(ui.main, ctypes.byref(origin)),
            'Cannot determine the smaller-window client intersection.')
    intersection = [origin.x, origin.y, origin.x + client.right, origin.y + client.bottom]
    rectangles = sorted({tuple([max(r['rectangle'][0], intersection[0]),
                                max(r['rectangle'][1], intersection[1]),
                                min(r['rectangle'][2], intersection[2]),
                                min(r['rectangle'][3], intersection[3])])
                         for reference in references.values() for r in reference['record']['regions']})
    rectangles = [r for r in rectangles if r[0] < r[2] and r[1] < r[3]]
    expected = {size: tuple(region_bytes(ref['raw'], canvas, rect) for rect in rectangles)
                for size, ref in references.items()}
    require(expected[(960, 680)] != expected[(1024, 728)], 'Diagnostic endpoints are visually indistinguishable.')
    group.update(observationOnly=True, bursts=[], comparedRectangles=rectangles,
                 commonClientIntersection=intersection,
                 assertionStarts='No differential or pixel acceptance assertion in this observational mode.',
                 acquisition='Main thread owns GDI. Raw frames and timestamps only during each burst; no DwmFlush, pacing, geometry queries, hashing or file writes.',
                 observationLimit='Read intervals overlapping resize calls do not identify the exact presentation instant; normal compositor latency can produce an earlier endpoint.')
    for burst_index in range(3):
        started = time.perf_counter()
        begin, stop, done = threading.Event(), threading.Event(), threading.Event()
        calls, errors, captured = [], [], []
        row = {'burst': burst_index, 'resizeCalls': calls, 'workerErrors': errors,
               'samples': [], 'captures': [], 'workerJoined': False, 'samplingComplete': False,
               'frameLimit': 64, 'requestedPostMotionMs': 200}
        group['bursts'].append(row)
        def motion():
            previous_dpi = ui.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            try:
                require(previous_dpi, 'Cannot establish matching DPI awareness on resize worker.')
                begin.wait()
                for index, size in enumerate([(1024, 728), (960, 680)] * 6):
                    if stop.is_set():
                        break
                    call_start = time.perf_counter()
                    ok = ui.user.MoveWindow(ui.main, canvas[0], canvas[1], *size, True)
                    call_end = time.perf_counter()
                    calls.append({'index': index, 'size': list(size),
                                  'startMs': (call_start - started) * 1000,
                                  'returnMs': (call_end - started) * 1000, 'returnedSuccess': bool(ok)})
                    require(ok, 'Concurrent diagnostic resize request failed.')
            except Exception as error:
                errors.append(str(error))
            finally:
                if previous_dpi:
                    ui.user.SetThreadDpiAwarenessContext(previous_dpi)
                done.set()
        worker = threading.Thread(target=motion, name='resize-observation-motion')
        worker.start()
        try:
            stamp, raw, read_start = stream.immediate()
            captured.append((read_start, stamp, raw))
            begin.set()  # At least one capture has finished before any resize.
            while True:
                stamp, raw, read_start = stream.immediate()
                captured.append((read_start, stamp, raw))
                if done.is_set() and (errors or (calls and (stamp - started) * 1000 >= calls[-1]['returnMs'] + 200)):
                    break
                require(len(captured) < 64 and time.perf_counter() - started < 4,
                        'Concurrent diagnostic exceeded its 64-frame/four-second acquisition bound.')
        finally:
            stop.set()
            begin.set()
            worker.join(timeout=5)
            if worker.is_alive():
                # Terminating only this disposable gate-owned process releases a
                # hung cross-process MoveWindow before any later UI cleanup.
                ui.process.kill()
                worker.join(timeout=5)
            row['workerJoined'] = not worker.is_alive()
            row['acquiredFrames'] = len(captured)
            require(not worker.is_alive(), 'Resize worker did not stop before desktop cleanup.')
        require(not errors and len(calls) == 12 and all(call['returnedSuccess'] for call in calls),
                'Concurrent resize worker did not complete all twelve requests: ' + '; '.join(errors))
        saved = set()
        for index, (read_start, stamp, raw) in enumerate(captured):
            observed = tuple(region_bytes(raw, canvas, rect) for rect in rectangles)
            matched = next((list(size) for size, pixels in expected.items() if pixels == observed), None)
            start_ms, end_ms = (read_start - started) * 1000, (stamp - started) * 1000
            sample = {'index': index, 'captureStartMs': start_ms, 'captureEndMs': end_ms,
                      'matchingEndpoint': matched,
                      'overlappingResizeCallIndices': [call['index'] for call in calls
                                                      if start_ms < call['returnMs'] and end_ms > call['startMs']],
                      'startsAfterFinalReturn': start_ms >= calls[-1]['returnMs']}
            row['samples'].append(sample)
            digest = hashlib.sha256(b''.join(observed)).hexdigest()
            if index in (0, len(captured) - 1) or (matched is None and digest not in saved and len(saved) < 12):
                saved.add(digest)
                row['captures'].append(save(raw, '%s-resize-diagnostic-%02d-frame-%03d' %
                                             (group['installation'], burst_index, index)))
        after = [sample for sample in row['samples'] if sample['startsAfterFinalReturn'] and
                 sample['matchingEndpoint'] == [960, 680]]
        row.update(samplingComplete=True, frames=len(captured),
                   totalReadIntervalMs=(captured[-1][1] - captured[0][0]) * 1000,
                   elapsedPostMotionMs=(captured[-1][1] - started) * 1000 - calls[-1]['returnMs'],
                   capturesOverlappingResizeCalls=sum(bool(s['overlappingResizeCallIndices']) for s in row['samples']),
                   framesMatchingNeitherEndpoint=sum(s['matchingEndpoint'] is None for s in row['samples']),
                   firstFinalTargetReadIntervalMsAfterReturn=([after[0]['captureStartMs'] - calls[-1]['returnMs'],
                                                              after[0]['captureEndMs'] - calls[-1]['returnMs']]
                                                             if after else None))
        require(ui.bounds(ui.main) == references[(960, 680)]['record']['geometry']['windowBounds'],
                'Diagnostic did not end at the requested smaller window size.')


def resize_scenarios(ui, report, label, mode, keys, *, expect_defect=False, observation_only=False):
    """Actual shrink/grow, with passive references and no corrective repaint."""
    if mode == 'tool':
        # Use the same populated, nested native form in the old negative control
        # and both candidate installations; an empty form is a weaker oracle.
        ui.set_text(ui.child(102), 'Index a reference')
        ui.wait('one resize reference-index operation', lambda: len(ui.library().tools()) == 1)
        stable_since = None
        def ready():
            nonlocal stable_since
            available = resize_tool_pointer_ready(ui, ui.child(104), ui.library().first_tool_point())
            stable_since = (stable_since or time.monotonic()) if available else None
            return stable_since is not None and time.monotonic() - stable_since >= .1
        ui.wait('resize operation row visible and hit-ready', ready, seconds=5)
        ui.click_at(*ui.library().first_tool_point(), expected=ui.child(104))
        ui.wait('populated resize tool form', lambda:
                ui.user.IsWindowEnabled(ui.child(113)) and
                any('Index a reference' in control['text'] for control in ui.controls(ui.child(118))))
        ui.set_text(ui.child(102), '')
        ui.wait('resize library filter cleared', lambda: not ui.label(ui.child(102)))
        # Reuse this desktop's keyboard driver: constructing another binds new
        # ctypes structure types to its shared DLL and breaks later focus reads.
        keys.key(0x09)  # Move the caret out of the edit before references.
    area = ui.work_area()
    require(area[2] - area[0] >= 1024 and area[3] - area[1] >= 728,
            'Resize regression requires the real 1024 by 728 work area.')
    canvas = [area[0], area[1], area[0] + 1024, area[1] + 728]
    ui.mouse(area[0] + 480, area[1] + 12)  # Park outside sampled client regions.
    stream = ResizeFrames(ui, canvas)
    group = {'installation': label, 'mode': mode, 'canvas': canvas, 'references': [],
             'transitions': [], 'method': 'Visible desktop BitBlt only; no PrintWindow or target repaint.',
             'immediateRead': 'Before any sleep, compositor synchronization, geometry query or file write.',
             'assertionStarts': 'First passive DwmFlush completion after resize; immediate pre-compositor pixels retained separately.',
             'excludedRegions': 'Edit/caret interiors, tree, status, mode-button hover/focus and nonclient chrome.',
             'limit': 'Finite hosted desktop samples; compositor pacing does not flush the target paint queue.'}
    report.setdefault('temporalResize', []).append(group)
    references = {}

    def move(size):
        require(ui.user.MoveWindow(ui.main, area[0], area[1], *size, True),
                'Native resize request failed.')

    def save(raw, name):
        frame = stream.save(ui.evidence, name + '.bmp', raw)
        frame.update(dpi=ui.user.GetDpiForWindow(ui.main), method=group['method'])
        report['captures'].append(frame)
        return frame

    try:
        for size in [(1024, 728), (960, 680)]:
            move(size)
            geometry = fixed_layout(ui, mode)
            require(geometry['windowBounds'] == [area[0], area[1], area[0] + size[0], area[1] + size[1]],
                    'Actual native window did not reach the exact requested test size.')
            regions = resize_regions(ui, geometry['windowBounds'])
            started, same, previous = time.perf_counter(), 0, None
            while time.perf_counter() - started < 3:
                _, raw, _ = stream.read()
                value = tuple(region_bytes(raw, canvas, region['rectangle']) for region in regions)
                same = same + 1 if value == previous else 0
                previous = value
                if same >= 8 and time.perf_counter() - started >= .35:
                    break
            require(same >= 8, 'Passive resize reference failed to settle without repaint intervention.')
            reference = {'requestedSize': list(size), 'geometry': geometry, 'regions': regions,
                         'stableSamples': same + 1, 'settlingSeconds': time.perf_counter() - started,
                         'capture': save(raw, '%s-%s-resize-reference-%dx%d' % (label, mode, *size))}
            group['references'].append(reference)
            references[size] = {'raw': raw, 'record': reference}

        if observation_only:
            resize_observation_bursts(ui, stream, references, group, save)
            passed(report, label + '-resize-observation-completed',
                   'Three bounded concurrent resize bursts observed; this records completion, not a defect-fix or pixel acceptance verdict.')
            return group

        current = (960, 680)
        for index, target in enumerate([(1024, 728), (960, 680)] * 3):
            expected = references[target]
            regions = expected['record']['regions']
            comparisons = [(region_bytes(expected['raw'], canvas, region['rectangle']),
                            region_bytes(references[current]['raw'], canvas, region['rectangle']))
                           for region in regions]
            require(sum(a != b for a, b in comparisons) >= 3,
                    'Resize regions do not distinguish source and target geometry.')
            native_controls = [(ui.child(control['id']), control['bounds'])
                               for control in expected['record']['geometry']['controls']
                               if control['id'] in (113, 115, 415, 416)]
            row = {'fromSize': list(current), 'toSize': list(target), 'samples': [], 'captures': [],
                   'samplingComplete': False, 'targetSeen': False,
                   'postCompositorSourceFrames': 0, 'postCompositorNonTargetFrames': 0,
                   'immediateNonTargetFrames': 0, 'comparedRegions': len(regions),
                   'sourceDistinctRegions': sum(a != b for a, b in comparisons)}
            group['transitions'].append(row)
            start = time.perf_counter()
            move(target)
            returned = time.perf_counter()
            stamp, raw, read_start = stream.immediate()
            saved, pending_captures = set(), []
            for sample_index in range(120):
                # The very first pixels precede every target geometry query.
                actual_bounds = ui.bounds(ui.main)
                require(actual_bounds == expected['record']['geometry']['windowBounds'],
                        'Visible resize was not associated with the requested native window geometry.')
                require(all(ui.bounds(handle) == bounds for handle, bounds in native_controls),
                        'Native footer control geometry did not match the resized target.')
                states = [resize_pixel_state(region_bytes(raw, canvas, region['rectangle']), a, b)
                          for region, (a, b) in zip(regions, comparisons)]
                target_frame = all(state == 'target' for state in states)
                sample = {'index': sample_index,
                          'phase': 'immediate-pre-compositor' if sample_index == 0 else 'post-compositor',
                          'captureStartMsAfterReturn': round((read_start - returned) * 1000, 3),
                          'captureEndMsAfterReturn': round((stamp - returned) * 1000, 3),
                          'nativeGeometryMatchesTarget': True,
                          'targetRegions': states.count('target'),
                          'sourceGeometryRegions': states.count('source-geometry'),
                          'otherRegions': states.count('other')}
                row['samples'].append(sample)
                row['targetSeen'] |= target_frame and sample_index > 0
                if sample_index == 0:
                    row['immediateNonTargetFrames'] += int(not target_frame)
                else:
                    row['postCompositorSourceFrames'] += int('source-geometry' in states)
                    row['postCompositorNonTargetFrames'] += int(not target_frame)
                digest = hashlib.sha256(raw).hexdigest()
                if sample_index == 0 or (not target_frame and digest not in saved and len(saved) < 12):
                    saved.add(digest)
                    pending_captures.append((raw, '%s-%s-resize-%02d-frame-%03d' % (label, mode, index, sample_index)))
                if stamp - returned >= .45 and sample_index >= 8:
                    break
                stamp, raw, read_start = stream.read()
            pending_captures.append((raw, '%s-%s-resize-%02d-last' % (label, mode, index)))
            row['captures'] = [save(pixels, name) for pixels, name in pending_captures]
            row.update(samplingComplete=True, moveWindowMs=round((returned - start) * 1000, 3),
                       frames=len(row['samples']), elapsedSeconds=stamp - returned,
                       maxCaptureGapMs=max(b['captureStartMsAfterReturn'] - a['captureStartMsAfterReturn']
                                           for a, b in zip(row['samples'], row['samples'][1:])))
            current = target
        require_resize_outcome(group['transitions'], expect_defect)
        passed(report, label + '-' + mode + '-temporal-resize',
               ('Exact old-package source-geometry defect reproduced and naturally recovered.' if expect_defect else
                label + ': ' + mode + ' shrink/grow regions match target geometry in all post-compositor samples; immediate frames retained separately.'))
        return group
    finally:
        stream.close()


def seed_baseline(base, evidence, external):
    record = synthetic_reference(base, external)
    host = PrivateHost(base, evidence, 'baseline-fixtures', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.16.0', 'Fixture host is not the exact published baseline.')
        run = local_reference_run(host, base, evidence, record, 'preserved-reference-result')
        run_id = host.call('history')['runs'][0]['run_id']
        state = host.call('workspace/tool', {'toolId': 'align/paired-end'})
        node = state['graph']['nodes'][0]
        state = host.call('model', {'action': 'apply_fields', 'payload': {
            'nodeId': node['id'], 'params': {'threads': '3'}}})
        node = state['graph']['nodes'][0]
        host.call('save', {'kind': 'preset', 'name': 'UI patch preservation settings', 'nodeId': node['id']})
        host.call('workspace/mode', {'mode': 'workflow'})
        first = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        second = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        source = host.call('model', {'action': 'add_input', 'payload': {'inputType': 'reference'}})['selected']
        host.call('model', {'action': 'connect', 'payload': {'nodeId': first, 'portId': 'reference', 'refs': [source]}})
        host.call('model', {'action': 'connect', 'payload': {'nodeId': second, 'portId': 'reference', 'refs': [first + '::reference']}})
        host.call('save', {'kind': 'pipeline', 'name': 'UI patch preservation pipeline'})
    finally:
        host.close()
    saved = read_json(base / 'user-data/saved.json')
    require(len(saved['presets']) == len(saved['pipelines']) == 1 and
            saved['presets'][0]['pin'] == node['pin'] and saved['presets'][0]['params']['threads'] == '3',
            'Separate nondefault settings and exact pipeline pins were not saved.')
    return {'reference': record, 'saved': saved, 'run': run, 'runId': run_id}



def seed_fresh_result(root, evidence, external, report):
    record = synthetic_reference(root, external)
    host = PrivateHost(root, evidence, 'fresh-result-fixture', offline=True)
    try:
        require(host.call('init')['app_version'] == TARGET_VERSION, 'Wrong fresh candidate version.')
        result = local_reference_run(host, root, evidence, record, 'fresh-search-reference-result')
        require(len(host.call('results/search', {'query': 'SAMtools'})['runs']) == 1,
                'Fresh search fixture must contain one actual completed SAMtools result.')
        report['freshResultFixture'] = result
    finally:
        host.close()
    passed(report, 'fresh-result-fixture', 'Candidate private host creates one real native SAMtools result for populated keyboard search.')


def fixed_layout(ui, mode):
    bounds, area = ui.bounds(ui.main), ui.work_area()
    require(inside(bounds, area), 'Native window clips outside the actual monitor work area.')
    identities = [102, 104, 402, 410, 411, 417, 424, 425, 113, 115, 415, 416]
    if mode == 'workflow':
        identities += [419, 105, 412, 107, 108, 418, 420, 421, 422]
    measured = []
    for identity in identities:
        handle = ui.child(identity)
        require(handle and ui.user.IsWindowVisible(handle), 'Missing fixed control: ' + str(identity))
        rect = ui.bounds(handle)
        extra = {}
        if identity == 104:
            library = ui.library()
            if hasattr(library, 'viewport') and library.viewport() != handle:
                # The pixel-scrolling child deliberately extends beyond its
                # clipping parent. The visible pane, not its backing child,
                # must remain wholly inside the actual window and work area.
                extra = {'nativeChildBounds': rect, 'viewportControlId': 430,
                         'visibleClientBounds': library.visible_bounds()}
                rect = ui.bounds(library.viewport())
        require(inside(rect, bounds) and inside(rect, area), 'Fixed control clips: ' + str(identity))
        measured.append({'id': identity, 'class': ui.label(handle, True), 'bounds': rect, **extra})
    buttons = [row for row in measured if row['class'] == 'Button']
    for index, a in enumerate(buttons):
        for b in buttons[index + 1:]:
            require(not overlaps(a['bounds'], b['bounds']),
                    'Fixed buttons overlap: ' + str((a['id'], b['id'])))
    return {'windowBounds': bounds, 'workArea': area, 'controls': measured,
            'horizontalClipping': False, 'verticalClipping': False}


def desktop_scenarios(root, evidence, report, label):
    ui = PatchUI(root, evidence)
    keys = Keyboard(ui)
    try:
        require(inside(ui.initial_bounds, ui.initial_work_area), 'Unmodified startup window clips outside work area.')
        report.setdefault('startupBounds', {})[label] = {
            'windowBounds': ui.initial_bounds, 'workArea': ui.initial_work_area,
            'capturedBeforeDriverResize': True}
        passed(report, label + '-startup-bounds', label + ': real initial window fits the work area before driver repositioning.')
        ui.wait('desktop ready', lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        setup_window = lambda: next((h for h in ui.windows() if ui.label(h) == 'Tool setup · Native Workbench'), None)
        if label == 'fresh':
            ui.wait('fresh native tool setup', setup_window)
        else:
            ui.wait('upgraded startup requests complete', lambda: ui.user.IsWindowEnabled(ui.child(417)))
        setup = setup_window()
        report.setdefault('startupSetup', {})[label] = {'observed': bool(setup)}
        if setup:
            pack_snapshot = tree_hashes(root / 'packs')
            starter = unique_button(ui, setup, 'Starter')
            pointer_click(ui, starter)
            ui.wait('Starter selected', lambda: ui.send(starter, 0x00F0) == 1)
            require(inside(ui.bounds(setup), ui.work_area()), 'First-open setup clips outside the work area.')
            capture(ui, report, label + '-first-open-starter.bmp', setup)
            pointer_click(ui, unique_button(ui, setup, 'Use Workbench'))
            state_path = root / 'user-data/tool-setup.json'
            ui.wait('setup dismissal recorded', lambda:
                    not setup_window() and state_path.is_file() and read_json(state_path)['dismissed'])
            state = read_json(state_path)
            require(not state['queue'] and not state['operation']['active'] and
                    state['operation']['status'] == 'idle' and tree_hashes(root / 'packs') == pack_snapshot,
                    'Offline Starter selection changed packs or queued work.')
            report['startupSetup'][label].update(starterSelected=True, dismissed=True,
                                                queuedInstalls=0, unchangedPackFiles=len(pack_snapshot))
            passed(report, label + '-starter-setup', label + ': real offline Starter setup fits and dismisses without pack changes or installs.')
        if label == 'fresh':
            # Any result/reference record marks an installation as an existing
            # user. Exercise pristine first-open setup before creating the
            # scientific search fixture, then reopen the same installation.
            # A persisted dismissal precedes the asynchronous UI reply; closing
            # before edit controls return can legitimately ask to cancel setup.
            ui.wait('setup dismissal reply completed', lambda:
                    ui.user.IsWindowEnabled(ui.child(410)) and
                    ui.user.IsWindowEnabled(ui.child(102)))
            ui.close()
            ui = None
            seed_fresh_result(root, evidence, evidence / 'fresh external reference', report)
            ui = PatchUI(root, evidence)
            keys = Keyboard(ui)
            require(inside(ui.initial_bounds, ui.initial_work_area), 'Reopened fresh window clips outside work area.')
            report['startupBounds'][label]['reopenedAfterFixture'] = ui.initial_bounds
        ui.wait('desktop unobscured', lambda: ui.user.IsWindowEnabled(ui.child(417)))
        search = ui.child(102)
        pointer_click(ui, search)
        ui.wait('library keyboard focus', lambda: keys.focus() == search)
        report.setdefault('keyboardEdits', []).append({
            'stage': label + '-library-before-filter', **clear_focused_edit(ui, keys, search)})
        keys.text('reference')
        ui.wait('keyboard library filter', lambda: ui.label(search) == 'reference' and ui.library().tools())
        retention = report.setdefault('libraryFocusRetention', {}).setdefault(label, {})
        retention['search'] = retain_keyboard_focus(ui, keys, search)
        keys.key(0x09)
        ui.wait('Tab advances from library search', lambda: keys.focus() not in (None, search))
        next_focus = keys.focus()
        require(ui.user.IsChild(ui.main, next_focus) and ui.user.IsWindowVisible(next_focus) and
                ui.user.IsWindowEnabled(next_focus), 'Tab reached an unavailable or foreign control.')
        retention['afterTab'] = retain_keyboard_focus(ui, keys, next_focus)
        keys.key(0x09, 0x10)
        ui.wait('Shift+Tab restores search', lambda: keys.focus() == search)
        report['keyboardEdits'].append({
            'stage': label + '-library-after-tab', **clear_focused_edit(ui, keys, search)})
        ui.wait('keyboard filter cleared', lambda: not ui.label(search) and ui.library().tools())
        passed(report, label + '-library-keyboard', label + ': library filtering and Tab/Shift+Tab preserve real enabled focus.')
        layouts = []
        for mode, button in [('tool', 410), ('workflow', 411)]:
            ui.click_button(button)
            ui.wait(mode + ' controls ready', lambda: ui.user.IsWindowEnabled(ui.child(417)) and
                    (mode != 'workflow' or ui.user.IsWindowVisible(ui.child(420))))
            resize_scenarios(ui, report, label, mode, keys)
            for width, height in [(960, 680), (1024, 728), (1280, 900)]:
                ui.fit_window(width, height)
                row = fixed_layout(ui, mode)
                row.update(mode=mode, requestedSize=[width, height])
                layouts.append(row)
                if width == 960:
                    # Observe the displayed desktop before PrintWindow can
                    # request a separate render. Later samples allow natural
                    # post-resize painting; no input or forced redraw occurs.
                    started = time.monotonic()
                    series = []
                    for phase, delay in [('immediate', 0), ('250ms', .25),
                                         ('750ms', .5), ('1250ms', .5)]:
                        if delay:
                            time.sleep(delay)
                        frame, _ = ui.screen_capture(
                            label + '-' + mode + '-960-visible-' + phase + '.bmp', ui.bounds(ui.main))
                        frame['dpi'] = ui.user.GetDpiForWindow(ui.main)
                        frame['method'] = 'visible desktop BitBlt before PrintWindow'
                        frame['secondsAfterResizeObservation'] = time.monotonic() - started
                        report['captures'].append(frame)
                        series.append(frame)
                    report.setdefault('passiveResizeCaptureSeries', []).append({
                        'installation': label, 'mode': mode, 'requestedSize': [width, height],
                        'inputOrForcedRedrawBetweenFrames': False, 'frames': series})
                capture(ui, report, label + '-' + mode + '-%dx%d.bmp' % (width, height))
        report.setdefault('layouts', {})[label] = layouts
        passed(report, label + '-layout', label + ': both three-pane modes, navigation and fixed footer controls fit actual work-area bounds without button overlap at every observed size.')
        for case, query_text, expected_count in [('empty', 'patch-no-matching-result', 0), ('populated', 'SAMtools', 1)]:
            ui.click_button(417)
            title = 'Recorded results · Native Workbench'
            window = lambda: next((h for h in ui.windows() if ui.label(h) == title), None)
            ui.wait('Results opened', window)
            owner = window()
            query = ui.child(1501, owner)
            ui.wait('native initial Results query focus', lambda: keys.focus() == query and
                    ui.user.IsWindowEnabled(ui.child(1502, owner)))
            require(inside(ui.bounds(owner), ui.work_area()), 'Results dialog clips outside work area.')
            # No pointer/refocus/SetFocus intervention is allowed after opening.
            report['keyboardEdits'].append({
                'stage': label + '-results-' + case, **clear_focused_edit(ui, keys, query)})
            keys.text(query_text)
            ui.wait('query entered by keyboard', lambda: ui.label(query) == query_text)
            keys.key(0x09)
            ui.wait('Tab reaches Search', lambda: keys.focus() == ui.child(1502, owner))
            keys.key(0x09, 0x10)
            ui.wait('Shift+Tab restores query', lambda: keys.focus() == query)
            keys.key(0x09)
            ui.wait('Tab returns to Search', lambda: keys.focus() == ui.child(1502, owner))
            held_search = retain_keyboard_focus(ui, keys, ui.child(1502, owner))
            keys.key(0x20)
            ui.wait('keyboard Search returns with retained query focus', lambda:
                    keys.focus() == query and ui.user.IsWindowEnabled(ui.child(1502, owner)) and
                    ui.send(ui.child(1503, owner), 0x1004) == expected_count and
                    (('Execution status: completed' in ui.label(ui.child(1504, owner))) if expected_count else
                     ui.label(ui.child(1504, owner)) == 'No matching recorded analyses. Clear the search and press Search to show recent runs.'))
            require(bool(ui.user.IsWindowEnabled(ui.child(1505, owner))) == bool(expected_count),
                    'View availability differs from actual selected results.')
            observation = {'query': query_text, 'resultCount': expected_count,
                           'searchFocusRetention': held_search,
                           'beforeEscape': focus_observation(ui, keys, owner),
                           'pointerInterventionAfterOpen': False}
            capture(ui, report, label + '-results-' + case + '.bmp', owner)
            report.setdefault('resultsKeyboard', {}).setdefault(label, {})[case] = observation
            keys.key(0x1B)
            observation['closedImmediatelyAfterSearch'] = observe_close(ui, window)
            observation['afterEscape'] = focus_observation(ui, keys, owner)
            require(observation['closedImmediatelyAfterSearch'], 'Escape after keyboard Search did not close Results.')
            passed(report, label + '-results-' + case, label + ': ' + case + ' Search retains query focus; immediate Escape closes only Results without pointer intervention.')
    except Exception:
        if ui is not None:
            try:
                focus = keys.focus()
                report.setdefault('desktopFailureFocus', {})[label] = {
                    'focusWindow': focus,
                    'focusControlId': ui.user.GetDlgCtrlID(focus) if focus else None,
                    'focusEnabled': bool(ui.user.IsWindowEnabled(focus)) if focus else False,
                    'searchEnabled': bool(ui.user.IsWindowEnabled(ui.child(102))),
                    'searchText': ui.label(ui.child(102)),
                    'searchSelection': ui.send(ui.child(102), 0x00B0)}
            except Exception as focus_error:
                report.setdefault('desktopFailureFocus', {})[label] = {'observationError': str(focus_error)}
            for number, owner in enumerate(ui.windows()):
                capture(ui, report, label + '-failure-%d.bmp' % number, owner)
        raise
    finally:
        if ui is not None:
            ui.close()

def run(args, report):
    require(os.name == 'nt', 'Native Windows is unavailable; this gate cannot pass.')
    validate_identities(args)
    target, update_input, work, evidence = args.app_root.resolve(), args.update_root.resolve(), args.work.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (target / 'runtime/python/python.exe').resolve(), 'Use the exact Starter private interpreter.')
    require(not work.exists() and all(not work.is_relative_to(root) and not root.is_relative_to(work)
                                    for root in (target, update_input)), 'Use a new, separate disposable work directory.')
    for role, path, expected in [('starter', args.starter_archive, args.starter_sha256), ('baseline', args.baseline_archive, BASELINE_SHA), ('update', args.update_archive, args.update_sha256)]:
        require(sha256(path) == expected, 'Wrong exact ' + role + ' archive.')
        report['archives'][role] = {'name': path.name, 'bytes': path.stat().st_size, 'sha256': expected}
    report['archiveFilesVerified'] = {'starter': verify_extracted(args.starter_archive, target), 'update': verify_extracted(args.update_archive, update_input)}
    work.mkdir(parents=True)
    update = work / 'updater'
    shutil.copytree(update_input, update)
    updater_snapshot = tree_hashes(update_input)
    require(tree_hashes(update) == updater_snapshot, 'Disposable updater copy differs from verified bundle input.')
    extract(args.baseline_archive, work / 'baseline')
    base, external = work / 'baseline/native-workbench', work / 'external references'
    report['archiveFilesVerified']['baseline'] = verify_extracted(args.baseline_archive, base)
    pack_snapshots = {'fresh': tree_hashes(target / 'packs'), 'upgraded': tree_hashes(base / 'packs')}
    invalid = work / 'not a Workbench installation'
    invalid.mkdir()
    # Explicit bytes prevent Windows text-mode CRLF translation from making
    # the preservation oracle disagree with its own freshly created fixture.
    (invalid / 'keep.txt').write_bytes(b'Invalid folder must remain unchanged.\n')
    target_manifest = read_json(target / 'manifest.json')
    target_core_files = verify_candidate_core(target, target_manifest)
    verify_inventory(base, read_json(base / 'manifest.json')['files'])
    verify_inventory(update, read_json(update / 'update-inventory.json')['files'])
    report['updaterLauncherSha256'] = sha256(update / 'UpdateWorkbench.exe')
    passed(report, 'candidate-input-identities', 'Every extracted candidate Starter and updater file matches its exact archive; the packaged launcher is exercised unchanged.')
    fixtures = seed_baseline(base, evidence, external)
    report['nativeWindowsExecuted'] = True
    report['baselineFixtures'] = fixtures
    saved_bytes = (base / 'user-data/saved.json').read_bytes()
    preserved = preserved_files(base, external)
    write_json(evidence / 'picker-preservation-before.json', preserved)
    passed(report, 'baseline-fixtures', 'Published 0.16.0 executes a local native SAMtools reference result and saves independent settings plus connected pipeline pins.')
    baseline_snapshot = tree_hashes(base)
    external_snapshot = tree_hashes(external)
    invalid_snapshot = tree_hashes(invalid)
    report['unchangedScenarioEvidence'] = {}
    for scenario in ('cancel', 'invalid'):
        updater_scenario(update, evidence, report, scenario, base, invalid)
        differences = {name: tree_difference(before, tree_hashes(folder)) for name, folder, before in
                       [('installation', base, baseline_snapshot), ('externalReference', external, external_snapshot),
                        ('invalidSelection', invalid, invalid_snapshot)]}
        report['unchangedScenarioEvidence'][scenario] = differences
        require(not any(differences.values()),
                'Cancellation or invalid-folder handling changed fixture files: ' + json.dumps(differences))
        passed(report, 'updater-' + scenario, 'Packaged folder picker ' + ('cancels with Escape' if scenario == 'cancel' else 'rejects a real non-installation folder, explains the required files, reopens for retry and allows Escape') + ' with every baseline/reference/invalid-folder file unchanged.')
    updater_scenario(update, evidence, report, 'install', base, invalid)
    verify_inventory(base, target_manifest['files'])
    require((base / 'manifest.json').read_bytes() == (target / 'manifest.json').read_bytes(), 'Updated manifest differs from accepted Starter.')
    after = preserved_files(base, external)
    report['preservation'] = verify_preserved(preserved, after)
    write_json(evidence / 'picker-preservation-after.json', after)
    require((base / 'user-data/saved.json').read_bytes() == saved_bytes, 'Folder-picker update changed saved settings or pins.')
    transactions = list((base / 'updates').glob('core-*/update-result.json'))
    require(len(transactions) == 1, 'Expected one real committed updater transaction.')
    transaction = read_json(transactions[0])
    verify_core_transaction(transaction, target_core_files)
    report['transaction'] = transaction
    report['coreFilesVerified'] = target_core_files
    report['preservedFiles'] = len(preserved)
    passed(report, 'updater-install', 'Selecting the actual baseline through the published folder picker displays success, commits all ' + str(target_core_files) + ' exact Starter core files, and preserves every recorded pack/user/result/reference file.')
    installed_snapshot = tree_hashes(base)
    updater_scenario(update, evidence, report, 'repeat', base, invalid)
    differences = {'installation': tree_difference(installed_snapshot, tree_hashes(base)),
                   'externalReference': tree_difference(external_snapshot, tree_hashes(external))}
    report['unchangedScenarioEvidence']['repeat'] = differences
    require(not any(differences.values()),
            'Repeating through the folder picker changed the installed state: ' + json.dumps(differences))
    passed(report, 'updater-repeat', 'Repeating the update through the same real picker displays success and leaves all installation/reference files and the single transaction unchanged.')
    host = PrivateHost(base, evidence, 'updated-fixture-readback', offline=True)
    try:
        require(host.call('init')['app_version'] == TARGET_VERSION, 'Updated host version differs.')
        saved = fixtures['saved']
        state = host.call('workspace/tool', {'toolId': saved['presets'][0]['tool']})
        host.call('load', {'kind': 'preset', 'id': saved['presets'][0]['id'], 'node_id': state['graph']['nodes'][0]['id']})
        loaded_preset = host.call('state')['graph']['nodes'][0]
        require(loaded_preset['pin'] == saved['presets'][0]['pin'] and loaded_preset['params']['threads'] == '3',
                'Saved nondefault settings or exact pin changed.')
        loaded = host.call('load', {'kind': 'pipeline', 'id': saved['pipelines'][0]['id']})['graph']
        original = saved['pipelines'][0]['graph']
        require(loaded['nodes'] == original['nodes'] and
                [(row['id'], row['type']) for row in loaded['sources']] ==
                [(row['id'], row['type']) for row in original['sources']], 'Saved connected pipeline or exact pins changed.')
        require(any(row['run_id'] == fixtures['runId'] for row in host.call('results/search', {'query': 'SAMtools'})['runs']), 'Updated host lost the actual baseline result.')
        require(any(row['id'] == fixtures['reference']['id'] and row['available'] and
                    row['receipt_sha256'] == fixtures['reference']['receipt_sha256']
                    for row in host.call('references/list')['local']), 'Updated host lost the preserved local reference.')
    finally:
        host.close()
    passed(report, 'upgraded-fixture-readback', 'Updated private host reloads the unchanged settings and connected pipeline, finds the actual baseline result, and resolves its preserved exact reference receipt offline.')
    for label, root in [('fresh', target), ('upgraded', base)]:
        try:
            desktop_scenarios(root, evidence, report, label)
        except Exception as error:
            failed(report, label + '-desktop-incomplete', str(error))
            report.setdefault('desktopErrors', {})[label] = traceback.format_exc()
    verify_inventory(target, target_manifest['files'])
    verify_inventory(base, target_manifest['files'])
    require(tree_hashes(target / 'packs') == pack_snapshots['fresh'] and
            tree_hashes(base / 'packs') == pack_snapshots['upgraded'], 'Native checks changed installed packs.')
    require(tree_hashes(update_input) == updater_snapshot, 'Immutable original updater input changed.')
    report['observedDpi'] = sorted({row['dpi'] for row in report['captures']})
    report['nativeWindowsExecuted'] = True
    report['nativeGUIObservationsCompleted'] = not report.get('desktopErrors')


def run_resize_only(args, report):
    require(os.name == 'nt', 'Native Windows is unavailable; this gate cannot pass.')
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(),
            'Use the exact Starter private interpreter.')
    require(sha256(args.starter_archive) == args.starter_sha256, 'Wrong exact resize-control Starter archive.')
    report['archives']['starter'] = {'name': args.starter_archive.name,
                                    'bytes': args.starter_archive.stat().st_size,
                                    'sha256': args.starter_sha256}
    report['archiveFilesVerified'] = verify_extracted(args.starter_archive, root)
    manifest = read_json(root / 'manifest.json')
    report['coreFilesVerified'] = verify_candidate_core(root, manifest)
    packs = tree_hashes(root / 'packs')
    ui = PatchUI(root, evidence)
    keys = Keyboard(ui)
    report['nativeWindowsExecuted'] = report['nativeGUILaunched'] = True
    try:
        ui.wait('resize-control desktop ready', lambda:
                ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        setup_window = lambda: next((h for h in ui.windows() if ui.label(h) == 'Tool setup · Native Workbench'), None)
        ui.wait('pristine resize-control setup', setup_window)
        setup = setup_window()
        pointer_click(ui, unique_button(ui, setup, 'Starter'))
        pointer_click(ui, unique_button(ui, setup, 'Use Workbench'))
        ui.wait('resize-control setup reply complete', lambda:
                not setup_window() and ui.user.IsWindowEnabled(ui.child(417)))
        ui.click_button(410)
        ui.wait('resize-control Tools ready', lambda: ui.user.IsWindowEnabled(ui.child(417)))
        resize_scenarios(ui, report, 'observation' if args.resize_observation_only else 'previous', 'tool', keys,
                         expect_defect=args.expect_known_resize_defect,
                         observation_only=args.resize_observation_only)
    finally:
        ui.close()
    verify_inventory(root, manifest['files'])
    require(tree_hashes(root / 'packs') == packs, 'Resize negative control changed installed packs.')
    report['nativeGUIObservationsCompleted'] = True
    report['negativeControl'] = bool(args.expect_known_resize_defect)
    report['observedDpi'] = sorted({row['dpi'] for row in report['captures']})


def validate_resize_destinations(args):
    app, report, archive = args.app_root.resolve(), args.report.resolve(), args.starter_archive.resolve()
    require(not report.is_relative_to(app) and report != archive,
            'Resize evidence must be outside the disposable application and immutable archive.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app-root', 'starter-archive', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('baseline-archive', 'update-root', 'update-archive', 'work'):
        parser.add_argument('--' + name, type=Path)
    for name in ('source-commit', 'gate-commit', 'starter-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--update-sha256')
    parser.add_argument('--resize-only', action='store_true')
    parser.add_argument('--expect-known-resize-defect', action='store_true')
    parser.add_argument('--resize-observation-only', action='store_true')
    args = parser.parse_args()
    args.bundle_root = None
    require(not args.expect_known_resize_defect or args.resize_only,
            'Expected defect mode is restricted to the separate resize-only negative control.')
    require(not args.resize_observation_only or (args.resize_only and not args.expect_known_resize_defect),
            'Resize observation is a separate resize-only diagnostic, not an expected-defect acceptance gate.')
    if not args.resize_only:
        require(all(getattr(args, name) is not None for name in
                    ('baseline_archive', 'update_root', 'update_archive', 'work', 'update_sha256')),
                'Full gate requires baseline, updater, work and update identity arguments.')
    validate_identities(args)
    if args.resize_only:
        validate_resize_destinations(args)
    else:
        validate_destinations(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'native-ui-patch', 'appVersion': TARGET_VERSION, 'baselineVersion': '0.16.0',
              'sourceCommit': args.source_commit, 'gateCommit': args.gate_commit, 'gateSha256': sha256(__file__),
              'platform': platform.platform(), 'startedUtc': utc(), 'archives': {}, 'checks': [],
              'scenarios': [], 'captures': [], 'skips': [], 'limits': list(LIMITS),
              'nativeWindowsExecuted': False, 'nativeGUILaunched': False, 'nativeGUIValidated': False,
              'nativeGUIObservationsCompleted': False, 'success': False}
    try:
        (run_resize_only if args.resize_only else run)(args, report)
    except Exception as error:
        report['failure'] = str(error)
        report['traceback'] = traceback.format_exc()
        report['scenarios'].append({'id': 'gate-completion', 'status': 'blocked' if os.name != 'nt' else 'failed',
                                    'observedAt': utc(), 'note': 'Native gate did not complete; retained diagnostics describe the failure.'})
    finally:
        report['finishedUtc'] = utc()
        finalize_report(report)
        if args.expect_known_resize_defect:
            report['kind'] = 'native-ui-resize-negative-control'
            report['negativeControlValidated'] = report['success']
            report['nativeGUIValidated'] = False  # Reproducing old failure is not an application pass.
        if args.resize_observation_only:
            report['kind'] = 'native-ui-resize-observation-only'
            report['diagnosticCompleted'] = report['success']
            report['nativeGUIValidated'] = False
            report['successMeaning'] = 'Diagnostic acquisition completed; no application fix or differential verdict.'
        write_json(args.report, report)
    print(json.dumps({'success': report['success'], 'passed': report['passed'], 'failed': report['failed'],
                      'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
