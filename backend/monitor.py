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
    def __init__(self, ledger=None):
        self.lock = threading.Lock()
        self.latest: dict = {}
        self.per: dict[str, dict] = {}          # model -> 该实例最新解析
        self.prev: dict[str, dict] = {}         # model -> 上次解析（tps 差分用）
        self.prev_time: float = 0.0
        self.hist: list[dict] = []
        self.raw: str = ""
        self._tick_count = 0
        # 最近一次**真正抓到的**指标读数。抓取是每 2 tick 一次（0.5Hz），
        # 但 UI 每 2.5s 读一次 snapshot；若 snapshot 直接取 hist[-1]，
        # 落在没抓取的那一 tick 上就全是 None → 实时数字一会儿有一会儿没有。
        # 所以这里跨 tick 保留，只被新的抓取覆盖。
        self.metrics_last: dict = {}
        self.ledger = ledger   # UsageLedger（可选）：累计用量账本
        self._cpu_primed = False
        self._cpu_at = 0.0
        self._prime_cpu()

    def _prime_cpu(self) -> None:
        """预热 psutil.cpu_percent（整机 + 每核两套基线都要建）。

        它用「距上次调用的 CPU 时间差」算占用率，进程内**第一次调用恒返回 0.0**
        （没有基线）—— 监控页开局那一格永远是 0，看起来就是"假数字"。
        所以启动时先把两套基线都建起来；tick 里再挡住"间隔太近"的那一次。
        """
        try:
            import psutil
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None, percpu=True)
            self._cpu_primed = True
            self._cpu_at = time.time()
        except Exception:
            self._cpu_primed = False

    def reset(self):
        with self.lock:
            self.latest = {}
            self.per = {}
            self.prev = {}
            self.prev_time = 0.0
            self.hist = []
            self.raw = ""
            self.metrics_last = {}
        if self.ledger is not None:
            self.ledger.new_session()

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
            # close_fds=False → 走 posix_spawn（fork 在 AppKit+WebKit 多线程进程里会死锁）
            r = subprocess.run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
                               capture_output=True, text=True, timeout=2, close_fds=False)
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
                now_c = time.time()
                # 基线没建好、或距上次采样不足 0.2s（间隔太小算出来的比例没有意义），
                # 这一次只刷新基线、不出数 —— 总比把假的 0 当读数好。
                warm = (not self._cpu_primed) or (now_c - self._cpu_at < 0.2)
                per = psutil.cpu_percent(interval=None, percpu=True)
                total = psutil.cpu_percent(interval=None)
                self._cpu_primed = True
                self._cpu_at = now_c
                if not warm:
                    sample["cpu_percent"] = total
                    if per:                       # 每核占用（真实读数）：UI 画"核心 + 使用情况"
                        sample["cpu_per"] = [int(round(v)) for v in per]
            except Exception:
                pass
        # GPU 利用率：Apple Silicon 用 IOAccelerator 的 Device Utilization %（实测可行，~10ms 开销）
        sample["gpu_percent"] = self._gpu_percent()
        ready = pool.ready_instances() if hasattr(pool, "ready_instances") else (
            [pool] if getattr(pool, "state", "") == "ready" else [])
        if ready and self._tick_count % 2 == 0:
            now = time.time()
            agg = {"tps": 0.0, "running": 0, "waiting": 0, "kv": 0.0, "footprint_gb": 0.0,
                   "prompt_tokens": 0.0, "gen_tokens_total": 0.0,
                   "prefill_tps": 0.0, "requests_done": 0,
                   "decode_sum": 0.0, "ttft_sum": 0.0, "ttft_count": 0.0}
            per: dict[str, dict] = {}
            raws = []
            counters: dict[str, dict] = {}      # 实例键 -> raw counter（喂累计账本）
            with self.lock:
                prev_time = self.prev_time
            dt = now - prev_time if prev_time else 0
            first = dt <= 0.5
            measured = False                   # 本轮是否真抓到了 /metrics
            for inst in ready:
                text = self.fetch_metrics(inst.base_url())
                if text is None:
                    continue
                measured = True
                parsed = self.parse(text)
                raws.append(f"== {inst.model} ==\n{text[-1500:]}")
                counters[f"{inst.model}#{inst.port}"] = {
                    "model": inst.model,
                    "requests": parsed.get("ttft_count", 0),
                    "prompt_tokens": parsed.get("prompt_tokens", 0),
                    "generation_tokens": parsed.get("gen_tokens", 0),
                    "drafted": parsed.get("drafted", 0),
                    "accepted": parsed.get("accepted", 0),
                    "decode_seconds": parsed.get("decode_sum", 0),
                    "ttft_seconds": parsed.get("ttft_sum", 0),
                }
                with self.lock:
                    prev = self.prev.get(inst.model)
                    self.prev[inst.model] = parsed
                gen = parsed.get("gen_tokens", 0)
                dec = parsed.get("decode_sum", 0)
                d_gen = d_dec = d_prompt = d_ttft = 0.0
                if prev and dt > 0.5:
                    d_gen = gen - prev.get("gen_tokens", 0)
                    d_dec = dec - prev.get("decode_sum", 0)
                    d_prompt = parsed.get("prompt_tokens", 0) - prev.get("prompt_tokens", 0)
                    d_ttft = parsed.get("ttft_sum", 0) - prev.get("ttft_sum", 0)
                    if d_gen >= 0:
                        # 生成速率优先用「解码耗时增量」当分母 —— 这才是不含排队与
                        # 空闲等待的真解码 tok/s。引擎没给 decode 直方图（d_dec=0）
                        # 时退回墙钟差分，保证任何引擎都还有个数。
                        agg["tps"] += round(d_gen / d_dec, 1) if d_dec > 0.02 else round(d_gen / dt, 1)
                    if d_prompt > 0 and d_ttft > 0:
                        agg["prefill_tps"] += round(d_prompt / d_ttft, 1)
                agg["running"] += parsed.get("running", 0)
                agg["waiting"] += parsed.get("waiting", 0)
                agg["kv"] = max(agg["kv"], round(parsed.get("kv_max", 0.0) * 100, 1))
                agg["footprint_gb"] = round(agg["footprint_gb"] + parsed.get("footprint_bytes", 0) / 1024**3, 2)
                agg["prompt_tokens"] += parsed.get("prompt_tokens", 0)
                agg["gen_tokens_total"] += gen
                agg["decode_sum"] += dec
                agg["ttft_sum"] += parsed.get("ttft_sum", 0)
                # 完成请求数用 TTFT count（每个完成请求恰好计一次）
                tc = int(parsed.get("ttft_count", 0))
                agg["ttft_count"] += tc
                agg["requests_done"] += tc
                inst_ttft = (parsed.get("ttft_sum", 0) / tc) if tc else None
                drafted = parsed.get("drafted", 0)
                per[inst.model] = {
                    "port": inst.port, "name": inst.name,
                    "tps": (round(d_gen / d_dec, 1) if d_dec > 0.02 else round(d_gen / dt, 1))
                           if (prev and dt > 0.5 and d_gen >= 0) else None,
                    "running": parsed.get("running", 0), "waiting": parsed.get("waiting", 0),
                    "kv": round(parsed.get("kv_max", 0.0) * 100, 1),
                    "footprint_gb": round(parsed.get("footprint_bytes", 0) / 1024**3, 2),
                    "accepted_ratio": (parsed.get("accepted", 0) / drafted) if drafted else None,
                    "prompt_tokens": parsed.get("prompt_tokens", 0),
                    "gen_tokens": gen,
                    "ttft_avg_ms": round(inst_ttft * 1000, 1) if inst_ttft is not None else None,
                    "prefill_tps": round(d_prompt / d_ttft, 1) if (prev and dt > 0.5 and d_prompt > 0 and d_ttft > 0) else None,
                }
            if measured and self.ledger is not None:
                # 累计用量：账本按增量自己累加（引擎 counter 会随重启归零，不能直接当累计）
                self.ledger.observe(counters)
            # 会话口径的真实平均速率：引擎只给累计量与耗时，平均要自己除；
            # 这两个数就是 oMLX「平均速度」那种稳定读数（不像瞬时 tps 会跳）。
            gen_avg = round(agg["gen_tokens_total"] / agg["decode_sum"], 1) if agg["decode_sum"] > 0.05 else None
            pre_avg = round(agg["prompt_tokens"] / agg["ttft_sum"], 1) if agg["ttft_sum"] > 0.05 else None
            ttft_avg = round(agg["ttft_sum"] / agg["ttft_count"] * 1000, 1) if agg["ttft_count"] else None
            shown = {
                "tps": agg["tps"] if not first else None,
                "gen_avg_tps": gen_avg,
                "prefill_tps": agg["prefill_tps"] if not first else None,
                "prefill_avg_tps": pre_avg,
                "ttft_avg_ms": ttft_avg,
                "running": agg["running"], "waiting": agg["waiting"],
                "kv": agg["kv"], "footprint_gb": agg["footprint_gb"],
                "prompt_tokens": agg["prompt_tokens"],
                "gen_tokens_total": agg["gen_tokens_total"],
                "requests_done": agg["requests_done"],
            }
            with self.lock:
                self.prev_time = now
                self.per = per
                self.raw = "\n".join(raws)[-6000:]
                if not first:
                    self.latest = dict(per)
                # 跨 tick 保留最近一次真读数（抓取是 0.5Hz，UI 读得更快）
                self.metrics_last = {**self.metrics_last, **{k: v for k, v in shown.items() if v is not None}}
                sample.update(self.metrics_last)
        elif not ready:
            with self.lock:
                self.metrics_last = {}          # 没有实例在跑 → 读数不该继续挂着
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
            last = self.hist[-1] if self.hist else {}   # noqa: F841 —— 保留给后续扩展
            latest = {"tps": None, "gen_avg_tps": None, "prefill_tps": None,
                      "prefill_avg_tps": None, "ttft_avg_ms": None, "kv": None,
                      "running": None, "waiting": None, "footprint_gb": None,
                      "prompt_tokens": None, "gen_tokens_total": None, "requests_done": None}
            # 指标读数取「最近一次真抓到的」（跨 tick 保留），不用 hist[-1]：
            # 抓取是 0.5Hz、UI 读得更快，直接读 hist[-1] 会有一半时候读到空值。
            latest.update({k: v for k, v in self.metrics_last.items() if v is not None})

            # 主机读数（内存/CPU/GPU）也取"最近一次有值的那笔"：GPU 读 ioreg 偶尔会
            # 拿不到（返回 None），取 hist[-1] 会让监控页的 CPU/GPU 数字一闪一闪。
            def _recent(key):
                for s in reversed(self.hist):
                    if s.get(key) is not None:
                        return s[key]
                return None

            latest["mem_free"] = _recent("mem_free")
            latest["cpu_percent"] = _recent("cpu_percent")
            latest["gpu_percent"] = _recent("gpu_percent")
            latest["cpu_per"] = _recent("cpu_per")
            return {
                "series": series,
                "latest": latest,
                "per": {m: dict(v) for m, v in self.per.items()},
                "raw": self.raw,
            }
