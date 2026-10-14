"""Single local host per extracted application folder, with safe window reopen."""
import http.client
import json
import os
from pathlib import Path
import re
import time


class Session:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(exist_ok=True)
        self.path = directory / "session.json"
        self.file = (directory / "session.lock").open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        self.owned = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.owned = True
        except OSError:
            pass

    def existing_url(self):
        for _ in range(50):
            try:
                if self.path.stat().st_size > 2048:
                    raise ValueError("Invalid session record")
                state = json.loads(self.path.read_text(encoding="utf-8"))
                port, token = state["port"], state["token"]
                if type(port) is not int or not 1 <= port <= 65535 or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
                    raise ValueError("Invalid session record")
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    connection.request("GET", "/api/ping", headers={"X-Workbench-Token": token})
                    response = connection.getresponse()
                    data = response.read(4096)
                    if response.status == 200 and json.loads(data).get("ok") is True:
                        return "http://127.0.0.1:" + str(port) + "/#" + token
                finally:
                    connection.close()
            except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        raise RuntimeError("Native Workbench is still starting in another window. Wait a moment and open it again.")

    def publish(self, port, token):
        if not self.owned:
            raise RuntimeError("This session does not own the workbench host")
        self.path.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
        if os.name != "nt":
            self.path.chmod(0o600)

    def close(self):
        if self.owned:
            self.path.unlink(missing_ok=True)
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
