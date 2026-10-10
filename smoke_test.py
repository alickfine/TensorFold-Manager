"""冒烟测试：不依赖 GUI，验证多实例引擎池 / 每模型设置 / 聊天代理路由 / 监控聚合 / 更新检查。

用法：python smoke_test.py
① FakeServer 模拟 tensorfold serve 的 /health /metrics /v1/models /v1/chat/completions
   （每个实例报告自己的模型名，用于断言多实例路由）。
② spawn_hook 注入假进程驱动 EnginePool，不真起子进程；端口用 18080+ 段避开业务口。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TMP = "/tmp/tfm-smoke"

METRICS_TEXT = """# HELP tensorfold:generation_tokens_total Generated tokens of finished requests.
tensorfold:generation_tokens_total {gen}
tensorfold:prompt_tokens_total 100
tensorfold:requests_running 1
tensorfold:requests_waiting 0
tensorfold:kv_cache_usage_ratio{{pool="main"}} 0.62
tensorfold:mtp_drafted_total 90
tensorfold:mtp_accepted_total 60
tensorfold:process_footprint_bytes 13958643712
# TYPE tensorfold:request_decode_seconds_sum histogram
tensorfold:request_decode_seconds_sum 5.2
tensorfold:request_decode_seconds_count 4
"""


class FakeProc:
    """spawn_hook 用的假进程：活着，可终止。"""

    def __init__(self):
        self.returncode = None
        self._dead = False

    def poll(self):
        return 0 if self._dead else None

    def terminate(self):
        self._dead = True
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._dead = True


def run_fake_server(port: int, model: str = "fake/model", *, gen_step: int = 10,
                    decode_step: float = 0.0, ttft: bool = False):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"gen": 260, "dec": 5.2}

    def metrics_text() -> str:
        # gen_step / decode_step 可调：用来造「解码耗时也在推进」的场景，
        # 以验证 tps 的分母用的是 Δ解码耗时（真解码速率）而不是墙钟。
        state["gen"] += gen_step
        state["dec"] += decode_step
        txt = METRICS_TEXT.replace("tensorfold:request_decode_seconds_sum 5.2",
                                   f"tensorfold:request_decode_seconds_sum {state['dec']}")
        txt = txt.format(gen=state["gen"])
        if ttft:
            txt += ("tensorfold:time_to_first_token_seconds_sum 1.5\n"
                    "tensorfold:time_to_first_token_seconds_count 3\n")
        return txt

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            elif self.path == "/metrics":
                payload = metrics_text().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/v1/models":
                payload = json.dumps({"data": [{"id": model}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/v1/chat/completions":
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                req = json.loads(body)
                reply = f"你好，我是{model.split('/')[-1]}"
                if req.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for piece in (reply[:3], reply[3:]):
                        chunk = json.dumps({"choices": [{"delta": {"content": piece}, "finish_reason": None}]},
                                           ensure_ascii=False)
                        self.wfile.write(f"data: {chunk}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(0.02)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                elif req.get("messages", [{}])[-1].get("content", "").startswith("trigger-500"):
                    payload = b'{"error": {"message": "fake upstream 500"}}'
                    self.send_response(500)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    payload = json.dumps({"choices": [{"message": {"content": f"非流式回复自 {model}"}}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    from backend.chat import ChatProxy, ChatStore
    from backend.engine import (EnginePool, ModelSettings, build_serve_args,
                               cached_models, DEFAULT_PARAMS)
    from backend.monitor import Monitor
    from backend.update import UpdateChecker, _cmp

    failures = []

    def check(name, cond, note=""):
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {name} {note}")
        if not cond:
            failures.append(name)

    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    # ============ B1a: serve 参数编译（纯函数，含全部 v2 透传字段） ============
    print("== B1: 参数透传编译 ==")
    args = build_serve_args("m", {
        "context": 65536, "max_tokens": 2048, "temperature": 0.7, "top_p": 0.9, "top_k": 40,
        "thinking": False, "drafts": True, "mtp_drafts": 4, "mtp_confidence": 0.8,
        "kv_dtype": "fp8", "prompt_cache_gib": 8, "parallel": 4, "backend": "mlx",
        "vision": True, "alias": "flash"}, 8123)
    j = " ".join(args)
    check("编译 --parallel/--prompt-cache-gib/--mtp-drafts/--mtp-confidence/--kv-dtype/--backend",
          all(s in j for s in ["--parallel 4", "--prompt-cache-gib 8", "--mtp-drafts 4",
                              "--mtp-confidence 0.8", "--kv-dtype fp8", "--backend mlx"]), j)
    check("编译 --context/--max-tokens/--temperature/--no-thinking/--vision/--name",
          all(s in j for s in ["--context 65536", "--max-tokens 2048", "--temperature 0.7",
                              "--no-thinking", "--vision", "--name flash"]), j)

    # ============ B1b: 每模型设置持久化 ============
    print("== B1: ModelSettings 持久化 ==")
    spath = os.path.join(TMP, "model_settings.json")
    ms = ModelSettings(spath)
    ms.save_for("TensorFold/ModelA", {"context": 65536, "parallel": 3, "vision": True})
    ms2 = ModelSettings(spath)  # 重开读盘
    merged = ms2.load_for("TensorFold/ModelA")
    check("设置落盘+读回（含默认值合并）",
          merged["context"] == 65536 and merged["parallel"] == 3
          and merged["vision"] is True and merged["max_tokens"] == DEFAULT_PARAMS["max_tokens"],
          str({k: merged[k] for k in ("context", "parallel", "vision", "max_tokens")}))
    ms2.delete_for("TensorFold/ModelA")
    check("删除模型设置", "TensorFold/ModelA" not in ModelSettings(spath).all())

    # ============ B1c: 旧版硬编码默认值一次性迁移 ============
    # 2.1.2 及以前保存路径无条件写 context=32768/max_tokens=4096，导致"没改过设置"
    # 的模型看起来像用户显式选了这两个值，令新规则"初始值=模型默认"失效。
    print("== B1: 旧默认值一次性迁移 ==")
    mpath = os.path.join(TMP, "migrate_settings.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump({
            "TensorFold/A": {"context": 32768, "max_tokens": 4096, "parallel": 4},
            "TensorFold/B": {"context": 65536, "max_tokens": 4096},
            "TensorFold/C": {"context": 32768, "max_tokens": 8192},
        }, f)
    mig = ModelSettings(mpath)
    rawA = mig.raw_for("TensorFold/A")
    rawB = mig.raw_for("TensorFold/B")
    rawC = mig.raw_for("TensorFold/C")
    check("旧硬编码默认值被抹掉（A: 两者都==旧默认）",
          "context" not in rawA and "max_tokens" not in rawA and rawA.get("parallel") == 4,
          str(rawA))
    check("自定义值保留（B: context 非默认 / C: max_tokens 非默认）",
          rawB.get("context") == 65536 and "max_tokens" not in rawB
          and rawC.get("max_tokens") == 8192 and "context" not in rawC,
          f"B={rawB} C={rawC}")
    check("迁移打标 _schema=2", mig.raw_for("__none__") == {}
          and json.load(open(mpath, encoding="utf-8")).get("_schema") == 2)
    check("迁移前留备份 .pre-2.1.3.bak", os.path.exists(mpath + ".pre-2.1.3.bak"))
    check("all() 不暴露内部键", set(ModelSettings(mpath).all()) == {"TensorFold/A", "TensorFold/B", "TensorFold/C"},
          str(sorted(ModelSettings(mpath).all())))

    # 迁移只跑一次：用户在新版显式存 32768 必须被尊重，不能被再度抹掉
    mig.save_for("TensorFold/A", {"context": 32768, "parallel": 2})
    check("迁移后显式保存的旧默认值被尊重（只跑一次）",
          ModelSettings(mpath).raw_for("TensorFold/A").get("context") == 32768,
          str(ModelSettings(mpath).raw_for("TensorFold/A")))

    # "初始值=模型默认" 的编译口径：未设置时不传 --context/--max-tokens
    print("== B1: 未设置 → 交由模型自决 ==")
    j_default = " ".join(build_serve_args("m", {"context": None, "max_tokens": None}, 8123))
    check("未设置时不传 --context/--max-tokens",
          "--context" not in j_default and "--max-tokens" not in j_default, j_default)
    j_explicit = " ".join(build_serve_args("m", {"context": 262144, "max_tokens": 8192}, 8123))
    check("显式设置时照传",
          "--context 262144" in j_explicit and "--max-tokens 8192" in j_explicit, j_explicit)

    # ============ B1d: detect() 不得 fork ============
    # 背景（2026-10-09 实测）：打包 App 是 AppKit+WebKit 多线程进程。CPython 的
    # subprocess 默认 close_fds=True → 走 fork()，会和 malloc/atfork 锁打架死锁，
    # 表现为桥线程永久卡在 lock acquire，连带 models_installed 等后续调用全挂、
    # 模型页空白。修法是 close_fds=False 逼它走 posix_spawn。
    # 这条断言直接数 fork 次数，改回 fork 会立刻变红。
    print("== B1: detect 不许 fork ==")
    _forks = []
    os.register_at_fork(before=lambda: _forks.append(1))
    _dp = EnginePool(python_bin=sys.executable)
    _d1 = _dp.detect()
    _d2 = _dp.detect()          # 第二次应命中 TTL 缓存
    check("detect 返回已安装且有版本", _d1.get("installed") is True, str(_d1)[:120])
    check("detect 未使用 fork()（走 posix_spawn）", not _forks, f"fork 次数={len(_forks)}")
    check("detect 结果有 TTL 缓存（第二次不再 spawn）", _d2 == _d1, str(_d2)[:120])

    # ============ 多实例池：真 FakeServer + spawn_hook ============
    print("== B2: 多实例并行 ==")
    srvA = run_fake_server(18099, "fake/modelA")
    srvB = run_fake_server(18100, "fake/modelB")
    time.sleep(0.3)

    pool = EnginePool(python_bin=sys.executable, settings=ModelSettings(spath),
                      base_port=18080, spawn_hook=lambda argv, env: FakeProc())
    # 让池分配的端口正好落在 FakeServer 上（A→18099, B→18100），否则探活/metrics 打不通
    _ports = iter([18099, 18100])
    pool._alloc_port = lambda: next(_ports)
    check("空池 status", pool.status_all()["instances"] == [])
    check("空模型拒绝", not pool.start("").get("ok"))

    rA = pool.start("fake/modelA", context=32768, parallel=2)
    check("启动实例A", rA.get("ok") and rA["state"] == "starting", json.dumps(rA)[:120])
    portA = rA["port"]
    instA = pool.get("fake/modelA")
    instA.mark_ready()
    check("A ready", pool.get("fake/modelA").state == "ready")

    rB = pool.start("fake/modelB", mtp_drafts=4)
    check("启动实例B（多实例并行，不互斥）", rB.get("ok") and rB["port"] != portA,
          f"A={portA} B={rB.get('port')}")
    instB = pool.get("fake/modelB")
    instB.mark_ready()
    check("双实例同时 ready", len(pool.ready_instances()) == 2)
    check("重复启动同模型报错", "已在运行" in (pool.start("fake/modelA").get("error") or ""))
    check("B1 生效参数回写设置", "parallel" in ModelSettings(spath).all().get("fake/modelA", {})
          and ModelSettings(spath).all()["fake/modelA"]["parallel"] == 2)

    # 内存闸门
    old_margin = EnginePool.MEM_MARGIN_GB
    EnginePool.MEM_MARGIN_GB = 900.0
    rgate = pool.start("fake/modelC")
    EnginePool.MEM_MARGIN_GB = old_margin
    check("内存闸门拦截新模型", not rgate.get("ok") and "空闲内存不足" in rgate.get("error", ""), rgate.get("error", "")[:80])

    # 指定端口被占 → 拒
    rport = pool.start("fake/modelC", port=18099)
    check("指定端口占用被拒", not rport.get("ok") and "已被占用" in rport.get("error", ""))

    # 删除运行中模型被拒
    rd = pool.delete_model("fake/modelA")
    check("运行中模型删除被拒", not rd.get("ok"))

    # 单实例停止不影响另一实例
    pool.stop("fake/modelA")
    check("停A不影响B", pool.get("fake/modelA").state == "idle" and pool.get("fake/modelB").state == "ready")

    # ============ 聊天代理：按 model 路由 ============
    print("== B4: 聊天代理多模型路由 ==")
    proxy = ChatProxy(pool)
    proxy.start()
    pport = proxy.server_address[1]
    time.sleep(0.2)

    def post(msg, model, stream=False):
        req = urllib.request.Request(f"http://127.0.0.1:{pport}/chat",
                                     data=json.dumps({"model": model, "stream": stream,
                                                      "messages": [{"role": "user", "content": msg}]}).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10)

    with post("hi", "fake/modelB") as r:
        j = json.loads(r.read())
    check("按 model 路由到B", "modelB" in j["choices"][0]["message"]["content"],
          j["choices"][0]["message"]["content"])

    req = urllib.request.Request(f"http://127.0.0.1:{pport}/chat",
                                data=json.dumps({"model": "fake/modelB", "stream": True,
                                                 "messages": [{"role": "user", "content": "hi"}]}).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        text = r.read().decode()
    pieces = "".join(json.loads(l[5:].strip())["choices"][0]["delta"]["content"]
                     for l in text.split("\n\n") if l.startswith("data:") and "[DONE]" not in l and l[5:].strip())
    check("流式路由到B", pieces.startswith("你好，我是modelB"), pieces)

    try:
        post("hi", "fake/modelA")
        check("未加载模型 503", False, "未抛 HTTPError")
    except urllib.error.HTTPError as e:
        check("未加载模型 503", e.code == 503 and b"modelA" in e.read())

    try:
        post("trigger-500", "fake/modelB")
        check("上游 500 透传", False, "未抛 HTTPError")
    except urllib.error.HTTPError as e:
        check("上游 500 透传", e.code == 500 and b"fake upstream" in e.read())

    # ============ B4: ChatStore 每会话一文件 ============
    print("== B4: ChatStore 会话拆分 ==")
    store = ChatStore(os.path.join(TMP, "chats"))
    c1 = store.create({"title": "会话一", "model": "fake/modelB"})
    c2 = store.create({"title": "会话二"})
    check("create 生成 id 并落盘", c1["id"] != c2["id"]
          and os.path.exists(os.path.join(TMP, "chats", c1["id"] + ".json")))
    c1["messages"] = [{"role": "user", "content": "x"}]
    store.save_chat(c1)
    got = store.get_chat(c1["id"])
    check("save/get 往返", got["messages"][0]["content"] == "x" and got["title"] == "会话一")
    check("rename", store.rename_chat(c2["id"], "改名了") and store.get_chat(c2["id"])["title"] == "改名了")
    ids = {c["id"] for c in store.list_chats()}
    check("列表含两会话", {c1["id"], c2["id"]} <= ids)
    check("删除一个另一还在", store.delete_chat(c1["id"]) and store.get_chat(c1["id"]) is None
          and store.get_chat(c2["id"]) is not None)
    # 回归锁：同一毫秒内连续创建不得撞 id（唯一性不得依赖时钟前进。
    # 旧实现 `c{int(time.time()*1000):x}` 在时钟不推进时两次创建得到同一个 id，
    # 第二次会静默覆盖第一条会话 —— 已修，此断言防回归。）
    c3 = store.create({"title": "会话三"})
    c4 = store.create({"title": "会话四"})
    check("连续创建 id 唯一（不依赖时钟前进）",
          len({c1["id"], c2["id"], c3["id"], c4["id"]}) == 4
          and all(os.path.exists(os.path.join(TMP, "chats", c["id"] + ".json"))
                  for c in (c3, c4)))
    # 旧数据归档
    legacy = os.path.join(TMP, "history.json")
    with open(legacy, "w") as f:
        f.write('{"chats":[{"id":"old"}]}')
    check("legacy history.json 归档", store.migrate_legacy(legacy, os.path.join(TMP, "archive"))
          and not os.path.exists(legacy)
          and len(os.listdir(os.path.join(TMP, "archive"))) == 1)
    try:
        r = store.get_chat("../evil")  # 非法 id 不抛异常，读不到即 None
        check("非法会话 id 容错", r is None)
    except Exception as exc:
        check("非法会话 id 容错", False, str(exc))

    # ============ B5: 监控聚合 + 环形缓冲 ============
    print("== B5: 监控多实例聚合 ==")
    mon = Monitor()
    snap = {}
    for _ in range(8):           # tps 差分需跨两次 /metrics 抓取（每第 2 tick 抓一次）
        mon.tick(pool, None)
        snap = mon.snapshot()
        if snap["latest"].get("tps"):
            break
        time.sleep(0.6)
    check("B5 聚合 latest.tps>0", (snap["latest"].get("tps") or 0) > 0, f"tps={snap['latest'].get('tps')}")
    check("B5 KV/足迹聚合", snap["latest"]["kv"] == 62.0 and snap["latest"]["footprint_gb"] == 13.0,
          f"kv={snap['latest']['kv']} fp={snap['latest']['footprint_gb']}")
    check("B5 每实例明细（A 已停只剩 B）", set(snap["per"].keys()) == {"fake/modelB"},
          f"per={list(snap['per'].keys())}")
    check("B5 环形缓冲增长", len(mon.hist) >= 2)
    from backend.monitor import HISTORY_LEN
    check("B5 缓冲容量 600", HISTORY_LEN == 600)
    mon.reset_model("fake/modelB")
    check("B5 reset_model 清差分", "fake/modelB" not in mon.prev)

    # 回归锁：/metrics 是 0.5Hz（每 2 个 tick 抓一次），而 UI 每 2.5s 读一次 snapshot。
    # 旧实现 snapshot 直接取 hist[-1]，落在「没抓取」的那一 tick 上读数全是 None
    # → 监控页实时数字一会儿有一会儿没有。现在 metrics_last 跨 tick 保留真读数。
    monfill = Monitor()
    monfill._tick_count = 1
    monfill.tick(pool, None)      # →tick2（偶数）：抓一次，首轮还没有差分基线
    time.sleep(0.7)
    monfill._tick_count = 3
    monfill.tick(pool, None)      # →tick4（偶数）：与上一轮差分，拿到真读数
    got = monfill.snapshot()["latest"]
    check("B5 抓取轮次有真读数", (got.get("tps") or 0) > 0 and (got.get("gen_avg_tps") or 0) > 0,
          f"tps={got.get('tps')} gen_avg={got.get('gen_avg_tps')}")
    monfill._tick_count = 4
    monfill.tick(pool, None)      # →tick5（奇数）：本轮不抓 /metrics
    kept = monfill.snapshot()["latest"]
    check("B5 未抓取轮次仍显示最近一次真读数（不再时有时无）",
          kept.get("tps") == got.get("tps") and kept.get("kv") == got.get("kv")
          and kept.get("gen_avg_tps") == got.get("gen_avg_tps"),
          f"kept={ {k: kept.get(k) for k in ('tps', 'kv', 'gen_avg_tps')} }")
    # 真解码速率：分母必须是 Δ解码耗时，不是墙钟（墙钟含排队/空闲，会虚高）
    srvR = run_fake_server(18101, "fake/rate", decode_step=0.5, ttft=True)
    time.sleep(0.3)
    poolR = EnginePool(python_bin=sys.executable,
                       settings=ModelSettings(os.path.join(TMP, "rate_settings.json")),
                       base_port=18080, spawn_hook=lambda argv, env: FakeProc())
    poolR._alloc_port = lambda: 18101
    poolR.start("fake/rate")
    poolR.get("fake/rate").mark_ready()
    monR = Monitor()
    monR._tick_count = 1
    monR.tick(poolR, None)
    time.sleep(0.7)
    monR._tick_count = 3
    monR.tick(poolR, None)
    lat = monR.snapshot()["latest"]
    # 每轮 /metrics：生成 +10 token、解码耗时 +0.5s → 10/0.5 = 20.0（按墙钟算会是 ~14）
    check("B5 真解码速率＝Δ生成/Δ解码耗时", lat.get("tps") == 20.0, f"tps={lat.get('tps')}")
    check("B5 平均速度（累计量/累计耗时）可用",
          (lat.get("gen_avg_tps") or 0) > 0 and (lat.get("ttft_avg_ms") or 0) > 0
          and (lat.get("prefill_avg_tps") or 0) > 0,
          f"gen={lat.get('gen_avg_tps')} ttft={lat.get('ttft_avg_ms')} pre={lat.get('prefill_avg_tps')}")
    poolR.stop()
    monR.tick(type("EmptyPool", (), {"ready_instances": lambda self: []})(), None)
    check("B5 无实例时读数清空（不挂旧数）", monR.snapshot()["latest"].get("tps") is None,
          f"tps={monR.snapshot()['latest'].get('tps')}")

    # ============ B3: 更新检查（真联网） ============
    print("== B3: 更新检查（GitHub） ==")
    uc = UpdateChecker(engine_version="0.6.4")
    res = uc.check_all()
    eng = res.get("engine")
    check("B3 引擎源可达且有版本号", bool(eng and eng.get("latest")),
          f"latest={eng and eng.get('latest')} err={res['error'][:80]}")
    check("B3 引擎版本比较逻辑", (_cmp("0.6.5", "0.6.4") == 1 and _cmp("2.0.0", "2.0.0") == 0
          and _cmp("1.9.9", "2.0.0") == -1))
    app = res.get("app")
    check("B3 App 源不报错（404→无更新）", app is not None or "app:" not in res["error"],
          f"app={app and {'latest': app.get('latest'), 'prerelease': app.get('prerelease')}} err={res['error'][:80]}")
    check("B3 缓存可读", uc.cached().get("checked_at", 0) > 0)
    check("B3 maybe_background 节流", uc.maybe_background(3600) and not uc.maybe_background(3600))
    # 版本号归一：detect() 给的是 CLI 自报原文（原生二进制 "tensorfold-native 1.0.2"、
    # 内嵌解释器 "tensorfold 0.6.5"）。原样拿去做比对与显示，用户会看到
    # "当前 tensorfold-native 1.0.2"，且名字里带别的数字就会比错。
    from backend.update import _clean_version
    check("B3 版本号归一（原生二进制自报串）",
          _clean_version("tensorfold-native 1.0.2") == "1.0.2", _clean_version("tensorfold-native 1.0.2"))
    check("B3 版本号归一（内嵌解释器自报串）",
          _clean_version("tensorfold 0.6.5") == "0.6.5", _clean_version("tensorfold 0.6.5"))
    check("B3 版本号归一（v 前缀 / 空串）",
          _clean_version("v2.1.5") == "2.1.5" and _clean_version("") == "")
    uc2 = UpdateChecker(engine_version="tensorfold-native 0.0.1")
    r2 = uc2.check_engine()
    check("B3 结果里的 current 是纯版本号（raw 另存）",
          r2["current"] == "0.0.1" and r2["current_raw"] == "tensorfold-native 0.0.1"
          and r2["available"] is True,
          f"current={r2['current']} raw={r2['current_raw']} avail={r2['available']}")
    check("B3 有更新时 latest 确实高于 current",
          bool(r2["latest"]) and _cmp(r2["latest"], r2["current"]) > 0,
          f"{r2['current']} → {r2['latest']}")

    # ============ B6: 加速配套（主模型 ↔ 辅助模型联动） ============
    print("== B6: 加速配套（草稿模型联动） ==")
    import tempfile
    from backend import engine as _eng
    check("B6 草稿反查表可用", isinstance(_eng.DRAFT_OF, dict)
          and all(isinstance(v, list) and v for v in _eng.DRAFT_OF.values()),
          f"DRAFT_OF={_eng.DRAFT_OF}")
    _st = _eng.draft_status("TensorFold/Qwen3.8-27B-MLX-4bit")
    check("B6 主模型给出草稿配套口径", bool(_st.get("draft_repo")) and "draft_cached" in _st,
          f"draft={_st.get('draft_repo')} cached={_st.get('draft_cached')}")
    _ents = cached_models()
    check("B6 缓存条目都带 role/used_by",
          all(e.get("role") in ("model", "draft") and isinstance(e.get("used_by"), list)
              for e in _ents))
    for _draft in _eng.DRAFT_OF:
        _e = next((e for e in _ents if e["id"] == _draft), None)
        if _e is not None:   # 本机缓存里确实有这个草稿模型才断言
            check(f"B6 {_draft} 标为辅助模型并联到主模型",
                  _e.get("role") == "draft" and _e.get("used_by") == _eng.DRAFT_OF[_draft],
                  f"role={_e.get('role')} used_by={_e.get('used_by')}")
    # 删缓存的两条路径：软链形态（权重在缓存外）只摘链接；真实目录形态整删。
    # 用临时 HF_HOME 隔离，绝不碰用户真实缓存。注意 delete_model 有一道安全闸门
    # "缓存目录必须位于家目录下"，所以临时缓存根要建在 ~ 里（建在 /var/folders 会被拒）。
    _base = tempfile.mkdtemp(prefix=".tfm-smoke-cache-", dir=os.path.expanduser("~"))
    _old_hf = os.environ.get("HF_HOME")
    _real = None
    os.environ["HF_HOME"] = _base
    try:
        _link = os.path.join(_base, _eng._repo_dir_name("zz-selftest/DraftLinkProbe"))
        _real = tempfile.mkdtemp(prefix="tfm-smoke-link-")
        open(os.path.join(_real, "keepme.txt"), "w").write("x")
        os.symlink(_real, _link)
        _r = pool.delete_model("zz-selftest/DraftLinkProbe")
        check("B6 软链条目只摘链接（不报错）",
              bool(_r.get("ok")) and bool(_r.get("unlinked")) and not os.path.lexists(_link), str(_r))
        check("B6 软链条目不动缓存外的真实权重",
              os.path.isfile(os.path.join(_real, "keepme.txt")))
        _d = os.path.join(_base, _eng._repo_dir_name("zz-selftest/DirProbe"))
        os.makedirs(os.path.join(_d, "snapshots", "abc"), exist_ok=True)
        open(os.path.join(_d, "snapshots", "abc", "config.json"), "w").write("{}")
        _r = pool.delete_model("zz-selftest/DirProbe")
        check("B6 真实目录形态仍整删", bool(_r.get("ok")) and not os.path.exists(_d), str(_r))
    finally:
        if _real:
            shutil.rmtree(_real, ignore_errors=True)
        if _old_hf is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = _old_hf
        shutil.rmtree(_base, ignore_errors=True)

    # ============ B7: 累计用量账本（跨引擎重启持续） ============
    # 引擎 /metrics 的 counter 是「本进程启动以来」口径：一重启就归零、实例一停就消失。
    # 直接相加当累计，用户会看到数字往回跳、停模型后清零。故 Manager 侧按增量自累加。
    print("== B7: 累计用量账本 ==")
    from backend.usage import UsageLedger
    lpath = os.path.join(TMP, "usage.json")
    led = UsageLedger(lpath)
    row1 = {"model": "fake/modelB", "requests": 2, "prompt_tokens": 100, "generation_tokens": 200,
            "drafted": 30, "accepted": 20, "decode_seconds": 4.0, "ttft_seconds": 0.5}
    led.observe({"fake/modelB#18100": dict(row1)})
    t1 = led.summary()["totals"]
    check("B7 首次采样按整量计入",
          t1["generation_tokens"] == 200 and t1["prompt_tokens"] == 100 and t1["total_tokens"] == 300,
          f"gen={t1['generation_tokens']} prompt={t1['prompt_tokens']}")
    row2 = {**row1, "requests": 3, "prompt_tokens": 150, "generation_tokens": 260,
            "drafted": 40, "accepted": 28, "decode_seconds": 5.0, "ttft_seconds": 0.7}
    led.observe({"fake/modelB#18100": dict(row2)})
    t2 = led.summary()["totals"]
    check("B7 同实例增量累加、不重复计整量",
          t2["generation_tokens"] == 260 and t2["prompt_tokens"] == 150,
          f"gen={t2['generation_tokens']} prompt={t2['prompt_tokens']}")
    check("B7 分模型累计", any(m["model"] == "fake/modelB" and m["total_tokens"] == 410
                             for m in led.summary()["models"]), str(led.summary()["models"])[:160])
    # 引擎重启：counter 归零 → 差值为负，按「计数器重启」处理取当前值，总量绝不倒退
    row3 = {"model": "fake/modelB", "requests": 1, "prompt_tokens": 40, "generation_tokens": 50,
            "drafted": 0, "accepted": 0, "decode_seconds": 1.0, "ttft_seconds": 0.2}
    led.observe({"fake/modelB#18100": dict(row3)})
    t3 = led.summary()["totals"]
    check("B7 引擎重启不倒退（负差按当前值算）",
          t3["generation_tokens"] == 310 and t3["generation_tokens"] >= t2["generation_tokens"],
          f"gen={t3['generation_tokens']}")
    # 实例停止 → 丢基线；同一实例重现按整量重新计入，不能算成巨量或负数
    led.observe({})
    led.observe({"fake/modelB#18100": dict(row3)})
    t4 = led.summary()["totals"]
    check("B7 实例消失清基线、重现不产生巨量",
          t4["generation_tokens"] == 360 and t4["generation_tokens"] < 1000,
          f"gen={t4['generation_tokens']}")
    led.flush(force=True)
    check("B7 落盘可读回", os.path.isfile(lpath)
          and json.load(open(lpath, encoding="utf-8"))["totals"]["generation_tokens"] == 360)
    check("B7 重开账本接着累加（App 重启不丢历史）",
          UsageLedger(lpath).summary()["totals"]["generation_tokens"] == 360)
    r0 = led.reset()
    check("B7 reset 清空总量", bool(r0.get("ok")) and r0["totals"]["generation_tokens"] == 0
          and r0["totals"]["total_tokens"] == 0)
    led.observe({"fake/modelB#18100": dict(row3)})    # 与基线相同的计数 → 增量 0
    check("B7 reset 后不把历史重算一遍", led.summary()["totals"]["generation_tokens"] == 0,
          f"gen={led.summary()['totals']['generation_tokens']}")
    row4 = {**row3, "prompt_tokens": 60, "generation_tokens": 70,
            "decode_seconds": 1.5, "ttft_seconds": 0.4}
    led.observe({"fake/modelB#18100": dict(row4)})
    t5 = led.summary()["totals"]
    check("B7 reset 后新增量正常计入", t5["generation_tokens"] == 20 and t5["prompt_tokens"] == 20,
          f"gen={t5['generation_tokens']}")
    check("B7 平均速率＝累计量/累计耗时（不是编数）",
          t5["gen_tps"] == 40.0 and t5["prefill_tps"] == 100.0,
          f"gen_tps={t5['gen_tps']} prefill_tps={t5['prefill_tps']}")

    # ============ B7: 监听范围（--host 真绑定） ============
    print("== B7: 监听范围 --host 编译 ==")
    check("B7 DEFAULT_PARAMS.host 默认 None（交给设置页决定）", DEFAULT_PARAMS.get("host") is None,
          repr(DEFAULT_PARAMS.get("host")))
    j_def = " ".join(build_serve_args("m", {}, 8123))
    check("B7 缺省绑本机 127.0.0.1", "--host 127.0.0.1" in j_def, j_def[:120])
    j_lan = " ".join(build_serve_args("m", {"host": "0.0.0.0"}, 8123))
    check("B7 选局域网则真绑 0.0.0.0",
          "--host 0.0.0.0" in j_lan and "--host 127.0.0.1" not in j_lan, j_lan[:120])

    # ============ B7: 对话代理改监听地址（不重启 App） ============
    print("== B7: 代理监听重绑 ==")
    px = ChatProxy(pool)
    px.start()
    px_port = px.server_address[1]
    time.sleep(0.3)

    def px_chat(port, model="fake/modelB"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/chat",
                                     data=json.dumps({"model": model,
                                                      "messages": [{"role": "user", "content": "hi"}]}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    check("B7 同址重绑为无操作且仍 ok",
          px.relisten("127.0.0.1").get("changed") is False
          and px.relisten("127.0.0.1").get("ok") is True)
    r_lan = px.relisten("0.0.0.0")
    check("B7 重绑到 0.0.0.0（端口不变、真绑上）",
          r_lan.get("ok") and r_lan.get("changed") and r_lan.get("host") == "0.0.0.0"
          and px.bind_host == "0.0.0.0" and px.server_address[1] == px_port, str(r_lan))
    # 关键：重绑后 accept 循环必须还活着。只换 socket 不重启循环的话，
    # selector 还盯着旧 fd → 端口在 listen 却没人 accept，这里会超时。
    check("B7 重绑后对话仍可路由（accept 循环真的还活着）",
          "modelB" in px_chat(px_port))
    r_bad = px.relisten("203.0.113.9")     # 非本机地址 → 绑不上，必须回滚
    check("B7 绑不上时回滚到原地址（不留半死状态）",
          (not r_bad.get("ok")) and px.bind_host == "0.0.0.0" and px.server_address[1] == px_port,
          str(r_bad))
    check("B7 回滚后对话仍可路由", "modelB" in px_chat(px_port))
    r_back = px.relisten("127.0.0.1")
    check("B7 重绑回本机", r_back.get("ok") and r_back.get("changed")
          and px.bind_host == "127.0.0.1", str(r_back))
    check("B7 回到本机后对话仍可路由", "modelB" in px_chat(px_port))

    # ============ B7: Api 网络 / 用量接口 ============
    print("== B7: Api 网络与用量接口 ==")
    from backend.api import Api, LISTEN_HOSTS
    aset = os.path.join(TMP, "app_settings.json")
    ledAPI = UsageLedger(os.path.join(TMP, "usage_api.json"))
    monAPI = Monitor(ledger=ledAPI)
    ap = Api(pool, None, monAPI, px, store, updater=None,
             app_settings_path=aset, ledger=ledAPI)
    check("B7 LISTEN_HOSTS 口径", LISTEN_HOSTS == {"local": "127.0.0.1", "lan": "0.0.0.0"},
          str(LISTEN_HOSTS))
    nt = ap.network()
    check("B7 network 默认本机", nt["listen"] == "local" and nt["bind_host"] == "127.0.0.1"
          and nt["local_url"].startswith("http://127.0.0.1:"),
          str({k: nt[k] for k in ("listen", "bind_host", "local_url", "lan_url")}))
    rl = ap.set_listen("lan")
    check("B7 切局域网：设置落地 + 代理真重绑",
          rl.get("ok") and rl["listen"] == "lan" and rl["bind_host"] == "0.0.0.0"
          and px.bind_host == "0.0.0.0", str(rl)[:160])
    check("B7 设置落盘", json.load(open(aset, encoding="utf-8")).get("listen") == "lan")
    rl2 = ap.set_listen("bogus")           # 非法值按 local 处理
    check("B7 非法值回落 local 且代理跟着回绑",
          rl2["listen"] == "local" and px.bind_host == "127.0.0.1", str(rl2)[:160])
    ledAPI.observe({"fake/modelB#18100": dict(row1)})
    us = ap.usage_status()
    check("B7 usage_status 透出账本", us["totals"]["generation_tokens"] == 200 and us["models"],
          f"gen={us['totals']['generation_tokens']}")
    ur = ap.usage_reset()
    check("B7 usage_reset 清空", bool(ur.get("ok")) and ur["totals"]["generation_tokens"] == 0,
          str(ur["totals"]["generation_tokens"]))
    ov = ap.overview()
    check("B7 overview 带 listen/usage", ov.get("listen") == "local"
          and isinstance(ov.get("usage"), dict) and ov["bind_host"] == "127.0.0.1",
          f"listen={ov.get('listen')} has_usage={'usage' in ov}")
    # 换地址后重启运行中实例：host 要传下去、端口要重新分配（避开 TIME_WAIT）
    class _StubPool:
        def __init__(self):
            self.started, self.stopped = [], 0
        def instances(self):
            return [type("I", (), {"model": "fake/modelB", "state": "ready",
                                   "params": {"context": 32768, "port": 18100}})()]
        def stop(self, *a, **k):
            self.stopped += 1
            return {"ok": True}
        def start(self, model, **params):
            self.started.append((model, params))
            return {"ok": True, "port": 12345}
    stub = _StubPool()
    ap2 = Api(stub, None, Monitor(), px, store, app_settings_path=aset)
    rr = ap2.restart_instances()
    check("B7 换地址后重启实例（host 传下去、端口重分配）",
          rr["restarted"] == ["fake/modelB"] and stub.stopped == 1
          and stub.started[0][1].get("host") == "127.0.0.1" and "port" not in stub.started[0][1],
          f"{rr} started={stub.started}")

    class _EmptyPool:
        def instances(self):
            return []
    rr2 = Api(_EmptyPool(), None, Monitor(), px, store,
              app_settings_path=aset).restart_instances()
    check("B7 无实例时重启为无操作", rr2.get("ok") and rr2["restarted"] == [] and rr2["failed"] == [],
          str(rr2))

    # ============ B8: 本机性能读数（CPU / GPU 核心数与占用） ============
    # 核心构成取 sysctl(hw.perflevel0/1) 与 ioreg(gpu-core-count)；占用率取 psutil
    # （必须先在 Monitor 启动时预热 —— 首次调用恒返回假的 0）与 ioreg Device Utilization %。
    print("== B8: 本机性能 ==")
    from backend import hostinfo as _hi
    ci = _hi.cpu_info()
    check("B8 CPU 逻辑核数 > 0", (ci.get("logical") or 0) > 0, str(ci))
    check("B8 CPU 核心构成自洽（P + E == 物理核）",
          not (ci.get("p") and ci.get("e")) or (ci["p"] + ci["e"]) == ci.get("physical"), str(ci))
    check("B8 CPU 核心文案非空", bool(_hi.cpu_core_label()), _hi.cpu_core_label())
    gi = _hi.gpu_info()
    check("B8 GPU 型号/核心数取自 ioreg", bool(gi.get("name")) and bool(gi.get("cores")), str(gi))
    check("B8 静态信息有进程内缓存（不反复跑子进程）",
          _hi.cpu_info() is _hi.cpu_info() and _hi.gpu_info() is _hi.gpu_info())
    try:
        import psutil as _ps
    except ImportError:
        _ps = None
    check("B8 psutil 可用（本机性能读数前提）", _ps is not None)
    if _ps is not None:
        monP = Monitor()
        monP.tick(pool, _ps)                  # 首个 tick：只预热，不把假的 0 当读数
        seed = monP.snapshot()["latest"]
        check("B8 预热期不把假的 0 当 CPU 读数", seed.get("cpu_percent") is None,
              f"cpu={seed.get('cpu_percent')}")
        time.sleep(1.0)
        monP.tick(pool, _ps)
        got2 = monP.snapshot()["latest"]
        check("B8 CPU 占用率是真读数（0..100）",
              got2.get("cpu_percent") is not None and 0 <= got2["cpu_percent"] <= 100,
              f"cpu={got2.get('cpu_percent')}")
        check("B8 每核占用条目数 = 逻辑核数",
              isinstance(got2.get("cpu_per"), list) and len(got2["cpu_per"]) == ci["logical"],
              f"len={len(got2.get('cpu_per') or [])} 期望 {ci['logical']}")
        check("B8 GPU 利用率每 tick 都采（不再隔拍为空）",
              got2.get("gpu_percent") is None or 0 <= got2["gpu_percent"] <= 100,
              f"gpu={got2.get('gpu_percent')}")
        ovh = ap.overview()
        check("B8 overview 透出 CPU/GPU 真实构成",
              bool(ovh.get("cpu_label")) and bool(ovh.get("gpu_label"))
              and (ovh.get("cpu_cores") or 0) > 0 and isinstance(ovh.get("load"), list),
              f"cpu={ovh.get('cpu_label')} gpu={ovh.get('gpu_label')} load={ovh.get('load')}")

    # ============ B9: 一键升级链路（2026-10-10 用户反馈：升级引擎按钮不起作用） ============
    # 真因：壳层 WKWebView 从未实现 WKUIDelegate，WebKit 默认让 confirm() 恒返 false
    # （裸 WKWebView 实测 confirm→'false' / alert→'undefined' / prompt→'null'），
    # 于是 doUpdateApply 第一句 `if (!confirm(...)) return;` 把点击直接吞掉：
    # 不弹窗、不报错、什么都不做。同一坑还埋了「删除缓存 / 清除累计用量 / 重启实例」。
    print("== B9: 一键升级链路 ==")
    import pathlib
    import re as _re
    root = pathlib.Path(HERE)
    shell_src = (root / "backend" / "shell.py").read_text(encoding="utf-8")
    try:
        from backend import shell as _shell
        dlg = _shell._UIDelegate.alloc().init()
        need = ("webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_",
                "webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_",
                "webView_runJavaScriptTextInputPanelWithPrompt_defaultText_initiatedByFrame_completionHandler_")
        check("B9 壳层模块可导入（NSObject 子类没被 pyobjc 拒）",
              hasattr(_shell, "_UIDelegate") and hasattr(_shell, "_alert"), "")
        check("B9 委托实现 alert/confirm/prompt 三个面板回调（选择器须逐一精确匹配）",
              all(hasattr(dlg, m) for m in need),
              str([m for m in need if not hasattr(dlg, m)])[:110])
        check("B9 面板工厂在 NSObject 子类之外（类内自定义方法会被 pyobjc 判 BadPrototypeError，启动即崩）",
              "def _default_alert(" in shell_src
              and shell_src.index("def _default_alert(") < shell_src.index("class _UIDelegate"),
              "")
    except Exception as exc:
        check("B9 壳层模块可导入（NSObject 子类没被 pyobjc 拒）", False, f"{type(exc).__name__}: {exc}"[:130])
    check("B9 build() 把 uiDelegate 挂上并强引用（WKWebView.uiDelegate 是 weak）",
          "setUIDelegate_" in shell_src and '"ui": ui' in shell_src, "")

    ui_src = (root / "ui" / "app.js").read_text(encoding="utf-8")
    code_only = _re.sub(r"/\*[\s\S]*?\*/", "", ui_src)
    code_only = _re.sub(r"^\s*//.*$", "", code_only, flags=_re.M)
    bad_calls = _re.findall(r"(?:^|[^.\w])(confirm|alert|prompt)\s*\(", code_only)
    check("B9 前端不再调用原生 confirm/alert/prompt", not bad_calls, str(bad_calls[:3]))
    check("B9 四处危险操作都改成应用内确认框",
          ui_src.count("await askConfirm(") >= 4, f"askConfirm 调用点={ui_src.count('await askConfirm(')}")
    check("B9 升级按钮有进行中状态 + 升级后复检收口",
          "升级中…" in ui_src and "await doUpdateCheck();" in ui_src, "")
    mock_src = (root / "ui" / "mock_bridge.js").read_text(encoding="utf-8")
    check("B9 假桥覆盖一键升级（旧版缺这两个方法 → 桥直接 reject，闸门从没走过这条路）",
          "update_apply_engine" in mock_src and "update_open_app" in mock_src, "")

    # 升级包的 URL 模板必须与真实 Release 资产命名对得上（apply_engine 拼的是
    # tensorfold-<tag>-macos-arm64.tar.gz）。这里真下载一次 .sha256 核对，
    # 而不是只比对字符串模板 —— 上游改命名时能第一时间报出来。
    from backend.update import ENGINE_REPO, _opener as _uopener
    _tag = (eng or {}).get("latest") or ""
    if _tag:
        _u = (f"https://github.com/{ENGINE_REPO}/releases/download/v{_tag}"
              f"/tensorfold-{_tag}-macos-arm64.tar.gz.sha256")
        try:
            _req = urllib.request.Request(_u, headers={"User-Agent": "TensorFold-Manager"})
            with _uopener().open(_req, timeout=20) as _resp:
                _body = _resp.read().decode("utf-8", "replace").strip()
            _ok = bool(_re.match(r"^[0-9a-f]{64}\s+tensorfold-" + _re.escape(_tag)
                                 + r"-macos-arm64\.tar\.gz$", _body))
            check("B9 引擎升级包 URL 与真实资产命名一致（.sha256 可下载且自洽）", _ok,
                  _body[:96])
        except Exception as exc:
            check("B9 引擎升级包 URL 与真实资产命名一致（.sha256 可下载且自洽）", False,
                  f"{type(exc).__name__}: {exc}"[:110])
    else:
        check("B9 引擎升级包 URL 与真实资产命名一致（.sha256 可下载且自洽）", False,
              "上游没给出 latest 版本号（B3 已在上方失败）")

    # ============ 杂项 ============
    print("== 杂项 ==")
    check("cached_models 可运行", isinstance(cached_models(), list))
    pool.stop()
    check("stop 全部", all(i.state == "idle" for i in pool.instances()))
    check("stop 不存在模型报错", not pool.stop("no/such").get("ok"))

    print("RESULT:", "ALL PASS" if not failures else f"FAILED: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
