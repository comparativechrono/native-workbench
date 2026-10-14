"""Explicit import path for the private, isolated CPython distribution."""
import os
from pathlib import Path
import sys
import traceback

workspace = Path(__file__).resolve().parent
sys.path.insert(0, str(workspace))
try:
    from server import main
    main()
except Exception:
    message = traceback.format_exc()
    try:
        with (workspace.parent / "workspace-startup-error.txt").open("w", encoding="utf-8") as stream:
            stream.write(message)
    except OSError:
        pass
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Native Workbench could not start.\n\n" + message[-3500:] + "\n\nDetails: workspace-startup-error.txt", "Native Workbench", 0x10)
    else:
        raise
