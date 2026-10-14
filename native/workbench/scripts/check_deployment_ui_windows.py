#!/usr/bin/env python3
"""Exercise the published updater's real folder picker and desktop keyboard flow.

Run with a disposable exact 0.16.0 Starter and its isolated bundled Python.
The baseline is extracted by this gate. No launcher is rebuilt, no update script
is invoked directly, and no security/display policy is changed. Raw evidence is
local and can contain disposable paths; the optional bounded acceptance summary
contains neither workstation identity nor local paths.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_090 import extract
from build_update_0160 import BASELINE_SHA, SOURCE_COMMIT, STARTER_SHA, verify_inventory
from check_references_windows import PrivateHost, require, sha256, stop_process_tree, write_json
from check_update_090_windows import read_json, preserved_files, synthetic_reference
from check_update_0160_windows import local_reference_run
from check_workspace_ui_windows import NativeUI

UPDATE_SHA = 'd75d5129e9b9feaef70faa62d5ea91049c0162df8c7bdc74c7bc81d1933eec8f'
PICKER_TITLE = 'Select your existing native-workbench folder'
LIMITS = [
    'Exact published 0.11.0 to 0.16.0 update only; other migration paths are not covered.',
    'Synthetic local reference and saved-state fixtures; no clinical or realistic-data acceptance claim.',
    'Observed hosted desktop DPI and sizes only; no high-DPI or DPI-transition claim.',
    'Physical trackpad, multiple monitors, representative PCs and institutional approval remain not tested.',
    'Scientific fixture hosts deny Python socket operations; this is not operating-system network isolation.',
]


def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def validate_destinations(args):
    """Refuse immutable/input overlap before creating any report directory."""
    app, updater, work, report = (getattr(args, name).resolve()
                                 for name in ('app_root', 'update_root', 'work', 'report'))
    if args.bundle_root:
        bundle = args.bundle_root.resolve()
        require(all(not path.is_relative_to(bundle) for path in (app, work, report)),
                'Disposable app, work and report destinations must be outside the immutable bundle.')
    require(all(not report.is_relative_to(root) for root in (app, updater)),
            'Report destination must be outside application and updater inputs.')
    archives = [getattr(args, name).resolve() for name in
                ('starter_archive', 'baseline_archive', 'update_archive')]
    require(report not in archives, 'Report destination must not replace an input archive.')
    require(not report.is_relative_to(work), 'Report destination must be outside the new disposable work directory.')
    require(not work.exists() and all(not work.is_relative_to(root) and not root.is_relative_to(work)
                                     for root in (app, updater)),
            'Use a new work directory separate from application and updater inputs.')


def tree_hashes(root):
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def tree_difference(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)}
            for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)}


def unique_button(ui, owner, text):
    """Resolve the actual owned dialog button, without assuming MessageBox IDs."""
    require(owner in ui.windows(), 'The requested button owner is not an observed gate-owned window.')
    matches = [row['hwnd'] for row in ui.controls(owner)
               if row['class'] == 'Button' and row['text'].replace('&', '') == text and
               ui.user.IsWindowVisible(row['hwnd']) and ui.user.IsWindowEnabled(row['hwnd'])]
    require(len(matches) == 1, 'Expected one visible enabled ' + text + ' button in the observed dialog.')
    return matches[0]


def verify_preserved(before, after):
    changes = {name: {'before': value, 'after': after.get(name)}
               for name, value in before.items() if after.get(name) != value}
    additions = {name: value for name, value in after.items() if name not in before}
    require(not changes and all(name == 'user-data/session.lock' and
                                value == hashlib.sha256(b'\0').hexdigest()
                                for name, value in additions.items()),
            'Folder-picker update changed existing files or added unexpected user data.')
    return {'existingFiles': len(before), 'changes': changes, 'additions': additions}


def verify_extracted(archive, root):
    """Bind every extracted archived file, including the published launcher."""
    count = 0
    with zipfile.ZipFile(archive) as zipped:
        files = [item for item in zipped.infolist() if not item.is_dir()]
        prefixes = {PurePosixPath(item.filename).parts[0] for item in files}
        # Starter has a native-workbench/ root; the published updater ZIP is
        # deliberately flat. Both layouts are bound to a pinned archive first.
        strip_root = prefixes == {'native-workbench'}
        for item in files:
            parts = PurePosixPath(item.filename).parts[int(strip_root):]
            require(parts and not item.filename.startswith('/') and '\\' not in item.filename and
                    ':' not in item.filename and all(part not in ('.', '..') for part in parts), 'Unsafe archived path.')
            path = root.joinpath(*parts)
            require(path.is_file() and path.stat().st_size == item.file_size and
                    sha256(path) == hashlib.sha256(zipped.read(item)).hexdigest(),
                    'Extraction differs from pinned archive: ' + '/'.join(parts))
            count += 1
    return count


class Keyboard:
    """Real SendInput keyboard events, with observed foreground/focus ownership."""
    def __init__(self, ui):
        self.ui = ui
        class Key(ctypes.Structure):
            _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        class Mouse(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('data', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
        class Union(ctypes.Union):
            _fields_ = [('keyboard', Key), ('mouse', Mouse)]
        class Input(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('value', Union)]
        class GuiInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('flags', wintypes.DWORD),
                        ('active', wintypes.HWND), ('focus', wintypes.HWND),
                        ('capture', wintypes.HWND), ('menu', wintypes.HWND),
                        ('moveSize', wintypes.HWND), ('caret', wintypes.HWND), ('rect', wintypes.RECT)]
        self.Key, self.Input, self.GuiInfo = Key, Input, GuiInfo
        ui.user.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GuiInfo)]
        ui.user.GetGUIThreadInfo.restype = wintypes.BOOL
        ui.user.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
        ui.user.SendInput.restype = wintypes.UINT

    def focus(self):
        value = self.GuiInfo()
        value.size = ctypes.sizeof(value)
        require(self.ui.user.GetGUIThreadInfo(0, ctypes.byref(value)), 'Cannot inspect active keyboard focus.')
        require(value.active and value.active in self.ui.windows(), 'Keyboard foreground is not gate-owned.')
        return value.focus

    def event(self, code, *, up=False, unicode=False):
        value = self.Input()
        value.type = 1
        value.value.keyboard = self.Key(0 if unicode else code, code if unicode else 0,
                                       (4 if unicode else 0) | (2 if up else 0), 0, 0)
        require(self.ui.user.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) == 1,
                'Actual keyboard input was unavailable.')

    def key(self, code, *modifiers):
        self.focus()
        for modifier in modifiers:
            self.event(modifier)
        try:
            self.event(code)
            self.event(code, up=True)
        finally:
            for modifier in reversed(modifiers):
                self.event(modifier, up=True)

    def text(self, value):
        self.focus()
        # UTF-16 code units are what KEYEVENTF_UNICODE delivers to Windows.
        encoded = value.encode('utf-16-le')
        for index in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[index:index + 2], 'little')
            self.event(unit, unicode=True)
            self.event(unit, up=True, unicode=True)


class UpdaterUI(NativeUI):
    """Reuse the native evidence helpers without starting the desktop app."""
    def __init__(self, root, evidence):
        self.root, self.evidence, self.main = root, evidence, None
        self.user = u = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = g = ctypes.WinDLL('gdi32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.previous_dpi = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        for name, args, result in [
            ('GetDpiForWindow', [wintypes.HWND], wintypes.UINT),
            ('EnumWindows', [self.callback, wintypes.LPARAM], wintypes.BOOL),
            ('EnumChildWindows', [wintypes.HWND, self.callback, wintypes.LPARAM], wintypes.BOOL),
            ('GetWindowThreadProcessId', [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            ('GetClassNameW', [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            ('GetDlgCtrlID', [wintypes.HWND], ctypes.c_int),
            ('GetDlgItem', [wintypes.HWND, ctypes.c_int], wintypes.HWND),
            ('IsWindowVisible', [wintypes.HWND], wintypes.BOOL),
            ('IsWindowEnabled', [wintypes.HWND], wintypes.BOOL),
            ('GetWindowRect', [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            ('SendMessageTimeoutW', [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)], wintypes.LPARAM),
            ('PostMessageW', [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            ('GetForegroundWindow', [], wintypes.HWND),
            ('WindowFromPoint', [wintypes.POINT], wintypes.HWND),
            ('GetAncestor', [wintypes.HWND, wintypes.UINT], wintypes.HWND),
            ('IsChild', [wintypes.HWND, wintypes.HWND], wintypes.BOOL),
            ('SetForegroundWindow', [wintypes.HWND], wintypes.BOOL),
            ('GetDC', [wintypes.HWND], wintypes.HDC),
            ('ReleaseDC', [wintypes.HWND, wintypes.HDC], ctypes.c_int),
            ('PrintWindow', [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
        ]:
            function = getattr(u, name)
            function.argtypes, function.restype = args, result
        for name, args, result in [
            ('CreateCompatibleDC', [wintypes.HDC], wintypes.HDC),
            ('CreateCompatibleBitmap', [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP),
            ('SelectObject', [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
            ('DeleteObject', [wintypes.HANDLE], wintypes.BOOL),
            ('DeleteDC', [wintypes.HDC], wintypes.BOOL),
            ('GetDIBits', [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT], ctypes.c_int),
        ]:
            function = getattr(g, name)
            function.argtypes, function.restype = args, result
        # Use the same real pointer implementation as NativeUI with the full
        # Windows INPUT union; Keyboard changes SendInput's pointer type only.
        self.keyboard = Keyboard(self)
        self.Input = self.keyboard.Input
        self.process = subprocess.Popen([str(root / 'UpdateWorkbench.exe')], cwd=root)
        try:
            self.main = self.wait_window(PICKER_TITLE)
            u.SetForegroundWindow(self.main)
            self.wait('updater folder picker in foreground', lambda: u.GetForegroundWindow() == self.main)
        except Exception:
            self.close()
            raise

    def wait(self, phase, predicate, seconds=30):
        self.progress(phase)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            require(self.process.poll() is None, 'Published updater exited before ' + phase)
            time.sleep(.1)
        raise TimeoutError(phase + ': ' + json.dumps([{'title': self.label(h), 'controls': self.controls(h)}
                                                     for h in self.windows()]))

    def wait_window(self, title, seconds=30):
        return self.wait(title, lambda: next((h for h in self.windows() if self.label(h) == title), None), seconds)

    def click(self, handle):
        require(handle and self.user.IsWindowVisible(handle) and self.user.IsWindowEnabled(handle),
                'The requested updater control is not available.')
        left, top, right, bottom = self.bounds(handle)
        x, y = (left + right) // 2, (top + bottom) // 2
        top_window = self.user.GetAncestor(handle, 2)
        self.user.SetForegroundWindow(top_window)
        self.wait('owned updater control foreground', lambda: self.user.GetForegroundWindow() == top_window)
        # NativeUI.mouse uses its own small INPUT wrapper. Build the complete
        # structure here, retaining its actual screen-hit requirement.
        width, height = self.user.GetSystemMetrics(0), self.user.GetSystemMetrics(1)
        require(0 <= x < width and 0 <= y < height, 'Updater button is off the actual desktop.')
        hit = self.user.WindowFromPoint(wintypes.POINT(x, y))
        require(hit == handle or self.user.IsChild(handle, hit), 'Updater control is obscured.')
        for flags in (0x8001, 0x8003, 0x8005):
            value = self.Input()
            value.type = 0
            value.value.mouse.dx, value.value.mouse.dy = round(x * 65535 / (width - 1)), round(y * 65535 / (height - 1))
            value.value.mouse.flags = flags
            require(self.user.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) == 1, 'Updater pointer input failed.')

    def choose(self, folder):
        picker = self.wait_window(PICKER_TITLE)
        self.main = picker
        self.user.SetForegroundWindow(picker)
        self.wait('picker foreground for address entry', lambda: self.user.GetForegroundWindow() == picker)
        self.keyboard.key(0x44, 0x12)  # Alt+D, the standard address-bar shortcut.
        self.wait('address-bar keyboard focus', lambda: self.label(self.keyboard.focus(), True) == 'Edit')
        self.keyboard.key(0x41, 0x11)
        self.keyboard.text(str(folder))
        self.wait('exact selected path entered', lambda: self.label(self.keyboard.focus()) == str(folder))
        self.keyboard.key(0x0D)
        # Re-open the address after navigation and observe the folder Windows
        # actually reached before pressing the launcher's normal confirmation.
        time.sleep(.7)
        self.keyboard.key(0x44, 0x12)
        self.wait('selected folder navigation observed', lambda:
                  self.label(self.keyboard.focus(), True) == 'Edit' and
                  os.path.normcase(self.label(self.keyboard.focus()).rstrip('\\')) ==
                  os.path.normcase(str(folder).rstrip('\\')))
        self.wait('picker still open after observed navigation', lambda: picker in self.windows())
        accept = self.child(1, picker)
        require('Update this Workbench' in self.label(accept), 'Expected published updater confirmation label.')
        self.click(accept)

    def close(self):
        try:
            if hasattr(self, 'process'):
                stop_process_tree(self.process)
        finally:
            self.user.SetThreadDpiAwarenessContext(self.previous_dpi)


def capture(ui, report, filename, owner=None):
    owner = owner or ui.main
    value = ui.capture(filename, owner)
    value['dpi'] = ui.user.GetDpiForWindow(owner)
    report['captures'].append(value)
    write_json(ui.evidence / (Path(filename).stem + '-controls.json'),
               {'title': ui.label(owner), 'bounds': ui.bounds(owner), 'dpi': value['dpi'], 'controls': ui.controls(owner)})


def passed(report, identity, note, **details):
    report['checks'].append(note)
    report['scenarios'].append({'id': identity, 'status': 'pass', 'observedAt': utc(), 'note': note, **details})
    print(json.dumps({'passed': len(report['checks']), 'id': identity}), flush=True)


def failed(report, identity, note, **details):
    report['scenarios'].append({'id': identity, 'status': 'failed', 'observedAt': utc(), 'note': note, **details})
    print(json.dumps({'failed': identity, 'note': note}), flush=True)


def finalize_report(report):
    """Completed observation collection must never turn a product failure green."""
    report['passed'] = sum(row['status'] == 'pass' for row in report['scenarios'])
    report['failed'] = sum(row['status'] == 'failed' for row in report['scenarios'])
    report['blocked'] = sum(row['status'] == 'blocked' for row in report['scenarios'])
    report['success'] = bool(report.get('nativeGUIObservationsCompleted') and report['passed'] and
                             all(row['status'] == 'pass' for row in report['scenarios']))
    report['nativeGUIValidated'] = report['success']


def focus_observation(ui, keys, owner):
    focus = keys.focus()
    return {'foregroundWindow': ui.user.GetForegroundWindow(), 'resultsWindow': owner,
            'focusWindow': focus, 'focusControlId': ui.user.GetDlgCtrlID(focus) if focus else None,
            'focusClass': ui.label(focus, True) if focus else None,
            'focusEnabled': bool(ui.user.IsWindowEnabled(focus)) if focus else None,
            'focusInsideResults': bool(focus and ui.user.IsChild(owner, focus))}


def observe_close(ui, window, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        require(ui.process.poll() is None and ui.user.IsWindowVisible(ui.main),
                'Closing the results window unexpectedly closed the application.')
        if not window():
            return True
        time.sleep(.1)
    return False


def seed_baseline(base, evidence, external):
    record = synthetic_reference(base, external)
    host = PrivateHost(base, evidence, 'baseline-fixtures', offline=True)
    try:
        require(host.call('init')['app_version'] == '0.11.0', 'Fixture host is not the exact published baseline.')
        run = local_reference_run(host, base, evidence, record, 'preserved-reference-result')
        run_id = host.call('history')['runs'][0]['run_id']
        state = host.call('workspace/tool', {'toolId': 'align/paired-end'})
        node = state['graph']['nodes'][0]
        state = host.call('model', {'action': 'apply_fields', 'payload': {
            'nodeId': node['id'], 'params': {'threads': '3'}}})
        node = state['graph']['nodes'][0]
        host.call('save', {'kind': 'preset', 'name': 'Deployment preservation settings', 'nodeId': node['id']})
        host.call('workspace/mode', {'mode': 'workflow'})
        first = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        second = host.call('model', {'action': 'add_tool', 'payload': {'toolId': 'bam/reference-index'}})['selected']
        source = host.call('model', {'action': 'add_input', 'payload': {'inputType': 'reference'}})['selected']
        host.call('model', {'action': 'connect', 'payload': {'nodeId': first, 'portId': 'reference', 'refs': [source]}})
        host.call('model', {'action': 'connect', 'payload': {'nodeId': second, 'portId': 'reference', 'refs': [first + '::reference']}})
        host.call('save', {'kind': 'pipeline', 'name': 'Deployment preservation pipeline'})
    finally:
        host.close()
    saved = read_json(base / 'user-data/saved.json')
    require(len(saved['presets']) == len(saved['pipelines']) == 1 and
            saved['presets'][0]['pin'] == node['pin'] and saved['presets'][0]['params']['threads'] == '3',
            'Separate nondefault settings and exact pipeline pins were not saved.')
    return {'reference': record, 'saved': saved, 'run': run, 'runId': run_id}


def updater_scenario(update, evidence, report, mode, base, invalid):
    ui = UpdaterUI(update, evidence)
    report['nativeGUILaunched'] = True
    try:
        capture(ui, report, 'updater-' + mode + '-picker.bmp')
        if mode == 'cancel':
            ui.keyboard.key(0x1B)
        elif mode == 'invalid':
            ui.choose(invalid)
            warning = ui.wait_window('Choose your existing Workbench')
            text = ' '.join(item['text'] for item in ui.controls(warning))
            require('does not contain the expected Workbench installation' in text and
                    'NativeWorkbench.exe and manifest.json' in text, 'Invalid-folder guidance is missing.')
            capture(ui, report, 'updater-invalid-warning.bmp', warning)
            ui.click(unique_button(ui, warning, 'OK'))
            picker = ui.wait_window(PICKER_TITLE)
            ui.main = picker
            capture(ui, report, 'updater-invalid-retry-picker.bmp', picker)
            ui.user.SetForegroundWindow(picker)
            ui.wait('retry picker foreground', lambda: ui.user.GetForegroundWindow() == picker)
            ui.keyboard.key(0x1B)
        else:
            ui.choose(base)
            success = ui.wait_window('Native Workbench update', seconds=180)
            text = ' '.join(item['text'] for item in ui.controls(success))
            require('The Workbench update is installed.' in text and 'NativeWorkbench.exe' in text,
                    'Published updater did not show its actual success dialog: ' + text)
            capture(ui, report, 'updater-' + mode + '-success.bmp', success)
            ui.click(unique_button(ui, success, 'OK'))
        require(ui.process.wait(timeout=30) == 0, 'Published updater did not exit successfully.')
    except Exception:
        for number, window in enumerate(ui.windows()):
            capture(ui, report, 'updater-' + mode + '-failure-%d.bmp' % number, window)
        raise
    finally:
        ui.close()


def desktop_scenarios(root, evidence, report, label):
    ui = NativeUI(root, evidence)
    keys = Keyboard(ui)
    try:
        ui.wait(label + ' desktop ready', lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        setup_window = lambda: next((h for h in ui.windows() if ui.label(h) == 'Tool setup · Native Workbench'), None)
        # A genuinely fresh installation normally offers setup above the main
        # window. Its normal Starter/Use Workbench controls must be exercised
        # before attempting to interact with the obscured library beneath it.
        if label == 'fresh':
            ui.wait('fresh installation offers its native tool setup', setup_window)
        else:
            ui.wait('upgraded desktop startup requests complete', lambda: ui.user.IsWindowEnabled(ui.child(417)))
        setup = setup_window()
        report.setdefault('startupSetup', {})[label] = {'observed': bool(setup)}
        if setup:
            pack_snapshot = tree_hashes(root / 'packs')
            starter = unique_button(ui, setup, 'Starter')
            left, top, right, bottom = ui.bounds(starter)
            ui.click_at((left + right) // 2, (top + bottom) // 2, expected=starter)
            ui.wait('Starter radio visibly selected', lambda: ui.send(starter, 0x00F0) == 1)  # BM_GETCHECK.
            capture(ui, report, label + '-first-open-starter.bmp', setup)
            use = unique_button(ui, setup, 'Use Workbench')
            left, top, right, bottom = ui.bounds(use)
            ui.click_at((left + right) // 2, (top + bottom) // 2, expected=use)
            state_path = root / 'user-data/tool-setup.json'
            ui.wait('Use Workbench closes setup and records dismissal', lambda:
                    not setup_window() and state_path.is_file() and read_json(state_path)['dismissed'])
            state = read_json(state_path)
            require(not state['queue'] and not state['operation']['active'] and
                    state['operation']['status'] == 'idle' and tree_hashes(root / 'packs') == pack_snapshot,
                    'Continuing from first-open setup queued work or changed installed packs.')
            report['startupSetup'][label].update(starterRadioSelected=True, dismissed=True,
                                                queuedInstalls=0, installedPackFilesUnchanged=len(pack_snapshot))
            passed(report, label + '-first-open-setup', label + ': actual first-open setup accepts the Starter radio and Use Workbench, with no queued installs or changed installed pack files.')
        ui.wait(label + ' unobscured desktop ready', lambda: ui.user.IsWindowEnabled(ui.child(417)))
        search = ui.child(102)
        left, top, right, bottom = ui.bounds(search)
        ui.click_at((left + right) // 2, (top + bottom) // 2, expected=search)
        ui.wait('physical library click delivers search focus', lambda: keys.focus() == search)
        keys.key(0x41, 0x11)
        keys.text('reference')
        ui.wait('real keyboard library search', lambda: ui.label(search) == 'reference' and ui.library().tools())
        keys.key(0x09)
        ui.wait('Tab advances focus', lambda: keys.focus() not in (None, search))
        next_focus = keys.focus()
        require(ui.user.IsChild(ui.main, next_focus) and ui.user.IsWindowVisible(next_focus) and
                ui.user.IsWindowEnabled(next_focus), 'Tab moved to unavailable or foreign control.')
        capture(ui, report, label + '-keyboard-focus.bmp')
        keys.key(0x09, 0x10)
        ui.wait('Shift+Tab restores search focus', lambda: keys.focus() == search)
        keys.key(0x41, 0x11)
        keys.key(0x08)
        ui.wait('keyboard search cleared', lambda: not ui.label(search) and ui.library().tools())
        passed(report, label + '-keyboard-focus', label + ': real keyboard text filters the library; Tab moves to an enabled visible owned control and Shift+Tab returns to search.', nextControlId=ui.user.GetDlgCtrlID(next_focus))
        layouts = []
        for width, height in [(1040, 680), (1280, 900)]:
            ui.fit_window(width, height)
            bounds = ui.bounds(ui.main)
            measured = []
            for identity in (102, 104, 410, 411, 417):
                handle = ui.child(identity)
                rect = ui.bounds(handle)
                require(ui.user.IsWindowVisible(handle) and rect[2] > rect[0] and rect[3] > rect[1] and
                        bounds[0] <= rect[0] < rect[2] <= bounds[2] and bounds[1] <= rect[1] < rect[3] <= bounds[3],
                        'Fixed library/navigation control lies outside resized desktop: ' + str(identity))
                measured.append({'id': identity, 'bounds': rect})
            area = ui.work_area()
            layouts.append({'requestedSize': [width, height], 'windowBounds': bounds, 'controls': measured,
                            'workArea': area, 'horizontalClipping': bounds[0] < area[0] or bounds[2] > area[2]})
            capture(ui, report, label + '-resize-%dx%d.bmp' % (width, height))
        if any(row['horizontalClipping'] for row in layouts):
            limitation = ('The observed desktop is narrower than the published application minimum width; '
                          'the window edge is horizontally clipped. Requested and actual sizes are recorded; '
                          'these checks do not establish acceptance on that narrower display.')
            if limitation not in report['limits']:
                report['limits'].append(limitation)
        passed(report, label + '-resize', label + ': library and fixed navigation remain visible within both observed resized windows.', layouts=layouts)
        ui.click_button(417)
        title = 'Recorded results · Native Workbench'
        window = lambda: next((h for h in ui.windows() if ui.label(h) == title), None)
        ui.wait('results dialog opened through native button', window)
        owner = window()
        query = ui.child(1501, owner)
        left, top, right, bottom = ui.bounds(query)
        ui.click_at((left + right) // 2, (top + bottom) // 2, expected=query)
        ui.wait('physical results click delivers query focus', lambda: keys.focus() == query)
        keys.text('deployment-no-matching-result')
        ui.wait('results query entered by real keyboard', lambda: ui.label(query) == 'deployment-no-matching-result')
        keys.key(0x09)
        ui.wait('Tab reaches result Search button', lambda: keys.focus() == ui.child(1502, owner))
        keys.key(0x20)
        ui.wait('keyboard search reports no results', lambda: ui.send(ui.child(1503, owner), 0x1004) == 0 and
                ui.user.IsWindowEnabled(ui.child(1502, owner)) and
                ui.label(ui.child(1504, owner)) ==
                'No matching recorded analyses. Clear the search and press Search to show recent runs.')
        require(not ui.user.IsWindowEnabled(ui.child(1505, owner)), 'Empty result search left View enabled.')
        capture(ui, report, label + '-results-keyboard.bmp', owner)
        passed(report, label + '-results-keyboard', label + ': keyboard query, Tab and Space operate results search, report zero matches and disable View.')
        observation = {'beforeEscape': focus_observation(ui, keys, owner)}
        report.setdefault('resultsEscape', {})[label] = observation
        keys.key(0x1B)
        closed = observe_close(ui, window)
        observation.update(closedAfterKeyboardSearch=closed, afterEscape=focus_observation(ui, keys, owner))
        if closed:
            passed(report, label + '-results-escape', label + ': Escape immediately after keyboard search closes only the results window.')
        else:
            failed(report, label + '-results-escape', label + ': real Escape after keyboard Search leaves the published results window open; this keyboard acceptance requirement failed.')
            capture(ui, report, label + '-results-escape-failed.bmp', owner)
            screen, _ = ui.screen_capture(label + '-results-escape-visible-screen.bmp', ui.bounds(owner))
            screen['dpi'] = ui.user.GetDpiForWindow(owner)
            report['captures'].append(screen)
            limitation = ('Published 0.16.0 results-window Escape after keyboard Search failed in this gate. '
                          'Any subsequent focus diagnostic or Close-button workaround does not satisfy that failed requirement.')
            if limitation not in report['limits']:
                report['limits'].append(limitation)
            # Diagnose a possible focus loss without replacing the failed
            # natural keyboard interaction above. This is a separate physical
            # click into the query, followed by a second genuine Escape key.
            left, top, right, bottom = ui.bounds(query)
            ui.click_at((left + right) // 2, (top + bottom) // 2, expected=query)
            ui.wait('diagnostic physical click delivers query focus', lambda: keys.focus() == query)
            diagnostic = {'scope': 'Additional explicit-focus diagnostic; does not replace original failed Escape.',
                          'beforeEscape': focus_observation(ui, keys, owner)}
            require(diagnostic['beforeEscape']['focusWindow'] == query, 'Diagnostic pointer click did not focus the query.')
            keys.key(0x1B)
            diagnostic['closed'] = observe_close(ui, window)
            diagnostic['afterEscape'] = focus_observation(ui, keys, owner)
            observation['explicitQueryFocusDiagnostic'] = diagnostic
            if not diagnostic['closed']:
                capture(ui, report, label + '-results-focused-escape-failed.bmp', owner)
                close_button = unique_button(ui, owner, 'Close')
                left, top, right, bottom = ui.bounds(close_button)
                ui.click_at((left + right) // 2, (top + bottom) // 2, expected=close_button)
                ui.wait('visible Close button closes results and retains desktop', lambda:
                        not window() and ui.user.IsWindowVisible(ui.main))
                observation['visibleCloseButtonFallback'] = {'tested': True, 'closed': True}
                passed(report, label + '-results-close-fallback', label + ': after the recorded Escape failure, physically clicking the visible Close button closes results and retains the desktop.')
            else:
                observation['visibleCloseButtonFallback'] = {'tested': False}
    except Exception:
        for number, window in enumerate(ui.windows()):
            capture(ui, report, label + '-failure-%d.bmp' % number, window)
        raise
    finally:
        ui.close()


def run(args, report):
    require(os.name == 'nt', 'Native Windows is unavailable; this gate cannot pass.')
    require(args.source_commit == SOURCE_COMMIT and re.fullmatch('[0-9a-f]{40}', args.gate_commit), 'Exact source/gate identities required.')
    target, update_input, work, evidence = args.app_root.resolve(), args.update_root.resolve(), args.work.resolve(), args.report.resolve().parent
    require(Path(sys.executable).resolve() == (target / 'runtime/python/python.exe').resolve(), 'Use the exact Starter private interpreter.')
    require(not work.exists() and all(not work.is_relative_to(root) and not root.is_relative_to(work)
                                    for root in (target, update_input)), 'Use a new, separate disposable work directory.')
    if args.bundle_root:
        from deployment_acceptance import verify_bundle
        bundle = verify_bundle(args.bundle_root, args.bundle_manifest_sha256)
        require(bundle['sourceCommit'] == args.source_commit and bundle['toolkitCommit'] == args.gate_commit,
                'Gate/source identities differ from verified deployment bundle.')
        args.bundle_manifest_sha256 = bundle['manifestSha256']
        report['bundleManifestSha256'] = bundle['manifestSha256']
    for role, path, expected in [('starter', args.starter_archive, STARTER_SHA), ('baseline', args.baseline_archive, BASELINE_SHA), ('update', args.update_archive, UPDATE_SHA)]:
        require(sha256(path) == expected, 'Wrong published ' + role + ' archive.')
        report['archives'][role] = {'name': path.name, 'bytes': path.stat().st_size, 'sha256': expected}
    report['archiveFilesVerified'] = {'starter': verify_extracted(args.starter_archive, target), 'update': verify_extracted(args.update_archive, update_input)}
    work.mkdir(parents=True)
    update = work / 'updater'
    shutil.copytree(update_input, update)
    updater_snapshot = tree_hashes(update_input)
    require(tree_hashes(update) == updater_snapshot, 'Disposable updater copy differs from verified bundle input.')
    extract(args.baseline_archive, work / 'baseline')
    base, external = work / 'baseline/native-workbench', work / 'external references'
    invalid = work / 'not a Workbench installation'
    invalid.mkdir()
    # Explicit bytes prevent Windows text-mode CRLF translation from making
    # the preservation oracle disagree with its own freshly created fixture.
    (invalid / 'keep.txt').write_bytes(b'Invalid folder must remain unchanged.\n')
    target_manifest = read_json(target / 'manifest.json')
    require(target_manifest['version'] == '0.16.0' and len(target_manifest['files']) == 87, 'Unexpected published target manifest.')
    verify_inventory(target, target_manifest['files'])
    verify_inventory(base, read_json(base / 'manifest.json')['files'])
    verify_inventory(update, read_json(update / 'update-inventory.json')['files'])
    report['publishedLauncherSha256'] = sha256(update / 'UpdateWorkbench.exe')
    passed(report, 'published-input-identities', 'Every extracted Starter and updater archive file matches its pinned published archive; the unchanged published launcher is exercised.')
    fixtures = seed_baseline(base, evidence, external)
    report['nativeWindowsExecuted'] = True
    report['baselineFixtures'] = fixtures
    saved_bytes = (base / 'user-data/saved.json').read_bytes()
    preserved = preserved_files(base, external)
    write_json(evidence / 'picker-preservation-before.json', preserved)
    passed(report, 'baseline-fixtures', 'Published 0.11.0 executes a local native SAMtools reference result and saves independent settings plus connected pipeline pins.')
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
        passed(report, 'updater-' + scenario, 'Published folder picker ' + ('cancels with Escape' if scenario == 'cancel' else 'rejects a real non-installation folder, explains the required files, reopens for retry and allows Escape') + ' with every baseline/reference/invalid-folder file unchanged.')
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
    require(transaction['status'] == 'installed' and transaction['version'] == '0.16.0' and
            transaction['files_verified'] == 87 and transaction['packs_changed'] is False,
            'Published launcher did not finish a verified core update.')
    report['transaction'] = transaction
    report['coreFilesVerified'] = 87
    report['preservedFiles'] = len(preserved)
    passed(report, 'updater-install', 'Selecting the actual baseline through the published folder picker displays success, commits all 87 exact Starter core files, and preserves every recorded pack/user/result/reference file.')
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
        require(host.call('init')['app_version'] == '0.16.0', 'Updated host version differs.')
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
    desktop_scenarios(target, evidence, report, 'fresh')
    desktop_scenarios(base, evidence, report, 'upgraded')
    verify_inventory(target, target_manifest['files'])
    verify_inventory(base, target_manifest['files'])
    require(tree_hashes(update_input) == updater_snapshot, 'Immutable original updater input changed.')
    if args.bundle_root:
        verify_bundle(args.bundle_root, args.bundle_manifest_sha256)
    report['observedDpi'] = sorted({row['dpi'] for row in report['captures']})
    report['nativeWindowsExecuted'] = True
    report['nativeGUIObservationsCompleted'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('app-root', 'baseline-archive', 'update-root', 'starter-archive', 'update-archive', 'work', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('source-commit', 'gate-commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--bundle-manifest-sha256')
    parser.add_argument('--bundle-root', type=Path)
    args = parser.parse_args()
    validate_destinations(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'kind': 'native-deployment-ui', 'success': False,
              'sourceCommit': args.source_commit, 'gateCommit': args.gate_commit, 'gateSha256': sha256(__file__),
              'platform': platform.platform(), 'startedUtc': utc(), 'archives': {}, 'checks': [],
              'scenarios': [], 'captures': [], 'skips': [], 'limits': list(LIMITS),
              'nativeWindowsExecuted': False, 'nativeGUILaunched': False, 'nativeGUIValidated': False,
              'nativeGUIObservationsCompleted': False}
    try:
        run(args, report)
    except Exception as error:
        report['failure'] = str(error)
        report['traceback'] = traceback.format_exc()
        report['scenarios'].append({'id': 'gate-completion', 'status': 'blocked' if os.name != 'nt' else 'failed',
                                    'observedAt': utc(), 'note': 'Native gate did not complete; review retained raw diagnostics.'})
    finally:
        report['finishedUtc'] = utc()
        finalize_report(report)
        write_json(args.report, report)
        if args.bundle_manifest_sha256:
            require(re.fullmatch('[0-9a-f]{64}', args.bundle_manifest_sha256), 'Invalid bundle manifest identity.')
            summary = {'schemaVersion': 1, 'kind': 'native-deployment-gate', 'sourceCommit': args.source_commit,
                       'toolkitCommit': args.gate_commit, 'bundleManifestSha256': args.bundle_manifest_sha256,
                       'observedAt': report['finishedUtc'], 'checks': [
                           {key: row[key] for key in ('id', 'status', 'observedAt', 'note')} for row in report['scenarios']],
                       'limits': report['limits']}
            write_json(args.report.parent / 'native-deployment-gate.json', summary)
    print(json.dumps({'success': report['success'], 'passed': report['passed'], 'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
