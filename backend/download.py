"""模型下载：后台线程跑 `tensorfold pull <repo_id>`，记录日志与进度。"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time


class DownloadManager:
    def __init__(self, python_bin: str):
        self.python_bin = python_bin
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}  # repo_id -> job

    def status(self, repo_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(repo_id)
            return dict(job) if job else None

    def statuses(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._jobs.items() if v.get("status") == "downloading"}

    def active(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._jobs.items() if v.get("status") == "downloading"}

    def start(self, repo_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(repo_id)
            if job and job.get("status") == "downloading":
                return {"ok": False, "error": f"{repo_id} 已在下载中"}
            self._jobs[repo_id] = {"status": "downloading", "started": time.time(),
                                   "error": "", "log": [], "proc": None}
        t = threading.Thread(target=self._run, args=(repo_id,), daemon=True,
                             name=f"pull-{repo_id.split('/')[-1]}")
        t.start()
        return {"ok": True}

    def _log(self, repo_id: str, line: str):
        with self._lock:
            job = self._jobs.get(repo_id)
            if job is not None:
                job["log"].append(line)
                if len(job["log"]) > 200:
                    del job["log"][: len(job["log"]) - 200]

    def _run(self, repo_id: str):
        import os
        try:
            if os.path.basename(self.python_bin) in ("python", "python3"):
                argv = [self.python_bin, "-m", "tensorfold", "pull", repo_id]
            else:
                argv = [self.python_bin, "pull", repo_id]
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, errors="replace",
                cwd=os.path.expanduser("~"))
        except OSError as exc:
            with self._lock:
                self._jobs[repo_id] = {"status": "error", "error": f"无法启动下载: {exc}"}
            return
        with self._lock:
            job = self._jobs.get(repo_id)
            if job is not None:
                job["proc"] = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self._log(repo_id, line)
        code = proc.wait()
        with self._lock:
            job = self._jobs.get(repo_id)
            if job is None:
                return
            if job.get("cancelled"):
                job["status"] = "cancelled"
            elif code == 0:
                job["status"] = "done"
            else:
                job["status"] = "error"
                job["error"] = f"下载失败 (code={code})"
            job["proc"] = None

    def cancel(self, repo_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(repo_id)
            if not job or job.get("status") != "downloading":
                return {"ok": False, "error": "该模型没有进行中的下载"}
            job["cancelled"] = True
            proc = job.get("proc")
        if proc is not None:
            proc.terminate()
        self._log(repo_id, "已取消下载")
        return {"ok": True}
