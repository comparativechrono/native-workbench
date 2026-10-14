#!/usr/bin/env python3
"""Validate the exact packaged native expandable tool library on Windows.

Requires a fresh disposable Starter extraction and its bundled Python. The
installed application code is unchanged. A clearly identified synthetic pack
is imported through its real native bridge for the independent-category case.
No network, browser, application test hooks or generated UI are used.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_workspace_ui_windows import NativeUI
from check_references_windows import PrivateHost, require, sha256, write_json


def check(report, text):
    report["checks"].append(text)
    print(json.dumps({"check": text}), flush=True)


def fixture_pack(root, evidence):
    """Wrap the unchanged Starter SAMtools in a new, test-only declared category."""
    binary = next((root / "packs").rglob("samtools.exe"))
    executable = binary.read_bytes()
    schema = json.dumps({"schema": 1, "category": "Library gate utilities",
        "workflows": {"version": {"ports": [], "outputs": [{"id": "version", "type": "metrics",
            "manifestOutputs": ["version"]}], "methods": "Synthetic library validation fixture."}}}).encode()
    manifest = f'''[pack]
format=2
id=library-gate
version=1.0.0
name=Library gate fixture
platform=windows-x86_64
[tool:samtools]
path=bin/samtools.exe
version=fixture
sha256={hashlib.sha256(executable).hexdigest()}
[asset:workbench-schema]
path=workbench-schema.json
sha256={hashlib.sha256(schema).hexdigest()}
[workflow:version]
name=Library category fixture
inputs=
outputs=version
steps=run
[output:version:version]
label=Version
path=version.txt
[step:version:run]
label=Version
kind=exec
tool=samtools
arg.0=--version
stdout=version
'''.encode()
    files = {"pack.ini": manifest, "workbench-schema.json": schema,
             "bin/samtools.exe": executable,
             "licenses/TEST-FIXTURE.txt": b"Test-only wrapper around unchanged bundled SAMtools; not a distributed pack.\n"}
    envelope = {"schema": 1, "id": "library-gate", "version": "1.0.0", "packApi": 1,
        "minAppVersion": "0.10.0", "platform": "windows-x86_64",
        "manifestSha256": hashlib.sha256(manifest).hexdigest(), "files": [
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()]}
    path = evidence / "library-gate-fixture.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("workbench-pack.json", json.dumps(envelope))
        for name, data in files.items():
            archive.writestr("pack/" + name, data)
    return path


def exercise(root, evidence, report):
    ui = NativeUI(root, evidence)
    captures = report["captures"]
    try:
        report["nativeGUILaunched"] = True
        report["nativeWindowsExecuted"] = True
        def setup_window():
            return next((h for h in ui.windows() if ui.label(h, True) == "WorkbenchToolSetup0100"), None)
        ui.wait("fresh Starter offers Tool setup", setup_window)
        welcome = setup_window()
        captures.append(ui.capture("library-first-launch-setup.bmp", welcome))
        use_workbench = ui.child(713, welcome)
        ui.wait("first launch permits Use Workbench", lambda: ui.user.IsWindowEnabled(use_workbench))
        left, top, right, bottom = ui.bounds(use_workbench)
        ui.click_at((left+right)//2, (top+bottom)//2)
        ui.wait("dismiss first launch through Use Workbench", lambda: not setup_window())
        ui.wait("native expandable library ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and len(ui.library().tools()) > 0)
        require(ui.label(ui.child(104), True) == "SysTreeView32", "Library is not a native TreeView.")
        require(not ui.child(103), "Obsolete category dropdown remains.")
        ui.fit_window(1280, 900)
        tree = ui.library()
        roots = tree.roots()
        categories = {tree.label(item): [tree.label(child) for child in tree.children(item)] for item in roots}
        report["initialCategories"] = categories
        report["initialRootStates"] = [tree.inspect(item) for item in roots]
        captures.append(ui.capture("library-initial-categories.bmp"))
        require(len(categories) >= 3 and all(categories.values()), "Starter category grouping is missing tools.")
        require(all(tree.expanded(item) == bool(tree.inspect(item)["itemState"] & 0x20) for item in roots),
                "Two documented native TreeView queries disagree about category expansion.")
        require(all(not tree.expanded(item) for item in roots), "Fresh library categories must start collapsed.")
        require(len(tree.tools()) == sum(map(len, categories.values())), "Tool appears outside category grouping.")
        check(report, "Fresh exact Starter displays native collapsed categories and program-named tools without a category dropdown.")

        def root_named(label):
            return next(item for item in tree.roots() if tree.label(item) == label)
        def edits():
            return [c for c in ui.controls(ui.child(118)) if c["id"] >= 2000 and c["class"].lower() == "edit"]
        def has_name(name):
            return any(c["text"] == name for c in edits())
        def filter_to(query, count):
            ui.set_text(ui.child(102), query)
            ui.wait("library filter " + (query or "cleared"), lambda: len(tree.tools()) == count)
        def click_category(item):
            # Separate double-click sequences by focusing a different control;
            # this models deliberate repeated expansion, not double activation.
            left, top, right, bottom = ui.bounds(ui.child(102))
            ui.click_at((left+right)//2, (top+bottom)//2)
            ui.click_at(*tree.point(item))

        # Keep a full native screenshot suitable for reviewing the actual
        # presentation with two real Starter sections open, then restore the
        # deliberate collapsed baseline before the state-transition checks.
        for item in roots[:2]:
            click_category(item)
            ui.wait("open preview category " + tree.label(item), lambda item=item: tree.expanded(item))
        captures.append(ui.capture("library-two-expanded-categories.bmp"))
        for item in roots[:2]:
            click_category(item)
            ui.wait("restore preview category", lambda item=item: not tree.expanded(item))

        first = roots[0]
        label = tree.label(first)
        click_category(first)
        ui.wait("category pointer expands", lambda: tree.expanded(first))
        require(not edits() and ui.send(ui.child(106), 0x1004) == 0, "Category selection launched a tool.")
        ui.key(tree.hwnd, 0x25)
        ui.wait("Left collapses category", lambda: not tree.expanded(first))
        ui.key(tree.hwnd, 0x27)
        ui.wait("Right expands category", lambda: tree.expanded(first))
        ui.key(tree.hwnd, 0x20)
        ui.wait("Space collapses category", lambda: not tree.expanded(first))
        ui.key(tree.hwnd, 0x0D)
        ui.wait("Enter expands category", lambda: tree.expanded(first))
        click_category(first)
        ui.wait("repeated category collapse", lambda: not tree.expanded(first))
        check(report, "Category pointer, Left/Right, Space and Enter toggle headings without opening tools or adding nodes.")

        filter_to("Coordinate sort", 1)
        require(all(tree.expanded(item) for item in tree.roots()), "Search did not reveal a hidden matching child.")
        require("SAMtools" in tree.label(tree.tools()[0]), "Search result lost the scientific program name.")
        captures.append(ui.capture("library-search-expanded.bmp"))
        filter_to("", sum(map(len, categories.values())))
        require(not tree.expanded(root_named(label)), "Search clearing forgot the explicit re-collapsed category.")
        item = root_named(label)
        click_category(item)
        ui.wait("reopen category before second filter", lambda: tree.expanded(item))
        filter_to("no-matching-library-tool-18371", 0)
        require(not tree.roots(), "Empty search left unmatching headings.")
        captures.append(ui.capture("library-empty-search.bmp"))
        filter_to("", sum(map(len, categories.values())))
        require(tree.expanded(root_named(label)), "Empty-search recovery lost a reopened category.")
        check(report, "Search reveals collapsed tools and empty results, and restores repeated open/closed choices when cleared.")

        filter_to("Coordinate sort", 1)
        ui.click_at(*tree.first_tool_point())
        ui.wait("standalone child opens on one click", lambda: has_name("Coordinate sort"))
        handles = tree.roots() + tree.tools()
        selected = tree.selected()
        name_edit = next(c["hwnd"] for c in edits() if c["text"] == "Coordinate sort")
        ui.set_text(name_edit, "Library selected tool")
        # Move focus to commit the real form and receive a fresh model snapshot.
        left, top, right, bottom = ui.bounds(ui.child(102))
        ui.click_at((left+right)//2, (top+bottom)//2)
        time.sleep(.5)
        ui.wait("edited standalone form retained", lambda: has_name("Library selected tool"))
        require(tree.roots() + tree.tools() == handles and tree.selected() == selected,
                "Unchanged model refresh rebuilt the tree or lost selected tool.")
        captures.append(ui.capture("library-standalone-selected.bmp"))
        check(report, "A child opens its standalone form on one click; editing that form preserves native tree handles and selection.")

        ui.click_button(411)
        ui.wait("workflow canvas", lambda: ui.user.IsWindowVisible(ui.child(117)))
        before = ui.send(ui.child(106), 0x1004)
        require(before == 0, "Fresh workflow inherited standalone nodes.")
        canvas = ui.bounds(ui.child(117))
        ui.drag(tree.point(tree.roots()[0]), (canvas[0]+150, canvas[1]+180))
        time.sleep(.2)
        require(ui.send(ui.child(106), 0x1004) == 0, "Dragging a category created a workflow node.")
        ui.click_at(*tree.first_tool_point())
        time.sleep(.2)
        require(ui.send(ui.child(106), 0x1004) == before, "Workflow library single click added a node.")
        # Genuine SendInput double-click sequence, separated from prior click by
        # focusing search. Selection-only first click must not create a duplicate.
        ui.click_at((left+right)//2, (top+bottom)//2)
        tool_point = tree.first_tool_point()
        ui.click_at(*tool_point)
        time.sleep(.08)
        ui.click_at(*tool_point)
        ui.wait("workflow doubleclick adds one tool", lambda: ui.send(ui.child(106), 0x1004) == 1 and has_name("Coordinate sort"))
        time.sleep(.3)
        require(ui.send(ui.child(106), 0x1004) == 1, "Workflow double-click added duplicate tools.")
        ui.click_button(105)
        ui.wait("explicit Add adds one tool", lambda: ui.send(ui.child(106), 0x1004) == 2)
        canvas = ui.bounds(ui.child(117))
        ui.drag(tree.first_tool_point(), (canvas[0]+150, canvas[1]+260))
        ui.wait("child drag adds one tool", lambda: ui.send(ui.child(106), 0x1004) == 3)
        time.sleep(.3)
        require(ui.send(ui.child(106), 0x1004) == 3, "Tree drag produced duplicate workflow nodes.")
        captures.append(ui.capture("library-workflow-three-tools.bmp"))
        ui.click_button(410)
        ui.wait("standalone settings after workflow", lambda: has_name("Library selected tool"))
        check(report, "Categories cannot be dragged into a workflow; child single click selects only, double click/Add/drag each add exactly one tool, and standalone settings survive.")

        # Exercise the library itself at the supported minimum size. Prior
        # scrolling gates concern the option panels, not this new TreeView.
        ui.fit_window(1040, 680)
        filter_to("", sum(map(len, categories.values())))
        for category in tree.roots():
            if not tree.expanded(category):
                click_category(category)
                ui.wait("expand scroll fixture category", lambda category=category: tree.expanded(category))
        bounds = tree.visible_bounds()
        wheel_point = ((bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2)
        scroll_initial = ui.scroll_info(tree.viewport())
        require(scroll_initial["nMax"] + 1 > scroll_initial["nPage"],
                "Expanded Starter library is not genuinely scrollable at the supported minimum size.")
        first_root = tree.roots()[0]
        ui.wheel(*wheel_point, 1200)
        ui.wait("actual library wheel reaches first category", lambda: tree.first_visible() == first_root)
        first_before = tree.first_visible()  # Native row/clip queries only; no scrolling side effects.
        top_state = ui.scroll_info(tree.viewport())
        ui.wheel(*wheel_point, -120)
        ui.wait("actual library wheel scrolls down", lambda:
                tree.first_visible() != first_before and ui.scroll_info(tree.viewport())["nPos"] > top_state["nPos"])
        first_down = tree.first_visible()
        down_state = ui.scroll_info(tree.viewport())
        captures.append(ui.capture("library-minimum-wheel-down.bmp"))
        ui.wheel(*wheel_point, 120)
        ui.wait("opposite library wheel restores first category", lambda:
                tree.first_visible() == first_before and ui.scroll_info(tree.viewport())["nPos"] == top_state["nPos"])
        captures.append(ui.capture("library-minimum-wheel-restored.bmp"))
        ui.wheel(*wheel_point, -120)
        ui.wait("library nonzero viewport before form commit", lambda: tree.first_visible() == first_down)
        handles_scrolled = tree.roots() + tree.tools()
        selected_scrolled = tree.selected()
        first_scrolled = tree.first_visible()
        state_scrolled = ui.scroll_info(tree.viewport())
        name_edit = next(c["hwnd"] for c in edits() if c["text"] == "Library selected tool")
        ui.set_text(name_edit, "Library scrolled tool")
        # Focus changes alone preserve a draft. Clicking the already-active
        # Tools mode commits it and obtains fresh private-host snapshots without
        # changing library mode, filter or catalogue. Recreated inspector HWND
        # proves a response was rendered, not merely local edit text changed.
        ui.click_button(410)
        ui.wait("form commit snapshot rendered while library scrolled", lambda: any(
            c["text"] == "Library scrolled tool" and c["hwnd"] != name_edit for c in edits()))
        require(tree.roots() + tree.tools() == handles_scrolled and tree.selected() == selected_scrolled,
                "Form commit rebuilt the scrolled library or changed its selection.")
        require(tree.first_visible() == first_scrolled and ui.scroll_info(tree.viewport())["nPos"] == state_scrolled["nPos"],
                "Unchanged model snapshot moved the library viewport.")
        require(all(tree.expanded(category) for category in tree.roots()),
                "Unchanged model snapshot collapsed an expanded category.")
        captures.append(ui.capture("library-minimum-scrolled-after-commit.bmp"))
        report["libraryScrolling"] = {
            "input": "Actual SendInput mouse wheel over the native TreeView",
            "requestedWindowSize": [1040, 680], "actualWindowBounds": ui.bounds(ui.main),
            "libraryBounds": tree.visible_bounds(), "dpi": ui.user.GetDpiForWindow(ui.main),
            "top": {"firstVisible": tree.label(first_before), "scroll": top_state},
            "down": {"firstVisible": tree.label(first_down), "scroll": down_state},
            "afterCommit": {"firstVisible": tree.label(tree.first_visible()), "scroll": ui.scroll_info(tree.viewport())},
            "stableHandles": len(handles_scrolled), "selectionPreserved": True,
            "allCategoriesStillExpanded": True, "modelSnapshotObserved": "Inspector edit HWND replaced after explicit commit"}
        check(report, "At minimum size real library wheel moves down and back; a committed model refresh preserves the scrolled viewport, item handles, selection and expanded categories.")
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["displayPixels"] = [ui.user.GetSystemMetrics(0), ui.user.GetSystemMetrics(1)]
    except Exception:
        # Assertion failures (as distinct from wait timeouts) also need the
        # displayed state; preserve the original error if diagnostics fail.
        try:
            report["failureRootStates"] = [ui.library().inspect(item) for item in ui.library().roots()]
            captures.append(ui.capture("library-failure.bmp"))
        except Exception as diagnostic:
            report["failureCaptureError"] = str(diagnostic)
        raise
    finally:
        ui.close()

    archive = fixture_pack(root, evidence)
    host = PrivateHost(root, evidence, "library-fixture-import", offline=True)
    try:
        host.call("init")
        host.call("packs/import", {"path": str(archive)})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            operation = host.call("packs/status")["operation"]
            if not operation.get("active"):
                require(operation.get("status") == "completed" and operation.get("success"),
                        "Native fixture import failed: " + json.dumps(operation))
                break
            time.sleep(.1)
        else:
            raise TimeoutError("Native fixture import timed out.")
    finally:
        host.close()
    report["fixture"] = {"archive": archive.name, "sha256": sha256(archive),
        "category": "Library gate utilities", "scope": "Test-only independent pack; real offline inventory validation and native bridge import, no scientific accuracy claim."}
    ui = NativeUI(root, evidence)
    try:
        ui.wait("new pack category discovered", lambda: ui.user.IsWindowEnabled(ui.child(410)) and any(
            ui.library().label(item) == "Library gate utilities" for item in ui.library().roots()))
        tree = ui.library()
        root_item = next(item for item in tree.roots() if tree.label(item) == "Library gate utilities")
        require(len(tree.children(root_item)) == 1, "New pack does not appear exactly once in its declared category.")
        # This unique fixture category cannot accidentally match unrelated
        # Starter descriptions, unlike generic categories such as Alignment.
        ui.set_text(ui.child(102), "Library gate utilities")
        ui.wait("search matches the independent category name", lambda: len(tree.roots()) == 1 and len(tree.tools()) == 1)
        require(tree.label(tree.roots()[0]) == "Library gate utilities" and tree.expanded(tree.roots()[0]),
                "Category-name search did not reveal its declared tool.")
        ui.set_text(ui.child(102), "")
        ui.wait("restore library after fixture category search", lambda: len(tree.roots()) == len(categories) + 1)
        root_item = next(item for item in tree.roots() if tree.label(item) == "Library gate utilities")
        ui.click_at(*tree.point(root_item))
        ui.wait("installed category expands", lambda: tree.expanded(root_item))
        ui.click_at(*tree.point(tree.children(root_item)[0]))
        ui.wait("installed pack child opens", lambda: any(c["class"].lower() == "edit" and
            c["text"] == "Library category fixture" for c in ui.controls(ui.child(118))))
        captures.append(ui.capture("library-installed-pack-category.bmp"))
        check(report, "An independently imported pack supplies a new category, category-name search result and working selectable child without changing application code.")
    except Exception:
        try:
            report["failureRootStates"] = [ui.library().inspect(item) for item in ui.library().roots()]
            captures.append(ui.capture("library-installed-pack-failure.bmp"))
        except Exception as diagnostic:
            report["failureCaptureError"] = str(diagnostic)
        raise
    finally:
        ui.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    args = parser.parse_args()
    root, target = args.app_root.resolve(), args.report.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "nativeWindowsExecuted": False,
        "nativeGUILaunched": False, "nativeGUIValidated": False, "checks": [], "skips": [], "captures": [],
        "startedUtc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(), "python": sys.version,
        "sourceCommit": args.source_commit, "assetName": args.asset_name, "assetSha256": args.asset_sha256,
        "validatorCommit": os.environ.get("VALIDATOR_COMMIT", args.source_commit),
        "gateSha256": sha256(__file__), "treeHelperSha256": sha256(Path(__file__).with_name("native_tree.py")),
        "appRoot": str(root), "limits": ["Actual reported DPI only; finite screenshots are not a physical-display flicker guarantee.",
            "The existing workspace gate separately verifies compatible port connections and the native 202-record scientific chain."]}
    try:
        require(os.name == "nt", "Native Windows is required; this gate has no passing skip mode.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(),
                "Use the exact packaged application's private Python.")
        report["appSha256"] = sha256(root / "NativeWorkbench.exe")
        protected = [root / "NativeWorkbench.exe", root / "WorkbenchBridge.exe", *sorted((root / "workspace").glob("*.py"))]
        report["applicationFiles"] = {str(p.relative_to(root)): sha256(p) for p in protected}
        exercise(root, target.parent, report)
        require(all(sha256(root / p) == digest for p, digest in report["applicationFiles"].items()),
                "Library validation or fixture import modified application files.")
        report.update(success=True, nativeWindowsExecuted=True, nativeGUIValidated=True)
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report["completedUtc"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = len(report["checks"])
        write_json(target, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(target)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
