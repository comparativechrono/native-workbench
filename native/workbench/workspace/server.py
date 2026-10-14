"""Local-only transport for Native Workbench. No third-party Python packages.

The browser never uploads biological files. The native bridge receives local
paths and performs the same guarded workflows as the classic desktop window.
"""
from __future__ import annotations

import argparse
import copy
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from catalog import load_catalog
from engine import Engine

VERSION = "0.5.0"
MAX_BODY = 2 * 1024 * 1024


from service import Workbench, atomic_json, strict_json, short_text


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    def __init__(self, app, port=0):
        self.app = app
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = "http://127.0.0.1:" + str(self.server_address[1])


class Handler(BaseHTTPRequestHandler):
    server_version = "NativeWorkbench/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        # URLs and local paths never enter a browser/server access log.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def headers_ok(self, auth=False):
        if self.client_address[0] != "127.0.0.1":
            return False
        if self.headers.get_all("Host") != [self.server.origin[7:]]:
            return False
        origins = self.headers.get_all("Origin") or []
        if origins and origins != [self.server.origin]:
            return False
        fetch_site = self.headers.get("Sec-Fetch-Site", "")
        if fetch_site == "cross-site":
            return False
        if auth:
            tokens = self.headers.get_all("X-Workbench-Token") or []
            if len(tokens) != 1 or not tokens[0].isascii() or not hmac.compare_digest(tokens[0], self.server.app.token):
                return False
        return True

    def send(self, status, content, mime="application/json; charset=utf-8"):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlsplit(self.path).path
        api = path.startswith("/api/")
        if not self.headers_ok(auth=api):
            return self.send(403, {"error": "This page is not authorised to access this workbench."})
        app = self.server.app
        if api:
            app.last_seen = time.monotonic()
        try:
            if path == "/api/catalog":
                return self.send(200, {**app.catalog, "app_version": VERSION, "platform": os.name})
            if path == "/api/ping":
                return self.send(200, {"ok": True, "active": app.active(), "active_run": next((r["run_id"] for r in app.runs.values() if r["status"] in ("preparing", "running", "cancelling")), None)})
            if path == "/api/saved":
                return self.send(200, app.saved())
            if path == "/api/runs":
                with app.lock:
                    return self.send(200, {"runs": [app.public_run(r) for r in app.runs.values()] + [r for r in app.history if r["run_id"] not in app.runs]})
            if path.startswith("/api/run/"):
                return self.send(200, app.get_run(path.removeprefix("/api/run/")))
            if path == "/api/example":
                from example import make_example
                return self.send(200, {"graph": make_example(app.root, app.catalog)})
            # Single allow-listed static directory, no arbitrary filesystem read.
            static = path[1:] or "index.html"
            if "/" in static or "\\" in static or static.startswith(".") or static not in {p.name for p in app.web.iterdir() if p.is_file()}:
                return self.send(404, {"error": "Not found"})
            file = app.web / static
            if file.is_symlink() or file.suffix not in (".html", ".js", ".css", ".svg", ".ico"):
                return self.send(404, {"error": "Not found"})
            mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".ico": "image/x-icon"}[file.suffix]
            self.send(200, file.read_bytes(), mime + "; charset=utf-8")
        except Exception as error:
            self.send(400, {"error": str(error)})

    def do_POST(self):
        if not self.headers_ok(auth=True):
            return self.send(403, {"error": "This request is not authorised."})
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length") or []) != 1:
            return self.send(400, {"error": "A single Content-Length is required."})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send(415, {"error": "Expected JSON."})
        try:
            length = int(self.headers["Content-Length"])
            if not 0 <= length <= MAX_BODY:
                return self.send(413, {"error": "Request is too large."})
            request = strict_json(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object.")
            app = self.server.app
            app.last_seen = time.monotonic()
            path = urlsplit(self.path).path
            if path == "/api/browse":
                result = app.browse(request)
            elif path == "/api/save":
                result = app.save(request)
            elif path == "/api/review":
                result = app.review(request.get("graph"))
            elif path == "/api/run":
                result = app.start(request)
            elif path == "/api/check":
                result = app.start(request, check=True)
            elif path == "/api/cancel":
                result = app.cancel(request.get("run_id"))
            elif path == "/api/open":
                result = app.open_results(request.get("run_id"))
            elif path == "/api/import":
                result = app.import_pack(request)
            elif path == "/api/shutdown":
                if app.active():
                    raise ValueError("Cancel the running analysis before closing the workbench.")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                result = {"closed": True}
            else:
                return self.send(404, {"error": "Not found"})
            self.send(200, result)
        except Exception as error:
            self.send(400, {"error": str(error)})

    def do_OPTIONS(self):
        self.send(403, {"error": "Cross-origin access is disabled."})


def open_window(url):
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                edge = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                if edge.is_file():
                    subprocess.Popen([str(edge), "--app=" + url, "--no-first-run"], creationflags=subprocess.CREATE_NO_WINDOW)
                    return
        os.startfile(url)
    else:
        import webbrowser
        if not webbrowser.open(url):
            raise RuntimeError("Could not open a browser window.")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--no-browser", action="store_true", help="Print local URL for development checks")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    from session import Session
    args.app_root = args.app_root.resolve()
    session = Session(args.app_root / "user-data")
    if not session.owned:
        try:
            url = session.existing_url()
            if args.check:
                import http.client
                parsed = urlsplit(url)
                results = args.app_root / "results"
                results.mkdir(exist_ok=True)
                connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=10)
                try:
                    connection.request("POST", "/api/check", json.dumps({"output_folder": str(results)}),
                                       {"Content-Type": "application/json", "X-Workbench-Token": parsed.fragment})
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                    if response.status != 200:
                        raise RuntimeError(payload.get("error", "Could not start installation checks"))
                finally:
                    connection.close()
            if args.no_browser:
                print(url, flush=True)
            else:
                open_window(url)
            return
        finally:
            session.close()
    app = Workbench(args.app_root)
    server = LocalServer(app)
    session.publish(server.server_address[1], app.token)
    def idle_watch():
        while True:
            time.sleep(10)
            if not app.active() and time.monotonic() - app.last_seen > 300:
                server.shutdown()
                return
    threading.Thread(target=idle_watch, daemon=True).start()
    url = server.origin + "/#" + app.token
    if args.check:
        results = app.root / "results"
        results.mkdir(exist_ok=True)
        app.start({"output_folder": str(results)}, check=True)
    if args.no_browser:
        print(url, flush=True)
    else:
        open_window(url)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        session.close()


if __name__ == "__main__":
    main()
