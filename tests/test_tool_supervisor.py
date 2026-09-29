import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manager"))

from tfmanager.jobs import Cancelled
from tfmanager.tools import Tools


FIXTURES = Path(__file__).parent / "fixtures"
SUPERVISOR = Path(__file__).resolve().parents[1] / "manager/tfmanager/tool_supervisor.py"
CHILD = FIXTURES / "tool_child.py"
MANAGER = FIXTURES / "tool_manager.py"


def read_event(process, wanted, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.1)
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            raise AssertionError("supervisor exited before " + wanted + ": " + process.stderr.read())
        event = json.loads(line)
        if event.get("event") == wanted:
            return event
    raise AssertionError("timed out waiting for " + wanted)


def competing_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def wait_lock(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fd = competing_lock(path)
        if fd is not None:
            return fd
        time.sleep(0.02)
    raise AssertionError("resource lock remained held")


def wait_pid_gone(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    raise AssertionError(f"process {pid} remained alive")


def wait_file(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"fixture did not create {path}")


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def launch(self, mode, duration=0.4, stop_timeout=0.3):
        lock = self.root / (mode + ".lock")
        marker = self.root / (mode + "-child.json")
        lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        live_read, live_write = os.pipe()
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(SUPERVISOR)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(lock_fd, live_write),
        )
        config = {
            "argv": [sys.executable, "-I", "-B", str(CHILD), mode, str(marker), str(duration)],
            "env": {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            "lease_fd": lock_fd,
            "liveness_fd": live_write,
            "stop_timeout": stop_timeout,
            "capture_output": mode != "secret",
            "max_output": 1024 * 1024,
            "sensitive": mode == "secret",
        }
        process.stdin.write(json.dumps(config) + "\n")
        process.stdin.flush()
        os.close(live_write)
        def cleanup():
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()
            try:
                os.close(live_read)
            except OSError:
                pass
        self.addCleanup(cleanup)
        return process, lock, lock_fd, live_read

    def test_normal_exit_holds_shared_lease_until_real_child_exit(self):
        process, lock, manager_fd, live_read = self.launch("normal", duration=0.35)
        started = read_event(process, "started")
        wait_file(self.root / "normal-child.json")
        os.close(manager_fd)
        self.assertIsNone(competing_lock(lock))
        exited = read_event(process, "exit")
        self.assertEqual(exited["returncode"], 0)
        self.assertIn("fixture-output", exited["output"])
        self.assertEqual(os.read(live_read, 1), b"")
        process.wait(timeout=3)
        available = wait_lock(lock)
        os.close(available)
        wait_pid_gone(started["pid"])

    def test_cancel_escalates_for_sigterm_ignoring_child_and_waits_for_exit(self):
        process, lock, manager_fd, live_read = self.launch("ignore-term", duration=30, stop_timeout=0.25)
        started = read_event(process, "started")
        wait_file(self.root / "ignore-term-child.json")
        os.close(manager_fd)
        began = time.monotonic()
        process.stdin.write('{"action":"cancel"}\n')
        process.stdin.flush()
        exited = read_event(process, "exit")
        self.assertLess(exited["returncode"], 0)
        self.assertGreaterEqual(time.monotonic() - began, 0.2)
        self.assertEqual(os.read(live_read, 1), b"")
        process.wait(timeout=3)
        wait_pid_gone(started["pid"])
        available = wait_lock(lock)
        os.close(available)

    def test_manager_pipe_eof_terminates_and_reaps_owned_child(self):
        process, lock, manager_fd, live_read = self.launch("ignore-term", duration=30, stop_timeout=0.2)
        started = read_event(process, "started")
        wait_file(self.root / "ignore-term-child.json")
        os.close(manager_fd)
        process.stdin.close()
        process.wait(timeout=3)
        self.assertEqual(os.read(live_read, 1), b"")
        wait_pid_gone(started["pid"])
        available = wait_lock(lock)
        os.close(available)

    def test_supervisor_sigkill_leaves_child_holding_lease_until_natural_exit(self):
        process, lock, manager_fd, live_read = self.launch("finite", duration=0.8)
        started = read_event(process, "started")
        wait_file(self.root / "finite-child.json")
        os.close(manager_fd)
        process.kill()
        process.wait(timeout=3)
        self.assertIsNone(competing_lock(lock))
        self.assertFalse(select.select([live_read], [], [], 0.1)[0])
        self.assertEqual(os.read(live_read, 1), b"")
        available = wait_lock(lock)
        os.close(available)
        wait_pid_gone(started["pid"])

    def test_manager_sigkill_keeps_lock_until_supervisor_stops_real_child(self):
        lock = self.root / "manager-crash.lock"
        marker = self.root / "child.json"
        data = self.root / "data"
        data.mkdir()
        manager = subprocess.Popen(
            [sys.executable, "-I", "-B", str(MANAGER), str(lock), str(marker), str(data)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: manager.kill() if manager.poll() is None else None)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            if manager.poll() is not None:
                self.fail(manager.stderr.read())
            time.sleep(0.02)
        child_pid = json.loads(marker.read_text())["pid"]
        manager.kill()
        manager.wait(timeout=3)
        manager.stderr.close()
        self.assertIsNone(competing_lock(lock))
        available = wait_lock(lock, timeout=4)
        os.close(available)
        wait_pid_gone(child_pid)

    def test_sensitive_child_output_is_drained_without_secret_in_result_or_log(self):
        secret = "tool-supervisor-secret"
        logs = []

        class Store:
            root = self.root

            def log(self, level, message):
                logs.append(message)

        class Job:
            id = "sensitive"

            def checkpoint(self):
                pass

        marker = self.root / "secret-child.json"
        runner = object.__new__(Tools)
        runner.store = Store()
        output = runner._run(
            [sys.executable, "-I", "-B", str(CHILD), "secret", str(marker), "0.05"],
            Job(),
            env={"PATH": "/usr/bin:/bin", "FIXTURE_SECRET": secret, "PYTHONDONTWRITEBYTECODE": "1"},
            secrets=(secret,),
            log_output=False,
        )
        self.assertEqual(output, "")
        self.assertFalse(json.loads(marker.read_text())["argv_has_secret"])
        self.assertNotIn(secret, "".join(logs))


if __name__ == "__main__":
    unittest.main()
