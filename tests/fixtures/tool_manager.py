"""Runs the production Tools._run path so a parent test can SIGKILL it."""

import fcntl
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "manager"))

from tfmanager.tools import Tools


class Store:
    def __init__(self, root):
        self.root = Path(root)

    def log(self, level, message):
        pass


class Job:
    id = "manager-crash-fixture"

    def checkpoint(self):
        pass


class Lease:
    def __init__(self, fd):
        self.fd = fd


lock_path, marker_path, data_root = sys.argv[1:]
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
runner = object.__new__(Tools)
runner.store = Store(data_root)
runner._run(
    [sys.executable, "-I", "-B", str(Path(__file__).with_name("tool_child.py")), "ignore-term", marker_path, "30"],
    Job(),
    lease=Lease(fd),
    stop_timeout=1.0,
)
os.close(fd)
