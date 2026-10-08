"""监控：轮询引擎 /metrics + 主机内存，维护采样环形缓冲供 UI 画 sparkline。

v2：多实例池——每 tick 遍历全部 ready 实例，聚合成一个总览样本
（tps/请求求和、KV 取最大、足迹求和），并保留每实例明细 per[model]。
由 main 主循环每 ~1s 调 tick()；/metrics 每 2 次 tick 抓一次（0.5Hz 足够）。
解析的指标族（Prometheus text, 前缀 tensorfold:）：
  requests_running / requests_waiting        gauge   在跑/排队请求
  prompt_tokens_total / generation_tokens_total  counter
  kv_cache_usage_ratio{pool=..}              gauge   0..1
  mtp_drafted_total / mtp_accepted_total     counter 草稿接受率
  request_decode_seconds{_sum,_count}        histogram
  process_footprint_bytes                    gauge   进程物理足迹（含 Metal 缓冲）
"""
from __future__ import annotations

import threading
import time
import urllib.request

HISTORY_LEN = 600  # 600 个采样点 @1s ≈ 10 分钟（B5 时序窗口）


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest: dict = {}
        self.per: dict[str, dict] = {}          # model -> 该实例最新解析
        self.prev: dict[str, dict] = {}         # model -> 上次解析（tps 差分用）
        self.prev_time: float = 0.0
        self.hist: list[dict] = []
        self.raw: str = ""
        self._tick_count = 0

    def reset(self):
        with self.lock:
            self.latest = {}
            self.per = {}
            self.prev = {}
            self.prev_time = 0.0
            self.hist = []
            self.raw = ""

    def reset_model(self, model: str):
        """实例停止后清掉它的差分基线，防止重启后 tps 出现巨大负跳/正跳。"""
        with self.lock:
            self.per.pop(model, None)
            self.prev.pop(model, None)

    def fetch_metrics(self, base_url: str) -> dict | None:
        try:
            with urllib.request.urlopen(f"{base_url}/metrics", timeout=1.5) as resp:
                if resp.status != 200:
                    return None
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    _gpu_cache = {"t": 0.0, "v": None}

    @classmethod
    def _gpu_percent(cls) -> float | None:
        """GPU 利用率（0-100）：ioreg IOAccelerator，500ms 缓存避免每 tick 都跑子进程。"""
        now = time.time()
        if now - cls._gpu_cache["t"] < 0.5:
            return cls._gpu_cache["v"]
        try:
            import subprocess, re
            r = subprocess.run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
                               capture_output=True, text=True, timeout=2)
            m = re.search(r'"Device Utilization %"\s*=\s*(\d+)', r.stdout or "")
            v = float(m.group(1)) if m else None
        except Exception:
            v = None
        cls._gpu_cache.update(t=now, v=v)
        return v

    def parse(self, text: str) -> dict:
        out: dict = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.rpartition(" ")
            name = name.strip()
            try:
                v = float(value)
            except ValueError:
                continue
            if "{" in name:
                base, _, labels = name.partition("{")
                if base == "tensorfold:kv_cache_usage_ratio" and 'pool="' in labels:
                    pool = labels.split('"')[1]
                    out.setdefault("kv_pools", {})[pool] = v
                    out["kv_max"] = max(out.get("kv_max", 0.0), v)
            else:
                if name in ("tensorfold:requests_running", "tensorfold:num_requests_running"):
                    out["running"] = v
                elif name in ("tensorfold:requests_waiting", "tensorfold:num_requests_waiting"):
                    out["waiting"] = v
                elif name == "tensorfold:generation_tokens_total":
                    out["gen_tokens"] = v
                elif name == "tensorfold:prompt_tokens_total":
                    out["prompt_tokens"] = v
                elif name == "tensorfold:mtp_drafted_total":
                    out["drafted"] = v
                elif name == "tensorfold:mtp_accepted_total":
                    out["accepted"] = v
                elif name == "tensorfold:process_footprint_bytes":
                    out["footprint_bytes"] = v
                elif name == "tensorfold:request_decode_seconds_sum":
                    out["decode_sum"] = v
                elif name == "tensorfold:request_decode_seconds_count":
                    out["decode_count"] = v
                elif name == "tensorfold:time_to_first_token_seconds_sum":
                    out["ttft_sum"] = v
                elif name == "tensorfold:time_to_first_token_seconds_count":
                    out["ttft_count"] = v
        return out

    def tick(self, pool, psutil):
        """主循环每秒调一次。pool 为 EnginePool（或任何提供 ready_instances() 的对象）。"""
        self._tick_count += 1
        sample: dict = {"t": time.time()}
        if psutil is not None:
            try:
                vm = psutil.virtual_memory()
                sample["mem_free"] = round(vm.available / 1024**3, 1)
            except Exception:
                pass
            try:
                sample["cpu_percent"] = psutil.cpu_percent(interval=None)
            except Exception:
                pass
        # GPU 利用率：Apple Silicon 用 IOAccelerator 的 Device Utilization %（实测可行，~10ms 开销）
        if self._tick_count % 2 == 0:
            sample["gpu_percent"] = self._gpu_percent()
        ready = pool.ready_instances() if hasattr(pool, "ready_instances") else (
            [pool] if getattr(pool, "state", "") == "ready" else [])
        if ready and self._tick_count % 2 == 0:
            now = time.time()
            agg = {"tps": 0.0, "running": 0, "waiting": 0, "kv": 0.0, "footprint_gb": 0.0,
                   "prompt_tokens": 0.0, "gen_tokens_total": 0.0, "ttft_avg": 0.0,
                   "prefill_tps": 0.0, "requests_done": 0}
            per: dict[str, dict] = {}
            raws = []
            with self.lock:
                prev_time = self.prev_time
            dt = now - prev_time if prev_time else 0
            first = dt <= 0.5
            for inst in ready:
                text = self.fetch_metrics(inst.base_url())
                if text is None:
                    continue
                parsed = self.parse(text)
                raws.append(f"== {inst.model} ==\n{text[-1500:]}")
                with self.lock:
                    prev = self.prev.get(inst.model)
                    self.prev[inst.model] = parsed
                    if prev and dt > 0.5:
                        d_gen = parsed.get("gen_tokens", 0) - prev.get("gen_tokens", 0)
                        if d_gen >= 0:
                            agg["tps"] += round(d_gen / dt, 1)
                agg["running"] += parsed.get("running", 0)
                agg["waiting"] += parsed.get("waiting", 0)
                agg["kv"] = max(agg["kv"], round(parsed.get("kv_max", 0.0) * 100, 1))
                agg["footprint_gb"] = round(agg["footprint_gb"] + parsed.get("footprint_bytes", 0) / 1024**3, 2)
                # 累计用量（引擎 counter 为 finished requests 口径，直接累加各实例）
                agg["prompt_tokens"] += parsed.get("prompt_tokens", 0)
                agg["gen_tokens_total"] += parsed.get("gen_tokens", 0)
                if prev and dt > 0.5:
                    # prefill 速度代理：TTFT sum 的增量 ≈ 本窗口新增 prompt 的预填时间，
                    # 除以同窗口新增 prompt tokens（无增量时跳过）
                    d_prompt = parsed.get("prompt_tokens", 0) - prev.get("prompt_tokens", 0)
                    d_ttft = parsed.get("ttft_sum", 0) - prev.get("ttft_sum", 0)
                    if d_prompt > 0 and d_ttft >= 0:
                        agg["prefill_tps"] += round(d_prompt / d_ttft, 1) if d_ttft > 0 else None or agg["prefill_tps"]
                # 完成请求数用 TTFT count（每个完成请求恰好计一次）
                agg["requests_done"] += int(parsed.get("ttft_count", 0))
                # TTFT 均值 = sum/count（有请求完成才有效）
                tc = parsed.get("ttft_count", 0)
                if tc:
                    inst_ttft = parsed.get("ttft_sum", 0) / tc
                else:
                    inst_ttft = None
                drafted = parsed.get("drafted", 0)
                gen_delta_ok = prev and dt > 0.5 and parsed.get("gen_tokens", 0) >= (prev or {}).get("gen_tokens", 0)
                per[inst.model] = {
                    "port": inst.port, "name": inst.name,
                    "tps": (round((parsed.get("gen_tokens", 0) - (prev or {}).get("gen_tokens", 0)) / dt, 1)
                            if gen_delta_ok else None),
                    "running": parsed.get("running", 0), "waiting": parsed.get("waiting", 0),
                    "kv": round(parsed.get("kv_max", 0.0) * 100, 1),
                    "footprint_gb": round(parsed.get("footprint_bytes", 0) / 1024**3, 2),
                    "accepted_ratio": (parsed.get("accepted", 0) / drafted) if drafted else None,
                    "prompt_tokens": parsed.get("prompt_tokens", 0),
                    "gen_tokens": parsed.get("gen_tokens", 0),
                    "ttft_avg_ms": round(inst_ttft * 1000, 1) if inst_ttft is not None else None,
                    "prefill_tps": (round(d_prompt / d_ttft, 1) if (prev and dt > 0.5
                                    and (d_prompt := parsed.get("prompt_tokens", 0) - prev.get("prompt_tokens", 0)) > 0
                                    and (d_ttft := parsed.get("ttft_sum", 0) - prev.get("ttft_sum", 0)) > 0) else None),
                }
            with self.lock:
                self.prev_time = now
                self.per = per
                self.raw = "\n".join(raws)[-6000:]
                if not first:
                    self.latest = dict(per)
                sample.update({
                    "tps": agg["tps"] if not first else None,
                    "prefill_tps": agg.get("prefill_tps") if not first else None,
                    "running": agg["running"], "waiting": agg["waiting"],
                    "kv": agg["kv"], "footprint_gb": agg["footprint_gb"],
                    "prompt_tokens": agg["prompt_tokens"],
                    "gen_tokens_total": agg["gen_tokens_total"],
                    "requests_done": agg["requests_done"],
                })
        with self.lock:
            self.hist.append(sample)
            if len(self.hist) > HISTORY_LEN:
                del self.hist[0]

    def snapshot(self) -> dict:
        """UI 用：最新值 + 曲线数组（ts/trend/percent 三种 kind）+ 每实例明细。"""
        with self.lock:
            series = {}
            for key, kind in (("tps", "trend"), ("kv", "percent"), ("footprint_gb", "trend"),
                              ("mem_free", "trend"), ("cpu_percent", "percent"),
                              ("gpu_percent", "percent")):
                vals = [s.get(key) for s in self.hist if s.get(key) is not None]
                if len(vals) >= 2:
                    series[key] = {"kind": kind, "values": [round(v, 2) for v in vals][-120:]}
            last = self.hist[-1] if self.hist else {}
            return {
                "series": series,
                "latest": {
                    "tps": last.get("tps"),
                    "prefill_tps": last.get("prefill_tps"),
                    "kv": last.get("kv"),
                    "running": last.get("running"),
                    "waiting": last.get("waiting"),
                    "footprint_gb": last.get("footprint_gb"),
                    "mem_free": last.get("mem_free"),
                    "cpu_percent": last.get("cpu_percent"),
                    "gpu_percent": last.get("gpu_percent"),
                    "prompt_tokens": last.get("prompt_tokens"),
                    "gen_tokens_total": last.get("gen_tokens_total"),
                    "requests_done": last.get("requests_done"),
                },
                "per": {m: dict(v) for m, v in self.per.items()},
                "raw": self.raw,
            }
