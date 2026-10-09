"""累计用量账本：Manager 自己按增量累加，跨引擎重启 / 实例停止 / App 重启持续。

为什么不能直接把引擎的 counter 当「累计」：
  /metrics 里的 prompt_tokens_total / generation_tokens_total / ttft_count 都是
  **本进程启动以来**的计数 —— 引擎一重启就归零，实例一停止这个数就消失。
  直接把它们相加当累计，用户会看到数字往回跳，停掉模型后清零。

做法：
  - 每个采样周期把各实例的 counter 与账本记住的上次值做差，增量累加进总量；
    增量 = cur - last（cur >= last），否则视为计数器回绕 / 引擎重启 → 增量 = cur；
  - 账本落盘 ~/.tensorfold-manager/usage.json，App 重启后接着累加，不丢历史；
  - 总账单调不减（正常路径只增不减），这是"累计"该有的性质。

注意 reset() 只清总量、不清 seen：留着 seen 才能让"清零之后"只统计新增量，
否则下一次采样会把每个实例的全部历史再算一遍，等于没清干净。
"""
from __future__ import annotations

import json
import os
import threading
import time

SETTINGS_DIR = os.path.expanduser("~/.tensorfold-manager")

# 累加的字段（全部来自 /metrics 的 counter）
FIELDS = ("requests", "prompt_tokens", "generation_tokens", "drafted", "accepted",
          "decode_seconds", "ttft_seconds")
_FLUSH_EVERY = 5.0     # 落盘节流：最多 5s 一次（1Hz 采样下不必每次都写盘）


def _zero() -> dict:
    return {k: 0 for k in FIELDS}


class UsageLedger:
    """累计用量账本（线程安全）。observe() 由监控循环每采样周期调一次。"""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(SETTINGS_DIR, "usage.json")
        self.lock = threading.RLock()
        self.totals: dict = _zero()
        self.models: dict[str, dict] = {}      # ref -> 累计
        self.seen: dict[str, dict] = {}        # 实例键(model#port) -> 上次 raw counter
        self.since: float = time.time()
        self._last_flush = 0.0
        self._dirty = False
        self.load()

    # ---------- 持久化 ----------
    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        with self.lock:
            for k, v in (data.get("totals") or {}).items():
                if k in self.totals and isinstance(v, (int, float)):
                    self.totals[k] = v
            models = data.get("models")
            if isinstance(models, dict):
                for ref, row in models.items():
                    if isinstance(row, dict):
                        self.models[str(ref)] = {k: float(row.get(k) or 0) for k in FIELDS}
            self.since = float(data.get("since") or self.since)

    def flush(self, force: bool = False) -> None:
        with self.lock:
            if not self._dirty and not force:
                return
            now = time.time()
            if not force and now - self._last_flush < _FLUSH_EVERY:
                return
            payload = {"_schema": 1, "totals": dict(self.totals),
                       "models": {k: dict(v) for k, v in self.models.items()},
                       "since": self.since, "saved_at": now}
            self._dirty = False
            self._last_flush = now
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---------- 采样 ----------
    def observe(self, snapshot: dict[str, dict]) -> None:
        """snapshot: 实例键(model#port) -> {model, 各 raw counter}。"""
        if not snapshot:
            with self.lock:
                if self.seen:            # 实例都没了 → 丢掉基线，避免下次重启算成大增量
                    self.seen = {}
            return
        with self.lock:
            for key, cur in snapshot.items():
                last = self.seen.get(key)
                row = {k: float(cur.get(k) or 0) for k in FIELDS}
                if last is None:
                    delta = dict(row)    # 首次见到：把已有计数当作本账本开始后的增量
                else:
                    delta = {}
                    for k in FIELDS:
                        d = row[k] - float(last.get(k) or 0)
                        delta[k] = d if d >= 0 else row[k]   # 负数 = 计数器重启，按当前值算
                for k in FIELDS:
                    self.totals[k] = self.totals.get(k, 0) + delta[k]
                ref = str(cur.get("model") or key)
                mrow = self.models.setdefault(ref, _zero())
                for k in FIELDS:
                    mrow[k] = mrow.get(k, 0) + delta[k]
                self.seen[key] = row
            self._dirty = True
        self.flush()

    # ---------- 读数 ----------
    @staticmethod
    def _rate(row: dict) -> dict:
        """按累计值算平均速率：生成 tok/s 与提示处理 tok/s（引擎只给 total 与耗时）。"""
        out = {}
        dec = float(row.get("decode_seconds") or 0)
        ttft = float(row.get("ttft_seconds") or 0)
        out["gen_tps"] = round(float(row.get("generation_tokens") or 0) / dec, 1) if dec > 0.05 else None
        out["prefill_tps"] = round(float(row.get("prompt_tokens") or 0) / ttft, 1) if ttft > 0.05 else None
        return out

    def summary(self) -> dict:
        with self.lock:
            totals = dict(self.totals)
            since = self.since
            models = {k: dict(v) for k, v in self.models.items()}
        totals.update(self._rate(totals))
        totals["total_tokens"] = totals.get("prompt_tokens", 0) + totals.get("generation_tokens", 0)
        rows = []
        for ref, row in models.items():
            r = dict(row)
            r.update(self._rate(row))
            r["model"] = ref
            r["total_tokens"] = r.get("prompt_tokens", 0) + r.get("generation_tokens", 0)
            rows.append(r)
        rows.sort(key=lambda x: x["total_tokens"], reverse=True)
        return {"totals": totals, "models": rows, "since": since, "path": self.path}

    def reset(self) -> dict:
        """清空累计（保留 seen 基线，只统计之后的新增量）。"""
        with self.lock:
            self.totals = _zero()
            self.models = {}
            self.since = time.time()
            self._dirty = True
        self.flush(force=True)
        return {"ok": True, **self.summary()}

    def new_session(self) -> None:
        """引擎全停时调用：清掉实例基线（下次启动从 0 开始算增量）。"""
        with self.lock:
            self.seen = {}
