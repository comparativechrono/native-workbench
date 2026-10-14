#!/usr/bin/env python3
"""Observe new pack forms and recorded results in the frozen native desktop.

Called by check_prodigal_fasttree_windows after importing the exact candidate
packs and completing a normal recorded run for each. This helper does not copy
application modules into the package, create history fixtures, or execute tools
through GUI automation. Scientific execution is a separate parent-gate scope.
"""
from __future__ import annotations

from pathlib import Path
import time

from check_batch_windows import NativeList
from check_references_windows import require, write_json
from check_workspace_ui_windows import NativeUI


OPERATIONS = (
    "prodigal/predict-genome", "prodigal/predict-metagenome",
    "fasttree/infer-nucleotide", "fasttree/infer-protein",
)


def run_gui(root, evidence, report):
    """Append native GUI checks/captures to the parent report; raise on failure.

    The caller must put the frozen application's workspace first on sys.path.
    ``report['guiRunTools']`` maps each pack ID to the operation used for its
    already completed ``Pack candidate <pack ID>`` history entry.
    """
    import catalog

    root, evidence = Path(root).resolve(), Path(evidence).resolve()
    require(Path(catalog.__file__).resolve().parent == root / "workspace",
            "GUI expectations must come from the frozen application's catalog module.")
    installed = catalog.load_catalog(root)
    require(not installed["errors"], "Installed catalogue errors: " + str(installed["errors"]))
    descriptors = {identity: installed["tools"].get(identity) for identity in OPERATIONS}
    require(all(tool and tool["packVersion"] == "1.0.0" for tool in descriptors.values()),
            "The native GUI gate requires all four exact 1.0.0 candidate operations.")
    run_tools = report.get("guiRunTools", {})
    require(set(run_tools) == {"prodigal", "fasttree"} and
            all(identity in descriptors and identity.startswith(pack + "/")
                for pack, identity in run_tools.items()),
            "Parent gate must identify the actual successful operation for each GUI result.")

    report.setdefault("checks", [])
    report.setdefault("captures", [])
    metadata = report["nativeGUI"] = {"forms": [], "libraries": [], "results": [],
        "scope": "Native form discovery, input labels, search and persisted result presentation; scientific execution is recorded separately.",
        "limitations": ["Observed hosted desktop and DPI only; no representative-PC, high-DPI, multiple-monitor or physical-trackpad acceptance.",
                        "PrintWindow captures are labelled separately from actual displayed BitBlt pixels; neither proves absence of transient flicker."]}

    def check(description):
        report["checks"].append(description)
        print(description, flush=True)

    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((hwnd for hwnd in ui.windows() if ui.label(hwnd) == title), None)

        def click(owner, identity):
            hwnd = ui.child(identity, owner)
            ui.wait("native visible enabled button " + str(identity), lambda:
                    hwnd and ui.user.IsWindowVisible(hwnd) and ui.user.IsWindowEnabled(hwnd))
            left, top, right, bottom = ui.bounds(hwnd)
            ui.click_at((left + right) // 2, (top + bottom) // 2, expected=hwnd)

        def capture(name, owner=None):
            owner = owner or ui.main
            time.sleep(.15)  # Settled layout observation, not a frame/flicker test.
            # Keep the actual visible desktop first: PrintWindow requests a
            # repaint and must not be mistaken for observed displayed pixels.
            desktop = [0, 0, ui.user.GetSystemMetrics(0), ui.user.GetSystemMetrics(1)]
            visible, _ = ui.screen_capture(name + "-display.bmp", desktop)
            report["captures"].append(visible)
            printed = ui.capture(name + "-window.bmp", owner)
            printed["method"] = "PrintWindow; complete window, including any off-desktop portion"
            report["captures"].append(printed)
            controls = ui.controls(owner)
            geometry = {"windowTitle": ui.label(owner), "windowBounds": ui.bounds(owner),
                        "workArea": ui.work_area(), "dpi": ui.user.GetDpiForWindow(owner),
                        "controls": controls}
            write_json(evidence / (name + "-controls.json"), geometry)
            return geometry

        ui.wait("returning native desktop and installed catalogue", lambda:
                ui.library().tools() and ui.user.IsWindowEnabled(ui.child(410)) and
                ui.user.IsWindowEnabled(ui.child(417)))
        ui.fit_window(1280, 900)
        ui.click_button(410)
        bounds, area = ui.bounds(ui.main), ui.work_area()
        metadata.update(windowBounds=bounds, workArea=area, dpi=ui.user.GetDpiForWindow(ui.main),
                        horizontalClipping=bounds[0] < area[0] or bounds[2] > area[2])
        if metadata["horizontalClipping"]:
            metadata["limitations"].append(
                "The application's minimum width exceeds this hosted desktop; right-edge clipping is recorded, not a full-window layout pass.")

        for pack in ("prodigal", "fasttree"):
            ui.set_text(ui.child(102), pack)
            expected = {tool.get("displayName", tool["name"])
                        for tool in descriptors.values() if tool["packId"] == pack}
            ui.wait("two native " + pack + " library operations", lambda:
                    {ui.library().label(item).partition("\n")[0] for item in ui.library().tools()} == expected)
            geometry = capture("pack-library-" + pack)
            metadata["libraries"].append({"query": pack, "labels": sorted(expected),
                                           "windowBounds": geometry["windowBounds"]})
        check("The native library discovers both installed 1.0.0 packs and displays both Prodigal and both FastTree operations under their actual catalogue labels.")

        for identity, tool in descriptors.items():
            title = tool.get("displayName", tool["name"])
            ui.set_text(ui.child(102), title)

            def choices():
                library = ui.library()
                return [item for item in library.tools() if library.label(item).partition("\n")[0] == title]

            ui.wait("exact library operation " + identity, lambda: len(choices()) == 1)
            library = ui.library()
            ui.click_at(*library.point(choices()[0]), expected=ui.child(104))
            expected_title = title + "  ·  " + tool["packVersion"]
            ui.wait("standalone form " + identity, lambda:
                    any(item["text"] == expected_title for item in ui.controls(ui.child(118))) and
                    ui.label(ui.child(113)) == "Run tool" and ui.user.IsWindowEnabled(ui.child(113)))
            form = ui.child(118)
            # Standalone forms retain scroll position across tool selection.
            # Reach the true beginning through the same wheel path as a user
            # before labelling any capture as the top of this form.
            for _ in range(30):
                position = ui.scroll_info(form)
                if position["nPos"] == position["nMin"]:
                    break
                left, top, right, bottom = ui.bounds(form)
                ui.wheel((left + right) // 2, (top + bottom) // 2, 720)
                ui.wait("rewind native form " + identity, lambda:
                        ui.scroll_info(form)["nPos"] < position["nPos"])
            else:
                raise AssertionError("Native form did not reach its first page: " + identity)
            require(ui.scroll_info(form)["nPos"] == ui.scroll_info(form)["nMin"],
                    "Top capture must start at the native form's minimum scroll position.")
            form_bounds = ui.bounds(form)
            library_bounds = ui.library().visible_bounds()
            require(library_bounds[2] <= form_bounds[0],
                    "The new pack form overlaps the visible native tool library: " + identity)
            controls = ui.controls(form)
            labels = {item["text"] for item in controls}
            expected_labels = {port["label"] for port in tool["ports"]}
            expected_labels.update(field["label"] for port in tool["ports"] for field in port["fields"])
            expected_labels.update(param["label"] for param in tool["params"])
            require(expected_labels <= labels,
                    "Native form omitted declared inputs/options for " + identity + ": " + str(sorted(expected_labels - labels)))
            require(any(item["class"].lower() == "edit" and item["id"] >= 2000 for item in controls),
                    "Native standalone form has no editable input/run-name controls: " + identity)
            name = "pack-form-" + identity.replace("/", "-")
            geometry = capture(name + "-top")
            pages = [{"capture": name + "-top", "scroll": ui.scroll_info(form)}]
            # Exercise the normal wheel path, retaining each settled page so
            # input help and options below the first viewport remain reviewable.
            for page in range(1, 25):
                before = ui.scroll_info(form)
                maximum = max(before["nMin"], before["nMax"] - before["nPage"] + 1)
                if before["nPos"] >= maximum:
                    break
                left, top, right, bottom = ui.bounds(form)
                ui.wheel((left + right) // 2, (top + bottom) // 2, -720)
                ui.wait("native option scrolling " + identity, lambda: ui.scroll_info(form)["nPos"] > before["nPos"])
                time.sleep(.15)
                page_name = name + "-page-" + str(page)
                capture(page_name)
                pages.append({"capture": page_name, "scroll": ui.scroll_info(form)})
            else:
                raise AssertionError("Native form exceeds the bounded GUI page walk: " + identity)
            metadata["forms"].append({"operation": identity, "displayName": title,
                "packVersion": tool["packVersion"], "manifestSha256": tool["manifestSha256"],
                "checkedInputOptionLabels": sorted(expected_labels), "pages": pages,
                "formBounds": form_bounds, "visibleLibraryBounds": library_bounds,
                "windowBounds": geometry["windowBounds"]})
            check("Native pointer selection opens " + identity + " with exact pack version, declared input/option labels and reachable form pages.")

        ui.set_text(ui.child(102), "")
        ui.wait("unfiltered native library retains all four new operations", lambda:
                {tool.get("displayName", tool["name"]) for tool in descriptors.values()} <=
                {ui.library().label(item).partition("\n")[0] for item in ui.library().tools()})
        capture("pack-library-unfiltered")
        ui.click_button(417)
        ui.wait("native recorded results window", lambda: window("Recorded results · Native Workbench"))
        results = window("Recorded results · Native Workbench")
        runs = NativeList(ui, ui.child(1503, results))
        for pack, identity in run_tools.items():
            query = "Pack candidate " + pack
            ui.set_text(ui.child(1501, results), query)
            click(results, 1502)
            ui.wait("exact recorded native result " + query, lambda: runs.count() == 1)
            runs.click(0)
            detail_control = ui.child(1504, results)
            operation_line = "Operation: " + identity + "; pack " + pack + " 1.0.0"
            ui.wait("recorded operation and successful status " + identity, lambda:
                    operation_line in ui.label(detail_control) and "Execution status: completed" in ui.label(detail_control))
            details = ui.label(detail_control)
            measurements_unavailable = "No supported hash-verified scientific measurements are available for this run." in details
            require(query in details and descriptors[identity]["manifestSha256"] in details,
                    "Native results omitted submitted analysis name or recorded manifest identity.")
            versions = [{"id": executable["id"], "version": executable["version"]}
                        for executable in descriptors[identity]["executables"]]
            require(versions and all(item["id"] + " " + item["version"] + "; SHA-256 " in details for item in versions),
                    "Native results omitted recorded executable versions: " + identity)
            require("not a QC pass/fail" in details,
                    "Native results lost the measured-results interpretation boundary.")
            capture("pack-results-" + pack, results)
            # Preserve a second view with the actual operation/version section
            # visible if the general interpretation text occupies the first page.
            line = ui.send(detail_control, 0x00C9, details.index(operation_line), 0)  # EM_LINEFROMCHAR.
            first_line = ui.send(detail_control, 0x00CE)  # EM_GETFIRSTVISIBLELINE.
            ui.send(detail_control, 0x00B6, 0, max(0, line - first_line - 1))  # EM_LINESCROLL.
            capture("pack-results-" + pack + "-versions", results)
            write_json(evidence / ("pack-results-" + pack + "-detail.json"),
                       {"query": query, "operation": identity, "text": details})
            metadata["results"].append({"query": query, "operation": identity, "versions": versions,
                                         "manifestSha256": descriptors[identity]["manifestSha256"],
                                         "nativeSummaryReportsMeasurementsUnavailable": measurements_unavailable,
                                         "measurementDisplayScope": "The unchanged application records status, versions and provenance; pack-specific JSON measurements are retained in result files and are not parsed into this native summary." if measurements_unavailable else "Review the retained native detail for supported measurements."})
            if measurements_unavailable:
                metadata["limitations"].append(pack + ": the unchanged application has no parser for this pack's JSON measurements; Native Results reports their unavailability and preserves status/version/provenance display.")
            check("Native Results search finds " + query + " and displays its successful native operation, exact pack/executable versions and recorded manifest identity without a QC verdict.")
        click(results, 1508)
        ui.wait("native Results closes", lambda: not window("Recorded results · Native Workbench"))
        report["nativeGUIValidated"] = True
    except Exception:
        try:
            ui.desktop_evidence("Prodigal/FastTree pack GUI gate failure")
            for number, hwnd in enumerate(ui.windows()):
                ui.capture("pack-gui-failure-%d.bmp" % number, hwnd)
                write_json(evidence / ("pack-gui-failure-%d-controls.json" % number),
                           {"title": ui.label(hwnd), "controls": ui.controls(hwnd)})
        except Exception as error:
            metadata["failureCaptureError"] = str(error)
        raise
    finally:
        ui.close()
