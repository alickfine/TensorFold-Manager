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


def run_fake_server(port: int, model: str = "fake/model"):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"gen": 260}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            elif self.path == "/metrics":
                state["gen"] += 10
                payload = METRICS_TEXT.format(gen=state["gen"]).encode()
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
