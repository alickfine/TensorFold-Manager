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
APP_VERSION = "2.1.7"

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


_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def _clean_version(s: str) -> str:
    """把引擎/App 自报的版本串归一成纯版本号（1.0.2）。

    实测坑：`detect()` 拿到的字符串是 CLI 自报原文 —— 原生二进制是
    "tensorfold-native 1.0.2"，内嵌解释器是 "tensorfold 0.6.5"。直接拿去比对
    只是靠"提取所有数字"侥幸能用，且 `current` 会原样显示成
    "tensorfold-native 1.0.2"，用户看不懂；万一名字里带别的数字就会比错。
    """
    m = _VERSION_RE.search(s or "")
    if m:
        return m.group(0)
    return (s or "").strip().lstrip("v")


def _cmp(a: str, b: str) -> int:
    ka, kb = _version_key(a), _version_key(b)
    n = max(len(ka), len(kb))
    ka += (0,) * (n - len(ka))
    kb += (0,) * (n - len(kb))
    return (ka > kb) - (ka < kb)


_TOKEN = None
_TOKEN_DONE = False


def _gh_token() -> str:
    """GitHub 匿名限流 60 次/h，共享 IP 极易 403。优先环境变量，其次 gh CLI。

    2026-10-08 实测：Finder 拉起的 App 子进程 PATH 只有 /usr/bin:/bin 等，
    homebrew 的 gh（/opt/homebrew/bin/gh）不在其中 → 兜底永远失败 →
    匿名请求撞限流 403，设置页「升级」按钮看起来"不可用"。
    因此显式探测常见安装位置，不能只赌裸 `gh`。
    """
    global _TOKEN, _TOKEN_DONE
    if _TOKEN_DONE:
        return _TOKEN
    _TOKEN_DONE = True
    _TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if _TOKEN:
        return _TOKEN
    gh_candidates = ["gh",
                     "/opt/homebrew/bin/gh",      # Apple Silicon homebrew
                     "/usr/local/bin/gh",          # Intel homebrew
                     os.path.expanduser("~/bin/gh")]
    for gh in gh_candidates:
        try:
            r = subprocess.run([gh, "auth", "token"], capture_output=True,
                               text=True, timeout=5, close_fds=False)  # posix_spawn；fork 会死锁
            if r.returncode == 0 and r.stdout.strip():
                _TOKEN = r.stdout.strip()
                break
        except Exception:
            continue
    if not _TOKEN:
        # 兜底：直接读 gh 的配置文件（CLI 不在 PATH / 无法执行时仍能拿到 token）
        _TOKEN = _token_from_hosts_file()
    return _TOKEN


def _token_from_hosts_file() -> str:
    """从 ~/.config/gh/hosts.yml 里抠 oauth_token（只做行解析，不引入 yaml 依赖）。"""
    import glob as _glob
    paths = [os.path.expanduser("~/.config/gh/hosts.yml")]
    paths += _glob.glob(os.path.expanduser("~/.config/gh/hosts.yml.d/*.yml"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("oauth_token:"):
                        tok = s.split(":", 1)[1].strip().strip("'\"")
                        if tok:
                            return tok
        except OSError:
            continue
    return ""


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
        cur = _clean_version(self.engine_version)
        newer = bool(tag) and _cmp(tag, cur) > 0
        return {"available": newer, "latest": tag, "current": cur,
                "current_raw": self.engine_version or "",
                "url": data.get("html_url", ""),
                "notes": (data.get("body") or "")[:2000]}

    # ---------- App ----------
    def check_app(self) -> dict:
        cur = _clean_version(self.app_version)
        try:
            releases = _get_json(f"https://api.github.com/repos/{APP_REPO}/releases")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # 仓库无 release → 无更新，不是错误
                return {"available": False, "latest": "", "current": cur, "url": ""}
            raise
        cands = [r for r in releases if not r.get("draft")]
        if not cands:
            return {"available": False, "latest": "", "current": cur, "url": ""}
        cands.sort(key=lambda r: _version_key((r.get("tag_name") or "").lstrip("v")), reverse=True)
        best = cands[0]
        tag = (best.get("tag_name") or "").lstrip("v")
        return {"available": bool(tag) and _cmp(tag, cur) > 0, "latest": tag,
                "current": cur, "url": best.get("html_url", ""),
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
    def apply_engine(self, python_bin: str = "", log=print) -> dict:
        """引擎一键升级：下载官方原生二进制 → SHA256 校验 → 解压到 engines/<版本>/。

        背景（2026-10-08 实测）：上游 v1.0+ 是原生二进制发布，pip 源码安装被官方
        禁用（setup.py 直接 raise SystemExit），pip 通道最高只能到 0.6.x。
        目录布局：~/.tensorfold-manager/engines/<tag>/bin/tensorfold-native
        旧版本保留可回退；engine.py 选引擎时优先取本目录最高版本。
        """
        import tarfile
        import tempfile

        with self.lock:
            eng = self.result.get("engine") or {}
        if not eng.get("latest"):
            return {"ok": False, "error": "先检查更新"}
        tag = eng["latest"]
        base = f"https://github.com/{ENGINE_REPO}/releases/download/v{tag}"
        url = f"{base}/tensorfold-{tag}-macos-arm64.tar.gz"
        sha_url = url + ".sha256"

        def _fetch(u: str) -> bytes:
            req = urllib.request.Request(u, headers={"User-Agent": "TensorFold-Manager"})
            with _opener().open(req, timeout=180) as resp:
                return resp.read()

        # 下载（带一次重试）
        data, sha_text = b"", ""
        for attempt in (1, 2):
            try:
                data = _fetch(url)
                try: sha_text = _fetch(sha_url).decode("utf-8", errors="replace")
                except Exception: sha_text = ""   # 无校验文件不阻断（如实标注）
                break
            except Exception as exc:
                log(f"下载引擎二进制 第{attempt}次失败: {exc}")
                if attempt == 2:
                    return {"ok": False, "error": f"下载失败: {exc}"}
                time.sleep(2)
        log(f"已下载引擎包 {len(data)//1024}KB")

        # SHA256 校验
        import hashlib
        actual = hashlib.sha256(data).hexdigest()
        expect = sha_text.split()[0].strip().lower() if sha_text else ""
        sha_ok = bool(expect) and expect == actual
        if sha_text and not sha_ok:
            return {"ok": False, "error": f"SHA256 不符: 期望 {expect[:16]}… 实得 {actual[:16]}…"}
        log(f"SHA256 {'校验通过' if sha_ok else '未提供校验文件，跳过'}: {actual[:16]}…")

        # 解压到 engines/<tag>/（临时目录再原子改名，避免半成品被选走）
        import glob as _glob
        root = os.path.expanduser("~/.tensorfold-manager/engines")
        dest_parent = os.path.join(root, f"v{tag}")
        if _glob.glob(os.path.join(dest_parent, "bin", "tensorfold-native")):
            log(f"引擎 v{tag} 已存在，直接标记使用")
        else:
            os.makedirs(root, exist_ok=True)
            tmpd = tempfile.mkdtemp(prefix=f".engine-{tag}-", dir=root)
            tarpath = os.path.join(tmpd, "pkg.tar.gz")
            with open(tarpath, "wb") as f:
                f.write(data)
            try:
                with tarfile.open(tarpath, "r:gz") as tf:
                    tf.extractall(tmpd)  # noqa: S202 - 官方来源 + SHA 校验后解包
                member = [d for d in os.listdir(tmpd)
                          if os.path.isdir(os.path.join(tmpd, d)) and d != "pkg.tar.gz"]
                if len(member) != 1:
                    raise RuntimeError(f"包结构异常: {member}")
                src = os.path.join(tmpd, member[0])
                binp = os.path.join(src, "bin", "tensorfold-native")
                if not (os.path.exists(binp) and os.access(binp, os.X_OK)):
                    raise RuntimeError("包内缺 bin/tensorfold-native 或无执行权限")
                # 版本自证
                r = subprocess.run([binp, "--version"], capture_output=True,
                                   text=True, timeout=15, env=_env_no_proxy(),
                                   close_fds=False)  # posix_spawn；fork 会死锁
                ver_out = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
                if f" {tag}" not in ver_out:
                    raise RuntimeError(f"二进制自报版本不符: {ver_out!r} 期望 {tag}")
                if os.path.exists(dest_parent):
                    import shutil as _sh
                    _sh.rmtree(dest_parent, ignore_errors=True)
                os.rename(src, dest_parent)   # 同分区 rename，原子
            except Exception as exc:
                return {"ok": False, "error": f"安装失败: {exc}"}
            finally:
                import shutil as _sh2
                _sh2.rmtree(tmpd, ignore_errors=True)
        self.engine_version = tag
        return {"ok": True, "version": tag, "path": os.path.join(dest_parent, "bin", "tensorfold-native"),
                "sha_verified": sha_ok}


def apply_app_open(url: str) -> dict:
    """App 一键 = 打开最新 Release 下载页（不做应用内自替换）。"""
    if not url:
        return {"ok": False, "error": "没有可打开的地址"}
    try:
        subprocess.run(["open", url], check=False, timeout=10, close_fds=False)  # posix_spawn
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
