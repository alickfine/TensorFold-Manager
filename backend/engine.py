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
import re
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
MIGRATION_KEY = "_schema"       # settings 文件里的内部键（非模型名）
MIGRATION_VER = 2               # 2 = 已清理旧版硬编码 context/max_tokens 默认值

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

# 每模型默认参数（与 serve --help 实测字段对齐；None = 不传该旗标，用引擎/模型默认）
# 2026-10-09：context/max_tokens 默认改为 None —— 老板要求"初始设置 = 模型默认配置"，
# 不传旗标时引擎按模型 config 的 max_position_embeddings 自决（实测 27B = 262144），
# 而不是被写死的 32768 覆盖。UI 弹窗会把模型默认值填出来供用户改。
DEFAULT_PARAMS = {
    "port": None,          # None = 池自动分配
    "context": None,
    "max_tokens": None,
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


def native_launchers() -> list[str]:
    """枚举原生引擎（v1.0+ 官方二进制），版本号语义降序；升级后新版本自动排前。"""
    root = os.path.expanduser("~/.tensorfold-manager/engines")
    if not os.path.isdir(root):
        return []
    cands = []
    for d in glob.glob(os.path.join(root, "v*", "bin", "tensorfold-native")):
        ver = d.split(os.sep)[-3].lstrip("v")
        key = tuple(int(x) for x in re.findall(r"\d+", ver)) if re.findall(r"\d+", ver) else (0,)
        cands.append((key, d))
    return [p for _k, p in sorted(cands, reverse=True)]


def find_launcher(project_dir: str) -> str:
    """找能把 `tensorfold serve` 跑起来的启动器，返回首选路径或 ""。

    优先级（2026-10-08 起）：
      1. 原生引擎目录 ~/.tensorfold-manager/engines/v*/bin/tensorfold-native
         （版本号最高者优先；升级后自动生效的关键）。
      2. 打包布局: <dir>/runtime/bin/python3 = 自包含运行时
         （site-packages 里有 tensorfold 即命中，用 `-m tensorfold` 模块式调用）。
      3. 开发机: 隔离 venv 的 tensorfold CLI。

    注意：native 引擎只覆盖部分模型族/尺寸（实测 v1.0.2 的 qwen3_5 族
    拒绝 27B checkpoint，`UnsupportedQwenConfig`），所以首选 ≠ 万能。
    EngineInstance.start 会按 launcher_candidates() 顺序在秒退时自动降级，
    本函数只决定"首选是谁"，兼容性兜底在启动层。
    """
    native = native_launchers()
    if native:
        return native[0]
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


def launcher_candidates(preferred: str) -> list[str]:
    """启动降级用完整候选链：native 各版本（新→旧）+ 解释器形态。

    与 find_launcher 同源，但返回全部可用启动器；解释器去重后垫底。
    project_dir 取本模块位置的上两级（backend/engine.py → app 根），
    打包布局下 runtime 与 app 同在 Contents/Resources/ 下。
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(p: str):
        if p and os.path.exists(p) and p not in seen:
            out.append(p)
            seen.add(p)

    for p in native_launchers():
        _add(p)
    # 解释器形态：打包 runtime。源码直跑时 runtime 在仓库根（here），
    # .app 里 runtime 与 app 同级（dir(here)=Contents/Resources），两个位置都要看，
    # 否则打包版只剩 native 一个候选，native 拒装某模型时无兜底 → 模型完全起不来。
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for root in (here, os.path.dirname(here)):
        py = os.path.join(root, "runtime", "bin", "python3")
        if (os.path.exists(py) and is_interpreter(py)
                and glob.glob(os.path.join(root, "runtime", "lib", "python*",
                                           "site-packages", "tensorfold"))):
            _add(py)
    # 开发机 venv CLI
    dev = os.path.expanduser("~/.workbuddy/binaries/python/envs/default")
    if glob.glob(os.path.join(dev, "lib/python*/site-packages/tensorfold")):
        _add(os.path.join(dev, "bin", "tensorfold"))
    return out


def is_interpreter(path: str) -> bool:
    return os.path.basename(path) in ("python", "python3")


def hf_cache_dir() -> str:
    return os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface/hub")


def _repo_dir_name(repo_id: str) -> str:
    return "models--" + repo_id.replace("/", "--")


# ---------- 模型扫描根目录（2026-10-08：除 HF 缓存外增加 oMLX/MTPLX/LM Studio 与自定义目录） ----------
# 背景：oMLX 的模型在 ~/.omlx/models/<名称>/（不是 HF 缓存），MTPLX 在 ~/.mtplx/models/，
# LM Studio 的 MLX 模型在 ~/.lmstudio/models/<owner>/<名称>/。以前只扫 HF 缓存，
# 所以这些目录里的模型在本 App 里完全看不见（老板 2026-10-08 反馈）。
BUILTIN_MODEL_ROOTS = [
    {"label": "oMLX", "path": "~/.omlx/models"},
    {"label": "MTPLX", "path": "~/.mtplx/models"},
    {"label": "LM Studio", "path": "~/.lmstudio/models"},
]

MIN_MODEL_BYTES = 50 * 1024 * 1024   # <50MB 的多半只是 tokenizer/config，不算模型


def model_roots(extra_dirs: list | None = None) -> list[dict]:
    """扫描根：HF 缓存 + 内置第三方目录 + 用户自定义目录（按 realpath 去重保序）。"""
    roots = [{"label": "Hugging Face 缓存", "path": hf_cache_dir(), "kind": "hf",
              "custom": False}]
    for r in BUILTIN_MODEL_ROOTS:
        roots.append({"label": r["label"], "path": os.path.expanduser(r["path"]),
                      "kind": "auto", "custom": False})
    seen = {os.path.realpath(r["path"]) for r in roots}
    for p in (extra_dirs or []):
        p = os.path.expanduser(str(p or "").strip())
        if not p:
            continue
        key = os.path.realpath(p)
        if key in seen:
            continue
        seen.add(key)
        roots.append({"label": "自定义", "path": p, "kind": "auto", "custom": True})
    return roots


def _dir_bytes(path: str) -> int:
    size = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                size += os.path.getsize(os.path.realpath(os.path.join(root, f)))
            except OSError:
                pass
    return size


def _hf_entries(root: str) -> list[dict]:
    """HF 缓存形态：<root>/models--<owner>--<name>/snapshots/<rev>/..."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, "models--*"))):
        if not os.path.isdir(path):
            continue
        repo = os.path.basename(path)[len("models--"):].replace("--", "/")
        size = 0
        for snap in glob.glob(os.path.join(path, "snapshots", "*")):
            size += _dir_bytes(snap)
        if size > MIN_MODEL_BYTES:
            out.append({"id": repo, "ref": repo, "path": path, "source": "hf",
                        "size_gb": round(size / 1024 ** 3, 2), "deletable": True})
    return out


def _local_entries(root: str, label: str) -> list[dict]:
    """本地目录形态：<root>/<名称>/ 或 <root>/<owner>/<名称>/（含 config.json 才算模型）。

    本地模型交给引擎时传绝对路径：tensorfold（原生与解释器两形态）都接受目录路径，
    省掉"必须先拷进 HF 缓存"这一步，也避免动用户原有的模型目录。
    """
    out = []
    if not os.path.isdir(root):
        return out
    for child in sorted(glob.glob(os.path.join(root, "*"))):
        base = os.path.basename(child)
        if not os.path.isdir(child) or base.startswith("."):
            continue
        if os.path.exists(os.path.join(child, "config.json")):
            cands = [(base, child)]
        else:   # 再下一层 owner/name 形态
            cands = [(f"{base}/{os.path.basename(g)}", g)
                     for g in sorted(glob.glob(os.path.join(child, "*")))
                     if os.path.isdir(g) and os.path.exists(os.path.join(g, "config.json"))]
        for name, p in cands:
            size = _dir_bytes(p)
            if size <= MIN_MODEL_BYTES:
                continue
            out.append({"id": name, "ref": p, "path": p, "source": label,
                        "size_gb": round(size / 1024 ** 3, 2), "deletable": False})
    return out


def _entries_of(root: dict) -> list[dict]:
    if root["kind"] == "hf":
        return _hf_entries(root["path"])
    # 第三方目录里也可能有 HF 缓存形态（如 omlx 拷过 HF 缓存），两种都扫
    return _hf_entries(root["path"]) + _local_entries(root["path"], root["label"])


def cached_models(extra_dirs: list | None = None) -> list[dict]:
    """扫描所有根目录，返回可见模型（含来源、大小、可否删除）。

    id  = 显示名（HF 用 owner/name，本地目录用目录名）
    ref = 传给引擎的引用（HF 用 repo id；本地目录用绝对路径）
    """
    out, seen = [], set()
    for r in model_roots(extra_dirs):
        for e in _entries_of(r):
            key = os.path.realpath(e["path"])
            if key in seen:      # 同一份权重被多个根指向（软链/重复拷贝）只列一次
                continue
            seen.add(key)
            e["root"] = r["path"]
            e["root_label"] = r["label"]
            # 辅助（草稿）模型打标：UI 据此写「辅助模型 · 供 X 使用」并联到主模型，
            # 而不是给一个会把它当主模型加载的「开启」按钮。
            used_by = DRAFT_OF.get(e["id"]) or DRAFT_OF.get(e["ref"]) or []
            e["role"] = "draft" if used_by else "model"
            e["used_by"] = list(used_by)
            out.append(e)
    return out


def scan_summary(extra_dirs: list | None = None) -> list[dict]:
    """给 UI 用：每个扫描根是否存在、命中几个模型。"""
    return [{"label": r["label"], "path": r["path"], "custom": r["custom"],
             "exists": os.path.isdir(r["path"]), "count": len(_entries_of(r))}
            for r in model_roots(extra_dirs)]


# ---------- 模型元信息（设置弹窗默认值 / 能力 / 加速配套检查） ----------
# 2026-10-09 老板要求：初始设置取模型自身默认配置（含输入输出上限）、模型属性可控
# （是否支持图像等）、模型 id 展示不带提供者、加速配套模型要有检查。
# 事实来源 = 模型目录里的 config.json（HF 缓存与本地目录两形态都能定位）。
ACCEL_DRAFTS = {
    # 主模型 → 可配的外部草稿（推测解码）模型。来源：引擎启动日志
    # "no draft model: `tensorfold pull z-lab/Qwen3.8-27B-DFlash2` once to draft with it"。
    "TensorFold/Qwen3.8-27B-MLX-4bit": "z-lab/Qwen3.8-27B-DFlash2",
}


def _draft_reverse() -> dict[str, list[str]]:
    """草稿模型 → 用到它的主模型列表（ACCEL_DRAFTS 的反查）。"""
    out: dict[str, list[str]] = {}
    for main, draft in ACCEL_DRAFTS.items():
        out.setdefault(draft, []).append(main)
    return out


# 2026-10-09：UI 靠它把「本机缓存」里的辅助模型跟主模型联起来 —— 辅助模型不是能单独
# 开启的模型，卡片上要写「供 X 使用」并联到主模型的设置，而不是给一个「开启」按钮。
DRAFT_OF = _draft_reverse()


def _model_config_path(ref: str) -> str:
    """定位模型 config.json：ref 是 HF repo id 或本地目录绝对路径。"""
    if os.path.isabs(ref) or ref.startswith("~"):
        p = os.path.expanduser(ref)
        return os.path.join(p, "config.json") if os.path.isdir(p) else ""
    base = hf_cache_dir()
    snaps = sorted(glob.glob(os.path.join(base, _repo_dir_name(ref), "snapshots", "*")))
    for snap in reversed(snaps):   # 多 revision 时用最新的
        cfg = os.path.join(snap, "config.json")
        if os.path.exists(cfg):
            return cfg
    return ""


def _is_cached(repo: str) -> bool:
    d = os.path.join(hf_cache_dir(), _repo_dir_name(repo))
    if not os.path.isdir(d):
        return False
    return bool(glob.glob(os.path.join(d, "snapshots", "*")))


def draft_cached_size_gb(repo: str) -> float:
    """该 repo 在 HF 缓存里的 snapshots 体积（GB，跟随软链）；没缓存返 0。"""
    d = os.path.join(hf_cache_dir(), _repo_dir_name(repo))
    if not os.path.isdir(d):
        return 0.0
    total = 0
    for snap in glob.glob(os.path.join(d, "snapshots", "*")):
        total += _dir_bytes(snap)
    return round(total / 1024 ** 3, 2)


def draft_status(ref: str) -> dict:
    """主模型 ref → 它的外部草稿模型配套；没有配套返空 dict。

    模型页卡片（families 接口）与设置弹窗（model_meta）共用同一份口径，
    避免两处各写一遍"有没有下载"。
    """
    repo = ACCEL_DRAFTS.get(ref)
    if not repo:
        return {}
    return {
        "draft_repo": repo,
        "draft_cached": _is_cached(repo),
        "draft_size_gb": draft_cached_size_gb(repo),
        "draft_used_by": list(DRAFT_OF.get(repo, [])),
    }


def model_meta(ref: str) -> dict:
    """读模型 config.json，给出默认配置、能力与加速配套状态。

    返回键：
      defaults      模型自身默认（context=输入上限、max_tokens 建议、采样参数），UI 用它填初值
      capabilities  能力探测：vision（视觉输入）/thinking（推理模式）/mtp（内置多 token 头）
      accel         加速配套：内置 MTP 头 + 外部草稿模型是否已下载
      display       id（去 provider 的展示名）与 provider
    """
    ref = (ref or "").strip()
    cfg_path = _model_config_path(ref)
    cfg: dict = {}
    if cfg_path:
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    tc = cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else {}
    gc = cfg.get("generation_config") if isinstance(cfg.get("generation_config"), dict) else {}

    def _pick(key, fallback=None):
        if key in tc:
            return tc[key]
        if key in cfg:
            return cfg[key]
        return fallback

    ctx_max = _pick("max_position_embeddings") or None
    vocab = _pick("vocab_size") or None
    mtp_layers = _pick("mtp_num_hidden_layers") or 0
    has_vision = bool(cfg.get("vision_config")) or cfg.get("image_token_id") is not None
    # 默认采样：模型 generation_config 优先，其次顶层字段（同一份配置两种写法）
    defaults = {
        "context": ctx_max,                       # 输入上限 = 模型位置编码上限
        "max_tokens": None,                       # 输出上限由引擎默认（config 通常不写）
        "temperature": gc.get("temperature", cfg.get("temperature")),
        "top_p": gc.get("top_p", cfg.get("top_p")),
        "top_k": gc.get("top_k", cfg.get("top_k")),
    }
    # 加速配套：内置 MTP 头（config 声明） + 外部草稿模型（是否已下载）
    accel = {
        "builtin_mtp": bool(mtp_layers),
        "mtp_layers": int(mtp_layers or 0),
        "draft_repo": "",
        "draft_cached": False,
        "draft_size_gb": 0.0,
        **draft_status(ref),
    }
    display = ref.split("/")[-1] if "/" in ref else os.path.basename(ref)
    provider = ref.rsplit("/", 1)[0] if "/" in ref else ""
    return {
        "ref": ref,
        "found": bool(cfg),
        "config_path": cfg_path,
        "context_max": ctx_max,
        "vocab_size": vocab,
        "model_type": cfg.get("model_type") or tc.get("model_type") or "",
        "architectures": cfg.get("architectures") or [],
        "defaults": defaults,
        "capabilities": {
            "vision": has_vision,
            "thinking": True,          # 引擎对 Qwen 系默认开启思考（可用 --no-thinking 关）
            "mtp": bool(mtp_layers),
        },
        "accel": accel,
        "display": display,
        "provider": provider,
    }


def build_serve_args(model: str, params: dict, port: int) -> list[str]:
    """把模型参数表编译成 `serve` 旗标列表（纯函数，便于测试）。

    context/max_tokens 为 None 时不传该旗标 —— 引擎按模型 config 的自身上限自决，
    这是"初始设置 = 模型默认配置"的落地（UI 填出的默认值若被用户改动才会显式传）。
    """
    extra = ["--host", "127.0.0.1", "--port", str(port)]
    if params.get("context") is not None:
        extra += ["--context", str(params["context"])]
    if params.get("max_tokens") is not None:
        extra += ["--max-tokens", str(params["max_tokens"])]
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


def serve_argv(python_bin: str, model: str, params: dict, port: int,
               dropped: list[str] | None = None) -> list[str]:
    """编译启动命令行。python_bin 两形态：

    - 解释器（runtime/venv python）→ `-m tensorfold serve`，旗标全量可用；
    - 原生二进制（tensorfold-native, v1.0+）→ 直接 `serve`，只透传它认得的旗标，
      其余（mtp_drafts / mtp_confidence / kv_dtype / vision）**直接丢弃**并把名字
      记进 dropped（调用方写日志），绝不让引擎因参数拒绝启动。

    ⚠️ 不要把丢掉的参数塞进 `--speed-up`：上游 1.0.x 的 `--speed-up` 是
    「双 Mac 分布式 rank/link 设置的**文件路径**」（见上游 README 旗标表），
    塞 JSON 会让引擎当成文件去打不开 → 秒退，正是"升级后模型起不来"的成因之一。
    这些参数在原生引擎里没有等价旗标，只能忽略（MTP 由引擎自决，kv_dtype 由引擎自选）。
    """
    args = build_serve_args(model, params, port)
    if is_interpreter(python_bin):
        return [python_bin, "-m", "tensorfold", "serve", model] + args
    # 原生二进制：过滤其不支持的旗标
    native_known = {"--host", "--port", "--name", "--alias", "--api-key", "--api-key-file",
                    "--metrics-open", "--dashboard", "--context", "--max-tokens",
                    "--temperature", "--top-p", "--top-k", "--min-p", "--thinking",
                    "--no-thinking", "--reasoning-effort", "--thinking-budget", "--loop-guard",
                    "--no-drafts", "--keep-warm", "--prompt-cache-gib", "--prompt-cache-over-cap",
                    "--parallel", "--backend"}
    argv = [python_bin, "serve", model]
    i = 0
    while i < len(args):
        flag = args[i]
        if flag.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
            val = args[i + 1]
        else:
            val = None
        if flag in native_known:
            argv += [flag] + ([val] if val is not None else [])
        elif dropped is not None:
            dropped.append(flag)
        i += 2 if val is not None else 1
    return argv


class ModelSettings:
    """每模型参数持久化：~/.tensorfold-manager/model_settings.json。"""

    # 旧版（≤2.1.2）保存路径无条件写入整份 DEFAULT_PARAMS，其中 context=32768 /
    # max_tokens=4096 是写死的默认值，于是"从没改过这两个字段"的模型在磁盘上也像
    # 用户显式选过 —— 会让新规则"初始设置 = 模型自身默认配置"看起来没生效
    # （实测 UI 仍显示 32768，而模型 config 是 262144）。
    # 一次性迁移：**逐键**判断，只要该键的值恰好等于旧硬编码默认就视为未设置并抹掉。
    # 逐键而非整条：旧版用户常常只改了其中一项（例如只把 max_tokens 调到 8192），
    # 若按"两项都等于旧默认才清理"就会漏掉另一项，UI 依旧显示 32768。
    # 用 _schema 标记防止重复执行（否则用户在新版显式保存 32768 会被下次加载再度抹掉）。
    LEGACY_DEFAULTS = {"context": 32768, "max_tokens": 4096}

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(SETTINGS_DIR, "model_settings.json")
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self.log_migration = False

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self._cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._cache = {}
        self._migrate_legacy_defaults()
        return self._cache

    def _migrate_legacy_defaults(self):
        data = self._cache or {}
        if data.get(MIGRATION_KEY) == MIGRATION_VER:
            return                      # 已迁移过：此后用户显式存的值一律尊重
        changed = False
        for model, cfg in data.items():
            if model.startswith("_") or not isinstance(cfg, dict):
                continue
            for k, v in self.LEGACY_DEFAULTS.items():
                if cfg.get(k) == v:          # 逐键：恰好等于旧硬编码默认 → 视为未设置
                    cfg.pop(k, None)
                    changed = True
        # 迁移前留一份原文件（可逆；只在首次产生 .pre-2.1.3.bak）
        try:
            bak = self.path + ".pre-2.1.3.bak"
            if not os.path.exists(bak) and os.path.exists(self.path):
                import shutil as _sh
                _sh.copy2(self.path, bak)
        except OSError:
            pass
        data[MIGRATION_KEY] = MIGRATION_VER
        self._save(data)
        if changed:
            self.log_migration = True

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
            return {k: dict(v) for k, v in self._load().items()
                    if not k.startswith("_") and isinstance(v, dict)}


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
        self._quick_exit = False  # 上次启动尝试是否秒退（降级判定用）

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
                # 实际在跑的启动器（升级后要能看出到底换了没换引擎）
                "launcher": os.path.basename(self.python_bin or ""),
                "launcher_path": self.python_bin or "",
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
            # 候选链：native（新→旧）+ 解释器。首选引擎可能不兼容当前模型
            # （实测 v1.0.2 native 的 qwen3_5 族拒绝 27B：UnsupportedQwenConfig），
            # 秒退自动降级到下一候选，直到有一个真的起得来。
            chain = launcher_candidates(self.python_bin)
            if self.python_bin not in chain:
                chain.insert(0, self.python_bin)
            self.params = {**DEFAULT_PARAMS, **params, "port": self.port}
            last_err: dict | None = None
            for launcher in chain:
                r = self._try_start(launcher)
                if r.get("ok"):
                    return r
                last_err = r
                # 降级条件：进程立刻退出（引擎拒绝该模型/参数），换下一个启动器。
                # 连接层失败（端口占用等）同样值得试下一个候选；用户主动取消不存在。
                if not self._quick_exit:
                    break  # 进程还活着（starting 中）但 health 未过 → 不降级，等探活
                self.log(f"引擎 {os.path.basename(launcher)} 启动失败，尝试下一个候选 …")
            return last_err or {"ok": False, "error": "无可用引擎启动器"}

    def _try_start(self, launcher: str) -> dict:
        """用指定启动器尝试一次启动；秒退（≤15s 退出）则返回失败并置 _quick_exit。"""
        self.python_bin = launcher
        self._quick_exit = False
        unsupported: list[str] = []
        argv = serve_argv(launcher, self.model, self.params, self.port, dropped=unsupported)
        if unsupported:
            # 原生引擎没有这些旗标；静默丢弃会让用户以为设置生效，必须留痕。
            self.log(f"该引擎不支持 {', '.join(sorted(set(unsupported)))}，本次已忽略")
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
        # 等 ≤15s：native 引擎拒装模型是秒退（<2s）；解释器加载要几十秒但不会立刻死。
        # health 提前 200 → 直接成功返回；健康交给主循环 mark_ready 升 ready。
        t0 = time.time()
        while time.time() - t0 < 15.0:
            if self.process is None or self.process.poll() is not None:
                err = self.error or "引擎进程启动即退出"
                self.state = "idle"
                self._quick_exit = True
                return {"ok": False, "error": err, "quick_exit": True}
            if self.health(timeout=0.8):
                break
            time.sleep(0.5)
        if self.process is None or self.process.poll() is not None:
            err = self.error or "引擎进程启动即退出"
            self.state = "idle"
            return {"ok": False, "error": err, "quick_exit": True}
        # 15s 活着 → 认定启动成功（加载大模型可能要几十秒，交给 health_tick 升 ready）
        self.name = self.params.get("alias") or self.model.split("/")[-1]
        self.state = "starting"
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
            proc = subprocess.Popen(
                argv, stdout=write_fd, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, close_fds=True,
                cwd=os.path.expanduser("~"),
                env={**env, "PATH": os.path.dirname(self.python_bin) + ":/usr/bin:/bin:/usr/sbin:/sbin"})
        except OSError:
            os.close(read_fd)
            os.close(write_fd)
            raise
        self.process = proc
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
                        if proc.poll() is not None:
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
            self._on_exit(proc)

        threading.Thread(target=pump, daemon=True, name=f"tf-log-pump-{self.port}").start()

    def _on_exit(self, proc: subprocess.Popen):
        """进程收尾。只处理自己那一代：降级后旧候选的 pump 可能晚到，
        绝不能清掉/干扰新进程的状态（实测会误杀 starting→error）。"""
        with self._lock:
            if self.process is not proc:
                return  # 已被新一代启动覆盖，本次收尾静默让位
            code = proc.returncode if proc.poll() is not None else proc.wait()
            self.process = None
            self._sel = None
            self.started_at = None
            if self.state in ("starting", "ready"):
                # 只在已进入 starting/ready（正式启动成功后）才标 error；
                # 启动尝试窗口内的秒退由 _try_start 自己兜住并降级。
                self.state = "error"
                self.error = f"引擎进程已退出 (code={code})，见日志"
            elif self.state == "idle":
                # 启动尝试中退出：记录错误供 _try_start 读取，不改 state（避免竞态覆盖）
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
    DETECT_TTL = 60.0     # detect() 结果缓存秒数（settings() 每次都会问，别反复 spawn）

    def __init__(self, python_bin: str = "", settings: ModelSettings | None = None,
                 base_port: int = DEFAULT_BASE_PORT, spawn_hook=None):
        self.python_bin = python_bin
        self.settings = settings or ModelSettings()
        self.base_port = base_port
        self.spawn_hook = spawn_hook
        self.model_dirs: list[str] = []   # 自定义扫描目录（Api 从 app_settings 注入）
        self._lock = threading.RLock()
        self._instances: dict[str, EngineInstance] = {}
        self._pool_log: list[str] = []
        self._psutil = None
        self._detect_cache: tuple[float, str, str] | None = None  # (ts, python_bin, version)

    def cached(self) -> list[dict]:
        """本机可见模型（HF 缓存 + oMLX/MTPLX/LM Studio + 自定义目录）。"""
        return cached_models(self.model_dirs)

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
        """引擎探测。结果带 TTL 缓存：settings() 会调用它，走得太频繁会反复 spawn。"""
        installed = bool(self.python_bin and os.path.exists(self.python_bin))
        now = time.time()
        cached = self._detect_cache
        if cached and now - cached[0] < self.DETECT_TTL and cached[1] == self.python_bin:
            return {"installed": installed, "path": self.python_bin, "version": cached[2]}
        ver = ""
        if installed:
            # CLI 入口脚本直接 --version；内嵌解释器才走 -m（与 serve_argv 同一分支规则）
            if os.path.basename(self.python_bin) in ("python", "python3"):
                cmd = [self.python_bin, "-m", "tensorfold", "--version"]
            else:
                cmd = [self.python_bin, "--version"]
            try:
                # close_fds=False 很关键：CPython 只在 close_fds 为假时才用 posix_spawn，
                # 否则走 fork()。本进程是 AppKit+WebKit 多线程环境，fork 会与
                # malloc/atfork 锁竞争而**死锁**（实测：桥线程卡死在 lock acquire，
                # 连带 models_installed 等后续调用全部挂住，模型页空白）。
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                                   close_fds=False)
                out = (r.stdout or r.stderr).strip()
                ver = out.splitlines()[-1] if out else ""
            except Exception:
                ver = ""
        self._detect_cache = (now, self.python_bin, ver)
        return {"installed": installed, "path": self.python_bin, "version": ver}

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
        for m in self.cached():
            if model in (m.get("id"), m.get("ref")):
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
        # 只允许删 HF 缓存里我们自己下过的模型（owner/name 形态且确实在缓存里）。
        # oMLX/MTPLX/自定义目录里的权重是用户自己的资料，本 App 一律不碰
        # （2026-10-08 加扫描目录时同步加的门：路径形态一律拒绝）。
        if os.path.isabs(repo_id) or repo_id.count("/") != 1:
            return {"ok": False, "error": "本地目录里的模型不在本 App 删除范围内"}
        base = hf_cache_dir()
        target = os.path.join(base, _repo_dir_name(repo_id))
        real = os.path.realpath(base)
        if not os.path.isdir(base) or not real.startswith(os.path.expanduser("~")):
            return {"ok": False, "error": "缓存目录异常，拒绝操作"}
        if not os.path.isdir(target):
            return {"ok": False, "error": f"缓存中不存在 {repo_id}（外部目录的模型需自行管理）"}
        # 本机约定：权重放在缓存外、缓存里只留软链（主模型与草稿模型都是这形态）。
        # 这种条目的「删缓存」= 摘掉链接入口，真实权重一律不动；以前直接 rmtree(软链)
        # 会抛 "Cannot call rmtree on a symbolic link"，删除按钮点了必然报错。
        if os.path.islink(target):
            os.remove(target)
            self.log(f"已移除缓存入口（软链）: {repo_id} · 真实权重未删除")
            self.settings.delete_for(repo_id)
            return {"ok": True, "unlinked": True,
                    "hint": "只摘除了缓存链接，权重文件仍在原目录"}
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
