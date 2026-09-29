"""Controlled long-running child used to verify tool supervision."""

import json
import os
from pathlib import Path
import signal
import sys
import time


mode = sys.argv[1]
marker = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-" else None
duration = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3

if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
elif mode == "secret":
    print(os.environ["FIXTURE_SECRET"], flush=True)

if marker:
    marker.write_text(json.dumps({"pid": os.getpid(), "argv_has_secret": "tool-supervisor-secret" in sys.argv}))

if mode in ("normal", "ignore-term", "finite", "secret"):
    print("fixture-output", flush=True)
    time.sleep(duration)
else:
    raise SystemExit(23)
