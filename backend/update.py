"""自动更新检查：引擎（ashhart/TensorFold）+ App（alickfine/TensorFold-Manager）。

实测结论（2026-10，写死在此以免被网上教程带偏）：
  - tensorfold 不发 PyPI（pypi.org/pypi/tensorfold → 404），更新源唯一 = GitHub Releases。
  - App 仓库 latest 端点当前 404（旧稿只有 prerelease），故查 releases 列表并过滤 draft，
    prerelease 也算有效目标。
  - 本机 HTTP(S)_PROXY 会劫持 127.0.0.1 与外网请求，联网一律走清代理 opener。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

ENGINE_REPO = "ashhart/TensorFold"
APP_REPO = "alickfine/TensorFold-Manager"
APP_VERSION = "2.0.0"

_OPENER = None


def _opener():
    """清代理 opener：本机代理会劫持请求（同 engine 的坑）。"""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER


def _env_no_proxy() -> dict:
    env = {k: v for k, v in os.environ.items()
           if "PROXY" not in k.upper() and k.upper() != "NO_PROXY"}
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["no_proxy"] = "127.0.0.1,localhost,::1"
    return env


def _version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _cmp(a: str, b: str) -> int:
    ka, kb = _version_key(a), _version_key(b)
    n = max(len(ka), len(kb))
    ka += (0,) * (n - len(ka))
    kb += (0,) * (n - len(kb))
    return (ka > kb) - (ka < kb)


_TOKEN = None
_TOKEN_DONE = False


def _gh_token() -> str:
    """GitHub 匿名限流 60 次/h，共享 IP 极易 403。优先环境变量，其次 gh CLI。"""
    global _TOKEN, _TOKEN_DONE
    if _TOKEN_DONE:
        return _TOKEN
    _TOKEN_DONE = True
    _TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not _TOKEN:
        try:
            r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                _TOKEN = r.stdout.strip()
        except Exception:
            pass
    return _TOKEN


def _get_json(url: str, timeout: float = 8.0):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "TensorFold-Manager"}
    tok = _gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    with _opener().open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


class UpdateChecker:
    """检查 + 提示 + 一键动作；结果缓存；后台线程每日一次 + 手动触发。"""

    def __init__(self, engine_version: str = "", app_version: str = APP_VERSION):
        self.engine_version = engine_version
        self.app_version = app_version
        self.lock = threading.Lock()
        self.result: dict = {"checked_at": 0, "engine": None, "app": None, "error": ""}
        self._last_bg = 0.0

    # ---------- 引擎 ----------
    def check_engine(self) -> dict:
        data = _get_json(f"https://api.github.com/repos/{ENGINE_REPO}/releases/latest")
        tag = (data.get("tag_name") or "").lstrip("v")
        cur = re.sub(r"^v", "", self.engine_version or "")
        newer = bool(tag) and _cmp(tag, cur) > 0
        return {"available": newer, "latest": tag, "current": cur,
                "url": data.get("html_url", ""),
                "notes": (data.get("body") or "")[:2000]}

    # ---------- App ----------
    def check_app(self) -> dict:
        try:
            releases = _get_json(f"https://api.github.com/repos/{APP_REPO}/releases")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # 仓库无 release → 无更新，不是错误
                return {"available": False, "latest": "", "current": self.app_version, "url": ""}
            raise
        cands = [r for r in releases if not r.get("draft")]
        if not cands:
            return {"available": False, "latest": "", "current": self.app_version, "url": ""}
        cands.sort(key=lambda r: _version_key((r.get("tag_name") or "").lstrip("v")), reverse=True)
        best = cands[0]
        tag = (best.get("tag_name") or "").lstrip("v")
        return {"available": _cmp(tag, self.app_version) > 0, "latest": tag,
                "current": self.app_version, "url": best.get("html_url", ""),
                "prerelease": bool(best.get("prerelease"))}

    # ---------- 组合 ----------
    def check_all(self) -> dict:
        out = {"checked_at": time.time(), "engine": None, "app": None, "error": ""}
        errs = []
        for key, fn in (("engine", self.check_engine), ("app", self.check_app)):
            try:
                out[key] = fn()
            except Exception as exc:
                out[key] = None
                errs.append(f"{key}: {exc}")
        out["error"] = "; ".join(errs)
        with self.lock:
            self.result = out
        return out

    def cached(self) -> dict:
        with self.lock:
            return dict(self.result)

    def maybe_background(self, interval: float = 86400.0) -> bool:
        """距上次 ≥interval 秒才真查（每日一次），返回本次是否触发。"""
        if time.time() - self._last_bg < interval:
            return False
        self._last_bg = time.time()
        threading.Thread(target=self.check_all, daemon=True, name="update-check").start()
        return True

    # ---------- 一键动作 ----------
    def apply_engine(self, python_bin: str, log=print) -> dict:
        """引擎一键 = 从 GitHub 拉该 tag 源码 pip 安装（覆盖式，pip install 支持 URL）。

        用 codeload tarball 直链（等价 git archive），避免本机无 git / 代理干扰 git 协议。
        """
        with self.lock:
            eng = self.result.get("engine") or {}
        if not eng.get("latest"):
            return {"ok": False, "error": "先检查更新"}
        tag = eng["latest"]
        url = f"https://codeload.github.com/{ENGINE_REPO}/tar.gz/refs/tags/v{tag}"
        pip = [python_bin, "-m", "pip", "install", "--force-reinstall", "--no-deps", url]
        if os.path.basename(python_bin) in ("python", "python3"):
            pass
        log(f"更新引擎: pip install {url}")
        try:
            r = subprocess.run(pip, capture_output=True, text=True, timeout=600,
                               env=_env_no_proxy())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[-500:]}
        self.engine_version = tag
        return {"ok": True, "version": tag}


def apply_app_open(url: str) -> dict:
    """App 一键 = 打开最新 Release 下载页（不做应用内自替换）。"""
    if not url:
        return {"ok": False, "error": "没有可打开的地址"}
    try:
        subprocess.run(["open", url], check=False, timeout=10)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
