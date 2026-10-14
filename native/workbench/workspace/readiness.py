"""Bounded, local readiness checks before preparing an analysis.

This report deliberately separates graph/file-signature checks from complete
scientific validation and successful tool execution. It does not hash datasets,
execute scientific programs, create a run, or claim a memory/storage estimate.
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile

try:
    from .engine import _check_path_policy, _display_path, _io_path, _resolved_path, clean_text
except ImportError:
    from engine import _check_path_policy, _display_path, _io_path, _resolved_path, clean_text


_INPUT_ERRORS = (ValueError, TypeError, AttributeError, KeyError, OSError,
                 EOFError, UnicodeError, RecursionError)


def _destination(value):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError("Choose an existing absolute output folder.")
    text = os.fspath(value)
    if not clean_text(text, 32768) or not text:
        raise ValueError("Choose an existing absolute output folder.")
    path = _display_path(text)
    if not path.is_absolute():
        raise ValueError("Choose an absolute output folder; relative folders are not supported.")
    # Inspect the requested spelling before resolution: resolving first would
    # hide a symlink/junction in either the destination or its ancestors.
    for ancestor in (path, *path.parents):
        physical = _io_path(ancestor)
        if physical.is_symlink() or (hasattr(physical, "is_junction") and physical.is_junction()):
            raise ValueError("The output folder must not use symbolic links or junctions.")
    if not _io_path(path).is_dir():
        raise ValueError("Choose an existing output folder; readiness does not create folders.")
    # Match Engine.prepare's canonical destination for both policy checks and
    # I/O. In particular, Windows short aliases can conceal non-ASCII names.
    # Resolve only after rejecting links/junctions in the requested spelling.
    return _resolved_path(path)


def _probe_write(path):
    # mkstemp creates a unique, exclusively opened file. Never touch an existing
    # result, and remove the probe even when writing/flushing fails.
    descriptor, filename = tempfile.mkstemp(prefix=".workbench-readiness-", dir=_io_path(path))
    try:
        try:
            if os.write(descriptor, b"\0") != 1:
                raise OSError("Could not write the output-folder probe.")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        _io_path(filename).unlink()


def build_readiness(engine, graph, output_folder=None):
    """Extend ``engine.review`` without changing its legacy graph contract.

    New failures also set ``valid``/``ok`` false so existing Run callers block.
    Omitting a destination is supported for methods previews but produces an
    incomplete readiness report, never a claim that a run is ready.
    """
    try:
        result = copy.deepcopy(engine.review(graph))
    except _INPUT_ERRORS as exc:
        message = "The workspace could not be reviewed: " + str(exc)
        result = {"ok": False, "valid": False, "errors": [{"message": message}],
                  "warnings": [], "issues": [{"severity": "error", "message": message}],
                  "order": [], "methods": "Correct the workspace validation errors to generate planned methods."}

    checks = []
    report = {"schema": 1, "status": "incomplete", "summary": "", "checks": checks,
              "outputFolder": {"path": None, "freeBytes": None, "totalBytes": None},
              "requirements": {"memoryBytes": None, "temporaryBytes": None, "outputBytes": None}}
    result["readiness"] = report

    def add(code, label, status, message):
        checks.append({"code": code, "label": label, "status": status, "message": message})

    def fail(code, label, message, node=None):
        add(code, label, "failed", message)
        issue = {"message": message, "code": code}
        if node is not None:
            issue["nodeId"] = node
        result.setdefault("errors", []).append(issue)
        result.setdefault("issues", []).append(dict(issue, severity="error"))
        result["ok"] = result["valid"] = False

    graph_valid = bool(result.get("valid", result.get("ok", False)))
    add("graph_inputs", "Workflow and inputs", "passed" if graph_valid else "failed",
        "Connections, parameters, input signatures and requested installed tool versions passed the workspace checks."
        if graph_valid else "Correct the workflow and input errors listed in this review.")

    selected_tools = []
    if not graph_valid:
        add("pack_manifests", "Selected pack definitions", "not_checked",
            "Pack manifests and typed schemas will be checked after the workflow and inputs are valid.")
    elif not callable(getattr(engine, "_tool", None)) or not callable(getattr(engine, "_verify_manifest", None)):
        add("pack_manifests", "Selected pack definitions", "not_checked",
            "This engine does not provide installed manifest/schema verification; readiness is incomplete.")
    else:
        manifests_ok = True
        verified = set()
        for node in graph["nodes"]:
            try:
                tool = engine._tool(node)
                selected_tools.append(tool)
                asset = tool.get("schemaAsset") or {}
                identity = (tool.get("packFolder"), tool.get("manifestSha256"),
                            asset.get("path"), asset.get("sha256"))
                if identity not in verified:
                    engine._verify_manifest(tool)
                    verified.add(identity)
            except _INPUT_ERRORS as exc:
                manifests_ok = False
                fail("pack_manifests", "Selected pack definitions", str(exc), node.get("id"))
        if manifests_ok:
            add("pack_manifests", "Selected pack definitions", "passed",
                "Selected installed pack manifests and typed schemas match their recorded identities. "
                "This does not verify every executable or establish successful execution.")

    destination = None
    if output_folder is None:
        add("output_location", "Output folder", "not_checked",
            "No output folder was supplied. Select a destination before checking run readiness.")
    else:
        try:
            destination = _destination(output_folder)
            report["outputFolder"]["path"] = str(destination)
            add("output_location", "Output folder", "passed",
                "The selected destination is an existing ordinary folder without symbolic links or junctions.")
        except _INPUT_ERRORS as exc:
            fail("output_location", "Output folder", str(exc))

    if destination is not None:
        try:
            _probe_write(destination)
            add("output_write", "Output write access", "passed",
                "A temporary file was written, flushed and removed successfully. Access is rechecked when preparing the run.")
        except OSError as exc:
            fail("output_write", "Output write access",
                 "The output-folder write/remove check failed: " + str(exc))
        try:
            usage = shutil.disk_usage(_io_path(destination))
            report["outputFolder"].update(freeBytes=usage.free, totalBytes=usage.total)
            if usage.free <= 0:
                fail("output_space", "Available output storage", "The output drive reports no free storage. Free space before running.")
            else:
                add("output_space", "Available output storage", "passed",
                    f"The output drive reports {usage.free:,} free bytes. Required output and temporary space is unknown; "
                    "this measurement does not establish that the analysis will fit.")
        except OSError as exc:
            add("output_space", "Available output storage", "warning",
                "Free output storage could not be measured: " + str(exc) + ". Check available space before running.")
        if graph_valid and selected_tools:
            try:
                for tool in selected_tools:
                    _check_path_policy(tool, [destination] + [destination / relative
                                       for output in tool.get("outputs", [])
                                       for relative in output.get("files", {}).values()])
                add("output_path_policy", "Tool filename requirements", "passed",
                    "The selected output folder and declared output names meet the tools' recorded path requirements.")
            except _INPUT_ERRORS as exc:
                fail("output_path_policy", "Tool filename requirements", str(exc))

    add("resource_requirements", "Memory and temporary storage", "warning",
        "Memory, temporary storage and final output requirements are unknown. "
        "Check the selected tools' guidance for the dataset size; no capacity guarantee is made.")
    add("input_integrity", "Complete file integrity", "deferred",
        "Complete input/reference hashes and the runner's executable integrity checks occur during preparation and execution. "
        "Only selected pack definitions were checked here; datasets have not been fully rehashed.")
    add("scientific_preflight", "Detailed scientific compatibility", "deferred",
        "Per-tool scientific checks, such as complete records, read-pair synchronisation and alignment/reference headers, "
        "remain required before each affected step. Signature and connection checks do not prove biological compatibility.")
    add("tool_execution", "Successful tool execution", "deferred",
        "No scientific tool was launched by this review. Installation checks and run readiness do not establish "
        "that this analysis will execute successfully or produce scientifically valid results.")

    if any(check["status"] == "failed" for check in checks):
        report.update(status="blocked", summary="Not ready: correct the reported errors before running.")
    elif any(check["status"] == "not_checked" for check in checks):
        report.update(status="incomplete", summary="Readiness is incomplete: some preparation checks have not been performed.")
    else:
        report.update(status="ready_for_preparation",
                      summary="Ready for preparation. Full integrity and per-step scientific checks are still required; execution success is not guaranteed.")
    return result
