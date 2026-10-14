"""Transport and lifecycle checks without executing Windows native programs.

Uses real loopback HTTP requests. The fake engine is an explicit boundary: these
checks prove transport/storage behavior, not biological correctness or Win32.
"""
from __future__ import annotations

import copy
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
spec = importlib.util.spec_from_file_location("transport_under_test", WORKSPACE / "server.py")
server = importlib.util.module_from_spec(spec)
# The transport accepts an injected engine. Do not import a half-built engine or
# require native pack assets simply to test the loopback trust boundary.
with patch.dict(sys.modules, {"engine": types.SimpleNamespace(Engine=object)}):
    spec.loader.exec_module(server)


class FakeEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.failure = None
        self.calls = []
        self.result = {"status": "success", "message": "Completed", "nodes": [{"id": "step-1", "status": "completed"}]}

    def review(self, graph):
        self.calls.append(("review", copy.deepcopy(graph)))
        return {"valid": True, "issues": [], "methods": "Planned methods"}

    def save_pipeline(self, graph):
        self.calls.append(("save_pipeline", copy.deepcopy(graph)))
        return {"nodes": [{"id": "step-1", "tool": "fixture/one"}, {"id": "step-2", "tool": "fixture/two"}],
                "sources": [{"id": "input-1", "type": "reads", "files": {}}]}

    def save_preset(self, node):
        self.calls.append(("save_preset", copy.deepcopy(node)))
        return {"tool": node["tool"], "params": {"threads": "2"}}

    def prepare(self, graph, output, cancel=None, resource_policy=None):
        self.calls.append(("prepare", copy.deepcopy(graph)))
        if self.failure:
            raise ValueError(self.failure)
        folder = Path(output) / "fixture-results"
        folder.mkdir(exist_ok=True)
        return {"folder": str(folder), "graph": graph}

    def execute(self, plan, event, cancel):
        self.started.set()
        event({"type": "phase", "message": "Running fixture"})
        event({"type": "log", "message": "Fixture diagnostic"})
        if not self.release.wait(5):
            raise TimeoutError("Test did not release fake engine")
        if cancel.is_set():
            return {"status": "cancelled", "message": "Cancelled", "nodes": []}
        return copy.deepcopy(self.result)


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench-http-")
        self.root = Path(self.tmp.name)
        web = self.root / "workspace" / "web"
        web.mkdir(parents=True)
        (web / "index.html").write_text("<!doctype html><title>Fixture</title>", encoding="utf-8")
        (web / "app.js").write_text("'use strict';", encoding="utf-8")
        (web / "private.json").write_text('{"secret":"do not serve"}', encoding="utf-8")
        (self.root / "outside.js").write_text("secret outside", encoding="utf-8")
        self.engine = FakeEngine()
        self.catalog = {"tools": {"fixture/one": {"id": "fixture/one"}}, "schema": 1}
        self.app = server.Workbench(self.root, engine=self.engine, catalog=self.catalog)
        self.http = server.LocalServer(self.app)
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.engine.release.set()
        for run in self.app.runs.values():
            if "_worker" in run:
                run["_worker"].join(5)
        self.app.shutdown(grace=1)
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(5)
        self.tmp.cleanup()

    def request(self, method="GET", path="/api/catalog", body=None, *, auth=True, headers=None):
        values = {"Host": self.http.origin[7:]}
        if auth:
            values["X-Workbench-Token"] = self.app.token
        if body is not None:
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body)
            values["Content-Type"] = "application/json"
        values.update(headers or {})
        connection = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        try:
            connection.request(method, path, body=body, headers=values)
            response = connection.getresponse()
            data = response.read()
            content = json.loads(data) if response.getheader("Content-Type", "").startswith("application/json") else data.decode("utf-8")
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def raw_headers(self, extras):
        connection = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        try:
            connection.putrequest("GET", "/api/catalog", skip_host=True)
            connection.putheader("Host", self.http.origin[7:])
            connection.putheader("X-Workbench-Token", self.app.token)
            for name, value in extras:
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def await_finished(self, identity):
        self.app.runs[identity]["_worker"].join(5)
        self.assertFalse(self.app.runs[identity]["_worker"].is_alive())
        return self.app.get_run(identity)

    def start_run(self):
        status, _, body = self.request("POST", "/api/run", {"output_folder": str(self.root), "graph": {"name": "Fixture"}})
        self.assertEqual(status, 200, body)
        self.assertTrue(self.engine.started.wait(3))
        return body["run_id"]

    def test_catalog_requires_token_and_never_returns_it(self):
        status, _, body = self.request(auth=False)
        self.assertEqual(status, 403)
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body["tools"], self.catalog["tools"])
        self.assertNotIn(self.app.token, json.dumps(body))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_foreign_host_and_dns_rebinding_are_denied(self):
        for host in ("evil.example", "localhost:" + str(self.http.server_address[1]), "127.0.0.1:1"):
            with self.subTest(host=host):
                self.assertEqual(self.request(headers={"Host": host})[0], 403)
        self.assertEqual(self.raw_headers([("Host", self.http.origin[7:])]), 403)

    def test_origin_and_cross_site_defenses(self):
        for origin in ("https://evil.example", "null", self.http.origin + "/"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request(headers={"Origin": origin})[0], 403)
        self.assertEqual(self.request(headers={"Origin": self.http.origin})[0], 200)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.raw_headers([("Origin", self.http.origin), ("Origin", "https://evil.example")]), 403)

    def test_invalid_and_duplicate_tokens_are_rejected_without_crashing(self):
        for token in ("", "not-the-token", "\u00e9"):
            with self.subTest(token=token):
                self.assertEqual(self.request(headers={"X-Workbench-Token": token})[0], 403)
        self.assertEqual(self.raw_headers([("X-Workbench-Token", self.app.token)]), 403)

    def test_static_files_have_no_traversal_or_json_access(self):
        self.assertEqual(self.request(path="/", auth=False)[0], 200)
        self.assertEqual(self.request(path="/app.js", auth=False)[0], 200)
        for path in ("/../outside.js", "/%2e%2e/outside.js", "/..%2foutside.js", "/..\\outside.js", "/private.json", "/user-data/saved.json", "/does-not-exist.js"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path, auth=False)[0], 404)
        try:
            (self.app.web / "linked.js").symlink_to(self.root / "outside.js")
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        self.assertEqual(self.request(path="/linked.js", auth=False)[0], 404)

    def test_cross_origin_preflight_and_form_posts_cannot_mutate(self):
        self.assertEqual(self.request("OPTIONS", "/api/save", auth=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/save", "name=x", headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(self.request("POST", "/api/save", {}, auth=False)[0], 403)
        self.assertFalse(self.app.saved_path.exists())

    def test_json_shape_duplicates_and_nonfinite_numbers_are_rejected(self):
        for body in ("[]", "null", '{"graph":{},"graph":{}}', '{"graph":NaN}', '{"graph":Infinity}', '{"graph":"\\ud800"'):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/review", body)[0], 400)
        self.assertFalse(self.engine.calls)

    def test_content_length_and_chunked_limits(self):
        self.assertEqual(self.request("POST", "/api/review", "", headers={"Content-Length": str(server.MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request("POST", "/api/review", "", headers={"Content-Length": "-1"})[0], 413)
        self.assertEqual(self.request("POST", "/api/review", "{}", headers={"Content-Length": "bad"})[0], 400)
        self.assertEqual(self.request("POST", "/api/review", "{}", headers={"Transfer-Encoding": "chunked"})[0], 400)

    def test_review_uses_engine_without_creating_results(self):
        status, _, body = self.request("POST", "/api/review", {"graph": {"name": "Draft"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["methods"], "Planned methods")
        self.assertEqual(self.engine.calls, [("review", {"name": "Draft"})])
        self.assertFalse(self.app.runs)
        self.assertFalse((self.root / "fixture-results").exists())

    def test_save_persists_engine_sanitized_graph_and_presets(self):
        graph = {"sources": [{"files": {"reads": "C:\\sensitive.fastq"}, "sample": "Patient1"}]}
        status, _, item = self.request("POST", "/api/save", {"kind": "pipeline", "name": "My pipeline", "graph": graph})
        self.assertEqual(status, 200)
        self.assertTrue(item["id"])
        status, _, preset = self.request("POST", "/api/save", {"kind": "preset", "name": "My settings", "tool": "fixture/one", "params": {"threads": "2", "sample": "Patient1"}})
        self.assertEqual(status, 200)
        self.assertEqual(preset["params"], {"threads": "2"})
        saved_text = self.app.saved_path.read_text(encoding="utf-8")
        self.assertNotIn("sensitive", saved_text)
        self.assertNotIn("Patient1", saved_text)
        status, _, stored = self.request(path="/api/saved")
        self.assertEqual(status, 200)
        self.assertEqual(stored["pipelines"][0], item)
        self.assertFalse(list(self.app.data.glob("*.tmp")))

    def test_invalid_saved_names_and_unknown_save_type_do_not_write(self):
        for body in ({"kind": "pipeline", "name": ""}, {"kind": "pipeline", "name": "line\nbreak"}, {"kind": "not-a-kind", "name": "Name"}):
            self.assertEqual(self.request("POST", "/api/save", body)[0], 400)
        self.assertFalse(self.app.saved_path.exists())

    def test_run_is_single_active_has_public_status_and_persistent_results(self):
        identity = self.start_run()
        status, _, current = self.request(path="/api/run/" + identity)
        self.assertEqual(status, 200)
        self.assertEqual(current["status"], "running")
        self.assertFalse(any(key.startswith("_") for key in current))
        self.assertEqual(self.request("POST", "/api/run", {"output_folder": str(self.root), "graph": {}})[0], 400)
        self.assertEqual(self.request("POST", "/api/import", {"source": str(self.root)})[0], 400)
        self.assertEqual(self.request("POST", "/api/shutdown", {})[0], 400)
        self.engine.release.set()
        result = self.await_finished(identity)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(Path(result["folder"]).is_dir())
        self.assertEqual(result["nodes"][0]["id"], "step-1")
        self.assertEqual(result["events"][-1]["message"], "Fixture diagnostic")
        stored = json.loads(self.app.history_path.read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["status"], "completed")
        self.assertFalse(any(key.startswith("_") for key in stored[0]))

    def test_cancel_signals_engine_and_removes_cancel_marker(self):
        identity = self.start_run()
        status, _, body = self.request("POST", "/api/cancel", {"run_id": identity})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "cancelling")
        self.assertTrue(self.app.runs[identity]["_cancel"].is_set())
        self.assertTrue(self.app.runs[identity]["_cancel_file"].exists())
        self.engine.release.set()
        result = self.await_finished(identity)
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(self.app.runs[identity]["_cancel_file"].exists())

    def test_preparation_failure_is_recorded_as_failure(self):
        self.engine.failure = "Reference does not match"
        status, _, body = self.request("POST", "/api/run", {"output_folder": str(self.root), "graph": {}})
        self.assertEqual(status, 200)
        result = self.await_finished(body["run_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], self.engine.failure)
        self.assertEqual(result["folder"], "")

    def test_engine_result_cannot_replace_transport_identity_or_events(self):
        self.engine.result.update(run_id="wrong-id", events=[], _cancel="private")
        identity = self.start_run()
        self.engine.release.set()
        result = self.await_finished(identity)
        self.assertEqual(result["run_id"], identity)
        self.assertEqual(len(result["events"]), 2)
        self.assertNotIn("_cancel", result)

    def test_recorded_running_status_is_interrupted_on_restart(self):
        server.atomic_json(self.app.history_path, [{"run_id": "old-run", "status": "running", "folder": str(self.root)}])
        self.app.shutdown(grace=1)
        restarted = server.Workbench(self.root, engine=self.engine, catalog=self.catalog)
        try:
            self.assertEqual(restarted.get_run("old-run")["status"], "interrupted")
            self.assertFalse(restarted.active())
        finally:
            restarted.shutdown(grace=1)

    def test_invalid_output_folder_and_unknown_run_are_rejected(self):
        for output in ("relative", str(self.root / "missing"), str(self.app.web / "app.js")):
            self.assertEqual(self.request("POST", "/api/run", {"output_folder": output, "graph": {}})[0], 400)
        self.assertEqual(self.request(path="/api/run/unknown")[0], 400)
        self.assertEqual(self.request("POST", "/api/open", {"run_id": "unknown"})[0], 400)
        self.assertFalse(self.app.runs)

    def test_native_bridge_success_requires_zero_exit(self):
        class Process:
            def __init__(self, exit_code):
                self.exit_code = exit_code
                self.stdout = io.StringIO('{"type":"result","success":true}\n')
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def wait(self):
                return self.exit_code
            def poll(self):
                return self.exit_code
        with patch.object(server.subprocess, "Popen", return_value=Process(1)):
            with self.assertRaisesRegex(RuntimeError, "exited abnormally"):
                self.app.bridge(["check"])
        with patch.object(server.subprocess, "Popen", return_value=Process(0)):
            self.assertTrue(self.app.bridge(["check"])["success"])

    def test_single_session_reopens_verified_host_without_removing_owner_record(self):
        from session import Session
        owner = Session(self.app.data)
        follower = replacement = None
        try:
            self.assertTrue(owner.owned)
            owner.publish(self.http.server_address[1], self.app.token)
            follower = Session(self.app.data)
            self.assertFalse(follower.owned)
            self.assertEqual(follower.existing_url(), self.http.origin + "/#" + self.app.token)
            follower.close()
            follower = None
            self.assertTrue(owner.path.exists())
            owner.close()
            owner = None
            replacement = Session(self.app.data)
            self.assertTrue(replacement.owned)
        finally:
            for instance in (follower, replacement, owner):
                if instance is not None:
                    instance.close()

    def test_single_session_does_not_accept_foreign_or_malformed_record(self):
        from session import Session
        owner = Session(self.app.data)
        follower = None
        try:
            follower = Session(self.app.data)
            self.assertFalse(follower.owned)
            for record in ({"port": "https://evil.example", "token": self.app.token},
                           {"port": self.http.server_address[1], "token": "short"},
                           {"port": self.http.server_address[1], "token": "X" * 43}):
                owner.path.write_text(json.dumps(record), encoding="utf-8")
                with patch("session.time.sleep"):
                    with self.assertRaisesRegex(RuntimeError, "still starting"):
                        follower.existing_url()
        finally:
            if follower is not None:
                follower.close()
            owner.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
