#!/usr/bin/env python3
"""Observe displayed frames during native scrolling, including wheel boundaries.

Uses the exact packaged desktop and private Python. Reference frames may request a
clean repaint; sampled frames only read the composed desktop, never PrintWindow.
The optional diagnostic mode reports old-package defects without calling them a
passing application check. No physical trackpad or arbitrary frame-rate claim.
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
import struct
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_workspace_ui_windows import NativeUI
from check_references_windows import require, sha256, write_json


class DisplayFrames:
    """Reuse a DIB for bounded, paced observations of the displayed desktop."""
    def __init__(self, ui, rectangle):
        self.ui, self.rectangle = ui, rectangle
        left, top, right, bottom = rectangle
        self.width, self.height = right-left, bottom-top
        self.size = self.width*self.height*4
        self.header = struct.pack("<IiiHHIIiiII", 40, self.width, -self.height,
                                  1, 32, 0, self.size, 0, 0, 0, 0)
        self.dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self.dwm.DwmFlush.argtypes = []
        self.dwm.DwmFlush.restype = ctypes.c_long
        g = ui.gdi
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.GdiFlush.argtypes = []
        g.GdiFlush.restype = wintypes.BOOL
        self.dc = ui.user.GetDC(None)
        self.memory = g.CreateCompatibleDC(self.dc)
        self.pixels = ctypes.c_void_p()
        info = ctypes.create_string_buffer(self.header)
        self.bitmap = g.CreateDIBSection(self.dc, info, 0, ctypes.byref(self.pixels), None, 0)
        require(self.bitmap and self.pixels.value, "Could not allocate desktop frame buffer.")
        self.old = g.SelectObject(self.memory, self.bitmap)
        self.last_read = 0.0

    def read(self):
        # DwmFlush is a timing aid, not a flush of the target application's paint
        # queue or the entire session. Pace even if the call returns immediately.
        # https://learn.microsoft.com/windows/win32/api/dwmapi/nf-dwmapi-dwmflush
        remaining = self.last_read + 1/120 - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)
        require(self.dwm.DwmFlush() == 0, "Desktop compositor synchronization is unavailable.")
        started = time.perf_counter()
        require(self.ui.gdi.BitBlt(self.memory, 0, 0, self.width, self.height,
                                  self.dc, self.rectangle[0], self.rectangle[1], 0x00CC0020),
                "Could not read displayed desktop frame.")
        require(self.ui.gdi.GdiFlush(), "Could not finish frame read.")
        self.last_read = time.perf_counter()
        return self.last_read, ctypes.string_at(self.pixels, self.size), started

    def save(self, evidence, filename, pixels):
        path = evidence / filename
        path.write_bytes(struct.pack("<2sIHHI", b"BM", 54+len(pixels), 0, 0, 54)+self.header+pixels)
        return {"path": filename, "sha256": sha256(path), "width": self.width, "height": self.height}

    def close(self):
        g = self.ui.gdi
        g.SelectObject(self.memory, self.old)
        g.DeleteObject(self.bitmap)
        g.DeleteDC(self.memory)
        self.ui.user.ReleaseDC(None, self.dc)


def pixel_spans(rectangle, masks):
    """Contiguous visible spans omit finite edit/button/caret/hover regions."""
    left, top, right, bottom = rectangle
    width = right-left
    spans = []
    for y in range(top, bottom):
        intervals = sorted((max(left, a-2), min(right, c+2))
                           for a, b, c, d in masks if b-2 <= y < d+2 and a-2 < right and c+2 > left)
        cursor = left
        for a, c in intervals:
            if a > cursor:
                spans.append((((y-top)*width+cursor-left)*4, ((y-top)*width+a-left)*4))
            cursor = max(cursor, c)
        if cursor < right:
            spans.append((((y-top)*width+cursor-left)*4, ((y-top)*width+right-left)*4))
    return spans


def visible_bytes(raw, spans):
    visible = bytearray(b"".join(raw[start:end] for start, end in spans))
    # Desktop BI_RGB does not define the unused fourth byte as an alpha channel.
    visible[3::4] = bytes(len(visible)//4)
    return bytes(visible)


def dark_pixels(raw):
    return sum(max(raw[i:i+3]) < 150 for i in range(0, len(raw), 4))


def temporal_panel(ui, panel, name, evidence, panels):
    state = ui.scroll_info(panel)
    maximum = state["nMax"]+1-state["nPage"]
    require(maximum >= 48, name+" needs at least one wheel notch of genuine scrolling.")
    left, top, right, bottom = ui.bounds(panel)
    rectangle = [left+3, top+3, min(right-23, ui.user.GetSystemMetrics(0)-1),
                 min(bottom-3, ui.user.GetSystemMetrics(1)-1)]
    require(rectangle[2]-rectangle[0] >= 200 and rectangle[3]-rectangle[1] >= 200,
            "Too little displayed panel remains for temporal observation.")
    wheel_point = (left+5, top+90)
    stream = DisplayFrames(ui, rectangle)
    result = {"panel": name, "initialScroll": state, "rectangle": rectangle,
              "method": "Paced screen BitBlt into a reusable DIB with DwmFlush timing aid; no app paint request during sampling",
              "timingLimit": "DwmFlush does not flush the target process or entire session; finite desktop samples cannot exclude flashes between samples.",
              "captures": [], "phases": [], "precisionWheel": []}
    panels.append(result)
    try:
        references = {}
        # Clean expected images for the only legitimate positions in each phase.
        for label, action, delta in [("top", 6, 0), ("notch", 6, -120), ("bottom", 7, 0)]:
            ui.send(panel, 0x0115, action)  # WM_VSCROLL SB_TOP/SB_BOTTOM.
            if delta:
                ui.wheel(*wheel_point, delta)
            time.sleep(.12)
            require(ui.user.RedrawWindow(panel, None, None, 0x0185), "Could not establish clean reference frame.")
            time.sleep(.1)
            _, raw, _ = stream.read()
            position = ui.scroll_info(panel)["nPos"]
            expected = {"top": 0, "notch": 48, "bottom": maximum}[label]
            require(position == expected, name+" did not reach the expected reference offset.")
            masks = [c["bounds"] for c in ui.controls(panel) if c["class"].lower() != "static"]
            references[label] = {"raw": raw, "position": position, "masks": masks}
            result["captures"].append(stream.save(evidence, name+"-clean-"+label+".bmp", raw))

        def phase(label, allowed, wheel_deltas):
            ui.progress("temporal scroll: "+name+" "+label)
            keys = list(allowed)
            masks = [m for key in keys for m in references[key]["masks"]]
            spans = pixel_spans(rectangle, masks)
            expected = [visible_bytes(references[key]["raw"], spans) for key in keys]
            compared = len(expected[0])//4
            inks = [dark_pixels(raw) for raw in expected]
            require(compared > 10000 and min(inks) > 100,
                    "Temporal mask removed too much static text/background.")
            require(len(expected) == 1 or expected[0] != expected[1],
                    "Temporal mask removed evidence of visible scrolling between endpoints.")
            samples, anomalous, endpoint_failures = [], {}, []
            details = {"name": label, "samples": samples, "endpointFailures": endpoint_failures}
            result["phases"].append(details)
            start = time.perf_counter()
            # At least two displayed samples per real wheel event. Fifty down/up
            # cycles exercise 100 endpoint transitions without repaint sleeps.
            for event, delta in enumerate(wheel_deltas):
                ui.wheel(*wheel_point, delta)
                target = keys[0] if len(keys) == 1 or delta > 0 else keys[1]
                target_seen = False
                for frame in range(8):
                    stamp, raw, read_start = stream.read()
                    visible = visible_bytes(raw, spans)
                    matched = next((keys[i] for i, value in enumerate(expected) if value == visible), None)
                    sample = {"event": event, "delta": delta, "frame": frame,
                              "elapsedMs": round((stamp-start)*1000, 3),
                              "readMs": round((stamp-read_start)*1000, 3), "matchingReference": matched,
                              "expectedReference": target, "scrollOffset": ui.scroll_info(panel)["nPos"]}
                    if matched is None:
                        digest = hashlib.sha256(visible).hexdigest()
                        sample["maskedSha256"] = digest
                        # Bound evidence while retaining counts for every frame.
                        if digest not in anomalous and len(anomalous) < 12:
                            anomalous[digest] = (raw, visible)
                    samples.append(sample)
                    target_seen = target_seen or matched == target
                    if frame >= 1 and target_seen and sample["scrollOffset"] == references[target]["position"]:
                        break
                if not target_seen or samples[-1]["scrollOffset"] != references[target]["position"]:
                    endpoint_failures.append({"event": event, "targetSeen": target_seen,
                                              "expectedOffset": references[target]["position"],
                                              "actualOffset": samples[-1]["scrollOffset"]})
            elapsed = time.perf_counter()-start
            anomalies = []
            for index, (digest, (raw, visible)) in enumerate(anomalous.items()):
                mismatches = [sum(visible[i:i+3] != ref[i:i+3] for i in range(0, len(visible), 4)) for ref in expected]
                entry = {"maskedSha256": digest, "differentPixelsFromReferences": mismatches,
                         "darkPixels": dark_pixels(visible),
                         **stream.save(evidence, name+"-"+label+"-anomaly-"+str(index)+".bmp", raw)}
                anomalies.append(entry)
                result["captures"].append(entry)
            changed = sum(x["matchingReference"] is None for x in samples)
            details.update({"wheelEvents": len(wheel_deltas),
                                     "frames": len(samples), "requestedEndpointTransitions": len(wheel_deltas) if len(keys) > 1 else 0,
                                     "observedEndpointTransitions": len(wheel_deltas)-len(endpoint_failures) if len(keys) > 1 else 0,
                                     "elapsedSeconds": round(elapsed, 4),
                                     "observedFramesPerSecond": round(len(samples)/elapsed, 2),
                                     "comparedPixelsPerFrame": compared, "referenceDarkPixels": inks,
                                     "unexpectedFrames": changed, "anomalies": anomalies,
                                     "samples": samples, "maskedChildControlBounds": masks})

        ui.send(panel, 0x0115, 6)
        time.sleep(.12)
        phase("top-boundary", ["top"], [120]*30)
        require(ui.scroll_info(panel)["nPos"] == 0, "Boundary wheel unexpectedly moved above the panel top.")
        phase("alternating", ["top", "notch"], [-120, 120]*50)
        require(ui.scroll_info(panel)["nPos"] == 0, "Alternating whole wheel notches did not return to the top.")
        ui.send(panel, 0x0115, 7)
        time.sleep(.12)
        phase("bottom-boundary", ["bottom"], [-120]*30)
        require(ui.scroll_info(panel)["nPos"] == maximum, "Boundary wheel unexpectedly moved below the panel bottom.")

        # Deterministic precision-wheel routing. These are sent native messages,
        # not a claim that physical trackpad hardware is present on hosted CI.
        for route in ["panel", "child-edit"]:
            ui.send(panel, 0x0115, 6)
            time.sleep(.08)
            target = panel
            if route == "child-edit":
                children = [c for c in ui.controls(panel) if c["class"].lower() == "edit"
                            and c["bounds"][1] >= top and c["bounds"][3] < bottom]
                require(children, "Precision wheel regression requires a visible native child edit.")
                target = children[0]["hwnd"]
            for label, deltas, expected in [("negative-one-unit", [-1]*120, 48),
                                             ("positive-one-unit", [1]*120, 0),
                                             ("opposite-fractions", [-1, 1]*60, 0)]:
                for delta in deltas:
                    ui.send(target, 0x020A, (delta & 0xffff) << 16,
                            (wheel_point[0] & 0xffff) | ((wheel_point[1] & 0xffff) << 16))
                actual = ui.scroll_info(panel)["nPos"]
                result["precisionWheel"].append({"route": route, "case": label, "messages": len(deltas),
                                                  "expectedOffset": expected, "actualOffset": actual,
                                                  "passed": actual == expected})
        result["unexpectedFrames"] = sum(p["unexpectedFrames"] for p in result["phases"])
        result["frames"] = sum(p["frames"] for p in result["phases"])
        result["endpointFailures"] = sum(len(p["endpointFailures"]) for p in result["phases"])
        result["precisionPassed"] = all(x["passed"] for x in result["precisionWheel"])
        result["success"] = result["unexpectedFrames"] == 0 and result["endpointFailures"] == 0 and result["precisionPassed"]
        return result
    finally:
        stream.close()


def observe(root, evidence, report):
    # Unlike the workspace/results gates, this observer launches a fresh app
    # without first creating any user records through the private host. Current
    # Starter releases therefore offer Tool Setup over the main window. Direct
    # WM_SETTEXT can still edit the covered search box, but a genuine pointer
    # click then hits the foreground setup window. Retain the older-package
    # diagnostic path, whose releases have no setup profile.
    profile_path = root / "workspace" / "setup-profile.json"
    data = root / "user-data"
    setup_path = data / "tool-setup.json"
    dismissed = json.loads(setup_path.read_text(encoding="utf-8")).get("dismissed", False) if setup_path.is_file() else False
    previous_records = data.exists() and any(p.name not in {"desktop-host.stderr.txt", "tool-setup.json"} for p in data.iterdir())
    has_profile = profile_path.is_file() and bool(json.loads(profile_path.read_text(encoding="utf-8")).get("packs"))
    expect_setup = has_profile and not dismissed and not previous_records
    ui = NativeUI(root, evidence)
    report["nativeWindowsExecuted"] = True
    observation_failed = False
    try:
        ui.wait("scroll gate tool library", lambda: ui.user.IsWindowEnabled(ui.child(410)) and len(ui.library().tools()) > 0)
        def setup_window():
            return next((h for h in ui.windows() if ui.label(h, True) == "WorkbenchToolSetup0100"), None)
        if expect_setup:
            ui.wait("fresh scroll fixture offers Tool Setup", setup_window)
        report["startup"] = {"setupExpected": expect_setup, "setupObserved": bool(setup_window()),
            "windows": [{"class": ui.label(h, True), "title": ui.label(h)} for h in ui.windows()]}
        if setup_window():
            setup = setup_window()
            report["startup"]["capture"] = ui.capture("scroll-first-launch-setup.bmp", setup)
            button = ui.child(713, setup)
            ui.wait("scroll fixture Use Workbench available", lambda: button and ui.user.IsWindowEnabled(button))
            left, top, right, bottom = ui.bounds(button)
            ui.click_at((left+right)//2, (top+bottom)//2)
            ui.wait("scroll fixture Tool Setup dismissed", lambda: not setup_window())
            ui.user.SetForegroundWindow(ui.main)
        # Closing the setup window sends an asynchronous setup/dismiss request.
        # Its window disappears before the host reply re-enables main controls.
        ui.wait("scroll fixture search and library enabled after setup", lambda:
                ui.user.IsWindowEnabled(ui.child(102)) and ui.user.IsWindowEnabled(ui.child(104)))
        # This is the documented supported minimum height, not an undersized
        # artificial viewport; it makes the general-settings panel scrollable.
        ui.user.MoveWindow(ui.main, 0, 0, 1040, 680, True)
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["windowBounds"] = ui.bounds(ui.main)
        ui.set_text(ui.child(102), "Paired-end alignment")
        ui.wait("unique paired-end tool", lambda: len(ui.library().tools()) == 1)
        def click_row():
            ui.click_at(*ui.library().first_tool_point())
        def form_ready():
            return any(c["class"].lower() == "edit" and c["text"] == "Paired-end alignment" for c in ui.controls(ui.child(118)))
        click_row()
        ui.wait("standalone alignment options", form_ready)
        temporal_panel(ui, ui.child(118), "standalone-options", evidence, report["panels"])
        # General settings have no public numeric panel id; the parent of the
        # public input-folder edit is the same native panel used by the user.
        ui.user.GetParent.argtypes = [wintypes.HWND]
        ui.user.GetParent.restype = wintypes.HWND
        temporal_panel(ui, ui.user.GetParent(ui.child(413)), "general-settings", evidence, report["panels"])
        ui.click_button(411)
        ui.wait("workflow mode", lambda: ui.user.IsWindowVisible(ui.child(105)) and
                ui.user.IsWindowEnabled(ui.child(102)) and ui.user.IsWindowEnabled(ui.child(104)))
        click_row()
        ui.click_button(105)
        ui.wait("workflow alignment inspector", form_ready)
        temporal_panel(ui, ui.child(118), "workflow-options", evidence, report["panels"])
    except Exception as exc:
        observation_failed = True
        report["observationError"] = str(exc)
        try:
            report["failureWindows"] = [{"class": ui.label(h, True), "title": ui.label(h)} for h in ui.windows()]
        except Exception as diagnostic:
            report["failureWindowDiagnosticError"] = str(diagnostic)
        raise
    finally:
        try:
            ui.close()
        except Exception as cleanup:
            # Keep the first failed assertion/action as the gate's error. The
            # close helper still terminates its process tree in its own finally.
            report["cleanupError"] = str(cleanup)
            if not observation_failed:
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    root, path = args.app_root.resolve(), args.report.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "nativeWindowsExecuted": False,
              "sourceCommit": args.source_commit, "assetSha256": args.asset_sha256,
              "gateSha256": sha256(__file__), "platform": platform.platform(), "python": sys.version,
              "startedUtc": datetime.now(timezone.utc).isoformat(), "panels": [], "skips": [],
              "diagnostic": args.diagnostic, "scope": "Displayed static text/background during finite scrolling; child edits/buttons masked; actual reported DPI only"}
    try:
        require(os.name == "nt", "This gate requires native Windows and cannot pass by skipping.")
        require(Path(sys.executable).resolve() == (root/"runtime/python/python.exe").resolve(),
                "Use the exact application's private Python.")
        report["executableSha256"] = sha256(root/"NativeWorkbench.exe")
        observe(root, path.parent, report)
        report["observationCompleted"] = True
        report["applicationChecksPassed"] = all(p["success"] for p in report["panels"])
        report["passed"] = sum(p["success"] for p in report["panels"])
        if args.diagnostic:
            report["diagnosticOutcome"] = ("defect-observed" if not report["applicationChecksPassed"] else
                                           "no-defect-observed-in-sampled-frames; not proof of no flicker")
        else:
            require(report["applicationChecksPassed"], "Displayed frame or precision-wheel regressions failed; see per-panel evidence.")
        report["success"] = True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report["completedUtc"] = datetime.now(timezone.utc).isoformat()
        write_json(path, report)
    print(json.dumps({"success": report["success"], "diagnostic": args.diagnostic,
                      "applicationChecksPassed": report.get("applicationChecksPassed"), "report": str(path)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
