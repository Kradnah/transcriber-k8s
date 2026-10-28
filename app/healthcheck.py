"""Worker liveness check used by the Kubernetes probe: python -m app.healthcheck

Exits 0 if the worker loop touched its heartbeat file recently, 1 otherwise.
A stuck worker (e.g. hung on a corrupt file) stops touching it and gets restarted.
"""

import os
import sys
import time

from .config import load_settings

MAX_AGE_SECONDS = int(os.environ.get("HEARTBEAT_MAX_AGE", "600"))


def main() -> int:
    path = load_settings().heartbeat_file
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        print(f"no heartbeat at {path}")
        return 1
    if age > MAX_AGE_SECONDS:
        print(f"heartbeat is {age:.0f}s old")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
