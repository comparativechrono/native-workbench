#!/usr/bin/env python3
"""Check the exact installed native three-pane desktop, never a browser mock.

Run on native Windows using this disposable application's isolated bundled Python.
The gate owns its GUI process, saves pixel captures and observed control bounds,
and verifies session/connection contracts against the installed private host.
It never modifies published artifacts or asserts unsupported DPI coverage.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import time
import traceback

# The helper is gate infrastructure from the same checked-out gate commit.
# Application imports/execution still come exclusively from --app-root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, stop_process_tree, write_json
from native_tree import NativeTree


class NativeUI:
    def __init__(self, root, evidence):
        self.root, self.evidence = root, evidence
        self.user = u = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = g = ctypes.WinDLL("gdi32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.previous_dpi = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.restype = wintypes.UINT
        u.EnumWindows.argtypes = [self.callback, wintypes.LPARAM]
        u.EnumChildWindows.argtypes = [wintypes.HWND, self.callback, wintypes.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetDlgCtrlID.argtypes = [wintypes.HWND]
        u.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetDlgItem.restype = wintypes.HWND
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowEnabled.argtypes = [wintypes.HWND]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        class ScrollInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("fMask", wintypes.UINT),
                        ("nMin", ctypes.c_int), ("nMax", ctypes.c_int),
                        ("nPage", wintypes.UINT), ("nPos", ctypes.c_int), ("nTrackPos", ctypes.c_int)]
        self.ScrollInfo = ScrollInfo
        u.GetScrollInfo.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.POINTER(ScrollInfo)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                         wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_size_t)]
        u.SendMessageTimeoutW.restype = wintypes.LPARAM
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        u.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
        u.GetAncestor.argtypes, u.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
        u.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetDC.argtypes = [wintypes.HWND]
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        g.SelectObject.restype = wintypes.HANDLE
        g.DeleteObject.argtypes = [wintypes.HANDLE]
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.BitBlt.restype = wintypes.BOOL
        u.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        u.RedrawWindow.restype = wintypes.BOOL
        g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        class InputUnion(ctypes.Union):
            _fields_ = [("mi", MouseInput)]
        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]
        self.Input, self.MouseInput = Input, MouseInput
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT
        self.process = subprocess.Popen([str(root / "NativeWorkbench.exe")], cwd=root)
        self.main = None
        try:
            self.wait("native main window", lambda: self.find_main())
            u.ShowWindow(self.main, 9)
            bounds = self.bounds(self.main)
            self.fit_window(bounds[2] - bounds[0], bounds[3] - bounds[1])
            u.SetForegroundWindow(self.main)
        except Exception:
            stop_process_tree(self.process)
            u.SetThreadDpiAwarenessContext(self.previous_dpi)
            raise

    def progress(self, phase, **details):
        value = {"phase": phase, "updatedUtc": datetime.now(timezone.utc).isoformat(), **details}
        write_json(self.evidence / "ui-progress.json", value)
        with (self.evidence / "ui-events.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(value, ensure_ascii=False) + "\n")
        print(json.dumps(value), flush=True)

    def send(self, hwnd, message, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        require(self.user.SendMessageTimeoutW(hwnd, message, wparam, lparam, 3, 5000, ctypes.byref(result)),
                "Native message timed out or failed: " + hex(message))
        return result.value

    def post(self, hwnd, message, wparam=0, lparam=0):
        require(self.user.PostMessageW(hwnd, message, wparam, lparam), "Could not queue native input.")

    def label(self, hwnd, class_name=False):
        # GetClassNameW rejects the oversized 32768-WCHAR text buffer on the
        # native runner. Class names use their own bounded buffer and a checked
        # return value so an automation failure cannot masquerade as missing UI.
        buffer = ctypes.create_unicode_buffer(1024 if class_name else 32768)
        if class_name:
            ctypes.set_last_error(0)
            require(self.user.GetClassNameW(hwnd, buffer, len(buffer)) > 0,
                    "Could not read native window class: hwnd=" + str(hwnd) +
                    " winerror=" + str(ctypes.get_last_error()))
        else:
            self.send(hwnd, 0x000D, len(buffer), ctypes.addressof(buffer))
        return buffer.value

    def set_text(self, hwnd, value):
        # Focus the real edit before replacing its text. Otherwise rapid native
        # row clicks separated only by WM_SETTEXT are interpreted by Windows as
        # a double-click at the unchanged pointer location, unlike a person
        # clicking the search field before editing it.
        require(hwnd, "The native edit does not exist.")
        # A preceding model commit can temporarily disable this same edit.
        # Match click_button's bounded availability wait; never send text to a
        # hidden/disabled control or bypass the actual native input path.
        self.wait("native edit ready for input", lambda:
                  self.user.IsWindowVisible(hwnd) and self.user.IsWindowEnabled(hwnd))
        left, top, right, bottom = self.bounds(hwnd)
        self.click_at((left + right) // 2, (top + bottom) // 2, expected=hwnd)
        buffer = ctypes.create_unicode_buffer(str(value))
        require(self.send(hwnd, 0x000C, 0, ctypes.addressof(buffer)), "Could not set native edit text.")

    def windows(self):
        found = []
        @self.callback
        def each(hwnd, _):
            owner = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == self.process.pid and self.user.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        self.user.EnumWindows(each, 0)
        return found

    def find_main(self):
        for hwnd in self.windows():
            if self.label(hwnd) == "Native Workbench":
                self.main = hwnd
                return hwnd
        return None

    def child(self, identity, owner=None):
        owner = owner or self.main
        direct = self.user.GetDlgItem(owner, identity)
        if direct:
            return direct
        found = []
        @self.callback
        def each(hwnd, _):
            if self.user.GetDlgCtrlID(hwnd) == identity:
                found.append(hwnd)
                return False
            return True
        self.user.EnumChildWindows(owner, each, 0)
        return found[0] if found else None

    def library(self):
        if self.label(self.child(104), True) == "SysListView32":
            # Retain the historical flat-library path only for exact published
            # baseline diagnostics (e.g. the scroll-frame comparison).
            ui = self
            class LegacyLibrary:
                def tools(self):
                    return list(range(1, ui.send(ui.child(104), 0x1004) + 1))
                def first_tool_point(self):
                    require(len(self.tools()) == 1, "Expected one filtered baseline tool.")
                    tasks = ui.child(104)
                    left, top, right, _ = ui.bounds(tasks)
                    scale = ui.user.GetDpiForWindow(ui.main) / 96
                    header = ui.send(tasks, 0x101F)
                    y = ui.bounds(header)[3] + round(11*scale) if header and ui.user.IsWindowVisible(header) else top + round(13*scale)
                    return left + min(round(70*scale), (right-left)//2), y
            return LegacyLibrary()
        return NativeTree(self.user, self.send, self.process.pid, self.child(104))

    def bounds(self, hwnd):
        rect = wintypes.RECT()
        require(self.user.GetWindowRect(hwnd, ctypes.byref(rect)), "Could not measure native control.")
        return [rect.left, rect.top, rect.right, rect.bottom]

    def work_area(self):
        area = wintypes.RECT()
        require(self.user.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0),
                "Could not inspect the desktop work area.")  # SPI_GETWORKAREA excludes the taskbar.
        return [area.left, area.top, area.right, area.bottom]

    def fit_window(self, width, height):
        """Place the test window above the taskbar; retain observed dimensions.

        The application's minimum width can exceed a small CI desktop. Do not
        invent a larger desktop: each pointer target must still be visible and
        hit the tested process. Native min/max sizing remains in force.
        """
        left, top, right, bottom = self.work_area()
        require(self.user.MoveWindow(self.main, left, top, min(width, right-left), min(height, bottom-top), True),
                "Could not position the native window in the desktop work area.")
        actual = self.bounds(self.main)
        require(actual[1] >= top and actual[3] <= bottom,
                "The native window's minimum height does not fit above this desktop's taskbar.")
        self.progress("native window positioned above taskbar", requestedSize=[width, height],
                      workArea=[left, top, right, bottom], actualWindowBounds=actual,
                      horizontalClipping=actual[0] < left or actual[2] > right)

    def desktop_evidence(self, phase, **details):
        """Retain actual displayed pixels and owned windows, including overlays."""
        foreground = self.user.GetForegroundWindow()
        observed = [{"hwnd": hwnd, "class": self.label(hwnd, True), "text": self.label(hwnd),
                     "bounds": self.bounds(hwnd)} for hwnd in self.windows()]
        self.progress(phase, foreground=foreground, workArea=self.work_area(), windows=observed, **details)
        self.screen_capture("visible-desktop-failure.bmp", [0, 0, self.user.GetSystemMetrics(0), self.user.GetSystemMetrics(1)])

    def controls(self, owner=None):
        found = []
        @self.callback
        def each(hwnd, _):
            if self.user.IsWindowVisible(hwnd):
                found.append({"id": self.user.GetDlgCtrlID(hwnd), "class": self.label(hwnd, True),
                              "text": self.label(hwnd), "bounds": self.bounds(hwnd), "hwnd": hwnd})
            return True
        self.user.EnumChildWindows(owner or self.main, each, 0)
        return found

    def wait(self, phase, predicate, seconds=30):
        self.progress(phase)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "Native desktop exited unexpectedly.")
            dialogs = [h for h in self.windows() if self.label(h, True) == "#32770"]
            require(not dialogs, "Unexpected native dialog: " + json.dumps([self.controls(h) for h in dialogs]))
            if predicate():
                return
            time.sleep(.1)
        if self.main:
            self.capture("failure.bmp")
            self.desktop_evidence(phase + " desktop timeout")
            self.progress(phase + " timed out", controls=self.controls())
        raise TimeoutError(phase)

    def click_button(self, identity):
        hwnd = self.child(identity)
        self.wait("native button " + str(identity), lambda:
                  hwnd and self.user.IsWindowVisible(hwnd) and self.user.IsWindowEnabled(hwnd))
        # Use a real pointer click for navigation too. A BM_CLICK between two
        # physical clicks on the same library row leaves Windows' double-click
        # sequence intact and does not reproduce a person's mode switch.
        left, top, right, bottom = self.bounds(hwnd)
        self.click_at((left + right) // 2, (top + bottom) // 2, expected=hwnd)

    def key(self, hwnd, code):
        self.post(hwnd, 0x0100, code, 1)
        self.post(hwnd, 0x0101, code, 0xC0000001)

    def mouse(self, x, y, flags=0):
        # Documented SendInput absolute screen coordinates, genuine pointer flow.
        width, height = self.user.GetSystemMetrics(0), self.user.GetSystemMetrics(1)
        require(0 <= x < width and 0 <= y < height, "Pointer target is outside the actual desktop.")
        item = self.Input()
        item.type = 0
        item.data.mi = self.MouseInput(round(x * 65535 / (width - 1)), round(y * 65535 / (height - 1)),
                                       0, 0x8001 | flags, 0, 0)
        require(self.user.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) == 1,
                "Native pointer input was unavailable; do not count drag as passed.")

    def scroll_info(self, hwnd, bar=1):
        value = self.ScrollInfo()
        value.cbSize, value.fMask = ctypes.sizeof(value), 0x17
        require(self.user.GetScrollInfo(hwnd, bar, ctypes.byref(value)), "Could not inspect native scroll state.")
        return {key: getattr(value, key) for key in ("nMin", "nMax", "nPage", "nPos")}

    def click_at(self, x, y, expected=None):
        # PrintWindow can show a perfectly drawn control under the taskbar or
        # another top-level window. Check its actual screen hit before clicking.
        if expected:
            top_window = self.user.GetAncestor(expected, 2)  # GA_ROOT.
            if self.user.GetForegroundWindow() != top_window:
                self.user.SetForegroundWindow(top_window)
                self.wait("native input window in foreground", lambda:
                          self.user.GetForegroundWindow() == top_window)
        target = self.user.WindowFromPoint(wintypes.POINT(x, y))
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(target, ctypes.byref(owner))
        left, top, right, bottom = self.work_area()
        expected_hit = not expected or target == expected or self.user.IsChild(expected, target)
        if not (left <= x < right and top <= y < bottom and owner.value == self.process.pid and expected_hit):
            self.desktop_evidence("pointer target is occluded or outside work area", pointer=[x, y],
                                  hitWindow=target, hitProcess=owner.value, expectedWindow=expected)
            raise AssertionError("Native pointer target is not an unobscured application surface.")
        self.mouse(x, y)
        self.mouse(x, y, 2)
        self.mouse(x, y, 4)

    def drag(self, start, finish):
        self.mouse(*start)
        self.mouse(*start, 2)
        try:
            for step in range(1, 17):
                point = [round(a + (b - a) * step / 16) for a, b in zip(start, finish)]
                self.mouse(*point)
                time.sleep(.035)
        finally:
            self.mouse(*finish, 4)

    def screen_capture(self, filename, bounds):
        """Read visible desktop pixels with BitBlt, without asking the app to paint."""
        left, top, right, bottom = bounds
        width, height = right-left, bottom-top
        require(0 <= left < right <= self.user.GetSystemMetrics(0) and
                0 <= top < bottom <= self.user.GetSystemMetrics(1), "Screen capture rectangle is off desktop.")
        dc = self.user.GetDC(None)
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, width, height)
        old = self.gdi.SelectObject(memory, bitmap)
        try:
            require(self.gdi.BitBlt(memory, 0, 0, width, height, dc, left, top, 0x00CC0020),
                    "Could not capture displayed pixels without repainting.")
            header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
            info = ctypes.create_string_buffer(header + bytes(1024))
            pixels = ctypes.create_string_buffer(width*height*4)
            self.gdi.SelectObject(memory, old)
            require(self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) == height,
                    "Actual screen pixel read failed.")
            raw = pixels.raw
            path = self.evidence / filename
            path.write_bytes(struct.pack("<2sIHHI", b"BM", 54+len(raw), 0, 0, 54) + header + raw)
            return {"path": filename, "width": width, "height": height, "sha256": sha256(path),
                    "method": "screen BitBlt; no PrintWindow repaint"}, raw
        finally:
            self.gdi.SelectObject(memory, old)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(None, dc)

    def wheel(self, x, y, delta):
        self.mouse(x, y)
        item = self.Input()
        item.type = 0
        item.data.mi = self.MouseInput(0, 0, delta & 0xffffffff, 0x0800, 0, 0)
        require(self.user.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) == 1,
                "Native wheel input was unavailable.")

    def capture(self, filename, owner=None):
        hwnd = owner or self.main
        path = self.evidence / filename
        left, top, right, bottom = self.bounds(hwnd)
        width, height = right-left, bottom-top
        dc = self.user.GetDC(hwnd)
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, width, height)
        old = self.gdi.SelectObject(memory, bitmap)
        try:
            require(self.user.PrintWindow(hwnd, memory, 0), "Native pixel capture failed.")
            header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
            info = ctypes.create_string_buffer(header + bytes(1024))
            pixels = ctypes.create_string_buffer(width*height*4)
            self.gdi.SelectObject(memory, old)
            require(self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) == height,
                    "Native screenshot pixel read failed.")
            raw = pixels.raw
            require(len(set(raw[::4])) > 4, "Native pixel capture appears blank.")
            path.write_bytes(struct.pack("<2sIHHI", b"BM", 54+len(raw), 0, 0, 54) + header + raw)
            return {"path": filename, "width": width, "height": height, "sha256": sha256(path)}
        finally:
            self.gdi.SelectObject(memory, old)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(hwnd, dc)

    def close(self):
        try:
            if self.main and self.process.poll() is None:
                self.post(self.main, 0x0010)
                require(self.process.wait(timeout=30) == 0, "Native desktop did not close cleanly.")
        finally:
            stop_process_tree(self.process)
            self.user.SetThreadDpiAwarenessContext(self.previous_dpi)
            log = self.root / "user-data" / "desktop-host.stderr.txt"
            if log.is_file():
                shutil.copyfile(log, self.evidence / "ui-desktop-host.stderr.txt")


def host_contracts(root, evidence):
    host = PrivateHost(root, evidence, "ui-contracts", offline=True)
    try:
        initial = host.call("init")
        require(initial.get("mode") == "tool", "Default mode must be standalone tool mode.")
        standalone = host.call("workspace/tool", {"toolId": "bam/reference-index"})
        node = standalone["nodes"][0]["id"]
        source = standalone["sources"][0]["id"]
        fixture = root / "examples" / "starter" / "reference.fa"
        host.call("model", {"action": "apply_fields", "payload": {
            "nodeId": node, "name": "Preserved reference index",
            "files": {source: {"reference": str(fixture)}}}})
        standalone = host.call("state")
        workflow = host.call("workspace/mode", {"mode": "workflow"})
        require(not workflow["nodes"], "Standalone operation leaked into empty workflow.")
        first = host.call("model", {"action": "add_tool", "payload": {"toolId": "bam/sort"}})
        first_id = first["selected"]
        require(not first["sources"] and all(not refs for refs in first["graph"]["nodes"][0]["inputs"].values()),
                "Adding a workflow tool invented external input boxes.")
        require(not first["inspector"]["sources"] and all(not port["sources"] for port in first["inspector"]["ports"]),
                "Workflow tool inspector duplicated input file forms.")
        second = host.call("model", {"action": "add_tool", "payload": {"toolId": "bam/sort"}})
        second_id = second["selected"]
        compatible_preview = host.call("workspace/connection-targets", {"ref": first_id + "::sorted"})
        require({"nodeId": second_id, "portId": "alignment"} in compatible_preview["targets"],
                "Compatible starter output was absent from the native port preview.")
        connected = host.call("model", {"action": "connect", "payload": {
            "nodeId": second_id, "portId": "alignment", "refs": [first_id + "::sorted"]}})
        require(connected["graph"]["nodes"][1]["inputs"]["alignment"] == [first_id + "::sorted"],
                "Compatible connection was not installed.")
        cycle_preview = host.call("workspace/connection-targets", {"ref": second_id + "::sorted"})
        require({"nodeId": first_id, "portId": "alignment"} not in cycle_preview["targets"],
                "Native port preview offered a graph cycle.")
        reference_node = host.call("model", {"action": "add_tool", "payload": {"toolId": "bam/reference-index"}})
        reference_ref = reference_node["selected"] + "::reference"
        type_preview = host.call("workspace/connection-targets", {"ref": reference_ref})
        require({"nodeId": first_id, "portId": "alignment"} not in type_preview["targets"],
                "Native port preview offered a FASTA reference to an alignment input.")
        added = host.call("model", {"action": "add_input", "payload": {"inputType": "reference", "label": "Shared genome"}})
        explicit_source = added["selected"]
        require(added["inspector"]["kind"] == "source" and added["inspector"]["sourceId"] == explicit_source,
                "Explicit input did not own its inspector.")
        field = added["inspector"]["fields"][0]["id"]
        host.call("model", {"action": "apply_fields", "payload": {"sourceId": explicit_source,
            "files": {explicit_source: {field: str(fixture)}}}})
        shared = host.call("model", {"action": "connect", "payload": {
            "nodeId": reference_node["selected"], "portId": "reference", "refs": [explicit_source]}})
        require(len(shared["sources"]) == 1, "Workflow input connection duplicated the external source.")
        require(not shared["inspector"].get("sources"), "Connected workflow input duplicated a file editor.")
        before = shared["graph"]
        rejected = []
        for label, payload in [
            ("cycle", {"nodeId": first_id, "portId": "alignment", "refs": [second_id + "::sorted"]}),
            ("type", {"nodeId": first_id, "portId": "alignment", "refs": [reference_ref]}),
        ]:
            try:
                host.call("model", {"action": "connect", "payload": payload})
            except ValueError as exc:
                rejected.append({"case": label, "message": str(exc)})
            else:
                raise AssertionError("Invalid connection was accepted: " + label)
            require(host.call("state")["graph"] == before, "Rejected connection mutated workflow.")
        back = host.call("workspace/mode", {"mode": "tool"})
        require(back["graph"] == standalone["graph"], "Standalone inputs/settings lost during workflow switch.")
        other = host.call("workspace/tool", {"toolId": "bam/index"})
        require(len(other["nodes"]) == 1, "Standalone selection appended another operation.")
        restored = host.call("workspace/tool", {"toolId": "bam/reference-index"})
        require(restored["graph"] == standalone["graph"], "Per-tool inputs/settings were not preserved.")
        restored_workflow = host.call("workspace/mode", {"mode": "workflow"})
        require(restored_workflow["graph"] == before, "Workflow lost after standalone selection.")
        return {"networkSocketOperationsDenied": True, "standaloneGraph": standalone["graph"],
                "workflowGraph": before, "rejected": rejected,
                "portPreviews": {"compatible": compatible_preview, "cycle": cycle_preview, "type": type_preview},
                "checks": ["Default standalone mode", "Independent preserved tool and workflow graphs",
                           "Compatible graph edge", "Bounded native compatibility preview",
                           "Atomic cycle and semantic type rejection", "Per-tool settings and input retention",
                           "Workflow additions leave ports unbound without automatic source boxes",
                           "Explicit reusable input owns one file editor and connects without duplication"]}
    finally:
        host.close()


def canonical_sam_record(line):
    """Preserve record values across BAM's typed serialization.

    SAMtools legitimately writes de:f:0.0100 as de:f:0.01 on BAM decoding.
    Compare float tags at their specified IEEE single-precision storage value;
    optional tag ordering and redundant numeric text zeros are not biology.
    """
    columns = line.split("\t")
    tags = []
    for tag in columns[11:]:
        key, kind, value = tag.split(":", 2)
        if kind == "f":
            value = struct.pack("<f", float(value)).hex()
        elif kind == "i":
            value = str(int(value))
        tags.append((key, kind, value))
    return tuple(columns[:11]) + tuple(sorted(tags))


def native_scientific_chain(root, evidence):
    """Exercise the requested SAM-to-BAM path through explicit native-host edits.

    The tiny starter fixture is public synthetic truth, never user data. We
    inspect both the original SAM and the BAM converted back to SAM by the
    exact bundled SAMtools, comparing every record rather than just file size.
    """
    host = PrivateHost(root, evidence, "workflow-science", offline=True)
    try:
        host.call("init")
        host.call("workspace/mode", {"mode": "workflow"})
        alignment = host.call("model", {"action": "add_tool", "payload": {"toolId": "align/paired-end"}})["selected"]
        sorting = host.call("model", {"action": "add_tool", "payload": {"toolId": "bam/sort"}})["selected"]
        require(not host.call("state")["sources"], "Scientific workflow tools auto-created inputs.")
        fixture = root / "examples" / "starter"
        profile = json.loads((root / "workspace" / "starter-check-profile.json").read_text(encoding="utf-8"))
        for name, expected in profile["fixtures"].items():
            require(sha256(fixture / name) == expected, "Scientific fixture hash mismatch: " + name)
        for kind, names, port in [("reference", ["reference.fa"], "reference"),
                                  ("pair", ["reads1.fastq", "reads2.fastq"], "reads")]:
            state = host.call("model", {"action": "add_input", "payload": {"inputType": kind}})
            source = state["selected"]
            fields = state["inspector"]["fields"]
            require(len(fields) == len(names), "Explicit workflow input fields differ from the declared semantic contract.")
            host.call("model", {"action": "apply_fields", "payload": {"sourceId": source,
                "files": {source: {field["id"]: str(fixture / name) for field, name in zip(fields, names)}}}})
            host.call("model", {"action": "connect", "payload": {"nodeId": alignment, "portId": port, "refs": [source]}})
        host.call("model", {"action": "apply_fields", "payload": {"nodeId": alignment,
            "params": {"sample": "starter", "threads": "2"}}})
        state = host.call("model", {"action": "connect", "payload": {
            "nodeId": sorting, "portId": "alignment", "refs": [alignment + "::sam"]}})
        require(len(state["sources"]) == 2 and len(state["nodes"]) == 2,
                "Two-input/two-tool workflow contains unexpected nodes or duplicated bindings.")
        require(host.call("review")["valid"], "Explicit minimap2-to-SAMtools graph failed review.")
        output = evidence / "scientific-results"
        output.mkdir(exist_ok=True)
        started = host.call("run", {"output_folder": str(output)})
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            run = host.call("run/get", {"run_id": started["run_id"]})
            if run["status"] not in ("preparing", "running", "cancelling"):
                break
            time.sleep(.1)
        else:
            raise TimeoutError("Native explicit-input SAM-to-BAM workflow did not finish.")
        require(run["status"] == "completed", "Native explicit-input SAM-to-BAM workflow failed: " + json.dumps(run))
        folder = Path(run["folder"])
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        sam = Path(record["outputs"][alignment + "::sam"]["files"]["sam"])
        bam = Path(record["outputs"][sorting + "::sorted"]["files"]["sorted"])
        with gzip.open(bam, "rb") as handle:
            require(handle.read(4) == b"BAM\x01", "SAMtools sort did not produce binary BAM.")
        samtools = root / "packs" / "bam-0.4.0" / "bin" / "samtools.exe"
        decoded = subprocess.run([str(samtools), "view", "-h", str(bam)], cwd=root,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        require(decoded.returncode == 0, "Bundled SAMtools could not decode sorted BAM: " + decoded.stderr.decode(errors="replace"))
        original_text = sam.read_text(encoding="utf-8")
        decoded_text = decoded.stdout.decode("utf-8")
        (evidence / "native-workflow-original.sam").write_text(original_text, encoding="utf-8")
        (evidence / "native-workflow-bam-roundtrip.sam").write_text(decoded_text, encoding="utf-8")
        original = [line for line in original_text.splitlines() if line and not line.startswith("@")]
        converted = [line for line in decoded_text.splitlines() if line and not line.startswith("@")]
        require(len(original) == len(converted) == 202, "Native alignment truth must contain exactly 202 records.")
        require(Counter(map(canonical_sam_record, original)) == Counter(map(canonical_sam_record, converted)),
                "SAM-to-BAM conversion changed alignment records, mate flags, sequence, qualities or typed tag values.")
        rows = [line.split("\t") for line in converted]
        require(all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 for row in rows),
                "Expected 202 mapped, paired and properly paired synthetic records.")
        require(all(row[2] == "starter" and "RG:Z:starter" in row[11:] for row in rows),
                "Converted alignments lost the expected reference or read group.")
        require([int(row[3]) for row in rows] == sorted(int(row[3]) for row in rows),
                "SAMtools output is not in coordinate order.")
        require(any(line.startswith("@SQ\tSN:starter\tLN:3000") for line in decoded_text.splitlines()),
                "BAM header lost the known synthetic reference length.")
        require(any(line.startswith("@RG\t") and "SM:starter" in line for line in decoded_text.splitlines()),
                "BAM header lost the sample read-group identity.")
        write_json(evidence / "native-workflow-science-run.json", record)
        result = {"networkSocketOperationsDenied": True, "nativeWindowsExecuted": True,
                  "graph": state["graph"], "records": len(rows), "fixtureHashes": profile["fixtures"],
                  "sam": {"path": str(sam), "sha256": sha256(sam)},
                  "bam": {"path": str(bam), "sha256": sha256(bam)},
                  "samtoolsSha256": sha256(samtools), "runFolder": str(folder),
                  "checks": ["Native minimap2 alignment chains to SAMtools coordinate-sorted binary BAM using two explicit inputs",
                             "All 202 synthetic mapped proper-pair records, mate flags, sequence, quality and typed tags survive SAM-to-BAM conversion"]}
        write_json(evidence / "native-workflow-science.json", result)
        return result
    finally:
        host.close()


# GUI assertions are filled against the public native controls/layout contract
# alongside the three-pane implementation; no test-only application RPC is used.
def gui_contracts(root, evidence, report):
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    report["nativeWindowsExecuted"] = True
    captures, geometry = [], []
    try:
        ui.wait("installed native tool library", lambda:
                ui.user.IsWindowEnabled(ui.child(410)) and len(ui.library().tools()) > 0)
        ui.click_button(402)
        def manager_window():
            return next((h for h in ui.windows() if ui.label(h, True) == "WorkbenchPackManager060"), None)
        ui.wait("first Manage tools click opens without a JSON array error", lambda: manager_window())
        manager = manager_window()
        ui.wait("first Manage tools opening populates installed packs", lambda:
                ui.send(ui.child(503, manager), 0x1004) >= 3 and bool(ui.label(ui.child(504, manager))))
        captures.append(ui.capture("manage-tools-first-open.bmp", manager))
        close = ui.child(513, manager)
        ui.send(close, 0x00F5)
        ui.wait("close Manage tools", lambda: not manager_window())
        ui.click_button(402)
        ui.wait("Manage tools reopens with populated installed packs", lambda:
                manager_window() and ui.send(ui.child(503, manager_window()), 0x1004) >= 3)
        ui.send(ui.child(513, manager_window()), 0x00F5)
        ui.wait("return from reopened Manage tools", lambda: not manager_window())
        ui.fit_window(1280, 900)
        dpi = ui.user.GetDpiForWindow(ui.main)
        scale = dpi / 96
        def point(hwnd, x, y):
            left, top, _, _ = ui.bounds(hwnd)
            return round(left + x * scale), round(top + y * scale)
        def edits():
            return [c for c in ui.controls() if c["id"] >= 2000 and c["class"].lower() == "edit"]
        def has_text(value):
            return any(c["text"] == value for c in edits())
        def first_tool_row():
            return ui.library().first_tool_point()
        def select_tool(query, *, drag_to=None, exact_label=None):
            ui.set_text(ui.child(102), query)
            def choices():
                library = ui.library()
                # Wrapped rows expose their description after the complete
                # title for accessibility. Keep exact operation disambiguation.
                return [item for item in library.tools() if not exact_label or
                        library.label(item).partition('\n')[0] == exact_label]
            ui.wait("filter tool " + query, lambda: len(choices()) == 1)
            # The 0.13 candidate also exposes an explicitly indexed alignment.
            # Select the actual ordinary-operation label for the unchanged
            # scroll regression, rather than assuming a search has one result.
            start = ui.library().point(choices()[0]) if exact_label else first_tool_row()
            if drag_to:
                ui.drag(start, point(ui.child(117), *drag_to))
            else:
                ui.click_at(*start)
        def name_edit():
            found = [c for c in edits() if c["text"] in ("Coordinate sort", "First coordinate sort", "Second coordinate sort")]
            require(found, "Selected workflow tool has no editable native name.")
            return found[0]["hwnd"]
        def measure(mode, size):
            rows = ui.controls()
            by_id = {c["id"]: c for c in rows if c["id"] > 0}
            for identity in (102, 104, 410, 411, 118):
                require(identity in by_id, "Missing visible native control: " + str(identity))
            library = ui.library()
            tools = library.visible_bounds() if hasattr(library, 'visible_bounds') else by_id[104]["bounds"]
            form = by_id[118]["bounds"]
            require(tools[2] <= form[0], "Tool library overlaps the selected tool form.")
            if mode == "tool":
                for identity in (101, 413, 111, 403):
                    require(identity in by_id, "General setting hidden in standalone mode: " + str(identity))
                    require(form[2] <= by_id[identity]["bounds"][0], "Central parameters overlap general settings.")
                require(117 not in by_id, "Workflow canvas remained visible in standalone mode.")
            else:
                require(117 in by_id, "Workflow canvas is not visible.")
                canvas = by_id[117]["bounds"]
                require(tools[2] <= canvas[0] and canvas[2] <= form[0], "Workflow panes overlap.")
            geometry.append({"mode": mode, "requestedSize": size, "actualWindowBounds": ui.bounds(ui.main),
                             "dpi": ui.user.GetDpiForWindow(ui.main), "visibleToolPane": tools, "controls": rows})
        def add_input(label):
            ui.click_button(419)
            def modal_window():
                return next((h for h in ui.windows() if ui.label(h) == "Add workflow input"), None)
            ui.wait("open native workflow input chooser", lambda: modal_window())
            modal = modal_window()
            # The nested native modal loop must safely process the preceding
            # draft commit while its input choices remain open.
            time.sleep(.3)
            choices = ui.child(105, modal)
            labels = []
            for index in range(ui.send(choices, 0x018B)):  # LB_GETCOUNT.
                buffer = ctypes.create_unicode_buffer(1024)
                require(ui.send(choices, 0x0189, index, ctypes.addressof(buffer)) < len(buffer),
                        "Native input type label is too long.")
                labels.append(buffer.value)
            require(label in labels, "Native input chooser lacks semantic type: " + label)
            index = labels.index(label)
            ui.send(choices, 0x0186, index)  # LB_SETCURSEL; native choice, no application RPC.
            button = ui.child(1, modal)
            left, top, right, bottom = ui.bounds(button)
            ui.click_at((left+right)//2, (top+bottom)//2)
            ui.wait("new workflow input owns its file form", lambda: has_text(label))

        def scroll_rendering_check():
            select_tool("Paired-end alignment", exact_label="minimap2 — Paired-end alignment (SAM)")
            ui.wait("long paired-end tool form available for rendering regression", lambda: has_text("Paired-end alignment"))
            form = ui.child(118)
            state = ui.scroll_info(form)
            require(state["nMax"] + 1 > state["nPage"], "Rendering regression requires a genuinely scrollable option form.")
            left, top, right, bottom = ui.bounds(form)
            # A real wheel over both child edits and background exercises routing
            # and repeated child relocation. Finish at a nonzero offset.
            edit = next(c for c in edits() if left < c["bounds"][0] and top <= c["bounds"][1] and c["bounds"][3] < bottom)
            edit_x, edit_y = (edit["bounds"][0] + edit["bounds"][2]) // 2, (edit["bounds"][1] + edit["bounds"][3]) // 2
            blank_x, blank_y = left + 5, min(top + 120, bottom - 20)
            for _ in range(3):
                ui.wheel(edit_x, edit_y, -240)
                time.sleep(.06)
                ui.wheel(blank_x, blank_y, 240)
                time.sleep(.06)
            ui.wheel(blank_x, blank_y, -120)
            time.sleep(.2)
            scrolled = ui.scroll_info(form)
            require(scrolled["nPos"] > 0, "Real mouse wheel did not scroll tool options.")
            # Exclude child controls (caret/focus/button states) while retaining
            # background and every static text region where stale lines appeared.
            rectangle = [left+3, top+3, min(right-23, ui.user.GetSystemMetrics(0)),
                         min(bottom-3, ui.user.GetSystemMetrics(1))]
            ui.mouse(5, 5)
            before, raw_before = ui.screen_capture("options-scroll-screen-before-redraw.bmp", rectangle)
            masks = [c["bounds"] for c in ui.controls(form) if c["class"].lower() != "static"]
            require(ui.user.RedrawWindow(form, None, None, 0x0185), "Could not request clean descendant repaint.")
            time.sleep(.2)
            after, raw_after = ui.screen_capture("options-scroll-screen-clean-redraw.bmp", rectangle)
            width = before["width"]
            checked = changed = 0
            for y in range(before["height"]):
                for x in range(width):
                    sx, sy = rectangle[0]+x, rectangle[1]+y
                    if any(a-2 <= sx < c+2 and b-2 <= sy < d+2 for a,b,c,d in masks):
                        continue
                    offset = (y*width+x)*4
                    checked += 1
                    changed += raw_before[offset:offset+3] != raw_after[offset:offset+3]
            require(checked > 10000, "Too little visible static text/background remained for the render comparison.")
            require(changed == 0, "Scrolled static text/background differed from a clean repaint: " + str(changed) + " pixels.")
            captures.extend([before, after])
            return {"scrollBefore": state, "scrollAfter": scrolled, "comparedPixels": checked,
                    "differentPixels": changed, "maskedChildControlBounds": masks,
                    "method": "Actual desktop BitBlt before and after forced descendant redraw at unchanged scroll offset"}

        # A selection made only in the workflow library must not leave a stale
        # highlighted row in an empty standalone workspace. Deliberately retain
        # the search and click the same row without resetting the filter.
        ui.click_button(411)
        ui.wait("open empty workflow for library-selection regression", lambda:
                ui.user.IsWindowVisible(ui.child(117)) and ui.user.IsWindowVisible(ui.child(105)))
        select_tool("Coordinate sort")
        ui.wait("select workflow library row without adding a tool", lambda:
                ui.library().selected() == ui.library().tools()[0])
        require(not has_text("Coordinate sort"), "Workflow library selection unexpectedly added a node.")
        ui.click_button(410)
        ui.wait("return to empty standalone workspace with unchanged filter", lambda:
                ui.user.IsWindowVisible(ui.child(118)) and not ui.user.IsWindowVisible(ui.child(117)))
        require(ui.label(ui.child(102)) == "Coordinate sort", "Switching modes unexpectedly cleared the library filter.")
        require(len(ui.library().tools()) == 1, "The selected library row disappeared after mode switch.")
        ui.click_at(*first_tool_row())
        ui.wait("same library row opens standalone tool on first click", lambda: has_text("Coordinate sort"))
        captures.append(ui.capture("tools-after-workflow-library-selection.bmp"))
        select_tool("Index a reference")
        ui.wait("single click opens standalone reference indexing form", lambda: has_text("Index a reference"))
        # Separate native-control notification regression, not a physical drag
        # assertion: a refreshed list can have a hit row but no selected row.
        # Exercise the TreeView's real double-click handler without constructing
        # or injecting a foreign-process NMITEMACTIVATE pointer.
        ui.set_text(ui.child(102), "Coordinate sort")
        ui.wait("filter other tool for native double-click notification regression", lambda:
                len(ui.library().tools()) == 1)
        # An unchanged filter may preserve selection; explicitly clear the native
        # caret to retain this existing hit-row-without-selection regression.
        ui.send(ui.child(104), 0x110B, 9, 0)  # TVM_SELECTITEM/TVGN_CARET.
        require(not ui.library().selected(), "Notification regression requires an unselected library row.")
        tasks = ui.child(104)
        screen_x, screen_y = first_tool_row()
        origin = wintypes.POINT()
        require(ui.user.ClientToScreen(tasks, ctypes.byref(origin)), "Could not locate the TreeView client origin.")
        local_x, local_y = screen_x - origin.x, screen_y - origin.y
        pointer_coordinates = (local_x & 0xffff) | ((local_y & 0xffff) << 16)
        ui.mouse(screen_x, screen_y)
        ui.post(tasks, 0x0203, 1, pointer_coordinates)  # WM_LBUTTONDBLCLK, MK_LBUTTON.
        ui.post(tasks, 0x0202, 0, pointer_coordinates)  # WM_LBUTTONUP.
        ui.wait("double-click notification uses hit row without an existing selection", lambda: has_text("Coordinate sort"))
        captures.append(ui.capture("tools-double-click-notification.bmp"))
        select_tool("Index a reference")
        ui.wait("restore standalone reference indexing after notification regression", lambda: has_text("Index a reference"))
        rendering = scroll_rendering_check()
        select_tool("Index a reference")
        ui.wait("restore reference form after scroll regression", lambda: has_text("Index a reference"))
        measure("tool", "1280x900")
        require(ui.user.IsWindowVisible(ui.child(403)), "References absent from general settings.")
        empty_inputs = [c for c in edits() if not c["text"]]
        require(empty_inputs, "Standalone reference input edit missing.")
        chosen_reference = str(root / "examples" / "starter" / "reference.fa")
        ui.set_text(empty_inputs[0]["hwnd"], chosen_reference)
        ui.set_text(ui.child(413), str(root / "examples" / "starter"))
        captures.append(ui.capture("tools-reference-1280.bmp"))
        ui.click_button(411)
        ui.wait("workflow canvas opens", lambda: ui.user.IsWindowVisible(ui.child(117)) and ui.user.IsWindowVisible(ui.child(105)))
        select_tool("Coordinate sort", drag_to=(144, 60))
        ui.wait("dragged tool shows workflow parameters", lambda: has_text("Coordinate sort"))
        ui.set_text(name_edit(), "First coordinate sort")
        # Dropping a second tool commits the first form and leaves its position.
        canvas_bounds = ui.bounds(ui.child(117))
        canvas_width = (canvas_bounds[2] - canvas_bounds[0]) / scale
        second_left = min(294, int(canvas_width - 242 - 24))
        require(second_left >= 24, "Native canvas cannot contain a workflow card at this display size.")
        select_tool("Coordinate sort", drag_to=(second_left + 120, 290))
        ui.wait("second dragged tool selected", lambda: has_text("Coordinate sort"))
        ui.set_text(name_edit(), "Second coordinate sort")
        # Explicitly dropped nodes have deterministic documented positions:
        # pointer minus(120,20); socket rows derive from the actual pack schema.
        canvas = ui.child(117)
        ui.drag(point(canvas, 266, 147), point(canvas, second_left, 335))
        ui.wait("compatible output connected through native port drag", lambda: any(
            c["class"].lower() == "static" and "From:" in c["text"] and "First coordinate sort" in c["text"]
            for c in ui.controls()), seconds=30)
        measure("workflow", "1280x900")
        captures.append(ui.capture("workflow-connected-1280.bmp"))
        ui.click_at(*point(canvas, 120, 58))
        ui.wait("canvas selection opens first tool on right", lambda: has_text("First coordinate sort"))
        captures.append(ui.capture("workflow-first-selected.bmp"))
        ui.click_button(412)
        ui.wait("workflow general settings available", lambda:
                ui.user.IsWindowVisible(ui.child(413)) and ui.user.IsWindowVisible(ui.child(403)))
        captures.append(ui.capture("workflow-general-settings.bmp"))
        ui.click_button(410)
        ui.wait("standalone input retained after workflow editing", lambda: has_text(chosen_reference))
        require(ui.label(ui.child(413)) == str(root / "examples" / "starter"), "Input browsing folder was lost.")
        require(ui.label(ui.child(119)) == "Select a tool, choose its inputs and options, then run it locally.",
                "Standalone status retained an instruction from workflow editing.")
        measure("tool", "restored")
        ui.fit_window(1100, 740)
        time.sleep(.2)
        measure("tool", "requested1100x740")
        captures.append(ui.capture("tools-minimum.bmp"))
        ui.click_button(411)
        ui.wait("workflow canvas restored", lambda: ui.user.IsWindowVisible(ui.child(117)))
        ui.click_at(*point(ui.child(117), 120, 58))
        ui.wait("workflow selection retained", lambda: has_text("First coordinate sort"))
        measure("workflow", "requested1100x740")
        captures.append(ui.capture("workflow-minimum.bmp"))
        # Navigation assertions use actual mouse gestures and public native
        # scrollbars/button labels, then retain displayed canvas pixels.
        canvas = ui.child(117)
        initial_scroll = [ui.scroll_info(canvas, bar)["nPos"] for bar in (0, 1)]
        ui.drag(point(canvas, 20, 215), point(canvas, 60, 255))
        moved_scroll = [ui.scroll_info(canvas, bar)["nPos"] for bar in (0, 1)]
        require(moved_scroll == [v-40 for v in initial_scroll], "Dragging blank canvas did not pan the viewport with the pointer.")
        captures.append(ui.capture("workflow-panned.bmp"))
        ui.drag(point(canvas, 60, 255), point(canvas, 20, 215))
        require([ui.scroll_info(canvas, bar)["nPos"] for bar in (0, 1)] == initial_scroll,
                "Reverse canvas drag did not restore the viewport.")
        ui.click_button(420)
        ui.wait("zoom-out button reduces workflow scale", lambda: int(ui.label(ui.child(422)).rstrip("%")) < 100)
        zoom_out = ui.label(ui.child(422))
        captures.append(ui.capture("workflow-zoomed-out.bmp"))
        zoom = int(zoom_out.rstrip("%")) / 100
        scroll_x, scroll_y = [ui.scroll_info(canvas, bar)["nPos"] for bar in (0, 1)]
        ui.click_at(*point(canvas, (second_left+100-scroll_x)*zoom, (288-scroll_y)*zoom))
        ui.wait("zoomed canvas hit testing selects second tool", lambda: has_text("Second coordinate sort"))
        ui.click_at(*point(canvas, (120-scroll_x)*zoom, (58-scroll_y)*zoom))
        ui.wait("zoomed canvas hit testing selects first tool", lambda: has_text("First coordinate sort"))
        ui.click_button(421)
        ui.wait("zoom-in button enlarges workflow scale", lambda:
                int(ui.label(ui.child(422)).rstrip("%")) > int(zoom_out.rstrip("%")))
        ui.click_button(422)
        ui.wait("reset workflow zoom to 100 percent", lambda: ui.label(ui.child(422)) == "100%")
        # Precision touchpads may emit Ctrl+wheel deltas far smaller than120.
        # Inject documented native messages to check accumulation; this is not
        # evidence that physical trackpad hardware was available on the runner.
        wheel_x, wheel_y = point(canvas, 180, 210)
        wheel_coordinates = (wheel_x & 0xffff) | ((wheel_y & 0xffff) << 16)
        for _ in range(120):
            ui.send(canvas, 0x020A, (1 << 16) | 0x0008, wheel_coordinates)
        ui.wait("precision Ctrl-wheel deltas accumulate into visible zoom", lambda:
                int(ui.label(ui.child(422)).rstrip("%")) > 100)
        precision_zoom = ui.label(ui.child(422))
        ui.click_button(422)
        ui.wait("reset after injected precision wheel", lambda: ui.label(ui.child(422)) == "100%")
        def current_world_point(x, y):
            sx, sy = [ui.scroll_info(canvas, bar)["nPos"] for bar in (0, 1)]
            factor = int(ui.label(ui.child(422)).rstrip("%")) / 100
            return point(canvas, (x-sx)*factor, (y-sy)*factor)
        ui.click_at(*current_world_point(120, 58))
        ui.wait("select tool before hover deletion", lambda: has_text("First coordinate sort"))
        ui.mouse(*current_world_point(24+242-17, 40+20))
        time.sleep(.15)
        captures.append(ui.capture("workflow-tool-delete-hover.bmp"))
        ui.click_at(*current_world_point(24+242-17, 40+20))
        ui.wait("hover close removes selected workflow tool", lambda: not has_text("First coordinate sort"))
        ui.click_button(108)
        ui.wait("Undo restores deleted tool and its selection", lambda: has_text("First coordinate sort"))
        # Explicit reference creation is exercised through the real native modal;
        # it starts unconnected and has exactly one file editor of its own.
        ui.set_text(name_edit(), "Saved before Add input")
        add_input("Reference FASTA")
        source_edits = edits()
        require(len(source_edits) == 2, "Explicit reference input duplicated its filename or name controls.")
        source_name = next(c for c in source_edits if c["text"] == "Reference FASTA")
        file_edit = next(c for c in source_edits if not c["text"])
        ui.set_text(source_name["hwnd"], "Reusable genome")
        ui.set_text(file_edit["hwnd"], chosen_reference)
        captures.append(ui.capture("workflow-explicit-reference-input.bmp"))
        ui.click_button(418)  # Arrange resets presentation only, keeping graph.
        ui.wait("arrange workflow with explicit source", lambda: ui.label(ui.child(422)) == "100%")
        ui.click_at(*point(canvas, 380, 52))
        ui.wait("draft tool name survives the Add input modal loop", lambda: has_text("Saved before Add input"))
        ui.click_at(*point(canvas, 120, 52))
        ui.wait("explicit source fields remain after selecting its consumer tool", lambda:
                has_text("Reusable genome") and has_text(chosen_reference))
        select_tool("Index a reference", drag_to=(144, 390))
        ui.wait("new workflow reference tool has unconnected input", lambda: has_text("Index a reference"))
        require(len(edits()) == 1, "Unconnected workflow reference tool duplicated a filename form.")
        # The explicitly created source has one output at (274,97); the new
        # tool was dropped with header at(24,370), reference input at(24,435).
        ui.drag(point(canvas, 274, 97), point(canvas, 24, 435))
        ui.wait("explicit source output connects to a compatible tool input by mouse", lambda: any(
            c["class"].lower() == "static" and "From:" in c["text"] and "Reusable genome" in c["text"]
            for c in ui.controls()))
        require(len(edits()) == 1, "Connected workflow reference tool duplicated the shared filename form.")
        captures.append(ui.capture("workflow-explicit-input-connected.bmp"))
        ui.click_at(*point(canvas, 120, 52))
        ui.wait("select reusable source after physical connection", lambda:
                has_text("Reusable genome") and has_text(chosen_reference))
        # Arrange puts the sole explicit source at (32,32). Select its header,
        # reveal its own close control, remove it, and verify Undo restores it.
        ui.mouse(*point(canvas, 32+242-17, 32+20))
        time.sleep(.15)
        captures.append(ui.capture("workflow-source-delete-hover.bmp"))
        ui.click_at(*point(canvas, 32+242-17, 32+20))
        ui.wait("hover close removes selected explicit input", lambda: not has_text("Reusable genome"))
        ui.click_button(108)
        ui.wait("Undo restores explicit input files and name", lambda: has_text("Reusable genome") and has_text(chosen_reference))
        captures.append(ui.capture("workflow-source-delete-undone.bmp"))
        write_json(evidence / "ui-control-geometry.json", geometry)
        return {"dpi": dpi, "displayPixels": [ui.user.GetSystemMetrics(0), ui.user.GetSystemMetrics(1)],
                "captures": captures, "geometryFile": "ui-control-geometry.json", "scrollRendering": rendering,
                "navigation": {"initialScroll": initial_scroll, "pannedScroll": moved_scroll,
                               "zoomOutLabel": zoom_out, "resetZoomLabel": ui.label(ui.child(422)),
                               "precisionWheel": {"messages": 120, "delta": 1, "flags": "MK_CONTROL",
                                                  "resultingZoomLabel": precision_zoom,
                                                  "input": "Injected WM_MOUSEWHEEL on the native canvas; physical trackpad not tested"}},
                "checks": ["Manage tools loads installed packs on its first click without a modal error and reopens cleanly",
                           "First click opens a previously selected workflow-library row in empty tool mode",
                           "Single-click standalone tool form",
                           "Separate queued native double-click notification opens its hit row after selection clears",
                           "Three independent panes with general settings",
                           "Actual mouse drag from tool list onto workflow canvas twice",
                           "Actual compatible output-to-input mouse connection",
                           "Canvas selection displays tool options on right",
                           "General settings remain available in workflow mode",
                           "Standalone input and browsing folder survive workflow mode",
                           "Mode-specific status guidance replaces the previous workflow drag hint",
                           "Workflow graph/selection survives mode switching", "Normal/minimum observed pane separation",
                           "Real repeated option scrolling leaves static text identical to a clean repaint",
                           "Blank-canvas mouse drag pans and reverses the viewport",
                           "Zoom buttons decrease, increase and reset scale; scaled card hit testing selects both tools",
                           "Injected one-unit native Ctrl-wheel deltas accumulate into visible zoom",
                           "Editing a tool immediately before Add input preserves its draft through the nested modal loop",
                           "Native Add input creates one independently editable reference file slot",
                           "Actual mouse connection from an explicit input output socket to a tool input without duplicate file fields",
                           "Header hover close deletes a tool and Undo restores its selection",
                           "Header hover close deletes an explicit input and Undo restores its files"],
                "notificationRegression": {"input": "Queued WM_LBUTTONDBLCLK and WM_LBUTTONUP to the real native TreeView",
                                           "scope": "Hit-row activation without prior selection; separate from the SendInput pointer and drag assertions."},
                "limits": ["DPI coverage is only the actual reported monitor DPI; no simulated WM_DPICHANGED claim.",
                           "Physical trackpad pinch hardware is unavailable on this CI runner; the gesture implementation is not claimed as hardware-validated.",
                           "Human usability acceptance, multi-monitor movement and native folder pickers remain separate."]}
    finally:
        ui.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--gui-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root, report_path = args.app_root.resolve(), args.report.resolve()
    evidence = report_path.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "startedUtc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": sys.version, "nativeWindowsExecuted": False,
              "nativeGUILaunched": False, "nativeGUIValidated": False,
              "appRoot": str(root), "sourceCommit": args.source_commit, "assetSha256": args.asset_sha256,
              "assetName": args.asset_name, "gateSha256": sha256(__file__), "checks": [], "skips": []}
    try:
        require(os.name == "nt", "This gate requires actual native Windows; it has no passing skip mode.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(),
                "Run using the exact application's private Python.")
        if args.gui_worker:
            report["gui"] = gui_contracts(root, evidence, report)
            report["checks"] = report["gui"]["checks"]
            report["nativeGUIValidated"] = True
        else:
            report["appFiles"] = {str(p.relative_to(root)): sha256(p) for p in [root/"NativeWorkbench.exe", *sorted((root/"workspace").glob("*.py"))]}
            report["host"] = host_contracts(root, evidence)
            report["nativeWindowsExecuted"] = True
            report["checks"].extend(report["host"]["checks"])
            report["science"] = native_scientific_chain(root, evidence)
            report["checks"].extend(report["science"]["checks"])
            worker_report = evidence / "ui-worker.json"
            command = [sys.executable, "-I", "-u", str(Path(__file__).resolve()), "--gui-worker",
                       "--app-root", str(root), "--report", str(worker_report), "--source-commit", args.source_commit,
                       "--asset-sha256", args.asset_sha256, "--asset-name", args.asset_name]
            with (evidence/"ui-worker.stderr.txt").open("wb") as err:
                worker = subprocess.Popen(command, stderr=err)
                try:
                    worker.wait(timeout=240)
                finally:
                    stop_process_tree(worker)
            require(worker_report.is_file(), "Native GUI worker did not produce a report.")
            result = json.loads(worker_report.read_text(encoding="utf-8"))
            report["nativeGUILaunched"] = result.get("nativeGUILaunched", False)
            report["nativeGUIValidated"] = result.get("nativeGUIValidated", False)
            require(worker.returncode == 0 and result.get("success"), "Native GUI worker failed: " + json.dumps(result))
            report["gui"] = result["gui"]
            report["checks"].extend(result["checks"])
        report["nativeWindowsExecuted"] = True
        report["success"] = True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report["completedUtc"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = len(report["checks"])
        write_json(report_path, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(report_path)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
