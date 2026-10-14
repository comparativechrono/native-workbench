"""Native Workbench's private stdio host. No listening port or browser runtime.

Each UTF-8 JSON line is {"id": ..., "method": ..., "params": {...}}. Replies
are {"id": ..., "ok": true, "result": ...} or {"id": ..., "ok": false,
"error": "..."}. Slow review/import requests may complete out of order; IDs
are authoritative. Analysis execution runs in the shared service's worker.
The owning native process controls file dialogs and owns this process tree.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import copy
import json
import os
from pathlib import Path
import sys
import threading

# The bundled interpreter runs with -I and an isolated ._pth. The only explicit
# application import root is this installed directory, never the current folder.
WORKSPACE = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKSPACE))

from service import Workbench, strict_json, short_text
from app_version import APP_VERSION
from catalog import resolve_tool

VERSION = APP_VERSION
MAX_REQUEST = 2 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024


def validate_request(request):
    stack, count = [(request, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > 64 or count > 200000:
            raise ValueError("Native request nesting or value count exceeds the supported limit.")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
    if not isinstance(request, dict) or set(request) - {"id", "method", "params"}:
        raise ValueError("Expected a native request with id, method and params.")
    identity = request.get("id")
    if not ((type(identity) is int and 0 <= identity < 2**31)
            or isinstance(identity, str) and 0 < len(identity) <= 100
            and all(32 <= ord(c) < 127 for c in identity)):
        raise ValueError("A request needs a short string or non-negative integer id.")
    method = short_text(request.get("method"), "request method", 40)
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("Native request params must be a JSON object.")
    return identity, method, params


class DesktopHost:
    def __init__(self, root, *, app=None, model=None):
        self.app = app if app is not None else Workbench(root)
        from desktop_model import DesktopModel
        # Standalone tools and the workflow have independent edits, bindings,
        # selections and undo stacks. An explicitly supplied model remains the
        # active workflow for callers embedding the older single-model host.
        self._workflow_model = model if model is not None else DesktopModel(self.app.root, self.app.catalog, auto_sources=False)
        self._tool_model = DesktopModel(self.app.root, self.app.catalog)
        self._tool_models = {}
        self.mode = "workflow" if model is not None else "tool"
        self.model = self._workflow_model if model is not None else self._tool_model
        self.model_lock = threading.RLock()
        self.closing = threading.Event()
        self._pack_model_revision = None
        self._setup_model_revision = None

    def snapshot(self):
        with self.model_lock:
            result = copy.deepcopy(self.model.snapshot())
            result["mode"] = self.mode
        # Catalogue metadata describes installed operations, never command input.
        result.setdefault("catalog", self.app.catalog)
        result["app_version"] = VERSION
        result.update(self.app.activity())
        return result

    def graph(self):
        with self.model_lock:
            return copy.deepcopy(self.model.graph)

    def _select_mode(self, mode):
        """Caller holds app.lock then model_lock, including the busy check."""
        self.mode = mode
        self.model = self._workflow_model if mode == "workflow" else self._tool_model

    def _refresh_models(self):
        """Update every session without replacing its exact saved pack pins."""
        with self.app.lock:
            with self.model_lock:
                models = [self._workflow_model, self._tool_model, *self._tool_models.values()]
                for model in {id(model): model for model in models}.values():
                    model.update_catalog(self.app.catalog)

    def dispatch(self, method, params):
        if self.closing.is_set() and method != "shutdown":
            raise ValueError("The workbench is closing.")
        if method in ("init", "state"):
            result = self.snapshot()
            if method == "init":
                result["saved"] = self.app.saved_summaries()
                history = self.app.recent(summaries=True)
                result["history"] = history["runs"]
                result["history_omitted"] = history.get("omitted", 0)
            return result
        if method in ("workspace/mode", "workspace/tool"):
            key = "mode" if method == "workspace/mode" else "toolId"
            if set(params) != {key}:
                raise ValueError("Unknown workspace request field.")
            value = short_text(params[key], "workspace " + key, 200)
            if key == "mode" and value not in ("tool", "workflow"):
                raise ValueError("Choose tool or workflow mode.")
            with self.app.lock:
                self.app.ensure_model_editable()
                with self.model_lock:
                    if key == "toolId":
                        # Resolve before touching the current selection. Failed
                        # requests must leave the workflow and active tool intact.
                        tool = resolve_tool(self.app.catalog, value)
                        model = self._tool_models.get(value)
                        if model is None or not model.graph["nodes"]:
                            from desktop_model import DesktopModel
                            model = DesktopModel(self.app.root, self.app.catalog)
                            model.dispatch("add_tool", {"toolId": value})
                            model.graph["name"] = tool["name"]
                            self._tool_models[value] = model
                        self._tool_model = model
                        self._select_mode("tool")
                    else:
                        self._select_mode(value)
                return self.snapshot()
        if method == "workspace/connection-targets":
            if set(params) != {"ref"}:
                raise ValueError("Unknown connection preview field.")
            ref = short_text(params["ref"], "connection source", 200)
            with self.model_lock:
                return {"ref": ref, "targets": self.model.connection_targets(ref)}
        if method.startswith("setup/"):
            action = method.split("/", 1)[1]
            if action == "start":
                result = self.app.start_setup_operation(action, params)
            elif params:
                raise ValueError("Unknown tool setup request field.")
            elif action in ("refresh", "retry"):
                result = self.app.start_setup_operation(action, params)
            elif action == "status":
                result = self.app.setup_state()
            elif action == "cancel":
                result = self.app.cancel_setup_operation()
            elif action == "dismiss":
                result = self.app.dismiss_setup()
            else:
                raise ValueError("Unknown tool setup action.")
            revision = result.get("revision")
            if revision != self._setup_model_revision:
                self._refresh_models()
                self._setup_model_revision = revision
                result["model"] = self.snapshot()
            return result
        if method.startswith("packs/"):
            action = method.split("/", 1)[1]
            if action in ("list", "status"):
                result = self.app.pack_state()
            elif action == "cancel":
                result = self.app.cancel_pack_operation()
            elif action in ("source", "refresh", "install", "import"):
                result = self.app.start_pack_operation(action, params)
            else:
                raise ValueError("Unknown pack manager action.")
            operation = result.get("operation", {})
            if (operation.get("status") == "completed" and operation.get("success")
                    and operation.get("id") != self._pack_model_revision):
                self._refresh_models()
                self._pack_model_revision = operation["id"]
                result["model"] = self.snapshot()
            return result
        if method.startswith("references/"):
            action = method.split("/", 1)[1]
            if action in ("search", "discover", "download", "resume", "discard", "import-preview", "import", "relocate-preview", "relocate"):
                return self.app.start_reference_operation(action, params)
            allowed = {"list": set(), "status": set(), "cancel": set(), "pause": set(), "open": {"record_id"},
                       "targets": {"record_id", "file_id"},
                       "use": {"record_id", "file_id", "source_id", "field_id"}}
            if action not in allowed or set(params) != allowed[action]:
                raise ValueError("Unknown reference action or request field.")
            if action in ("list", "status"):
                return self.app.reference_state()
            if action == "cancel":
                return self.app.cancel_reference_operation()
            if action == "pause":
                return self.app.pause_reference_operation()
            record_id = short_text(params.get("record_id"), "local reference", 100)
            manager = self.app.reference_manager()
            if action == "open":
                return {"path": manager.record_folder(record_id)}
            file_id = short_text(params.get("file_id"), "local reference file", 100)
            # IDs are resolved exclusively against completed local records. No
            # client path, URI or provenance object is accepted for binding.
            resource = manager.resolve_file(record_id, file_id)
            if action == "targets":
                with self.model_lock:
                    targets = self.model.reference_targets(resource)
                return {"targets": targets, "notice":
                        "Choose the named input to fill. Check the assembly and reference type required by your analysis."
                        if targets else "Add a Reference FASTA workflow input, or open a tool with a compatible reference input. Other uses can be chosen with the input's Browse button."}
            source_id = short_text(params.get("source_id"), "reference input source", 100)
            field_id = short_text(params.get("field_id"), "reference input field", 100)
            with self.app.lock:
                self.app.ensure_model_editable()
                with self.model_lock:
                    self.model.use_reference(resource, source_id, field_id)
                result = self.app.reference_state()
                result["model"] = self.snapshot()
            return result
        if method == "model":
            action = short_text(params.get("action"), "model action", 60)
            payload = params.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("Model payload must be a JSON object.")
            read_only = action in ("select", "snapshot") or action == "use_output" and not payload.get("toolId")
            with self.app.lock:
                if not read_only:
                    self.app.ensure_model_editable()
                with self.model_lock:
                    self.model.dispatch(action, payload)
                return self.snapshot()
        if method == "review":
            if set(params) - {"graph", "output_folder"}:
                raise ValueError("Unknown readiness request field.")
            return self.app.review(copy.deepcopy(params.get("graph", self.graph())), params.get("output_folder"))
        if method == "methods/preview":
            if set(params) - {"graph"}:
                raise ValueError("Unknown methods preview field.")
            return self.app.preview_methods(copy.deepcopy(params.get("graph", self.graph())))
        if method in ("resources/get", "resources/set"):
            allowed = {"graph"} if method == "resources/get" else {"graph", "policy"}
            if set(params) - allowed or method == "resources/set" and "policy" not in params:
                raise ValueError("Unknown resource settings field.")
            graph = copy.deepcopy(params.get("graph", self.graph()))
            return self.app.resource_state(graph) if method == "resources/get" else self.app.set_resources(graph, params["policy"])
        if method == "restart/review":
            if set(params) != {"run_id"}:
                raise ValueError("Choose a recorded run to review for restart.")
            return self.app.review_restart(params["run_id"])
        if method == "restart/queue":
            if set(params) != {"token", "output_folder"}:
                raise ValueError("Review a restart and choose its new output folder.")
            return self.app.enqueue(params, restart=True)
        if method.startswith("project/"):
            action = method.split("/", 1)[1]
            if action == "export-preview":
                if (set(params) - {"graph", "run_id", "include_data", "sample_metadata"}
                        or "run_id" in params and ("graph" in params or "sample_metadata" in params)):
                    raise ValueError("Choose a current workflow or a recorded result for project export.")
                return self.app.project_preview(params if "run_id" in params else dict(params, graph=copy.deepcopy(params.get("graph", self.graph()))))
            if action == "inspect":
                if set(params) != {"path"}:
                    raise ValueError("Choose a project archive to inspect.")
                return self.app.project_preview(params, importing=True)
            if action == "resolve":
                if set(params) != {"token", "mappings"}:
                    raise ValueError("Choose reviewed project inputs and explicit file mappings.")
                return self.app.project_resolve(params["token"], params["mappings"])
            if action == "export":
                if set(params) != {"token", "destination"}:
                    raise ValueError("Choose a reviewed project and a new archive destination.")
                return self.app.project_commit(params["token"], params["destination"])
            if action in ("import", "open"):
                allowed = {"token", "destination_folder"} if action == "import" else {"folder"}
                if set(params) != allowed:
                    raise ValueError("Choose a reviewed project and its destination folder.")
                self.app.ensure_model_editable()
                before = self.app._graph_key(self.graph())
                result = (self.app.project_commit(params["token"], params["destination_folder"], importing=True)
                          if action == "import" else self.app.open_project(params["folder"]))
                graph = result.pop("graph")
                with self.app.lock:
                    self.app.ensure_model_editable()
                    with self.model_lock:
                        if self.app._graph_key(self.model.graph) == before:
                            self._workflow_model.dispatch("load_graph", {"graph": graph, "template": False})
                            self._select_mode("workflow")
                            result["model_loaded"] = True
                        else:
                            result["model_loaded"] = False
                            result["notice"] = "The draft changed while the project was being verified. The project remains saved; open it when ready to replace the draft."
                    result["model"] = self.snapshot()
                    if result["model_loaded"]:
                        # Snapshot normalizes display counters. Bind context to
                        # the actual loaded draft, not its pre-normalized copy.
                        self.app.remember_project(result["model"]["graph"], result)
                return result
            raise ValueError("Unknown project action.")
        if method == "sample/table":
            if set(params) != {"path"}:
                raise ValueError("Choose a sample table file.")
            return self.app.import_sample_table(params["path"])
        if method == "sample/edit":
            if set(params) != {"table_token"}:
                raise ValueError("Choose a complete imported sample table to edit.")
            return self.app.edit_sample_table(params["table_token"])
        if method == "sample/apply":
            if set(params) - {"table", "retain_token"} or "table" not in params:
                raise ValueError("Apply the complete sample-table editor draft.")
            retain = short_text(params["retain_token"], "retained sample table token", 100) if "retain_token" in params else None
            return self.app.apply_sample_table(params["table"], retain)
        if method == "sample/save":
            if set(params) - {"table_token", "path", "file_columns", "retain_token"} or not {"table_token", "path", "file_columns"} <= set(params):
                raise ValueError("Choose a table, a new CSV/TSV filename and explicit file-path columns.")
            retain = short_text(params["retain_token"], "retained sample table token", 100) if "retain_token" in params else None
            return self.app.save_sample_table(params["table_token"], params["path"], params["file_columns"], retain)
        if method == "sample/example":
            if set(params) - {"retain_token"}:
                raise ValueError("Unknown synthetic sample-table field.")
            retain = short_text(params["retain_token"], "retained sample table token", 100) if "retain_token" in params else None
            return self.app.example_sample_table(retain)
        if method == "sample/targets":
            if set(params) - {"graph"}:
                raise ValueError("Unknown sample targets field.")
            from sample_table import binding_targets
            return binding_targets(self.app.engine, copy.deepcopy(params.get("graph", self.graph())))
        if method == "sample/preview":
            if (set(params) - {"graph", "table", "table_token", "bindings", "parameter_bindings", "mode", "shared_sources", "combined_target"}
                    or "bindings" not in params or (("table" in params) == ("table_token" in params))):
                raise ValueError("Choose a sample table and explicit input mappings.")
            return self.app.preview_batch(dict(params, graph=copy.deepcopy(params.get("graph", self.graph()))))
        if method.startswith("queue/"):
            action = method.split("/", 1)[1]
            if action == "add":
                if set(params) - {"graph", "output_folder"}:
                    raise ValueError("Unknown queue request field.")
                return self.app.enqueue(dict(params, graph=copy.deepcopy(params.get("graph", self.graph()))))
            if action == "add-batch":
                if set(params) != {"token", "output_folder"}:
                    raise ValueError("Review a sample batch before queueing it.")
                return self.app.enqueue(params, batch=True)
            if action == "cancel":
                if set(params) != {"job_id"}:
                    raise ValueError("Choose a queued job to cancel.")
                return self.app.cancel_queued(params["job_id"])
            if params:
                raise ValueError("Unknown queue request field.")
            actions = {"status": self.app.queue_state, "start": self.app.start_queue, "pause": self.app.pause_queue}
            if action not in actions:
                raise ValueError("Unknown queue action.")
            return actions[action]()
        if method in ("index/list", "index/verify"):
            from reference_indexes import ReferenceIndexStore
            store = ReferenceIndexStore(self.app.root)
            if method == "index/list":
                if params:
                    raise ValueError("Unknown reference index request field.")
                return store.list()
            if set(params) != {"key"}:
                raise ValueError("Choose an index to verify.")
            return store.verify(short_text(params["key"], "reference index key", 100))
        if method == "diagnostics/review":
            if set(params) - {"run_id"}:
                raise ValueError("Unknown diagnostic review field.")
            return self.app.review_diagnostics(params.get("run_id"))
        if method == "diagnostics/save":
            if set(params) != {"token", "output_folder"}:
                raise ValueError("Choose a reviewed diagnostic report and output folder.")
            return self.app.save_diagnostics(params["token"], params["output_folder"])
        if method in ("run", "check"):
            self.app.ensure_editable()
            request = {"output_folder": params.get("output_folder")}
            if method == "run":
                request["graph"] = copy.deepcopy(params.get("graph", self.graph()))
            return self.app.start(request, check=method == "check")
        if method in ("status", "run/get"):
            if params.get("run_id"):
                result = self.app.get_run(params["run_id"])
                result.update(self.app.activity())
                return result
            return self.app.activity()
        if method == "cancel":
            identity = params.get("run_id") or self.app.activity()["active_run"]
            if identity is None:
                raise ValueError("There is no active analysis to cancel.")
            return self.app.cancel(identity)
        if method == "history":
            return self.app.recent(summaries=True)
        if method == "results/search":
            if set(params) - {"query"}:
                raise ValueError("Unknown results search field.")
            return self.app.search_results(params.get("query", ""))
        if method == "results/summary":
            if set(params) != {"id"}:
                raise ValueError("Choose a recorded result to summarize.")
            return self.app.result_summary(params["id"])
        if method == "examples/list":
            if params:
                raise ValueError("Unknown curated workflow catalogue field.")
            from curated_workflows import list_catalogue
            with self.app.lock:
                return list_catalogue(self.app.root, self.app.catalog)
        if method == "examples/load":
            if set(params) != {"id"}:
                raise ValueError("Choose a curated workflow to load.")
            identity = short_text(params["id"], "curated workflow id", 100)
            from curated_workflows import load_workflow
            with self.app.lock:
                self.app.ensure_model_editable()
                graph = load_workflow(self.app.root, self.app.catalog, identity)
                with self.model_lock:
                    self._workflow_model.dispatch("load_graph", {"graph": graph, "template": False})
                    self._select_mode("workflow")
                return self.snapshot()
        if method == "saved":
            return self.app.saved_summaries()
        if method == "save":
            self.app.ensure_model_editable()
            request = copy.deepcopy(params)
            if request.get("kind") == "pipeline":
                request.setdefault("graph", self.graph())
            elif request.get("kind") == "preset" and ("nodeId" in request or "node_id" in request):
                identity = request.get("nodeId", request.get("node_id"))
                with self.model_lock:
                    node = next((n for n in self.model.graph["nodes"] if n["id"] == identity), None)
                    if node is None:
                        raise ValueError("Select an existing step before saving its settings.")
                    pin = node.get("pin")
                    try:
                        tool = resolve_tool(self.app.catalog, node.get("tool"), pin)
                    except ValueError:
                        tool = None
                    if tool is None or not isinstance(pin, dict):
                        raise ValueError("This step requires a different installed tool version. Explicitly select the installed version before saving a preset.")
                    # Resolve after the preceding atomic form update. A cached
                    # native snapshot must never overwrite newly edited values.
                    request["tool"] = node["tool"]
                    request["pin"] = copy.deepcopy(pin)
                    request["params"] = copy.deepcopy(node.get("params", {}))
            return self.app.save(request)
        if method == "load":
            kind = params.get("kind")
            key = {"pipeline": "pipelines", "preset": "presets"}.get(kind)
            if key is None:
                raise ValueError("Choose a saved pipeline or tool preset.")
            identity = short_text(params.get("id"), "saved item id", 100)
            item = next((s for s in self.app.saved()[key] if s.get("id") == identity), None)
            if item is None:
                raise ValueError("The selected saved item is no longer available.")
            with self.app.lock:
                self.app.ensure_model_editable()
                with self.model_lock:
                    if kind == "pipeline":
                        self._workflow_model.dispatch("load_graph", {"graph": item["graph"], "template": True})
                        self._select_mode("workflow")
                    else:
                        self.model.dispatch("apply_preset", {"nodeId": params.get("node_id", params.get("nodeId")), "preset": item})
                return self.snapshot()
        if method == "example":
            from example import make_example
            with self.app.lock:
                self.app.ensure_model_editable()
                graph = make_example(self.app.root, self.app.catalog)
                with self.model_lock:
                    self._workflow_model.dispatch("load_graph", {"graph": graph, "template": False})
                    self._select_mode("workflow")
                return self.snapshot()
        if method == "import":
            result = self.app.import_pack(params)
            if result.get("success"):
                self._refresh_models()
                result["model"] = self.snapshot()
            return result
        if method == "open":
            return self.app.open_results(params.get("run_id"))
        if method == "shutdown":
            self.closing.set()
            return {"closed": self.app.shutdown(), "cancelled_active_work": True}
        raise ValueError("Unknown native method: " + method)

    def close(self, grace=10):
        self.closing.set()
        return self.app.shutdown(grace=grace)


def serve(host, input_stream, output_stream):
    """Run a bounded private pipe protocol; return whether shutdown was clean."""
    output_lock = threading.Lock()
    pending_lock = threading.Lock()
    pending = set()
    capacity = threading.BoundedSemaphore(2)
    slow = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workbench-native-request")
    clean = True

    def send(identity, *, result=None, error=None):
        payload = {"id": identity, "ok": error is None}
        payload["result" if error is None else "error"] = result if error is None else str(error)
        try:
            line = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
            if len(line) > MAX_RESPONSE:
                raise ValueError("The native response is too large; use a smaller workspace.")
        except (ValueError, TypeError) as exc:
            line = json.dumps({"id": identity, "ok": False, "error": str(exc)}, ensure_ascii=True).encode("utf-8") + b"\n"
        try:
            with output_lock:
                output_stream.write(line)
                output_stream.flush()
        except (BrokenPipeError, OSError):
            host.closing.set()

    def handle(identity, method, params):
        try:
            send(identity, result=host.dispatch(method, params))
        except Exception as exc:
            send(identity, error=exc)

    def done(future):
        with pending_lock:
            pending.discard(future)
        capacity.release()

    try:
        while not host.closing.is_set():
            line = input_stream.readline(MAX_REQUEST + 1)
            if not line:
                break
            if len(line) > MAX_REQUEST:
                # Drain one oversized frame; its suffix must not become commands.
                while line and not line.endswith(b"\n"):
                    line = input_stream.readline(MAX_REQUEST + 1)
                send(None, error="The native request exceeds the 2 MiB limit.")
                continue
            try:
                request = strict_json(line.decode("utf-8"))
                identity, method, params = validate_request(request)
            except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
                send(None, error=exc)
                continue
            if method == "queue/cancel":
                try:
                    if set(params) != {"job_id"}:
                        raise ValueError("Choose a queued job to cancel.")
                    immediate = host.app.cancel_queued_immediate(params["job_id"])
                except Exception as error:
                    send(identity, error=error)
                    continue
                if immediate is not None:
                    send(identity, result=immediate)
                    continue
            if method in ("review", "methods/preview", "import", "diagnostics/save", "sample/table", "sample/edit", "sample/apply", "sample/save", "sample/example", "sample/preview", "sample/targets", "queue/add", "queue/add-batch", "queue/cancel", "index/list", "index/verify", "resources/set", "restart/review", "restart/queue", "project/export-preview", "project/inspect", "project/resolve", "project/export", "project/import", "project/open", "results/summary"):
                if not capacity.acquire(blocking=False):
                    if method == "queue/cancel":
                        try:
                            immediate = host.app.cancel_queued_immediate(params["job_id"])
                            if immediate is not None:
                                send(identity, result=immediate)
                                continue
                        except Exception as error:
                            send(identity, error=error)
                            continue
                    send(identity, error="Two background requests are still running. Wait before trying again.")
                    continue
                if (method in ("review", "methods/preview", "sample/preview", "sample/targets", "queue/add", "resources/set", "project/export-preview")
                        and "graph" not in params and "run_id" not in params):
                    # Snapshot at command receipt, after preceding model edits,
                    # rather than at the background worker's scheduling time.
                    params = dict(params, graph=host.graph())
                future = slow.submit(handle, identity, method, params)
                with pending_lock:
                    pending.add(future)
                future.add_done_callback(done)
            else:
                handle(identity, method, params)
            if method == "shutdown":
                break
    finally:
        clean = host.close()
        slow.shutdown(wait=False, cancel_futures=True)
        with pending_lock:
            unfinished = tuple(pending)
        if unfinished:
            _, unfinished = wait(unfinished, timeout=3)
            clean = clean and not unfinished
    return clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=WORKSPACE.parent)
    args = parser.parse_args(argv)
    # Preserve a dedicated protocol stream; incidental Python diagnostics go to
    # stderr, separate from the native window's JSON response pipe.
    output = sys.stdout.buffer
    sys.stdout = sys.stderr
    try:
        host = DesktopHost(args.app_root)
        clean = serve(host, sys.stdin.buffer, output)
    except Exception as error:
        reply = {"id": None, "ok": False, "error": "Workbench startup failed: " + str(error)}
        output.write(json.dumps(reply, ensure_ascii=True).encode("utf-8") + b"\n")
        output.flush()
        return 1
    if not clean:
        # Native GUI's enclosing Job Object owns every descendant. If a broken
        # device prevented a worker from stopping, do not strand an interpreter
        # during Python's implicit non-daemon-thread join at process exit.
        os._exit(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
