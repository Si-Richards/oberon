from __future__ import annotations

import os
import sys
import time
from pathlib import Path

path = Path(os.getenv("HEALTH_FILE", "/tmp/oberon-health"))
try:
    age = time.time() - path.stat().st_mtime
except FileNotFoundError:
    sys.exit(1)
sys.exit(0 if age < 90 else 1)
