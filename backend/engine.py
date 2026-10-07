"""TensorFold 引擎子进程管理：多实例池 + 启动/停止/探活 + 每模型参数持久化。

v2 语义（老板补充"可以允许多个模型同时运行"）：
  - 每个模型一个独立子进程 = 独立端口 + 独立日志泵 + 独立状态机（EngineInstance）。
  - EnginePool 负责端口分配、内存闸门、每模型设置持久化、启停路由。
启动器 python_bin 两种取值：
  a) tensorfold CLI 可执行脚本  → argv = [cli, "serve", model, ...]
  b) 内嵌 Python 解释器        → argv = [python, "-m", "tensorfold", "serve", model, ...]
单实例状态机: idle -> starting (进程活着但 /health 还没 200) -> ready -> idle
              starting/ready 期间进程退出 -> error
"""
from __future__ import annotations

import glob
import json
import os
import selectors
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

LOG_CAP = 800  # 内存里保留的日志行数
DEFAULT_BASE_PORT = 8080
SETTINGS_DIR = os.path.expanduser("~/.tensorfold-manager")

_OPENER = None

# 已知受支持的模型族（来源：TensorFold 包内 families 反查，2026-10 实测修正）
FAMILIES = [
    {"name": "Nemotron 3.5 Lightning 30B", "id": "TensorFold/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-MLX-4bit", "size_gb": 17, "note": "内置 MTP 草稿头"},
    {"name": "Qwen3.8-27B (4bit)", "id": "TensorFold/Qwen3.8-27B-MLX-4bit", "size_gb": 15, "note": "可配 DFlash2 草稿模型"},
    {"name": "Qwen3.8 Flash Next", "id": "TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP", "size_gb": 15, "note": "内置 MTP 头"},
    {"name": "GLM-5.3-Flash", "id": "TensorFold/GLM-5.3-Flash-MLX-4bit-MTP", "size_gb": 20, "note": "256GB Mac 可跑；可配 --vision"},
    {"name": "Qwen3.6-35B-A3B", "id": "TensorFold/Qwen3.6-35B-A3B-MLX-4bit-MTP", "size_gb": 20, "note": "内置 MTP 头"},
    {"name": "DeepSeek-V4-Flash DSpark", "id": "TensorFold/DeepSeek-V4-Flash-DSpark-MLX", "size_gb": 40, "note": "256GB Mac 可跑"},
]

# 每模型默认参数（与 serve --help 实测字段对齐；None = 不传该旗标，用引擎默认）
DEFAULT_PARAMS = {
    "port": None,          # None = 池自动分配
    "context": 32768,
    "max_tokens": 4096,
    "temperature": None,
    "top_p": None,
    "top_k": None,
    "thinking": False,
    "reasoning_effort": None,
    "drafts": True,
    "mtp_drafts": None,
    "mtp_confidence": None,
    "kv_dtype": None,
    "prompt_cache_gib": None,
    "parallel": None,
    "backend": None,
    "vision": False,
    "alias": "",
}


def find_launcher(project_dir: str) -> str:
    """找能把 `tensorfold serve` 跑起来的启动器，返回路径或 ""。

    - 打包布局（优先）: <dir>/runtime/bin/python3 = 自包含运行时
      （site-packages 里有 tensorfold 即命中，用 `-m tensorfold` 模块式调用，路径无关）。
    - 开发机: 隔离 venv ~/.workbuddy/binaries/python/envs/default 的 tensorfold CLI。
    """
    dirs = [project_dir, os.path.dirname(project_dir), os.path.expanduser("~/.workbuddy/binaries/python/envs/default")]
    for d in dirs:
        py = os.path.join(d, "runtime", "bin", "python3")
        if os.path.exists(py) and glob.glob(
                os.path.join(d, "runtime", "lib", "python*", "site-packages", "tensorfold")):
            return py
    dev = os.path.expanduser("~/.workbuddy/binaries/python/envs/default")
    if glob.glob(os.path.join(dev, "lib/python*/site-packages/tensorfold")):
        cli = os.path.join(dev, "bin", "tensorfold")
        if os.path.exists(cli):
            return cli
    return ""


def is_interpreter(path: str) -> bool:
    return os.path.basename(path) in ("python", "python3")


def hf_cache_dir() -> str:
    return os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface/hub")


def _repo_dir_name(repo_id: str) -> str:
    return "models--" + repo_id.replace("/", "--")


def cached_models() -> list[dict]:
    """扫描 HF 缓存，返回已下载的模型（含大小）。"""
    out = []
    base = hf_cache_dir()
    if not os.path.isdir(base):
        return out
    for path in sorted(glob.glob(os.path.join(base, "models--*"))):
        if not os.path.isdir(path):
            continue
        name = os.path.basename(path)[len("models--"):].replace("--", "/")
        snaps = glob.glob(os.path.join(path, "snapshots", "*"))
        size = 0
        for snap in snaps:
            for root, _dirs, files in os.walk(snap):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        size += os.path.getsize(os.path.realpath(fp))
                    except OSError:
                        pass
        if size > 50 * 1024 * 1024:  # <50MB 的多半是 tokenizer/config，不算模型
            out.append({"id": name, "size_gb": round(size / 1024**3, 2)})
    return out


def build_serve_args(model: str, params: dict, port: int) -> list[str]:
    """把模型参数表编译成 `serve` 旗标列表（纯函数，便于测试）。"""
    extra = ["--host", "127.0.0.1", "--port", str(port),
             "--context", str(params.get("context") or 32768),
             "--max-tokens", str(params.get("max_tokens") or 4096)]
    if params.get("temperature") is not None:
        extra += ["--temperature", str(params["temperature"])]
    if params.get("top_p") is not None:
        extra += ["--top-p", str(params["top_p"])]
    if params.get("top_k") is not None:
        extra += ["--top-k", str(params["top_k"])]
    if not params.get("thinking"):
        extra.append("--no-thinking")
    if params.get("reasoning_effort"):
        extra += ["--reasoning-effort", str(params["reasoning_effort"])]
    if not params.get("drafts", True):
        extra.append("--no-drafts")
    if params.get("mtp_drafts") is not None:
        extra += ["--mtp-drafts", str(params["mtp_drafts"])]
    if params.get("mtp_confidence") is not None:
        extra += ["--mtp-confidence", str(params["mtp_confidence"])]
    if params.get("kv_dtype"):
        extra += ["--kv-dtype", str(params["kv_dtype"])]
    if params.get("prompt_cache_gib") is not None:
        extra += ["--prompt-cache-gib", str(params["prompt_cache_gib"])]
    if params.get("parallel") is not None:
        extra += ["--parallel", str(params["parallel"])]
    if params.get("backend"):
        extra += ["--backend", str(params["backend"])]
    if params.get("vision"):
        extra.append("--vision")
    alias = params.get("alias") or ""
    if alias:
        extra += ["--name", alias]
    return extra


def serve_argv(python_bin: str, model: str, params: dict, port: int) -> list[str]:
    args = build_serve_args(model, params, port)
    if os.path.basename(python_bin) in ("python", "python3"):
        return [python_bin, "-m", "tensorfold", "serve", model] + args
    return [python_bin, "serve", model] + args


class ModelSettings:
    """每模型参数持久化：~/.tensorfold-manager/model_settings.json。"""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(SETTINGS_DIR, "model_settings.json")
        self._lock = threading.Lock()
        self._cache: dict | None = None

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self._cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._cache = {}
        return self._cache

    def _save(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def load_for(self, model: str) -> dict:
        """读取某模型的有效参数（默认值 + 已保存值合并）。"""
        with self._lock:
            merged = dict(DEFAULT_PARAMS)
            merged.update(self._load().get(model, {}))
            return merged

    def raw_for(self, model: str) -> dict:
        """仅已显式保存过的键（区分「用户存过」与「DEFAULT 占位」，全局兜底判断用）。"""
        with self._lock:
            return dict(self._load().get(model, {}))

    def save_for(self, model: str, params: dict):
        with self._lock:
            data = self._load()
            cur = data.get(model, {})
            cur.update({k: v for k, v in params.items() if k in DEFAULT_PARAMS})
            data[model] = cur
            self._save(data)

    def delete_for(self, model: str):
        with self._lock:
            data = self._load()
            if data.pop(model, None) is not None:
                self._save(data)

    def all(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._load().items()}


class EngineInstance:
    """单个模型 = 一个引擎子进程。一个实例一套状态机/日志泵。"""

    def __init__(self, model: str, port: int, python_bin: str,
                 log_sink=None, spawn_hook=None):
        self.model = model
        self.port = port
        self.python_bin = python_bin
        self.log_sink = log_sink  # 池汇总日志回调 fn(line)
        self.spawn_hook = spawn_hook  # 测试注入: fn(argv, env) -> Popen-like
        self._lock = threading.RLock()
        self._log: list[str] = []
        self._sel = None
        self.state = "idle"  # idle|starting|ready|error
        self.error = ""
        self.process: subprocess.Popen | None = None
        self.name = ""
        self.started_at: float | None = None
        self.params: dict = dict(DEFAULT_PARAMS)

    @property
    def host(self):
        return "127.0.0.1"

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ---------- 日志 ----------
    def log(self, line: str):
        with self._lock:
            stamp = time.strftime("%H:%M:%S")
            self._log.append(f"[{stamp}] {line}")
            if len(self._log) > LOG_CAP:
                del self._log[: len(self._log) - LOG_CAP]
        if self.log_sink:
            try:
                self.log_sink(line)
            except Exception:
                pass

    def get_log(self) -> list[str]:
        with self._lock:
            return list(self._log[-400:])

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "alive": self.alive(),
                "model": self.model,
                "name": self.name or self.model.split("/")[-1],
                "url": self.base_url(),
                "port": self.port,
                "drafts": self.params.get("drafts", True),
                "vision": self.params.get("vision", False),
                "params": dict(self.params),
                "error": self.error,
                "uptime": (time.time() - self.started_at) if (self.state == "ready" and self.started_at) else 0,
            }

    # ---------- 启停 ----------
    def start(self, params: dict) -> dict:
        with self._lock:
            if self.alive():
                return self._err("该模型引擎已在运行")
            if not (self.python_bin and os.path.exists(self.python_bin)):
                return self._err("未找到 tensorfold CLI，请检查安装")
            self.params = {**DEFAULT_PARAMS, **params, "port": self.port}
            argv = serve_argv(self.python_bin, self.model, self.params, self.port)
            self.log(f"启动: {' '.join(argv)}")
            try:
                # 清掉 PAC/代理环境：本地 127.0.0.1 流量绝不外绕，
                # 否则 HF 下载/健康探活会被系统代理劫持（实测会被 502/连接拒绝）。
                env = {k: v for k, v in os.environ.items()
                       if "PROXY" not in k.upper() and k.upper() != "NO_PROXY"}
                env.update({"NO_PROXY": "127.0.0.1,localhost,::1",
                            "no_proxy": "127.0.0.1,localhost,::1",
                            "PYTHONUNBUFFERED": "1"})
                self._start_pump(argv, env)
            except Exception as exc:
                self.state = "error"
                self.error = f"无法启动: {exc}"
                self.log(f"启动失败: {exc}")
                return {"ok": False, "error": self.error}
            self.name = self.params.get("alias") or self.model.split("/")[-1]
            self.state = "starting"
            self.error = ""
            self.started_at = None
            return {"ok": True, **self.status()}

    def _err(self, msg: str) -> dict:
        self.error = msg
        return {"ok": False, "error": self._redact(msg)}

    @staticmethod
    def _redact(s: str) -> str:
        import re
        return re.sub(r"\b(hf_|HF_)[A-Za-z0-9_-]{8,}", "[REDACTED]", s)

    def _start_pump(self, argv: list[str], env: dict[str, str]):
        if self.spawn_hook is not None:
            # 测试注入：不建管道，由 hook 自行返回进程对象
            self.process = self.spawn_hook(argv, env)
            return
        read_fd, write_fd = os.pipe()
        try:
            self.process = subprocess.Popen(
                argv, stdout=write_fd, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, close_fds=True,
                cwd=os.path.expanduser("~"),
                env={**env, "PATH": os.path.dirname(self.python_bin) + ":/usr/bin:/bin:/usr/sbin:/sbin"})
        except OSError:
            os.close(read_fd)
            os.close(write_fd)
            raise
        os.close(write_fd)  # 父进程只留读端
        self._sel = selectors.DefaultSelector()
        self._sel.register(read_fd, selectors.EVENT_READ)

        def pump():
            sel = self._sel
            assert sel is not None
            buf = b""
            while True:
                try:
                    if not sel.select(0.5):
                        if self.process is not None and self.process.poll() is not None:
                            break
                        continue
                    chunk = os.read(read_fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self.log(self._redact(line.decode("utf-8", errors="replace").rstrip()))
            if buf.strip():
                self.log(self._redact(buf.decode("utf-8", errors="replace").rstrip()))
            try:
                sel.close()
            except Exception:
                pass
            self._on_exit()

        threading.Thread(target=pump, daemon=True, name=f"tf-log-pump-{self.port}").start()

    def _on_exit(self):
        with self._lock:
            code = self.process.returncode if self.process is not None else None
            self.process = None
            self._sel = None
            self.started_at = None
            if self.state in ("starting", "ready"):
                self.state = "error"
                self.error = f"引擎进程已退出 (code={code})，见日志"
            self.log(f"引擎进程退出 (code={code})")

    def stop(self) -> dict:
        with self._lock:
            if self.process is None or self.process.poll() is not None:
                self.state = "idle"
                self.error = ""
                return {"ok": True, "state": "idle"}
            self.log("发送终止信号")
            self.process.terminate()
            proc = self.process
        try:
            proc.wait(8)
        except subprocess.TimeoutExpired:
            self.log("进程未在 8s 内退出，强制结束")
            proc.kill()
        with self._lock:
            # 手动停止一律回到 idle；只有崩溃退出才标 error
            self.state = "idle"
            self.error = ""
            self.started_at = None
            return {"ok": True, **self.status()}

    def mark_ready(self):
        with self._lock:
            if self.state == "starting":
                self.state = "ready"
                self.started_at = time.time()
                self.log("服务就绪 (health=200)")

    def health(self, timeout: float = 2.0) -> bool:
        return self._probe("/health", timeout) is not None

    def _probe(self, path: str, timeout: float = 2.0):
        try:
            with _get_opener().open(self.base_url() + path, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
        except (urllib.error.URLError, OSError):
            pass
        return None


def _get_opener():
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER


class EnginePool:
    """多实例池：每模型独立进程/端口/日志；端口从 base_port 起找空闲；内存闸门。"""

    MEM_MARGIN_GB = 10.0  # 空闲内存需 ≥ 模型估计大小 + 该余量才允许新加载

    def __init__(self, python_bin: str = "", settings: ModelSettings | None = None,
                 base_port: int = DEFAULT_BASE_PORT, spawn_hook=None):
        self.python_bin = python_bin
        self.settings = settings or ModelSettings()
        self.base_port = base_port
        self.spawn_hook = spawn_hook
        self._lock = threading.RLock()
        self._instances: dict[str, EngineInstance] = {}
        self._pool_log: list[str] = []
        self._psutil = None

    # ---------- 日志（池级汇总，仿 v1 EngineManager 接口） ----------
    def log(self, line: str):
        stamp = time.strftime("%H:%M:%S")
        self._pool_log.append(f"[{stamp}] {line}")
        if len(self._pool_log) > LOG_CAP:
            del self._pool_log[: len(self._pool_log) - LOG_CAP]

    def get_log(self) -> list[str]:
        return list(self._pool_log[-400:])

    # ---------- 基本信息 ----------
    def detect(self) -> dict:
        ver = ""
        if self.python_bin and os.path.exists(self.python_bin):
            # CLI 入口脚本直接 --version；内嵌解释器才走 -m（与 serve_argv 同一分支规则）
            if os.path.basename(self.python_bin) in ("python", "python3"):
                cmd = [self.python_bin, "-m", "tensorfold", "--version"]
            else:
                cmd = [self.python_bin, "--version"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                out = (r.stdout or r.stderr).strip()
                ver = out.splitlines()[-1] if out else ""
            except Exception:
                ver = ""
        return {"installed": bool(self.python_bin and os.path.exists(self.python_bin)),
                "path": self.python_bin, "version": ver}

    def get(self, model: str) -> EngineInstance | None:
        with self._lock:
            return self._instances.get(model)

    def instances(self) -> list[EngineInstance]:
        with self._lock:
            return list(self._instances.values())

    def ready_instances(self) -> list[EngineInstance]:
        with self._lock:
            return [i for i in self._instances.values() if i.state == "ready"]

    def resolve(self, model: str) -> EngineInstance | None:
        """按模型 id 或别名找实例（聊天路由用）。"""
        with self._lock:
            inst = self._instances.get(model)
            if inst is not None:
                return inst
            for i in self._instances.values():
                if i.name == model:
                    return i
            return None

    # ---------- 端口 ----------
    def _alloc_port(self) -> int:
        with self._lock:
            used = {i.port for i in self._instances.values() if i.alive() or i.state == "starting"}
        port = self.base_port
        while port < self.base_port + 100:
            if port not in used and _port_free(port):
                return port
            port += 1
        raise RuntimeError("端口分配失败（8080-8179 均被占用）")

    # ---------- 内存闸门 ----------
    def _estimate_gb(self, model: str) -> float:
        for f in FAMILIES:
            if f["id"] == model and f.get("size_gb"):
                return float(f["size_gb"]) * 1.3  # 权重 + KV/运行开销
        for m in cached_models():
            if m["id"] == model:
                return m["size_gb"] * 1.3
        return 20.0  # 未知模型保守估 20G

    def mem_available(self) -> float:
        if self._psutil is None:
            try:
                import psutil
                self._psutil = psutil
            except ImportError:
                return 999.0
        try:
            return round(self._psutil.virtual_memory().available / 1024**3, 1)
        except Exception:
            return 999.0

    # ---------- 启停 ----------
    def start(self, model: str, **overrides) -> dict:
        model = (model or "").strip()
        if not model:
            return {"ok": False, "error": "请选择模型"}
        with self._lock:
            inst = self._instances.get(model)
            if inst is not None and inst.alive():
                return {"ok": False, "error": f"{model} 已在运行（端口 {inst.port}）"}
        avail = self.mem_available()
        need = self._estimate_gb(model)
        if avail < need + self.MEM_MARGIN_GB:
            return {"ok": False, "error":
                    f"空闲内存不足：需约 {need:.0f}G（含 {self.MEM_MARGIN_GB:.0f}G 余量），当前仅 {avail:.0f}G。"
                    f"先停掉其它模型再加载。"}
        params = self.settings.load_for(model)
        params.update({k: v for k, v in overrides.items() if k in DEFAULT_PARAMS and v is not None})
        if params.get("port"):  # 用户显式指定端口 → 校验空闲
            if not _port_free(int(params["port"])):
                return {"ok": False, "error": f"端口 {params['port']} 已被占用"}
            port = int(params["port"])
        else:
            try:
                port = self._alloc_port()
            except RuntimeError as exc:
                return {"ok": False, "error": str(exc)}
        inst = EngineInstance(model, port, self.python_bin,
                             log_sink=lambda line: self.log(f"[{model.split('/')[-1]}] {line}"),
                             spawn_hook=self.spawn_hook)
        r = inst.start(params)
        if not r.get("ok"):
            return r
        with self._lock:
            self._instances[model] = inst
        self.settings.save_for(model, {k: v for k, v in params.items() if k != "port"})
        return r

    def stop(self, model: str | None = None) -> dict:
        """model=None 停止全部。"""
        with self._lock:
            if model is not None:
                inst = self._instances.get(model)
                if inst is None:
                    return {"ok": False, "error": f"{model} 没有运行中的实例"}
                targets = [inst]
            else:
                targets = list(self._instances.values())
        for inst in targets:
            inst.stop()
        return {"ok": True, "stopped": [i.model for i in targets]}

    def health_tick(self):
        """主循环每秒调：starting→ready 探活升级；ready 连续失败标 error。"""
        for inst in self.instances():
            if inst.state == "starting":
                if inst.health(timeout=1.0):
                    inst.mark_ready()
            elif inst.state == "ready":
                if inst.health(timeout=1.0):
                    inst._miss = 0
                else:
                    inst._miss = getattr(inst, "_miss", 0) + 1
                    if inst._miss >= 3:
                        inst.state = "error"
                        inst.error = "健康探活连续 3 次失败，引擎疑似退出"

    def status_all(self) -> dict:
        return {"instances": [i.status() for i in self.instances()]}

    def log_for(self, model: str) -> list[str]:
        inst = self.get(model)
        return inst.get_log() if inst else []

    # ---------- 模型删除 ----------
    def delete_model(self, repo_id: str) -> dict:
        with self._lock:
            inst = self._instances.get(repo_id)
            if inst is not None and inst.alive():
                return {"ok": False, "error": "该模型正在提供服务，先停止引擎再删除"}
        base = hf_cache_dir()
        target = os.path.join(base, _repo_dir_name(repo_id))
        real = os.path.realpath(base)
        if not os.path.isdir(base) or not real.startswith(os.path.expanduser("~")):
            return {"ok": False, "error": "缓存目录异常，拒绝操作"}
        if not os.path.isdir(target):
            return {"ok": False, "error": f"缓存中不存在 {repo_id}"}
        shutil.rmtree(target)
        self.log(f"已删除缓存: {repo_id}")
        self.settings.delete_for(repo_id)
        return {"ok": True}


def _port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


# 兼容 v1 引用（main/api 重构完后可移除）
EngineManager = EnginePool
