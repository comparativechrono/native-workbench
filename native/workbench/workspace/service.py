"""Shared local workbench operations, independent of any UI transport.

Desktop stdio and the historical browser prototype use the same execution,
validation, persistence and native runner implementation in this module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
import uuid

from catalog import load_catalog, load_pack
from engine import Engine
from file_io import replace_file

MAX_PUBLIC_LOG_BYTES = 256 * 1024
MAX_RECENT_BYTES = 3 * 1024 * 1024
MAX_HISTORY_BYTES = 12 * 1024 * 1024
MAX_SAVED_BYTES = 12 * 1024 * 1024
MAX_RESOURCE_BYTES = 128 * 1024
MAX_REVIEW_BYTES = 16 * 1024 * 1024
RESOURCE_NOTICE = ("CPU reservations control admission of independent steps, not an operating-system CPU limit. "
                   "A step with no reservation runs alone. Memory and temporary-storage requirements remain unknown. "
                   "Reservations apply only to this exact workflow; editing it clears them for the new draft. "
                   "Queued plans retain their frozen settings.")

def atomic_json(path, value, *, retry_sharing=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        if retry_sharing:
            replace_file(tmp, path)
        else:
            os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON field: " + key)
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError("Non-finite JSON value: " + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad_constant)


def short_text(value, label, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid " + label)
    return value.strip()


class Workbench:
    def __init__(self, app_root, *, engine=None, catalog=None):
        self.root = Path(app_root).resolve()
        self.web = self.root / "workspace" / "web"
        self.data = self.root / "user-data"
        self.data.mkdir(exist_ok=True)
        self.catalog = catalog if catalog is not None else load_catalog(self.root)
        self.engine = engine or Engine(self.root, self.catalog)
        self.lock = threading.RLock()
        self.dialog_lock = threading.Lock()
        self._history_write_lock = threading.Lock()
        self._resource_write_lock = threading.Lock()
        self._processes = set()
        self._closing = False
        self._changing_packs = False
        self._pack_manager = None
        self._pack_worker = None
        self._pack_cancel = threading.Event()
        self._pack_listing = None
        self._setup_manager = None
        self._setup_worker = None
        self._setup_cancel = threading.Event()
        self._pack_operation = {"id": "", "active": False, "status": "idle",
                                "message": "", "bytes": 0, "total": 0, "cancellable": False}
        self._changing_references = False
        self._reference_manager = None
        self._reference_worker = None
        self._reference_cancel = threading.Event()
        self._reference_listing = None
        self._reference_review = None
        self._reference_operation = {"id": "", "active": False, "status": "idle",
                                     "message": "", "bytes": 0, "total": 0, "cancellable": False}
        self.runs = {}
        self._diagnostic_previews = {}
        self._last_readiness = None
        self._batch_previews = {}
        self._sample_tables = {}
        self._restart_previews = {}
        self._project_export_previews = {}
        self._project_import_previews = {}
        self._project_contexts = {}
        self._queue_prepare_worker = None
        self._queue_prepare_cancel = threading.Event()
        self._queue_worker = None
        self._queue_scheduled = []
        self._queue_current = None
        self._queue_preparing = False
        self._queue_cancelling = set()
        self._queue_admission = threading.Event()
        self._queue_admission.set()
        self.last_seen = time.monotonic()
        self.token = secrets.token_urlsafe(32)
        self.saved_path = self.data / "saved.json"
        self.history_path = self.data / "runs.json"
        self.history = self.read_json(self.history_path, [])
        from run_queue import RunQueue
        self.run_queue = RunQueue(self.data)
        self.resource_path = self.data / "resource-settings.json"
        self._resource_state = None
        self._resource_error = ""
        self._load_resources()
        # A previous host cannot still own an active run after a normal restart.
        # Keep these records explicitly interrupted; never infer success.
        for run in self.history:
            if self.run_queue.owned and run.get("status") in ("preparing", "running", "cancelling"):
                run["status"] = "interrupted"
                run["message"] = "The previous workbench session ended before completion. Inspect the recorded run folder."

    @staticmethod
    def read_json(path, default):
        if not path.exists():
            return copy.deepcopy(default)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Saved workspace file is too large: " + str(path))
        return strict_json(path.read_text(encoding="utf-8"))

    def active(self):
        with self.lock:
            return (self._queue_preparing or self._queue_worker is not None
                    or any(run["status"] in ("preparing", "running", "cancelling") for run in self.runs.values()))

    def activity(self):
        with self.lock:
            identity = next((r["run_id"] for r in self.runs.values()
                             if r["status"] in ("preparing", "running", "cancelling")), None)
            return {"active": identity is not None, "active_run": identity,
                    "changing_packs": self._changing_packs,
                    "changing_references": self._changing_references, "closing": self._closing,
                    "queue_preparing": self._queue_preparing, "queue_running": self._queue_worker is not None,
                    "workspace_editable": not (self._closing or self._changing_packs or self._changing_references)}

    def recent(self, summaries=False):
        with self.lock:
            items = list(self.runs.values()) + [r for r in self.history if r["run_id"] not in self.runs]
            runs, size = [], 0
            for run in list(reversed(list(self.runs.values()))) + [r for r in self.history if r["run_id"] not in self.runs]:
                public = self.public_run(run)
                if summaries:
                    public = {key: public[key] for key in
                              ("run_id", "id", "name", "status", "folder", "started", "started_at",
                               "finished", "finished_at", "success", "cancelled") if key in public}
                    public["node_count"] = len(run.get("nodes", []))
                length = len(json.dumps(public, ensure_ascii=True).encode("utf-8"))
                if size + length > MAX_RECENT_BYTES:
                    continue
                runs.append(public)
                size += length
            return {"runs": runs, "omitted": len(items) - len(runs),
                    "note": "Older or large recent records may be omitted here. Full results remain in their recorded folders."}

    def ensure_model_editable(self):
        """Edits target the next graph, never the immutable executing plan."""
        with self.lock:
            if self._closing:
                raise ValueError("The workbench is closing.")
            if self._changing_packs:
                raise ValueError("Wait for the pack operation to finish.")
            if self._changing_references:
                raise ValueError("Wait for the reference operation to finish or cancel it.")

    def search_results(self, query=""):
        """Search recorded metadata without scanning scientific output files."""
        from results_summary import search_entry, matches
        if not isinstance(query, str) or len(query) > 500 or any(ord(c) < 32 for c in query):
            raise ValueError("Use a results search of at most 500 characters.")
        with self.lock:
            items = list(reversed(list(self.runs.values()))) + [
                run for run in self.history if run.get("run_id") not in self.runs]
            entries = [search_entry(run) for run in items]
        selected = [entry for entry in entries if matches(entry, query)]
        runs, size = [], 0
        for entry in selected:
            length = len(json.dumps(entry, ensure_ascii=True).encode("utf-8"))
            if size + length > MAX_RECENT_BYTES:
                continue
            runs.append(entry)
            size += length
        return {"runs": runs, "omitted": len(selected) - len(runs),
                "note": "Search covers recorded names, samples, states and tools. Full outputs remain in each result folder."}

    def result_summary(self, identity):
        from results_summary import build_summary
        identity = short_text(identity, "recorded run id", 200)
        return build_summary(self.get_run(identity))

    def ensure_editable(self):
        with self.lock:
            self.run_queue.ready()
            if self._closing:
                raise ValueError("The workbench is closing.")
            if self._changing_packs:
                raise ValueError("Wait for the pack operation to finish.")
            if self._changing_references:
                raise ValueError("Wait for the reference operation to finish or cancel it.")
            if self.active():
                raise ValueError("Wait for the active analysis to finish or cancel it before changing the workspace.")

    def saved(self):
        value = self.read_json(self.saved_path, {"pipelines": [], "presets": []})
        if not isinstance(value, dict) or not all(isinstance(value.get(k), list) for k in ("pipelines", "presets")):
            raise ValueError("Saved analyses cannot be read. Keep user-data/saved.json for recovery.")
        return value

    def saved_summaries(self):
        """Small picker records; full bindings-free templates stay server-side."""
        saved = self.saved()
        result = {}
        for key, items in saved.items():
            if key not in ("pipelines", "presets"):
                continue
            result[key] = []
            for item in items:
                summary = {field: item[field] for field in ("id", "name", "saved_at", "tool") if field in item}
                if key == "pipelines":
                    summary["node_count"] = len(item.get("graph", {}).get("nodes", []))
                result[key].append(summary)
        result["summaries"] = True
        return result

    def save(self, request):
        self.run_queue.ready()
        name = short_text(request.get("name"), "saved name")
        kind = request.get("kind")
        if kind == "pipeline":
            item = {"graph": self.engine.save_pipeline(request.get("graph"))}
            key = "pipelines"
        elif kind == "preset":
            node = {"tool": request.get("tool"), "params": request.get("params", {})}
            if "pin" in request:
                node["pin"] = copy.deepcopy(request["pin"])
            item = self.engine.save_preset(node)
            key = "presets"
        else:
            raise ValueError("Choose a pipeline or tool settings to save.")
        item.update(id=uuid.uuid4().hex, name=name, saved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with self.lock:
            saved = self.saved()
            if len(saved[key]) >= 500:
                raise ValueError("The saved analysis limit (500) has been reached.")
            saved[key].append(item)
            if len(json.dumps(saved, ensure_ascii=True, indent=2).encode("utf-8")) > MAX_SAVED_BYTES:
                raise ValueError("Saving this item would exceed the supported saved-workspace size. Existing saved items have been preserved.")
            atomic_json(self.saved_path, saved)
        return item

    def bridge(self, arguments, emit=None, cancel=None):
        command = [str(self.root / "WorkbenchBridge.exe"), *map(str, arguments)]
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        with self.lock:
            if self._closing or cancel is not None and cancel.is_set():
                raise InterruptedError("The workbench is closing or this operation was cancelled.")
            # The desktop launcher selected a safe short working directory for
            # CreateProcessW. Actual workflow steps set their own result cwd.
            process = subprocess.Popen(command, cwd=None if os.name == "nt" else self.root, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", **kwargs)
            self._processes.add(process)
        try:
            result = None
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    event = {"type": "log", "message": line.rstrip()[:16000]}
                if not isinstance(event, dict):
                    event = {"type": "log", "message": str(event)[:16000]}
                if emit:
                    emit(event)
                if event.get("type") == "result":
                    result = event
            exit_code = process.wait()
        finally:
            with self.lock:
                self._processes.discard(process)
            if process.stdout:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        if result is None:
            raise RuntimeError("The native runner did not return a result (exit " + str(exit_code) + ").")
        if result.get("success") and exit_code != 0:
            raise RuntimeError("The native runner reported success but exited abnormally (exit " + str(exit_code) + ").")
        return result

    def browse(self, request):
        if os.name != "nt":
            raise ValueError("Native file selection is available in the Windows build.")
        kind = request.get("kind")
        if kind == "folder":
            args = ["choose-folder"]
        elif kind == "file":
            args = ["choose-file"]
            if request.get("multiple") is True:
                args.append("--multiple")
            if request.get("filter"):
                args.extend(["--filter", short_text(request["filter"], "file filter", 2000)])
        else:
            raise ValueError("Unknown file selection type.")
        if not self.dialog_lock.acquire(blocking=False):
            raise ValueError("A file selection window is already open. Check the Windows taskbar.")
        try:
            return self.bridge(args)
        finally:
            self.dialog_lock.release()

    def review(self, graph, output_folder=None):
        if hasattr(self.engine, "review"):
            from readiness import build_readiness
            result = build_readiness(self.engine, graph, output_folder)
            from execution_resources import storage
            try:
                policy = self.resource_policy(graph)
                resource = {"policy": policy, "memoryBytes": None, "temporaryBytes": None, "notice": RESOURCE_NOTICE}
                if policy["temporaryFolder"]:
                    resource["temporaryStorage"] = storage(policy["temporaryFolder"])
                result["readiness"]["resources"] = resource
                result["readiness"]["checks"].append({"code": "execution_resources", "label": "CPU and temporary storage", "status": "passed",
                    "message": "The CPU admission policy is valid. " + ("The selected temporary folder exists and has available space. " if policy["temporaryFolder"] else "Temporary files use the result folder. ") + "Memory and storage requirements are unknown; this is not an analysis execution check."})
            except (ValueError, OSError, TypeError, KeyError) as error:
                message = str(error)
                result["readiness"]["checks"].append({"code": "execution_resources", "label": "CPU and temporary storage", "status": "failed", "message": message})
                result["readiness"].update(status="blocked", summary="Correct the resource settings before preparing this analysis.")
                result.setdefault("errors", []).append({"message": message, "code": "execution_resources"})
                result.setdefault("issues", []).append({"severity": "error", "message": message, "code": "execution_resources"})
                result["valid"] = result["ok"] = False
            with self.lock:
                self._last_readiness = copy.deepcopy(result["readiness"])
            return result
        result = self.engine.validate(graph)
        issues = [{"severity": "error", "message": str(e)} for e in result.get("errors", [])]
        issues += [{"severity": "warning", "message": str(e)} for e in result.get("warnings", [])]
        return {"valid": result.get("ok", False), "issues": issues, "methods": result.get("methods", "")}

    def preview_methods(self, graph):
        """Read planned methods and graph issues without output/resource probes."""
        return self.engine.review(copy.deepcopy(graph))

    def review_diagnostics(self, run_id=None):
        """Freeze a bounded report for explicit local review; collect no files."""
        from diagnostics import build_report, preview_text
        if run_id is not None:
            run_id = short_text(run_id, "run identity", 200)
        with self.lock:
            run = self.get_run(run_id) if run_id else None
            # A last workspace review is not evidence about a historical run.
            readiness = None if run_id else copy.deepcopy(self._last_readiness)
            report = build_report(self.root, self.catalog, run, readiness)
            preview = preview_text(report)
            now = time.monotonic()
            self._diagnostic_previews = {key: value for key, value in self._diagnostic_previews.items()
                                         if now - value[0] < 900}
            while len(self._diagnostic_previews) >= 4:
                self._diagnostic_previews.pop(next(iter(self._diagnostic_previews)))
            token = secrets.token_urlsafe(32)
            self._diagnostic_previews[token] = (now, copy.deepcopy(report))
        return {"token": token, "preview": preview,
                "notice": "Review this exact report before saving. It contains software versions and broad system information, but no files, paths, sample names, logs or commands. Readiness counts describe the most recent review and may precede later edits. Nothing is uploaded."}

    def save_diagnostics(self, token, output_folder):
        """Export only the immutable report that this host previously previewed."""
        from diagnostics import export_report
        token = short_text(token, "diagnostic preview token", 100)
        destination = short_text(output_folder, "diagnostic output folder", 30000)
        with self.lock:
            item = self._diagnostic_previews.get(token)
            if item is None or time.monotonic() - item[0] >= 900:
                self._diagnostic_previews.pop(token, None)
                raise ValueError("This diagnostic preview expired. Review a new report before saving.")
            # Reserve this one-shot token, then release the execution lock before
            # destination I/O. Slow storage must not block run status/cancellation.
            del self._diagnostic_previews[token]
        try:
            path = export_report(copy.deepcopy(item[1]), destination)
        except Exception:
            with self.lock:
                if time.monotonic() - item[0] < 900 and len(self._diagnostic_previews) < 4:
                    self._diagnostic_previews[token] = item
            raise
        return {"path": str(path), "uploaded": False}

    @staticmethod
    def _graph_key(graph):
        if not isinstance(graph, dict):
            raise ValueError("Choose a workflow for CPU reservations.")
        raw = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("The workflow is too large for resource settings.")
        return hashlib.sha256(raw).hexdigest()

    def _load_resources(self):
        from execution_resources import normalize
        default = normalize(None)
        self._resource_state = {"schema": 1, "defaults": {key: default[key] for key in
                                ("cpuBudget", "maxParallel", "temporaryFolder")}, "profiles": []}
        try:
            if not self.resource_path.exists() and not self.resource_path.is_symlink():
                return
            if self.resource_path.is_symlink() or self.resource_path.stat().st_size > MAX_RESOURCE_BYTES:
                raise ValueError("Invalid resource settings file.")
            value = strict_json(self.resource_path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or set(value) != {"schema", "defaults", "profiles"}
                    or type(value["schema"]) is not int or value["schema"] != 1
                    or not isinstance(value["defaults"], dict)
                    or set(value["defaults"]) != {"cpuBudget", "maxParallel", "temporaryFolder"}
                    or not isinstance(value["profiles"], list) or len(value["profiles"]) > 4):
                raise ValueError("Invalid saved resource settings.")
            # Parse stored syntax without confusing a removed scratch folder or
            # smaller new host with corrupt state. Runtime review rejects an
            # unavailable choice, and the user can explicitly replace it.
            normalize(dict(value["defaults"], stepCpus={}), check_environment=False)
            keys = set()
            for profile in value["profiles"]:
                if (not isinstance(profile, dict) or set(profile) != {"graphSha256", "stepCpus"}
                        or not re.fullmatch(r"[0-9a-f]{64}", str(profile["graphSha256"]))
                        or profile["graphSha256"] in keys):
                    raise ValueError("Invalid saved workflow resource profile.")
                keys.add(profile["graphSha256"])
                normalize(dict(value["defaults"], stepCpus=profile["stepCpus"]), check_environment=False)
            self._resource_state = value
        except (ValueError, TypeError, OSError, KeyError, RecursionError) as error:
            self._resource_error = "Saved resource settings cannot be used. Preserve user-data/resource-settings.json for recovery. " + str(error)

    def resource_state(self, graph=None):
        key = self._graph_key(graph) if graph is not None else None
        with self.lock:
            policy = copy.deepcopy(self._resource_state["defaults"])
            profile = next((item for item in self._resource_state["profiles"] if item["graphSha256"] == key), None)
            policy["stepCpus"] = copy.deepcopy(profile["stepCpus"]) if profile else {}
            return {"policy": policy, "graph_sha256": key, "logical_cpus": max(1, os.cpu_count() or 1),
                    "notice": RESOURCE_NOTICE, "error": self._resource_error}

    def resource_policy(self, graph, *, check_environment=True):
        result = self.resource_state(graph)
        if result["error"]:
            raise ValueError(result["error"])
        from execution_resources import normalize
        return normalize(result["policy"], nodes=graph.get("nodes", []), check_environment=check_environment)

    def set_resources(self, graph, policy):
        from execution_resources import normalize
        key = self._graph_key(graph)
        value = normalize(copy.deepcopy(policy), nodes=graph.get("nodes", []))
        with self._resource_write_lock:
            with self.lock:
                self.run_queue.ready()
                self.ensure_model_editable()
                if self._resource_error:
                    raise ValueError(self._resource_error)
                state = copy.deepcopy(self._resource_state)
            state["defaults"] = {field: value[field] for field in ("cpuBudget", "maxParallel", "temporaryFolder")}
            # Old profiles may reserve more than the newly reduced CPU budget;
            # discard those profiles rather than silently resizing reservations.
            state["profiles"] = [profile for profile in state["profiles"]
                                 if profile["graphSha256"] != key and all(n <= value["cpuBudget"] for n in profile["stepCpus"].values())]
            if value["stepCpus"]:
                state["profiles"].append({"graphSha256": key, "stepCpus": value["stepCpus"]})
            state["profiles"] = state["profiles"][-4:]
            if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > MAX_RESOURCE_BYTES:
                raise ValueError("Resource settings exceed the supported size.")
            if self.resource_path.is_symlink():
                raise ValueError("Resource settings must not be a symbolic link.")
            atomic_json(self.resource_path, state, retry_sharing=True)
            with self.lock:
                self._resource_state = state
        return self.resource_state(graph)

    def _store_preview(self, collection, value):
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > MAX_REVIEW_BYTES:
            raise ValueError("This review exceeds the supported size. Choose a smaller project.")
        with self.lock:
            now = time.monotonic()
            for token, item in list(collection.items()):
                if now - item[0] >= 900:
                    del collection[token]
            while collection and (len(collection) >= 4 or sum(item[2] for item in collection.values()) + size > 32 * 1024 * 1024):
                del collection[next(iter(collection))]
            token = secrets.token_urlsafe(32)
            collection[token] = (now, copy.deepcopy(value), size)
        return token

    def _preview(self, collection, token, *, consume=False):
        token = short_text(token, "review token", 100)
        with self.lock:
            item = collection.get(token)
            if item is None or time.monotonic() - item[0] >= 900:
                collection.pop(token, None)
                raise ValueError("This review expired. Review the selection again.")
            if consume:
                del collection[token]
            return copy.deepcopy(item[1])

    def review_restart(self, identity):
        identity = short_text(identity, "run identity", 200)
        with self.lock:
            run = self.get_run(identity)
            if run.get("status") not in ("completed", "failed", "cancelled", "interrupted"):
                raise ValueError("Choose a finished or interrupted run to review for restart.")
            graph = copy.deepcopy(run.get("graph"))
            folder = run.get("folder")
        if not isinstance(graph, dict) or not folder:
            raise ValueError("This run has no recorded workflow and result folder for restart.")
        policy = self.resource_policy(graph)
        review = self.engine.review_restart(graph, folder, resource_policy=policy)
        token = self._store_preview(self._restart_previews,
                                    {"graph": graph, "review": review, "policy": policy, "run_id": identity})
        nodes = [{key: item[key] for key in ("id", "action", "reason") if key in item} for item in review.get("nodes", [])]
        return {"token": token, "source_run_id": identity, "source_folder": folder, "policy": policy, "nodes": nodes,
                "reuse_count": sum(node.get("action") == "reuse" for node in nodes),
                "rerun_count": sum(node.get("action") != "reuse" for node in nodes),
                "notice": "Only verified completed steps are reused, with copies in a new result folder. Queueing does not run the workflow. Source evidence is checked again before use."}

    def remember_project(self, graph, result):
        key = self._graph_key(graph)
        context = {"sampleMetadata": copy.deepcopy(result.get("sampleMetadata")),
                   "projectMetadata": copy.deepcopy(result.get("projectMetadata"))}
        if len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > MAX_REVIEW_BYTES:
            raise ValueError("Imported project context exceeds the supported size.")
        with self.lock:
            self._project_contexts.pop(key, None)
            self._project_contexts[key] = context
            while len(self._project_contexts) > 4:
                del self._project_contexts[next(iter(self._project_contexts))]

    def _project_context(self, graph):
        key = self._graph_key(graph)
        with self.lock:
            return copy.deepcopy(self._project_contexts.get(key, {}))

    def _result_export(self, identity):
        from engine import _io_path, _ordinary, digest_file, canonical
        from recovery import _source
        identity = short_text(identity, "result identity", 200)
        run = self.get_run(identity)
        if run.get("status") not in ("completed", "failed", "cancelled", "interrupted") or not run.get("folder"):
            raise ValueError("Choose a finished or interrupted recorded result for export.")
        plan, record, _ = _source(run["folder"])
        if run.get("id") is not None and run["id"] != plan["id"]:
            raise ValueError("The selected result identity differs from its saved plan.")
        if canonical(plan.get("batch")) != canonical(record.get("batch")):
            raise ValueError("The saved result sample metadata differs from its frozen plan.")
        for path, expected in plan.get("inputs", {}).items():
            source = _ordinary(path)
            if (_io_path(source).stat().st_size != expected.get("bytes")
                    or digest_file(source) != expected.get("sha256")):
                raise ValueError("An original result input changed. Export the current draft to describe new input bytes.")
        return copy.deepcopy(plan["graph"]), copy.deepcopy(plan.get("batch")), plan

    def project_preview(self, request, *, importing=False):
        from project_manager import ProjectManager
        manager = ProjectManager(self.engine)
        if importing:
            preview = manager.preview_import(short_text(request.get("path"), "project archive", 30000))
            collection = self._project_import_previews
        else:
            if "run_id" in request:
                graph, sample, source_plan = self._result_export(request["run_id"])
                project_context = source_plan.get("project")
                reference_metadata = source_plan.get("references", {})
                validation_tools = {node["id"]: copy.deepcopy(node["validationTools"]["samtools"])
                                    for node in source_plan.get("nodes", []) if node.get("validationTools", {}).get("samtools")}
            else:
                graph = copy.deepcopy(request["graph"])
                context = self._project_context(graph)
                sample = copy.deepcopy(request.get("sample_metadata", context.get("sampleMetadata")))
                project_context = context.get("projectMetadata")
                reference_metadata = None
                validation_tools = None
            options = {"include_data": copy.deepcopy(request.get("include_data", False)), "sample_metadata": sample}
            if project_context is not None:
                options["project_metadata"] = copy.deepcopy(project_context)
            if reference_metadata is not None:
                options["reference_metadata"] = copy.deepcopy(reference_metadata)
                options["validation_tools"] = validation_tools
            preview = manager.export_preview(graph, **options)
            preview["summary"]["source"] = "recorded-result" if "run_id" in request else "current-workflow"
            preview["summary"]["sample_metadata"] = copy.deepcopy(sample)
            preview["summary"]["metadata_notice"] = "Sample metadata describes the original selection; importing a project does not configure or start a sample batch."
            collection = self._project_export_previews
        token = self._store_preview(collection, preview)
        return dict(copy.deepcopy(preview["summary"]), token=token)

    def project_resolve(self, token, mappings):
        from project_manager import ProjectManager
        if not isinstance(mappings, dict) or len(mappings) > 1024:
            raise ValueError("Choose explicit project file mappings.")
        previous = self._preview(self._project_import_previews, token)
        merged = dict(previous.get("mappings", {}))
        merged.update(copy.deepcopy(mappings))
        current = ProjectManager(self.engine).preview_import(previous["archive"], mappings=merged)
        if current["archiveSha256"] != previous["archiveSha256"]:
            raise ValueError("The project archive changed after review. Inspect it again.")
        # Replace the old preview only after the replacement is verified.
        self._preview(self._project_import_previews, token, consume=True)
        new_token = self._store_preview(self._project_import_previews, current)
        return dict(copy.deepcopy(current["summary"]), token=new_token)

    def project_commit(self, token, destination, *, importing=False):
        from project_manager import ProjectManager
        with self.lock:
            self.run_queue.ready()
            self.ensure_model_editable()
        collection = self._project_import_previews if importing else self._project_export_previews
        preview = self._preview(collection, token, consume=True)
        manager = ProjectManager(self.engine)
        target = short_text(destination, "project destination", 30000)
        # A failed write requires a new review; never replay an uncertain commit.
        return manager.import_project(preview, target) if importing else manager.export(preview, target)

    def open_project(self, folder):
        from project_manager import ProjectManager
        return ProjectManager(self.engine).open_project(short_text(folder, "project folder", 30000))

    def queue_state(self):
        result = self.run_queue.snapshot()
        result["jobs"] = [{key: value for key, value in job.items() if key not in ("metadata", "files")}
                          for job in result["jobs"]]
        with self.lock:
            result.update(paused=not bool(self._queue_scheduled or self._queue_worker),
                          scheduled=list(self._queue_scheduled), preparing=self._queue_preparing,
                          active_job=self._queue_current)
            result.update(self.activity())
        return result

    def import_sample_table(self, path):
        from sample_table import read_table
        table = read_table(short_text(path, "sample table path", 30000))
        return self._store_sample_table(table)

    def _retain_sample_token(self, token):
        if token is not None:
            token = short_text(token, "retained sample table token", 100)
            item = self._sample_tables.get(token)
            now = time.monotonic()
            if item is None:
                # This token protects the previous selection during editing;
                # it is not authority for the fully revalidated new draft.
                # Losing an old cache entry must not strand unsaved edits.
                return None
            # A complete local draft may have been edited for over 15 minutes.
            # Renew the still-retained immutable original for Cancel without
            # weakening the normal expiry rules for table reads or previews.
            self._sample_tables[token] = (now, item[1], item[2])
        return token

    def _sample_table_room(self, table, retain_token):
        size = len(json.dumps(table, ensure_ascii=False).encode("utf-8"))
        retained = self._sample_tables[retain_token][2] if retain_token is not None else 0
        if size + retained > 32 * 1024 * 1024:
            raise ValueError("These tables exceed the 32 MiB retained-table limit. The selected table is preserved.")
        return size

    def _store_sample_table(self, table, retain_token=None):
        # A new token always owns a full immutable table, never its short UI
        # summary. Editing, saving or importing cannot alter an older token.
        table = copy.deepcopy(table)
        retention_requested = retain_token is not None
        with self.lock:
            retain_token = self._retain_sample_token(retain_token)
            size = self._sample_table_room(table, retain_token)
            now = time.monotonic()
            self._sample_tables = {key: value for key, value in self._sample_tables.items() if now - value[0] < 900}
            while self._sample_tables and (len(self._sample_tables) >= 4 or sum(item[2] for item in self._sample_tables.values()) + size > 32 * 1024 * 1024):
                self._sample_tables.pop(next(key for key in self._sample_tables if key != retain_token))
            token = secrets.token_urlsafe(32)
            self._sample_tables[token] = (now, table, size)
        summary = {key: copy.deepcopy(value) for key, value in table.items() if key != "rows"}
        rows, total = [], 0
        for row in table["rows"][:100]:
            length = len(json.dumps(row, ensure_ascii=True).encode("utf-8"))
            if total + length > 256 * 1024:
                break
            rows.append(copy.deepcopy(row))
            total += length
        summary.update(table_token=token, rowCount=len(table["rows"]), rows=rows,
                       preview_omitted=len(table["rows"]) - len(rows),
                       retainedSelectionAvailable=not retention_requested or retain_token is not None)
        if retention_requested and retain_token is None:
            summary["retentionNotice"] = ("The previous sample-table selection is no longer cached. Your complete editor draft is retained. "
                                          "Use this table, or import the previous table again if you cancel.")
        return summary

    def _sample_table(self, token, *, refresh=False):
        token = short_text(token, "sample table token", 100)
        with self.lock:
            item = self._sample_tables.get(token)
            if item is None or time.monotonic() - item[0] >= 900:
                raise ValueError("This sample table preview expired. Import the table again or apply the complete editor draft.")
            if refresh:
                self._sample_tables[token] = (time.monotonic(), item[1], item[2])
            return copy.deepcopy(item[1])

    def edit_sample_table(self, token):
        from sample_table_editor import editable_table
        return dict(editable_table(self._sample_table(token, refresh=True)), table_token=token)

    def apply_sample_table(self, draft, retain_token=None):
        from sample_table_editor import apply_draft
        return self._store_sample_table(apply_draft(draft), retain_token)

    def save_sample_table(self, token, path, file_columns, retain_token=None):
        from sample_table_editor import EXPORT_NOTICE, save_table
        if isinstance(path, str) and path != path.strip():
            raise ValueError("Choose an exact new sample-table path without surrounding whitespace.")
        path = short_text(path, "new sample table path", 30000)
        # Keep the bounded token reservation and create-new save together:
        # malformed retention or insufficient room must fail before publication.
        with self.lock:
            requested_retention = retain_token
            retain_token = self._retain_sample_token(retain_token)
            table = save_table(self._sample_table(token), path, file_columns,
                               before_write=lambda value: self._sample_table_room(value, retain_token))
            return dict(self._store_sample_table(table, requested_retention), path=path, saved=True, exportNotice=EXPORT_NOTICE)

    def example_sample_table(self, retain_token=None):
        from sample_table_editor import synthetic_example
        return self._store_sample_table(synthetic_example(self.root, self.catalog), retain_token)

    def preview_batch(self, request):
        from sample_table import preview_batch
        if "table_token" in request:
            table = self._sample_table(request["table_token"])
        else:
            table = copy.deepcopy(request["table"])
        policy = self.resource_policy(request["graph"])
        project_context = self._project_context(request["graph"]).get("projectMetadata")
        result = preview_batch(self.engine, copy.deepcopy(request["graph"]), table,
                               copy.deepcopy(request["bindings"]),
                               parameter_bindings=copy.deepcopy(request.get("parameter_bindings")),
                               mode=request.get("mode", "independent"), shared_sources=copy.deepcopy(request.get("shared_sources", [])),
                               combined_target=copy.deepcopy(request.get("combined_target")))
        if result.get("valid"):
            context_key = self._graph_key(request["graph"])
            if project_context is not None and any(self._graph_key(sample["graph"]) != context_key for sample in result["samples"]):
                result.setdefault("warnings", []).append({"message": "This batch changes the imported project workflow. Its historical project context is not attached to changed sample graphs; actual sample file hashes and selected batch metadata are recorded normally."})
            if len(result["samples"]) > 200:
                raise ValueError("Choose at most 200 independent samples per queued batch.")
            size = len(json.dumps(result["samples"], ensure_ascii=False).encode("utf-8"))
            if size > 32 * 1024 * 1024:
                raise ValueError("This expanded sample batch is too large. Review fewer samples at a time.")
            with self.lock:
                now = time.monotonic()
                self._batch_previews = {key: value for key, value in self._batch_previews.items() if now - value[0] < 900}
                while self._batch_previews and (len(self._batch_previews) >= 4 or sum(item[2] for item in self._batch_previews.values()) + size > 32 * 1024 * 1024):
                    self._batch_previews.pop(next(iter(self._batch_previews)))
                token = secrets.token_urlsafe(32)
                self._batch_previews[token] = (now, copy.deepcopy(result["samples"]), size, policy, project_context, context_key)
            result["token"] = token
        result["samples"] = [{"sampleId": sample["sampleId"], "valid": sample.get("valid", True),
                               "nodeCount": len(sample.get("graph", {}).get("nodes", []))}
                              for sample in result.get("samples", [])]
        for key in ("errors", "warnings"):
            shown, size = [], 0
            items = result.get(key, [])
            for item in items:
                length = len(json.dumps(item, ensure_ascii=True).encode("utf-8"))
                if len(shown) >= 200 or size + length > 256 * 1024:
                    break
                shown.append(item)
                size += length
            result[key] = shown
            result[key + "_omitted"] = len(items) - len(shown)
        return result

    def enqueue(self, request, *, batch=False, restart=False):
        from run_queue import ordinary_directory, freeze_plan, utc
        output = ordinary_directory(short_text(request.get("output_folder"), "output folder", 30000))
        token = short_text(request.get("token"), "run preview token", 100) if batch or restart else None
        restart_preview = self._preview(self._restart_previews, token) if restart else None
        captured_policy = self.resource_policy(request.get("graph")) if not batch and not restart else None
        project_context = self._project_context(request["graph"]).get("projectMetadata") if not batch and not restart else None
        context_key = self._graph_key(request["graph"]) if not batch and not restart else None
        with self.lock:
            self.run_queue.ready()
            self.ensure_model_editable()
            if self._queue_preparing:
                raise ValueError("Another batch is being prepared. Wait for it to finish or cancel it.")
            if batch:
                item = self._batch_previews.get(token)
                if item is None or time.monotonic() - item[0] >= 900:
                    self._batch_previews.pop(token, None)
                    raise ValueError("This sample preview expired. Review the sample table again.")
                samples = copy.deepcopy(item[1])
                captured_policy = copy.deepcopy(item[3])
                project_context = copy.deepcopy(item[4])
                context_key = item[5]
            elif restart:
                # Reserve below with queue admission so a concurrent duplicate
                # token cannot prepare a second unintended restart.
                restart_preview = self._preview(self._restart_previews, token)
                samples = [{"graph": copy.deepcopy(restart_preview["graph"])}]
                captured_policy = copy.deepcopy(restart_preview["policy"])
            else:
                graph = copy.deepcopy(request.get("graph"))
                if not isinstance(graph, dict):
                    raise ValueError("Choose a workflow to queue.")
                samples = [{"graph": graph}]
            if not samples or len(samples) > 200:
                raise ValueError("Choose between one and 200 samples to queue.")
            self._queue_preparing = True
            self._queue_admission.clear()
            cancel = self._queue_prepare_cancel = threading.Event()
            engine = self.engine
            batch_id = secrets.token_hex(16)
        try:
            jobs = self.run_queue.add(samples, batch_id)
        except Exception:
            with self.lock:
                self._queue_preparing = False
                self._queue_admission.set()
            raise
        with self.lock:
            if batch:
                self._batch_previews.pop(token, None)
            if restart:
                self._restart_previews.pop(token, None)
        identities = [job["job_id"] for job in jobs]

        def work():
            try:
                for sample, job in zip(samples, jobs):
                    if cancel.is_set():
                        raise InterruptedError("Cancelled while preparing the batch.")
                    kwargs = {"cancel": cancel, "resource_policy": copy.deepcopy(captured_policy)}
                    if project_context is not None and self._graph_key(sample["graph"]) == context_key:
                        kwargs["project_metadata"] = copy.deepcopy(project_context)
                    if restart:
                        kwargs["restart_from"] = copy.deepcopy(restart_preview["review"])
                    if batch:
                        kwargs["run_metadata"] = {"batchId": batch_id, "sampleId": sample["sampleId"],
                                                  "metadata": copy.deepcopy(sample.get("metadata", {}))}
                    plan = engine.prepare(copy.deepcopy(sample["graph"]), output, **kwargs)
                    frozen = freeze_plan(plan)
                    self.run_queue.update([job["job_id"]], **frozen)
                if cancel.is_set():
                    raise InterruptedError("Cancelled while preparing the batch.")
                self.run_queue.update(identities, status="queued", message="Ready. Choose Start queue to execute this frozen plan.")
                if cancel.is_set():
                    raise InterruptedError("Cancelled while preparing the batch.")
            except Exception as error:
                try:
                    self.run_queue.update(identities, status="cancelled" if cancel.is_set() else "failed",
                                          finished_at=utc(), message=str(error)[:2000])
                except Exception as storage_error:
                    self.run_queue.error = "The run queue could not record preparation failure. " + str(storage_error)
            finally:
                with self.lock:
                    self._queue_preparing = False
                    self._queue_prepare_worker = None
        worker = threading.Thread(target=work, name="workbench-queue-prepare", daemon=False)
        with self.lock:
            self._queue_prepare_worker = worker
            worker.start()
            self._queue_admission.set()
        result = self.queue_state()
        result["added"] = identities
        result["batch_id"] = batch_id
        return result

    def start_queue(self):
        with self.lock:
            self.ensure_editable()
            snapshot = self.run_queue.snapshot()
            identities = [job["job_id"] for job in snapshot["jobs"] if job["status"] == "queued" and job["job_id"] not in self._queue_cancelling]
            if not identities:
                raise ValueError("There are no prepared queued analyses to start.")
            self._queue_scheduled = identities
            worker = threading.Thread(target=self._run_queued, name="workbench-run-queue", daemon=False)
            self._queue_worker = worker
            worker.start()
        return self.queue_state()

    def pause_queue(self):
        self.run_queue.ready()
        with self.lock:
            self._queue_scheduled = []
        return self.queue_state()

    def cancel_queued_immediate(self, identity):
        """Signal active/preparing work without storage or the slow RPC pool.

        A queued job returns None, so its durable cancellation stays off the
        protocol reader. Classification and signalling share the execution lock;
        a state race can never fall through to disk work on this fast path.
        """
        identity = short_text(identity, "queued job identity", 100)
        self.run_queue.ready()
        with self.lock:
            job = next((job for job in self.run_queue.snapshot()["jobs"] if job["job_id"] == identity), None)
            if job is None:
                raise ValueError("The selected queued job is no longer recorded.")
            if identity == self._queue_current:
                self._queue_scheduled = []
                run = self.runs.get(identity)
                if run is not None:
                    run["_cancel"].set()
                    run["status"] = "cancelling"
                return self.queue_state()
            if job["status"] == "preparing":
                self._queue_prepare_cancel.set()
                return self.queue_state()
            if job["status"] != "queued":
                return self.queue_state()
            return None

    def cancel_queued(self, identity):
        identity = short_text(identity, "queued job identity", 100)
        self.run_queue.ready()
        with self.lock:
            job = next((job for job in self.run_queue.snapshot()["jobs"] if job["job_id"] == identity), None)
            if job is None:
                raise ValueError("The selected queued job is no longer recorded.")
            if identity == self._queue_current:
                self._queue_scheduled = []
                run = self.runs.get(identity)
                if run:
                    run["_cancel"].set()
                    run["status"] = "cancelling"
                return self.queue_state()
            if job["status"] == "preparing":
                self._queue_prepare_cancel.set()
                return self.queue_state()
            if job["status"] != "queued":
                return self.queue_state()
            self._queue_scheduled = [value for value in self._queue_scheduled if value != identity]
            self._queue_cancelling.add(identity)
        from run_queue import utc
        try:
            self.run_queue.update([identity], status="cancelled", finished_at=utc(), message="Cancelled before execution.")
        finally:
            with self.lock:
                self._queue_cancelling.discard(identity)
        return self.queue_state()

    def _run_queued(self):
        from run_queue import load_plan, utc
        try:
            while True:
                with self.lock:
                    if self._closing or not self._queue_scheduled:
                        break
                    identity = self._queue_scheduled.pop(0)
                    job = next(job for job in self.run_queue.snapshot()["jobs"] if job["job_id"] == identity)
                    if job["status"] != "queued" or identity in self._queue_cancelling:
                        continue
                    self._queue_current = identity
                    run = {"run_id": identity, "queue_job_id": identity, "status": "running", "events": [],
                           "nodes": [], "folder": job["folder"], "name": job["name"], "message": "Verifying queued plan",
                           "started_at": utc(), "_cancel": threading.Event(),
                           "_cancel_file": self.data / ("cancel-" + identity)}
                    self.runs[identity] = run
                def emit(event):
                    if not isinstance(event, dict):
                        event = {"type": "log", "message": str(event)}
                    with self.lock:
                        run["events"].append(copy.deepcopy(event))
                        run["events"] = run["events"][-1500:]
                        if event.get("type") == "phase":
                            run["message"] = event.get("message", "")
                        if event.get("type") == "step" and event.get("nodeId"):
                            node = next((node for node in run["nodes"] if node.get("id") == event["nodeId"]), None)
                            if node is None:
                                node = {"id": event["nodeId"]}
                                run["nodes"].append(node)
                            node.update({key: value for key, value in event.items() if key in ("status", "message", "name", "folder")})
                try:
                    self.run_queue.update([identity], status="running", started_at=run["started_at"], message="Verifying and executing frozen plan.")
                    plan = load_plan(job, run["_cancel"])
                    with self.lock:
                        run.update(graph=copy.deepcopy(plan["graph"]), methods_planned=plan.get("methods", ""))
                        if "batch" in plan:
                            run["batch"] = copy.deepcopy(plan["batch"])
                    self.persist_run(run)
                    result = self.engine.execute(plan, event=emit, cancel=run["_cancel"])
                    with self.lock:
                        run.update({key: value for key, value in result.items() if key not in ("run_id", "events") and not key.startswith("_")})
                        status = str(result.get("status", "failed"))
                        run["status"] = "completed" if status in ("success", "succeeded", "complete", "completed") else "cancelled" if status == "cancelled" else "failed"
                except Exception as error:
                    with self.lock:
                        run["status"] = "cancelled" if run["_cancel"].is_set() else "failed"
                        run["message"] = str(error)
                        emit({"type": "error", "message": str(error)})
                finally:
                    with self.lock:
                        run["finished_at"] = utc()
                        if run["status"] != "completed":
                            self._queue_scheduled = []
                    run["_cancel_file"].unlink(missing_ok=True)
                    self.persist_run(run)
                    self.run_queue.update([identity], status=run["status"], finished_at=run["finished_at"], message=str(run.get("message", ""))[:2000])
                    with self.lock:
                        self._queue_current = None
        except Exception as error:
            self.run_queue.error = "The run queue could not safely continue. " + str(error)
        finally:
            with self.lock:
                self._queue_scheduled = []
                self._queue_current = None
                self._queue_worker = None

    def public_run(self, run):
        public = {key: copy.deepcopy(value) for key, value in run.items() if not key.startswith("_")}
        events, size = [], 0
        original = public.get("events", [])
        for event in reversed(original):
            length = len(json.dumps(event, ensure_ascii=True).encode("utf-8"))
            if size + length > MAX_PUBLIC_LOG_BYTES:
                break
            events.append(event)
            size += length
        public["events"] = list(reversed(events))
        public["events_omitted"] = public.get("events_omitted", 0) + len(original) - len(events)
        return public

    def get_run(self, identity):
        with self.lock:
            if identity in self.runs:
                return self.public_run(self.runs[identity])
            for run in self.history:
                if run.get("run_id") == identity:
                    return copy.deepcopy(run)
        raise ValueError("This run is not recorded in this workbench.")

    def persist_run(self, run):
        with self._history_write_lock:
            with self.lock:
                public = self.public_run(run)
                public["events_omitted"] += max(0, len(public.get("events", [])) - 100)
                public["events"] = public.get("events", [])[-100:]
                candidates = [public, *[r for r in self.history if r.get("run_id") != run["run_id"]]][:200]
            history, size = [], 0
            for item in candidates:
                length = len(json.dumps(item, ensure_ascii=True).encode("utf-8"))
                if history and size + length > MAX_HISTORY_BYTES:
                    continue
                history.append(item)
                size += length
            atomic_json(self.history_path, history, retry_sharing=True)
            with self.lock:
                self.history = history

    def start(self, request, check=False):
        graph = copy.deepcopy(request.get("graph")) if not check else None
        output = Path(short_text(request.get("output_folder"), "output folder", 30000))
        if not output.is_absolute() or not output.is_dir():
            raise ValueError("Choose an existing absolute output folder.")
        with self.lock:
            self.run_queue.ready()
            if self._closing:
                raise ValueError("The workbench is closing.")
            if self._changing_packs:
                raise ValueError("Wait for the tool pack import to finish before starting an analysis.")
            if self._changing_references:
                raise ValueError("Wait for the reference operation to finish or cancel it before starting an analysis.")
            if self.active():
                raise ValueError("An analysis is already running. Wait for it to finish or cancel it first.")
            if not check and not isinstance(graph, dict):
                raise ValueError("Choose an analysis workflow before starting.")
            policy = self.resource_policy(graph, check_environment=False) if not check else None
            project_context = self._project_context(graph).get("projectMetadata") if not check else None
            identity = uuid.uuid4().hex
            run = {"run_id": identity, "status": "preparing", "events": [], "nodes": [],
                   "folder": "", "message": "Preparing installation checks" if check else "Preparing analysis",
                   "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "_cancel": threading.Event(), "_cancel_file": self.data / ("cancel-" + identity)}
            # A preparation failure still needs a searchable identity and the
            # submitted draft for diagnosis. This is not a frozen execution plan.
            run["name"] = "Installation checks" if check else (str(graph.get("name") or "Untitled analysis")[:200])
            if not check:
                run["graph"] = copy.deepcopy(graph)
                run["graph_status"] = "submitted"
            self.runs[identity] = run
            self.persist_run(run)
        def emit(event):
            if not isinstance(event, dict):
                event = {"type": "log", "message": str(event)}
            with self.lock:
                run["events"].append(event)
                run["events"] = run["events"][-1500:]
                if event.get("type") == "phase":
                    run["message"] = event.get("message", "")
                if event.get("type") == "step" and event.get("nodeId"):
                    node = next((n for n in run["nodes"] if n.get("id") == event["nodeId"]), None)
                    if node is None:
                        node = {"id": event["nodeId"]}
                        run["nodes"].append(node)
                    node.update({k: v for k, v in event.items() if k in ("status", "message", "name", "folder")})
                if event.get("type") == "run" and event.get("folder"):
                    run["folder"] = str(event["folder"])
        def work():
            try:
                if check:
                    run["status"] = "running"
                    from core_checks import run_core_checks
                    result = run_core_checks(self.root, self.catalog, output, event=emit,
                                             cancel=run["_cancel"], backend=getattr(self.engine, "backend", None))
                    if result.get("success") and not run["_cancel"].is_set():
                        from pack_checks import run_pack_checks
                        checks_parent = Path(result.get("folder") or output)
                        extra = run_pack_checks(self.root, self.catalog, checks_parent,
                                                event=emit, cancel=run["_cancel"], backend=getattr(self.engine, "backend", None))
                        result["pack_checks"] = extra
                        result["success"] = extra["success"]
                        result["cancelled"] = extra.get("cancelled", False)
                        result["message"] = str(result.get("message", "Installation checks completed.")) + " " + extra["message"]
                    run.update({k: v for k, v in result.items() if k != "type"})
                    run["status"] = "cancelled" if result.get("cancelled") else "completed" if result.get("success") else "failed"
                else:
                    kwargs = {"cancel": run["_cancel"], "resource_policy": policy}
                    if project_context is not None:
                        kwargs["project_metadata"] = copy.deepcopy(project_context)
                    plan = self.engine.prepare(graph, output, **kwargs)
                    with self.lock:
                        run["folder"] = str(plan.get("folder", plan.get("run_folder", "")))
                        run["graph"] = copy.deepcopy(plan.get("graph", {}))
                        run["graph_status"] = "prepared"
                        run["methods_planned"] = plan.get("methods", "")
                        run["status"] = "running"
                    self.persist_run(run)
                    result = self.engine.execute(plan, event=emit, cancel=run["_cancel"])
                    with self.lock:
                        run.update({k: v for k, v in result.items() if k not in ("run_id", "events") and not k.startswith("_")})
                        status = str(result.get("status", "failed"))
                        run["status"] = "completed" if status in ("success", "succeeded", "complete") else status
                run["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            except Exception as error:
                with self.lock:
                    run["status"] = "cancelled" if run["_cancel"].is_set() else "failed"
                    run["message"] = str(error)
                    emit({"type": "error", "message": str(error)})
            finally:
                with self.lock:
                    run["_cancel_file"].unlink(missing_ok=True)
                    self.persist_run(run)
        worker = threading.Thread(target=work, name="workbench-run-" + identity, daemon=False)
        run["_worker"] = worker
        worker.start()
        return {"run_id": identity}

    def cancel(self, identity):
        with self.lock:
            run = self.runs.get(identity)
            if run is None:
                raise ValueError("This run is no longer active.")
            if run["status"] in ("preparing", "running", "cancelling"):
                if identity == self._queue_current:
                    self._queue_scheduled = []
                run["_cancel"].set()
                run["_cancel_file"].touch()
                run["status"] = "cancelling"
            return self.public_run(run)

    def open_results(self, identity):
        run = self.get_run(identity)
        folder = Path(run.get("folder") or "__missing__")
        if not folder.is_absolute() or not folder.is_dir():
            raise ValueError("The run has not created a results folder yet.")
        if os.name != "nt":
            raise ValueError("Opening Explorer is available in the Windows build.")
        os.startfile(str(folder))
        return {"opened": True}

    def _install_pack_folder(self, source):
        """The final, local publication step shared by online and offline installs."""
        if self._pack_cancel.is_set() and self._pack_operation.get("active"):
            raise InterruptedError("Pack installation cancelled before publication.")
        path = Path(source)
        from pack_manager import filesystem_path
        physical = filesystem_path(path)
        # Python graph metadata must be accepted before the native importer
        # publishes anything. Native manifest checks alone are insufficient.
        load_pack(physical / "pack.ini" if physical.is_dir() else physical)
        result = self.bridge(["import", "--app-root", self.root, "--source", path])
        if not result.get("success"):
            raise ValueError(result.get("message", "The pack could not be installed."))
        catalog = load_catalog(self.root)
        with self.lock:
            self.catalog = catalog
            self.engine = Engine(self.root, self.catalog)
        return result

    def import_pack(self, request):
        with self.lock:
            self.ensure_editable()
            self._changing_packs = True
        try:
            source = short_text(request.get("source"), "pack source", 30000)
            return self._install_pack_folder(source)
        finally:
            with self.lock:
                self._changing_packs = False

    def _manager(self):
        # Lazy construction keeps normal startup and analysis wholly offline.
        with self.lock:
            if self._pack_manager is None:
                from pack_manager import PackManager
                self._pack_manager = PackManager(self.root, self._install_pack_folder,
                                                 catalog_callback=lambda: self.catalog)
            return self._pack_manager

    def pack_state(self):
        with self.lock:
            if self._pack_listing is None or not self._pack_operation["active"]:
                self._pack_listing = self._manager().snapshot()
            value = copy.deepcopy(self._pack_listing)
            value["operation"] = copy.deepcopy(self._pack_operation)
            value.update(self.activity())
            return value

    def start_pack_operation(self, action, request):
        if action not in ("refresh", "source", "install", "import"):
            raise ValueError("Unknown pack operation.")
        with self.lock:
            self.ensure_editable()
            manager = self._manager()
            self._pack_listing = manager.snapshot()
            self._changing_packs = True
            self._pack_cancel = threading.Event()
            identity = uuid.uuid4().hex
            self._pack_operation = {"id": identity, "active": True, "status": "running",
                                    "action": action, "message": "Preparing pack operation…",
                                    "bytes": 0, "total": 0, "cancellable": True}
        request = copy.deepcopy(request)

        def progress(event):
            if not isinstance(event, dict):
                event = {"message": str(event)}
            with self.lock:
                for key in ("message", "bytes", "total", "cancellable", "phase"):
                    if key in event:
                        self._pack_operation[key] = event[key]

        def work():
            try:
                if self._pack_cancel.is_set():
                    raise InterruptedError("Pack operation cancelled.")
                if action == "refresh":
                    progress({"message": "Refreshing approved catalogues…"})
                    result = manager.snapshot(refresh=True, cancel=self._pack_cancel, event=progress)
                elif action == "source":
                    result = manager.add_source(short_text(request.get("path"), "catalogue file", 30000))
                elif action == "install":
                    result = manager.install(short_text(request.get("source_id"), "catalogue", 100),
                                             short_text(request.get("pack_id"), "pack", 100),
                                             short_text(request.get("version"), "pack version", 100),
                                             cancel=self._pack_cancel, event=progress)
                else:
                    source = Path(short_text(request.get("path"), "pack file or folder", 30000))
                    if source.is_dir() or source.name == "pack.ini":
                        progress({"message": "Verifying and importing local pack…", "cancellable": False})
                        result = self._install_pack_folder(source)
                    else:
                        result = manager.import_archive(source, cancel=self._pack_cancel, event=progress)
                if isinstance(result, dict) and result.get("success") is False:
                    raise ValueError(result.get("message", "The pack operation failed."))
                with self.lock:
                    if action in ("install", "import"):
                        self.catalog = load_catalog(self.root)
                        self.engine = Engine(self.root, self.catalog)
                    self._pack_operation.update(status="completed", success=True,
                                                message=(result.get("message") if isinstance(result, dict) else None)
                                                        or "Pack operation completed.")
                    if isinstance(result, dict):
                        for key in ("warnings", "installed", "publisherVerified", "verification"):
                            if key in result:
                                self._pack_operation[key] = copy.deepcopy(result[key])
                    self._pack_listing = manager.snapshot()
            except Exception as error:
                with self.lock:
                    cancelled = isinstance(error, InterruptedError)
                    self._pack_operation.update(status="cancelled" if cancelled else "failed",
                                                success=False, message=str(error))
            finally:
                with self.lock:
                    self._pack_operation.update(active=False, cancellable=False)
                    self._changing_packs = False

        worker = threading.Thread(target=work, name="workbench-pack-operation", daemon=True)
        with self.lock:
            self._pack_worker = worker
        worker.start()
        return self.pack_state()

    def cancel_pack_operation(self):
        with self.lock:
            if self._pack_operation["active"]:
                if not self._pack_operation.get("cancellable", True):
                    raise ValueError("Installation is being committed. Wait for it to finish.")
                self._pack_cancel.set()
                self._pack_operation["message"] = "Cancelling pack operation…"
        return self.pack_state()

    def setup_manager(self):
        with self.lock:
            if self._setup_manager is None:
                from setup_manager import SetupManager
                self._setup_manager = SetupManager(self.root, self._manager())
            return self._setup_manager

    def setup_state(self):
        with self.lock:
            value = self.setup_manager().snapshot()
            value.update(self.activity())
            return value

    def start_setup_operation(self, action, request):
        with self.lock:
            self.ensure_editable()
            manager = self.setup_manager()
            manager.prepare(action, copy.deepcopy(request))
            self._changing_packs = True
            self._setup_cancel = threading.Event()

        def work():
            try:
                manager.run(self._setup_cancel)
            except Exception as error:
                manager.host_failure(error)
            finally:
                with self.lock:
                    # Completed publications update the catalogue even when a
                    # later selected download fails or is cancelled.
                    try:
                        catalog = load_catalog(self.root)
                        engine = Engine(self.root, catalog)
                        self.catalog, self.engine = catalog, engine
                        self._pack_listing = None
                    except Exception as error:
                        manager.host_failure(error)
                    finally:
                        self._changing_packs = False

        worker = threading.Thread(target=work, name="workbench-tool-setup", daemon=True)
        with self.lock:
            self._setup_worker = worker
        worker.start()
        return self.setup_state()

    def cancel_setup_operation(self):
        with self.lock:
            self.setup_manager().cancel(self._setup_cancel)
        return self.setup_state()

    def dismiss_setup(self):
        with self.lock:
            self.run_queue.ready()
            self.setup_manager().dismiss()
        return self.setup_state()

    def reference_manager(self):
        # Construction and local snapshots never contact a reference provider.
        with self.lock:
            if self._reference_manager is None:
                from reference_manager import ReferenceManager
                self._reference_manager = ReferenceManager(self.root)
            return self._reference_manager

    def reference_state(self):
        with self.lock:
            if self._reference_listing is None or not self._reference_operation["active"]:
                self._reference_listing = self.reference_manager().snapshot()
            result = copy.deepcopy(self._reference_listing)
            result["operation"] = copy.deepcopy(self._reference_operation)
            review = self._reference_review
            if review is not None and time.monotonic() - review["created"] > 15 * 60:
                self._reference_review = review = None
            result["review"] = (dict(copy.deepcopy(review["review"]), kind=review["kind"], token=review["token"])
                                if review is not None else None)
            result.update(self.activity())
            return result

    def reference_request(self, action, request):
        """Accept named provider choices, never client-supplied download URLs."""
        fields = {"search": {"provider_id", "release", "query"},
                  "discover": {"provider_id", "release", "species_id"},
                  "download": {"selection_id", "file_ids", "destination"},
                  "resume": {"job_id"}, "discard": {"job_id"},
                  "import-preview": {"files", "metadata", "destination"},
                  "relocate-preview": {"destination"},
                  "import": {"token"}, "relocate": {"token"}}
        if action not in fields or not isinstance(request, dict) or set(request) - fields[action]:
            raise ValueError("Unknown reference operation or request field.")
        result = copy.deepcopy(request)
        if action in ("search", "discover"):
            provider = result.setdefault("provider_id", "ensembl-archive")
            if provider not in ("ensembl-archive", "ncbi-refseq"):
                raise ValueError("Choose an available reference provider.")
            release = result.setdefault("release", 116 if provider == "ensembl-archive" else "assembly")
            if provider == "ensembl-archive":
                if type(release) is not int or not 1 <= release <= 9999:
                    raise ValueError("Choose a numeric Ensembl archive release.")
            elif release != "assembly":
                raise ValueError("Choose the versioned RefSeq assembly lookup.")
        if action == "search":
            query = result.setdefault("query", "")
            if not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in query):
                raise ValueError("Use a short species name for the reference search.")
            result["query"] = query.strip()
        elif action == "discover":
            species = result.get("species_id")
            pattern = r"GCF_[0-9]{9}\.[1-9][0-9]*" if result["provider_id"] == "ncbi-refseq" else r"[a-z0-9_]{1,100}"
            if not isinstance(species, str) or re.fullmatch(pattern, species) is None:
                raise ValueError("Choose a species from the reference search results.")
        elif action == "download":
            result["selection_id"] = short_text(result.get("selection_id"), "reference selection", 100)
            identities = result.get("file_ids")
            if (not isinstance(identities, list) or not 1 <= len(identities) <= 20
                    or any(not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) is None for value in identities)
                    or len(identities) != len(set(identities))):
                raise ValueError("Choose one or more distinct files from the discovered reference.")
        elif action in ("resume", "discard"):
            job_id = result.get("job_id")
            if not isinstance(job_id, str) or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
                raise ValueError("Choose a pending reference download.")
        elif action in ("import", "relocate"):
            result["token"] = short_text(result.get("token"), "reference review", 100)
        elif action == "import-preview":
            files = result.get("files")
            kinds = {"genome", "annotation", "cdna", "ncrna", "protein"}
            if (not isinstance(files, list) or not 1 <= len(files) <= 5
                    or any(not isinstance(item, dict) or set(item) != {"kind", "path"}
                           or not isinstance(item.get("kind"), str) or item["kind"] not in kinds for item in files)
                    or len({item["kind"] for item in files}) != len(files)):
                raise ValueError("Choose distinct reference roles for one to five local files.")
            for item in files:
                path = Path(short_text(item.get("path"), "local reference file", 30000))
                if not path.is_absolute() or not path.is_file():
                    raise ValueError("Choose an existing absolute local reference file.")
                item["path"] = str(path)
            metadata = result.setdefault("metadata", {})
            limits = {"label": 240, "species": 240, "assembly": 240,
                      "assembly_accession": 100, "source": 1000, "release": 240}
            if not isinstance(metadata, dict) or set(metadata) - set(limits):
                raise ValueError("Unknown local reference metadata field.")
            for key, value in metadata.items():
                if (not isinstance(value, str) or len(value) > limits[key]
                        or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                    raise ValueError("Use short plain-text reference metadata.")
                metadata[key] = value.strip()
        if action in ("download", "import-preview", "relocate-preview"):
            from pack_manager import filesystem_path
            destination = Path(short_text(result.get("destination"), "reference destination folder", 30000))
            # Windows UI paths can use a short or ordinary spelling while the
            # application root has already been resolved. Compare filesystem
            # identities without changing the reviewed/user-facing path.
            io_destination = filesystem_path(destination)
            managed_default = (io_destination.resolve() == filesystem_path(self.data / "references").resolve()
                               and not io_destination.exists())
            if not destination.is_absolute() or not (io_destination.is_dir() or managed_default):
                raise ValueError("Choose an existing absolute reference destination folder.")
            result["destination"] = str(destination)
        return result

    def start_reference_operation(self, action, request):
        request = self.reference_request(action, request)
        with self.lock:
            self.ensure_editable()
            manager = self.reference_manager()
            reviewed = None
            if action in ("import", "relocate"):
                review = self._reference_review
                if (review is None or review["token"] != request["token"] or review["kind"] != action
                        or time.monotonic() - review["created"] > 15 * 60):
                    raise ValueError("This reference review is no longer available. Review it again before continuing.")
                reviewed = copy.deepcopy(review["review"])
            if action not in ("search", "discover"):
                self._reference_review = None
            self._reference_listing = manager.snapshot()
            self._changing_references = True
            cancel = self._reference_cancel = threading.Event()
            self._reference_operation = {"id": uuid.uuid4().hex, "active": True, "status": "running",
                                         "action": action, "message": "Preparing reference operation…",
                                         "bytes": 0, "total": 0, "cancellable": True}

            def progress(event):
                if not isinstance(event, dict):
                    event = {"message": str(event)}
                with self.lock:
                    for key in ("message", "bytes", "total", "cancellable", "phase"):
                        if key in event:
                            self._reference_operation[key] = event[key]

            def work():
                try:
                    if cancel.is_set():
                        raise InterruptedError("Reference operation cancelled.")
                    if action == "search":
                        options = {"provider_id": request["provider_id"]} if request["provider_id"] != "ensembl-archive" else {}
                        manager.search(request["release"], request["query"], cancel=cancel, event=progress, **options)
                    elif action == "discover":
                        options = {"provider_id": request["provider_id"]} if request["provider_id"] != "ensembl-archive" else {}
                        manager.discover(request["release"], request["species_id"], cancel=cancel, event=progress, **options)
                    elif action == "download":
                        manager.download(request["selection_id"], request["file_ids"], request["destination"],
                                         cancel=cancel, event=progress)
                    elif action == "resume":
                        manager.resume(request["job_id"], cancel=cancel, event=progress)
                    elif action == "discard":
                        manager.discard(request["job_id"])
                    elif action in ("import-preview", "relocate-preview"):
                        preview = (manager.preview_import(request["files"], request["metadata"], request["destination"],
                                                          cancel=cancel, event=progress)
                                   if action == "import-preview" else
                                   manager.preview_relocation(request["destination"], cancel=cancel, event=progress))
                        if cancel.is_set():
                            raise InterruptedError("Reference review cancelled.")
                        if len(json.dumps(preview, ensure_ascii=True).encode("utf-8")) > 3 * 1024 * 1024:
                            raise ValueError("The reference review is too large for this interface.")
                        with self.lock:
                            self._reference_review = {"token": secrets.token_urlsafe(24), "kind": action.split("-", 1)[0],
                                                      "review": copy.deepcopy(preview), "created": time.monotonic()}
                    elif action == "import":
                        manager.import_local(reviewed, cancel=cancel, event=progress)
                    elif action == "relocate":
                        manager.relocate_library(reviewed, cancel=cancel, event=progress)
                    with self.lock:
                        self._reference_listing = manager.snapshot()
                        self._reference_operation.update(status="completed", success=True,
                            message={"search": "Species search completed. Choose a species to discover its files.",
                                     "discover": "Reference files discovered. Review the assembly and files before downloading.",
                                     "download": "Reference download completed. The local files are ready to use.",
                                     "resume": "Reference download completed. The local files are ready to use.",
                                     "discard": "Incomplete download discarded. Ready references are unchanged.",
                                     "import-preview": "Local files verified for review. Confirm to copy them into the library.",
                                     "relocate-preview": "Library move reviewed. Confirm to copy, verify and switch locations; originals are retained.",
                                     "import": "Local references copied and verified. Their declared source metadata is recorded.",
                                     "relocate": "Library location changed after verification. Original files were retained for existing workflows."}[action])
                except Exception as error:
                    with self.lock:
                        from reference_manager import ReferencePaused
                        paused = isinstance(error, ReferencePaused)
                        cancelled = isinstance(error, InterruptedError)
                        self._reference_operation.update(status="paused" if paused else "cancelled" if cancelled else "failed",
                                                         success=False, message=str(error))
                finally:
                    with self.lock:
                        self._reference_operation.update(active=False, cancellable=False)
                        self._changing_references = False

            worker = threading.Thread(target=work, name="workbench-reference-operation", daemon=True)
            self._reference_worker = worker
            # Start while holding the lifecycle lock so shutdown cannot join an
            # unstarted worker between publication and Thread.start().
            worker.start()
        return self.reference_state()

    def cancel_reference_operation(self):
        with self.lock:
            if self._reference_operation["active"]:
                if not self._reference_operation.get("cancellable", True):
                    raise ValueError("The completed reference is being recorded. Wait for it to finish.")
                self._reference_cancel.set()
                self._reference_operation["message"] = "Cancelling reference operation…"
        return self.reference_state()

    def pause_reference_operation(self):
        with self.lock:
            operation = self._reference_operation
            if (not operation["active"] or operation.get("action") not in ("download", "resume")
                    or not operation.get("cancellable", True)):
                raise ValueError("There is no active reference transfer to pause.")
            self.reference_manager().pause()
            operation["message"] = "Pausing download; verified partial bytes will be retained."
        return self.reference_state()

    def shutdown(self, grace=10):
        """Cancel background work, wait, and stop native processes if necessary.

        The native window additionally owns the private interpreter and all its
        descendants in a kill-on-close Windows Job Object for crash containment.
        """
        with self.lock:
            self._closing = True
            workers = []
            self._queue_scheduled = []
            self._queue_prepare_cancel.set()
            for worker in (self._queue_prepare_worker, self._queue_worker):
                if worker is not None:
                    workers.append(worker)
            self._pack_cancel.set()
            if self._pack_worker is not None:
                workers.append(self._pack_worker)
            self._setup_cancel.set()
            if self._setup_worker is not None:
                workers.append(self._setup_worker)
            self._reference_cancel.set()
            if self._reference_worker is not None:
                workers.append(self._reference_worker)
            for run in self.runs.values():
                if run["status"] in ("preparing", "running", "cancelling"):
                    run["_cancel"].set()
                    run["_cancel_file"].touch()
                    run["status"] = "cancelling"
                if run.get("_worker"):
                    workers.append(run["_worker"])
        deadline = time.monotonic() + max(0, grace)
        admitted = self._queue_admission.wait(timeout=max(0, deadline - time.monotonic()))
        with self.lock:
            for worker in (self._queue_prepare_worker, self._queue_worker):
                if worker is not None and worker not in workers:
                    workers.append(worker)
        for worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        backend = getattr(self.engine, "backend", None)
        if backend is not None and hasattr(backend, "shutdown"):
            backend.shutdown()
        with self.lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for worker in workers:
            if worker.is_alive():
                worker.join(timeout=3)
        clean = admitted and not any(worker.is_alive() for worker in workers)
        if clean:
            self.run_queue.close()
        return clean
