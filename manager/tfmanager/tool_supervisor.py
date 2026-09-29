"""Own one tool process group while retaining inherited resource leases.

This file is launched as a standalone stdlib helper. It never unlocks a lease:
the manager, supervisor and real child close their copies naturally after the
real child has exited.
"""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time


def emit(payload):
    try:
        print(json.dumps(payload, separators=(",", ":")), flush=True)
    except (BrokenPipeError, OSError):
        pass


def validated_config(line):
    config = json.loads(line)
    argv = config.get("argv")
    env = config.get("env")
    if (
        not isinstance(config, dict)
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
        or not isinstance(env, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items())
    ):
        raise ValueError("invalid tool supervisor config")
    lease_fd = config.get("lease_fd")
    liveness_fd = config.get("liveness_fd")
    if lease_fd is not None and (type(lease_fd) is not int or lease_fd < 0):
        raise ValueError("invalid lease fd")
    if type(liveness_fd) is not int or liveness_fd < 0:
        raise ValueError("invalid liveness fd")
    os.fstat(liveness_fd)
    if lease_fd is not None:
        os.fstat(lease_fd)
    stop_timeout = config.get("stop_timeout", 10)
    max_output = config.get("max_output", 4 * 1024 * 1024)
    if not isinstance(stop_timeout, (int, float)) or isinstance(stop_timeout, bool) or not 0.05 <= stop_timeout <= 120:
        raise ValueError("invalid stop timeout")
    if type(max_output) is not int or not 1024 <= max_output <= 16 * 1024 * 1024:
        raise ValueError("invalid output limit")
    config["stop_timeout"] = float(stop_timeout)
    config["max_output"] = max_output
    config["sensitive"] = config.get("sensitive") is True
    config["capture_output"] = config.get("capture_output") is True and not config["sensitive"]
    return config


def main():
    try:
        config = validated_config(sys.stdin.readline())
    except Exception:
        emit({"event": "fatal", "message": "Tool supervisor rejected its configuration"})
        return 2

    inherited = [config["liveness_fd"]]
    if config.get("lease_fd") is not None:
        inherited.append(config["lease_fd"])
    try:
        child = subprocess.Popen(
            config["argv"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=config["env"],
            start_new_session=True,
            pass_fds=tuple(inherited),
        )
    except Exception:
        os.close(config["liveness_fd"])
        emit({"event": "fatal", "message": "Tool supervisor could not start its child"})
        return 3

    # Only the actual child now owns the liveness writer. The supervisor keeps
    # the lease descriptor until after wait(), but must not keep this pipe open.
    os.close(config["liveness_fd"])
    commands = queue.Queue()
    output = []
    output_size = 0
    overflow = False

    def drain():
        nonlocal output_size, overflow
        while True:
            chunk = child.stdout.read(4096)
            if not chunk:
                return
            if not config["capture_output"]:
                continue
            size = len(chunk.encode("utf-8", errors="replace"))
            if output_size + size <= config["max_output"]:
                output.append(chunk)
                output_size += size
            else:
                overflow = True

    def control():
        for line in sys.stdin:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("action") == "cancel":
                commands.put("cancel")
        commands.put("eof")

    output_thread = threading.Thread(target=drain, daemon=True, name="tool-output-drain")
    control_thread = threading.Thread(target=control, daemon=True, name="tool-parent-control")
    output_thread.start()
    control_thread.start()
    emit({"event": "started", "pid": child.pid})
    stopping_at = None
    forced = False
    while child.poll() is None:
        try:
            command = commands.get(timeout=0.05)
        except queue.Empty:
            command = None
        if command in ("cancel", "eof") and stopping_at is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            stopping_at = time.monotonic()
        if stopping_at is not None and not forced and time.monotonic() - stopping_at >= config["stop_timeout"]:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            forced = True
    returncode = child.wait()
    output_thread.join(timeout=10)
    child.stdout.close()
    emit(
        {
            "event": "exit",
            "pid": child.pid,
            "returncode": returncode,
            "output": "" if config["sensitive"] else "".join(output),
            "overflow": overflow,
        }
    )
    if config.get("lease_fd") is not None:
        os.close(config["lease_fd"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
