"""主机静态信息：CPU 核心构成 / GPU 型号与核心数。

这些量在一次运行里不会变，且取值都要跑子进程（sysctl / ioreg），所以进程内缓存，
只在第一次问的时候取一遍。取不到就如实给 None / ""，绝不用猜的数字凑。

实测（本机 Apple Silicon）：
  sysctl hw.perflevel0.physicalcpu → 12   （性能核 P）
  sysctl hw.perflevel1.physicalcpu → 24   （能效核 E）
  sysctl hw.ncpu                   → 36   （逻辑核）
  ioreg -c IOAccelerator           → "model" = "Apple M5 Ultra"，"gpu-core-count" = 80
"""
from __future__ import annotations

import os
import re
import subprocess

_cache: dict = {}


def _run(cmd: list[str]) -> str:
    """跑一条只读命令取 stdout。close_fds=False → 走 posix_spawn。

    App 是 AppKit+WebKit 多线程进程，subprocess 默认 close_fds=True 会走 fork()，
    和 malloc/atfork 锁打架会死锁（见 smoke_test B1d）。这里必须避开。
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=4, close_fds=False)
        return r.stdout or ""
    except Exception:
        return ""


def _sysctl(key: str) -> str:
    return _run(["sysctl", "-n", key]).strip()


def _int(s: str, default=None):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def cpu_info() -> dict:
    """CPU 型号 / 逻辑核 / 物理核 / P·E 核数（取不到的项为 None）。"""
    if "cpu" in _cache:
        return _cache["cpu"]
    ncpu = _int(_sysctl("hw.ncpu"), os.cpu_count() or 0)
    out = {
        "model": _sysctl("machdep.cpu.brand_string") or "",
        "logical": ncpu,
        "physical": _int(_sysctl("hw.physicalcpu"), ncpu),
        # Apple Silicon：perflevel0 = 性能核，perflevel1 = 能效核；Intel 机器上没有这两个键
        "p": _int(_sysctl("hw.perflevel0.physicalcpu"), None),
        "e": _int(_sysctl("hw.perflevel1.physicalcpu"), None),
    }
    _cache["cpu"] = out
    return out


def gpu_info() -> dict:
    """GPU 型号 / 核心数。Apple Silicon 用 ioreg 的 IOAccelerator 节点。"""
    if "gpu" in _cache:
        return _cache["gpu"]
    out = {"name": "", "cores": None}
    txt = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    m = re.search(r'"model"\s*=\s*"([^"]+)"', txt)
    if m:
        out["name"] = m.group(1)
    m = re.search(r'"gpu-core-count"\s*=\s*(\d+)', txt)
    if m:
        out["cores"] = int(m.group(1))
    if not out["cores"] or not out["name"]:
        # 兜底：system_profiler 慢（约 1s），只在 ioreg 取不到时才跑，且只跑一次
        t2 = _run(["system_profiler", "SPDisplaysDataType"])
        if not out["name"]:
            m = re.search(r"Chipset Model:\s*(.+)", t2)
            if m:
                out["name"] = m.group(1).strip()
        if not out["cores"]:
            m = re.search(r"Total Number of Cores:\s*(\d+)", t2)
            if m:
                out["cores"] = int(m.group(1))
    _cache["gpu"] = out
    return out


def cpu_core_label() -> str:
    """给 UI 用的一致口径：优先「12P + 24E · 36 逻辑核」，退化到「36 核」。"""
    c = cpu_info()
    if c.get("p") and c.get("e"):
        return f"{c['p']}P + {c['e']}E · {c['logical']} 逻辑核"
    if c.get("physical"):
        return f"{c['physical']} 物理核 · {c['logical']} 逻辑核"
    return f"{c['logical']} 核" if c.get("logical") else ""


def gpu_core_label() -> str:
    g = gpu_info()
    if g.get("name") and g.get("cores"):
        return f"{g['name']} · {g['cores']} 核"
    return g.get("name") or (f"{g['cores']} 核" if g.get("cores") else "")
