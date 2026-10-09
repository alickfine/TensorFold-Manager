"""模型下载：后台线程跑 `tensorfold pull <repo_id>`，记录日志与进度。"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time


def _hub_dir(repo_id: str) -> str:
    """该 repo 在 HF 缓存里的目录（models--owner--name）。"""
    from . import engine as engine_mod
    return os.path.join(engine_mod.hf_cache_dir(), "models--" + repo_id.replace("/", "--"))


def _dir_bytes_gb(path: str) -> float:
    """目录已落盘字节数（GB）。软链不计 —— 否则 .hf-cache 形式的模型会被重复计一遍。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            p = os.path.join(root, name)
            if os.path.islink(p):
                continue
            try:
                total += os.stat(p).st_size
            except OSError:
                continue
    return total / 1024 ** 3


class DownloadManager:
    def __init__(self, python_bin: str):
        self.python_bin = python_bin
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}  # repo_id -> job
        self._size_cache: dict[str, tuple[float, float, float]] = {}   # repo -> (t, gb, total)

    def progress(self, repo_id: str) -> dict:
        """真实进度：直接量 HF 缓存里该 repo 目录已落盘的字节（不猜、不写死百分比）。

        3s 内复用上次结果：目录里可能有上千个文件，UI 每 2.5s 拉一次，
        每次都全量 walk 一遍不值当。
        """
        now = time.time()
        hit = self._size_cache.get(repo_id)
        if hit and now - hit[0] < 3.0:
            gb, total = hit[1], hit[2]
        else:
            try:
                gb = _dir_bytes_gb(_hub_dir(repo_id))
            except Exception:
                gb = 0.0
            job = self._jobs.get(repo_id) or {}
            total = float(job.get("total_gb") or 0)
            self._size_cache[repo_id] = (now, gb, total)
        out = {"done_gb": round(gb, 2), "total_gb": round(total, 2) if total else None}
        if total > 0.01:
            out["percent"] = max(0, min(100, round(gb / total * 100)))
        return out

    def status(self, repo_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(repo_id)
            if not job:
                return None
            out = dict(job)
        if out.get("status") == "downloading":
            out.update(self.progress(repo_id))
            out["elapsed"] = round(time.time() - float(out.get("started") or time.time()))
        out.pop("proc", None)
        return out

    def statuses(self) -> dict:
        with self._lock:
            ids = [k for k, v in self._jobs.items() if v.get("status") == "downloading"]
        return {k: self.status(k) for k in ids}

    def active(self) -> dict:
        return self.statuses()

    def start(self, repo_id: str, total_gb: float | None = None) -> dict:
        with self._lock:
            job = self._jobs.get(repo_id)
            if job and job.get("status") == "downloading":
                return {"ok": False, "error": f"{repo_id} 已在下载中"}
            self._jobs[repo_id] = {"status": "downloading", "started": time.time(),
                                   "error": "", "log": [], "proc": None,
                                   "total_gb": float(total_gb or 0)}
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
