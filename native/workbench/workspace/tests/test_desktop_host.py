"""Private stdio host tests. No Windows native tool execution is implied."""
from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
import desktop_host
import service


PACK = """[pack]
format=2
id=fixture
version=1.0.0
name=Protocol fixture
platform=windows-x86_64
description=Fixture for native host protocol tests.
color=#347E88
[tool:count]
path=bin/count.exe
version=1.0.0
sha256={hash}
[workflow:count]
name=Count reads
description=Count fixture reads.
inputs=reads,threads
outputs=statistics
steps=count
[input:count:reads]
label=Reads
type=file
required=true
filter=FASTQ|*.fastq
[input:count:threads]
label=Threads
type=integer
default=2
min=1
max=8
[output:count:statistics]
label=Read statistics
path=stats.json
final=true
nonempty=true
[step:count:count]
label=Count reads
kind=exec
tool=count
stdout=statistics
arg.0=stats
arg.1={{input:reads}}
arg.2={{input:threads}}
""".format(hash="0" * 64)


class FakeModel:
    def __init__(self):
        self.graph = {"name": "Test", "nodes": [], "sources": []}
        self.calls = []
    def snapshot(self):
        return {"graph": self.graph, "catalog": {"tools": {}}}
    def dispatch(self, action, payload):
        self.calls.append((action, payload))
        if action == "rename":
            self.graph["name"] = payload["name"]
        return self.snapshot()
    def update_catalog(self, catalog):
        pass


class WaitingEngine:
    def __init__(self, prepare=False):
        self.block_prepare = prepare
        self.preparing = threading.Event()
        self.running = threading.Event()
        self.cancelled = threading.Event()
    def prepare(self, graph, output, cancel, resource_policy=None):
        self.preparing.set()
        if self.block_prepare:
            if not cancel.wait(5):
                raise RuntimeError("Test failed to cancel preparation")
            self.cancelled.set()
            raise InterruptedError("Cancelled during preparation")
        folder = Path(output) / "run-fixture"
        folder.mkdir(exist_ok=True)
        return {"folder": str(folder), "graph": graph, "methods": "Planned methods"}
    def execute(self, plan, event, cancel):
        self.running.set()
        if not cancel.wait(5):
            raise RuntimeError("Test failed to cancel execution")
        self.cancelled.set()
        return {"status": "cancelled", "folder": plan["folder"], "nodes": [], "message": "Cancelled"}
    def review(self, graph):
        return {"valid": False, "issues": [], "methods": graph["name"]}


class DesktopHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench-stdio-")
        self.root = Path(self.tmp.name)
        self.hosts = []

    def tearDown(self):
        for host in self.hosts:
            host.close(grace=.1)
        self.tmp.cleanup()

    def host(self, engine=None):
        engine = engine or WaitingEngine()
        app = service.Workbench(self.root, engine=engine, catalog={"tools": {}})
        host = desktop_host.DesktopHost(self.root, app=app, model=FakeModel())
        self.hosts.append(host)
        return host

    def test_production_host_startup_and_core_rpc_with_network_audit_denial(self):
        folder = self.root / "packs" / "fixture-1.0.0"
        folder.mkdir(parents=True)
        (folder / "pack.ini").write_text(PACK, encoding="utf-8")
        # Even a transitive module cannot create/connect/bind a socket. This is
        # actual isolated interpreter startup with the production host/model.
        bootstrap = r'''
import sys
def audit(event, args):
    if event.startswith("socket."):
        raise RuntimeError("Network API forbidden in native host test: " + event)
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from desktop_host import main
raise SystemExit(main(["--app-root", sys.argv[2]]))
'''
        requests = [
            {"id": 1, "method": "init"},
            {"id": 2, "method": "model", "params": {"action": "add_tool", "payload": {"toolId": "fixture/count"}}},
            {"id": 3, "method": "model", "params": {"action": "apply_fields", "payload": {"nodeId": "step-1", "params": {"threads": "3"}}}},
            {"id": 4, "method": "state"},
            {"id": 5, "method": "save", "params": {"kind": "preset", "name": "Count settings", "nodeId": "step-1"}},
            {"id": 6, "method": "saved"},
            {"id": 7, "method": "shutdown"},
        ]
        result = subprocess.run([sys.executable, "-I", "-c", bootstrap, str(WORKSPACE), str(self.root)],
                                input="".join(json.dumps(x) + "\n" for x in requests).encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([x["id"] for x in responses], list(range(1, 8)))
        self.assertTrue(all(x["ok"] for x in responses), responses)
        self.assertEqual(responses[0]["result"]["app_version"], desktop_host.VERSION)
        self.assertEqual(responses[3]["result"]["graph"]["nodes"][0]["id"], "step-1")
        self.assertEqual(responses[4]["result"]["params"], {"threads": "3"})
        self.assertNotIn("params", responses[5]["result"]["presets"][0])
        self.assertTrue(responses[5]["result"]["summaries"])
        self.assertTrue(responses[-1]["result"]["closed"])

    def test_native_host_modules_do_not_import_network_or_browser_transport(self):
        forbidden = {"http", "socket", "socketserver", "webbrowser", "server", "session"}
        for name in ("desktop_host.py", "service.py", "desktop_model.py", "engine.py", "catalog.py"):
            tree = ast.parse((WORKSPACE / name).read_text(encoding="utf-8"))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertFalse(modules & forbidden, (name, modules & forbidden))

    def test_preset_from_node_uses_committed_params_and_rejects_obsolete_pin(self):
        folder = self.root / "packs" / "fixture-1.0.0"
        folder.mkdir(parents=True)
        (folder / "pack.ini").write_text(PACK, encoding="utf-8")
        host = desktop_host.DesktopHost(self.root)
        self.hosts.append(host)
        host.dispatch("model", {"action": "add_tool", "payload": {"toolId": "fixture/count"}})
        host.dispatch("model", {"action": "apply_fields", "payload": {"nodeId": "step-1", "params": {"threads": "4"}}})
        saved = host.dispatch("save", {"kind": "preset", "name": "Committed", "node_id": "step-1",
                                       "tool": "stale/tool", "params": {"threads": "1"}})
        self.assertEqual(saved["tool"], "fixture/count")
        self.assertEqual(saved["params"], {"threads": "4"})
        host.model.graph["nodes"][0]["pin"]["packVersion"] = "0.0.1"
        with self.assertRaisesRegex(ValueError, "different installed tool version"):
            host.dispatch("save", {"kind": "preset", "name": "Obsolete", "nodeId": "step-1"})
        self.assertEqual(len(host.app.saved()["presets"]), 1)

    def test_protocol_rejects_bad_frames_and_continues_without_arbitrary_commands(self):
        host = self.host()
        incoming = b'[]\n{"id":1,"method":"state","method":"run"}\n'
        incoming += b'{"id":2,"method":"shell","params":{"command":"anything"}}\n'
        incoming += b'{"id":3,"method":"state","params":[]}\n'
        incoming += b'{"id":5,"method":"state","params":{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}}\n'
        incoming += b'{"id":4,"method":"state"}\n'
        output = io.BytesIO()
        self.assertTrue(desktop_host.serve(host, io.BytesIO(incoming), output))
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([x["ok"] for x in replies], [False, False, False, False, False, True])
        self.assertEqual(replies[2]["id"], 2)
        self.assertIn("Unknown native method", replies[2]["error"])

    def test_oversized_frame_is_drained_once_without_executing_its_suffix(self):
        host = self.host()
        incoming = b"x" * (desktop_host.MAX_REQUEST + 5) + b'{"id":99,"method":"run"}\n'
        incoming += b'{"id":1,"method":"state"}\n'
        output = io.BytesIO()
        self.assertTrue(desktop_host.serve(host, io.BytesIO(incoming), output))
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertFalse(replies[0]["ok"])
        self.assertEqual(replies[1]["id"], 1)
        self.assertTrue(replies[1]["ok"])

    def test_eof_cancels_and_joins_preparation(self):
        engine = WaitingEngine(prepare=True)
        host = self.host(engine)
        identity = host.dispatch("run", {"output_folder": str(self.root)})["run_id"]
        self.assertTrue(engine.preparing.wait(2))
        before = time.monotonic()
        self.assertEqual(host.dispatch("status", {"run_id": identity})["status"], "preparing")
        self.assertLess(time.monotonic() - before, .5)
        self.assertTrue(desktop_host.serve(host, io.BytesIO(), io.BytesIO()))
        self.assertTrue(engine.cancelled.is_set())
        self.assertFalse(host.app.runs[identity]["_worker"].is_alive())
        self.assertEqual(host.app.get_run(identity)["status"], "cancelled")

    def test_eof_cancels_execution_and_preserves_frozen_graph(self):
        engine = WaitingEngine()
        host = self.host(engine)
        host.model.graph["name"] = "Frozen analysis"
        identity = host.dispatch("run", {"output_folder": str(self.root)})["run_id"]
        self.assertTrue(engine.running.wait(2))
        self.assertTrue(desktop_host.serve(host, io.BytesIO(), io.BytesIO()))
        result = host.app.get_run(identity)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["graph"]["name"], "Frozen analysis")
        self.assertEqual(result["methods_planned"], "Planned methods")
        self.assertFalse(host.app.runs[identity]["_worker"].is_alive())

    def test_historical_run_selection_allows_next_draft_but_not_second_run(self):
        host = self.host()
        host.app.history.append({"run_id": "old", "status": "completed", "events": []})
        identity = host.dispatch("run", {"output_folder": str(self.root)})["run_id"]
        self.assertTrue(host.app.engine.running.wait(2))
        historical = host.dispatch("status", {"run_id": "old"})
        self.assertEqual(historical["status"], "completed")
        self.assertEqual(historical["active_run"], identity)
        frozen = host.app.get_run(identity)["graph"]
        host.dispatch("model", {"action": "rename", "payload": {"name": "changed"}})
        self.assertEqual(host.graph()["name"], "changed")
        self.assertEqual(host.app.get_run(identity)["graph"], frozen)
        with self.assertRaisesRegex(ValueError, "active analysis"):
            host.dispatch("run", {"output_folder": str(self.root)})
        self.assertEqual(host.dispatch("model", {"action": "snapshot"})["active_run"], identity)

    def test_review_and_run_observe_preceding_model_commit(self):
        host = self.host()
        host.dispatch("model", {"action": "rename", "payload": {"name": "Committed"}})
        self.assertEqual(host.dispatch("review", {})["methods"], "Committed")
        identity = host.dispatch("run", {"output_folder": str(self.root)})["run_id"]
        self.assertTrue(host.app.engine.running.wait(2))
        self.assertEqual(host.app.get_run(identity)["graph"]["name"], "Committed")

    def test_large_log_is_bounded_and_omissions_are_explicit(self):
        host = self.host()
        record = {"run_id": "large", "status": "completed", "graph": {"name": "Preserved"},
                  "events": [{"type": "log", "message": "x" * 16000} for _ in range(1500)]}
        public = host.app.public_run(record)
        self.assertGreater(public["events_omitted"], 0)
        self.assertEqual(public["graph"], record["graph"])
        self.assertLess(len(json.dumps(public["events"]).encode()), service.MAX_PUBLIC_LOG_BYTES)
        self.assertLess(len(json.dumps(public).encode()), desktop_host.MAX_RESPONSE)

    def test_saved_size_limit_preserves_existing_file(self):
        host = self.host()
        existing = {"pipelines": [], "presets": [{"id": "old", "name": "Existing", "tool": "fixture/count", "params": {}}]}
        service.atomic_json(host.app.saved_path, existing)
        before = host.app.saved_path.read_bytes()
        host.app.engine.save_preset = lambda node: {"tool": node["tool"], "params": {"oversized": "x" * 2048}}
        with patch.object(service, "MAX_SAVED_BYTES", 1024):
            with self.assertRaisesRegex(ValueError, "Existing saved items have been preserved"):
                host.app.save({"name": "New", "kind": "preset", "tool": "fixture/count", "params": {}})
        self.assertEqual(host.app.saved_path.read_bytes(), before)

    def test_shutdown_terminates_tracked_native_bridge_if_it_does_not_finish(self):
        host = self.host()
        spawned = []
        actual_popen = subprocess.Popen
        def launch(*args, **kwargs):
            process = actual_popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8")
            spawned.append(process)
            return process
        errors = []
        def invoke():
            try:
                host.app.bridge(["check"])
            except RuntimeError as exc:
                errors.append(str(exc))
        with patch.object(service.subprocess, "Popen", side_effect=launch):
            worker = threading.Thread(target=invoke)
            worker.start()
            deadline = time.monotonic() + 3
            while not spawned and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(spawned)
            self.assertTrue(host.close(grace=0))
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIsNotNone(spawned[0].poll())
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
