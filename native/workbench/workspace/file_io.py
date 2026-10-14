"""Bounded atomic replacement for local queue and run-history receipts."""
from __future__ import annotations

import os
from time import sleep

WINDOWS = os.name == "nt"
# A Windows reader can temporarily prevent replacement even when it permits
# DELETE sharing. Retry only the same prepared rename, never an analysis or a
# partial write. Persistent permission/storage errors still fail closed.
REPLACE_DELAYS = (.01, .02, .04, .08, .10, .10, .10, .10)


def replace_file(source, destination):
    """Atomically replace, allowing at most 550ms of Windows sharing waits.

    The caller owns staging, cleanup and publishing its new in-memory state.
    No destination deletion or non-atomic copy fallback is permitted.
    """
    for attempt in range(len(REPLACE_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if (not WINDOWS or getattr(error, "winerror", None) not in (5, 32, 33)
                    or attempt == len(REPLACE_DELAYS)):
                raise
            sleep(REPLACE_DELAYS[attempt])
