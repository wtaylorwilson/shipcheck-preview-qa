from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("SHIPCHECK_HOME", "/workspace/shipcheck")).resolve()
QUEUE_DIR = HOME / "queue"
REPORTS_DIR = HOME / "reports"


def ensure_dirs() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
