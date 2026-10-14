#!/usr/bin/env python3
"""Observe native viewport class compatibility; this is not UI acceptance.

Create isolated diagnostic windows with the application's exact viewport styles.
Compare the predefined STATIC class with an explicitly registered style-0 class.
No application is launched, inspected, modified or repaired by this probe.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import traceback


def probe(report):
    if os.name != 'nt':
        raise RuntimeError('This diagnostic requires native Windows.')
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class WindowClass(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                    ('lpfnWndProc', ctypes.c_void_p), ('cbClsExtra', ctypes.c_int),
                    ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                    ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                    ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                    ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]

    kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    user.RegisterClassExW.argtypes = [ctypes.POINTER(WindowClass)]
    user.RegisterClassExW.restype = wintypes.ATOM
    user.GetClassInfoExW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                   ctypes.POINTER(WindowClass)]
    user.GetClassInfoExW.restype = wintypes.BOOL
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.DestroyWindow.restype = wintypes.BOOL
    user.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user.UnregisterClassW.restype = wintypes.BOOL
    user.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
    user.DefWindowProcW.restype = ctypes.c_ssize_t
    user.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user.LoadCursorW.restype = wintypes.HANDLE
    instance = kernel.GetModuleHandleW(None)
    if not instance:
        raise ctypes.WinError(ctypes.get_last_error())
    classes, windows = [], []
    report['cleanup'] = []

    def native_call(function, *args):
        ctypes.set_last_error(0)
        value = function(*args)
        error = ctypes.get_last_error()
        return value, {'succeeded': bool(value), 'lastErrorAfterCall': error,
                       'errorMeaningful': not bool(value),
                       'failureMessage': ctypes.FormatError(error).strip() if not value else None}

    def register(name):
        value = WindowClass()
        value.cbSize = ctypes.sizeof(value)
        value.style = 0
        value.lpfnWndProc = ctypes.cast(user.DefWindowProcW, ctypes.c_void_p).value
        value.hInstance = instance
        value.hCursor = user.LoadCursorW(None, 32512)  # IDC_ARROW
        value.lpszClassName = name
        atom, detail = native_call(user.RegisterClassExW, ctypes.byref(value))
        if not atom:
            raise RuntimeError('Cannot register diagnostic class: ' + str(detail))
        classes.append(name)

    def class_info(name, owner):
        value = WindowClass()
        value.cbSize = ctypes.sizeof(value)
        ok, detail = native_call(user.GetClassInfoExW, owner, name, ctypes.byref(value))
        detail.update({'name': name, 'style': int(value.style),
                       'styleHex': hex(value.style),
                       'ownDC': bool(value.style & 0x20),
                       'classDC': bool(value.style & 0x40),
                       'parentDC': bool(value.style & 0x80)})
        if not ok:
            raise RuntimeError('Cannot inspect native class: ' + str(detail))
        return detail

    try:
        parent_class = 'WorkbenchClassProbeParent' + str(os.getpid())
        viewport_class = 'WorkbenchClassProbeViewport' + str(os.getpid())
        register(parent_class)
        register(viewport_class)
        report['classes'] = [class_info('STATIC', None),
                             class_info(viewport_class, instance)]
        # Match the application's parent class/style. Keep this unrelated parent
        # hidden so diagnostic windows cannot overlap native acceptance captures.
        parent, detail = native_call(user.CreateWindowExW, 0x00010000, parent_class,
            'Isolated class compatibility diagnostic', 0x00cf0000 | 0x02000000,
            0, 0, 320, 240, None, None, instance, None)
        report['parentCreation'] = detail
        if not parent:
            raise RuntimeError('Cannot create diagnostic parent: ' + str(detail))
        windows.append(parent)
        styles = 0x40000000 | 0x10000000 | 0x04000000 | 0x00200000 | 0x02000000
        ex_styles = 0x00000200 | 0x00010000 | 0x02000000
        report['viewportStyles'] = {'style': styles, 'styleHex': hex(styles),
                                    'exStyle': ex_styles, 'exStyleHex': hex(ex_styles),
                                    'controlId': 430, 'initialSize': [1, 1]}
        report['creations'] = []
        for name in ('STATIC', viewport_class):
            child, detail = native_call(user.CreateWindowExW, ex_styles, name, '',
                                       styles, 0, 0, 1, 1, parent, 430, instance, None)
            detail.update({'className': name, 'handle': int(child or 0)})
            report['creations'].append(detail)
            if child:
                windows.append(child)
        old, new = report['creations']
        report['oldCreationFailedAndStyleZeroSucceeded'] = not old['succeeded'] and new['succeeded']
        if not new['succeeded']:
            raise RuntimeError('Registered style-0 viewport creation failed: ' + str(new))
        report['diagnosticCompleted'] = True
    finally:
        for window in reversed(windows):
            _, detail = native_call(user.DestroyWindow, window)
            report['cleanup'].append({'operation': 'DestroyWindow', 'handle': int(window), **detail})
        for name in reversed(classes):
            _, detail = native_call(user.UnregisterClassW, name, instance)
            report['cleanup'].append({'operation': 'UnregisterClassW', 'className': name, **detail})
        if any(not entry['succeeded'] for entry in report['cleanup']):
            report['diagnosticCompleted'] = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--gate-commit', required=True)
    args = parser.parse_args()
    report = {'schema': 1, 'kind': 'viewport-class-compatibility-diagnostic-not-acceptance',
              'nativeGUIValidated': False, 'diagnosticCompleted': False,
              'utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'pointerBits': ctypes.sizeof(ctypes.c_void_p) * 8,
              'sourceCommit': args.source_commit, 'gateCommit': args.gate_commit,
              'scope': 'Isolated native class/window creation; no application launch or mutation.'}
    try:
        probe(report)
    except Exception as error:
        report.update({'diagnosticCompleted': False, 'error': str(error),
                       'traceback': traceback.format_exc()})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['diagnosticCompleted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
