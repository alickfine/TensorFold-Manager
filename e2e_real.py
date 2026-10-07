# -*- coding: utf-8 -*-
"""E2 真机 E2E：真实引擎、真实对话、真实端口。

用一次性 Api 实例（与真壳同一装配），逐步断言并打印证据。
前提：27B 模型已缓存；不依赖 UI（UI 由 CGWindow 截图 + 闸门另行验收）。
"""
import json
import os
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MODEL = "TensorFold/Qwen3.8-27B-MLX-4bit"
CTX = 8192  # E2E 用小上下文省内存
results = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    results.append((tag, name, detail))
    print(f"[{tag}] {name} {detail}", flush=True)
    return cond


def main():
    from backend.api import Api
    from backend.chat import ChatProxy, ChatStore
    from backend.engine import EnginePool, ModelSettings, find_launcher
    from backend.monitor import Monitor
    from backend.update import UpdateChecker

    data = os.path.expanduser("~/.tensorfold-manager")
    launcher = find_launcher(HERE)
    print(f"launcher: {launcher}")
    pool = EnginePool(python_bin=launcher,
                      settings=ModelSettings(os.path.join(data, "model_settings_e2e.json")))
    monitor = Monitor()
    store = ChatStore(os.path.join(data, "chats_e2e"))
    proxy = ChatProxy(pool)
    proxy.start()
    port = proxy.server_address[1]
    updater = UpdateChecker()
    api = Api(pool, None, monitor, proxy, store, updater,
              app_settings_path=os.path.join(data, "app_settings_e2e.json"))
    print(f"chat proxy :127.0.0.1:{port}", flush=True)

    try:
        # 1. 模型安装检测
        installed = api.models_installed()
        hit = [m for m in installed if m["id"] == MODEL]
        check("E2-1 已缓存 27B 模型", bool(hit), str([m["id"] for m in installed]))

        # 2. 加载引擎（真实 Popen tensorfold serve）
        t0 = time.time()
        r = api.engine_start(MODEL, context=CTX, parallel=2, prompt_cache_gib=8)
        check("E2-2 engine_start 受理", r.get("ok") is not False, json.dumps(r, ensure_ascii=False)[:120])

        # 3. 轮询 ready（27B 加载约 30-60s）
        ready = False
        st = {}
        deadline = time.time() + 240
        while time.time() < deadline:
            pool.health_tick()  # starting→ready 探活翻转（真壳由后台循环做）
            st = api.engine_status()
            inst = [i for i in st["instances"] if i["model"] == MODEL]
            if inst and inst[0]["state"] == "ready":
                ready = True
                break
            if inst and inst[0]["state"] == "error":
                check("E2-3 引擎进入 ready", False, "state=error " + json.dumps(inst[0])[:200])
                break
            time.sleep(2)
        load_s = round(time.time() - t0, 1)
        check("E2-3 引擎进入 ready", ready, f"{load_s}s port={inst and inst[0].get('port')}")
        if not ready:
            print("日志尾部:", json.dumps(api.engine_log(MODEL)[-15:], ensure_ascii=False))
            return finish(api, pool, proxy)

        # 4+5. 真实对话（经 chat 代理，SSE 流式）；负载期间并行采监控
        def chat_stream(prompt, max_tokens=400):
            body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                               "stream": True, "max_tokens": max_tokens}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/chat", data=body,
                                         headers={"Content-Type": "application/json"})
            out, first = "", None
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        obj = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if obj.get("error"):
                        break
                    delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                    c = delta.get("content") or ""
                    if c and first is None:
                        first = round(time.time() - t0, 1)
                    out += c
            return out, first

        # 长生成放后台制造 token 流，前台并行采 tps 差分
        load = {}
        th = threading.Thread(target=lambda: load.update(
            zip(("text", "ttfb"), chat_stream("用约500字介绍一下京杭大运河的历史"))),
            daemon=True)
        th.start()
        ok_metrics = False
        latest = {}
        deadline = time.time() + 120
        while time.time() < deadline:
            pool.health_tick()
            monitor.tick(pool, __import__("psutil"))
            latest = monitor.snapshot()["latest"] or {}
            if latest.get("tps"):
                ok_metrics = True
                break
            time.sleep(2)
        th.join(timeout=240)
        check("E2-4 监控出数（负载下）", ok_metrics,
              f"tps={latest.get('tps')} kv={latest.get('kv')}% footprint={latest.get('footprint_gb')}G")
        check("E2-4b per 明细含模型", MODEL in (monitor.snapshot()["per"] or {}))

        text, ttfb = chat_stream("1+1等于几？直接给数字。", max_tokens=16)
        ok_chat = "2" in text
        check("E2-5 对话返回含『2』", ok_chat, f"reply={text[:80]!r}")
        check("E2-5c 长生成有内容(负载真实)", len(load.get("text", "")) > 50,
              f"len={len(load.get('text', ''))}")
        saved = store.create({"title": "e2e", "model": MODEL,
                              "messages": [{"role": "user", "content": "1+1等于几？直接给数字。"},
                                           {"role": "assistant", "content": text}]})
        got = store.get_chat(saved["id"])
        check("E2-5b 会话落盘读回", got and len(got["messages"]) == 2, f"id={saved['id']}")

        # 6. 设置改并发 → 重启生效
        api.model_settings_save(MODEL, {"context": CTX, "parallel": 3})
        r2 = api.engine_stop(MODEL)
        check("E2-6 停止实例", r2.get("ok", True) is not False, json.dumps(r2, ensure_ascii=False)[:80])
        t1 = time.time()
        api.engine_start(MODEL)  # 读每模型设置
        ok2 = False
        deadline = time.time() + 240
        while time.time() < deadline:
            pool.health_tick()
            st = api.engine_status()
            inst = [i for i in st["instances"] if i["model"] == MODEL]
            if inst and inst[0]["state"] == "ready":
                ok2 = True
                break
            time.sleep(2)
        args_log = " ".join(api.engine_log(MODEL))
        check("E2-6b 按新设置重启(parallel=3)", ok2 and "--parallel 3" in args_log,
              f"{round(time.time() - t1, 1)}s")

        # 7. 更新检查
        upd = api.update_check()
        eng = (upd or {}).get("engine") or {}
        check("E2-7 更新检查检出新版", bool(eng.get("available")),
              f"latest={eng.get('latest')} current={eng.get('current')}")

        # 8. 未加载模型路由拒绝
        try:
            body2 = json.dumps({"model": "TensorFold/GLM-5.3-Flash-MLX-4bit",
                                "messages": [{"role": "user", "content": "hi"}], "stream": False}).encode()
            req2 = urllib.request.Request(f"http://127.0.0.1:{port}/chat", data=body2,
                                          headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req2, timeout=10)
            ok503 = False
            detail = "未报 503"
        except urllib.error.HTTPError as e:
            ok503 = e.code == 503
            detail = str(e.read()[:120], "utf-8", "ignore")
        check("E2-8 未加载模型 503 路由拒绝", ok503, detail)
    finally:
        pass
    return finish(api, pool, proxy)


def finish(api, pool, proxy):
    try:
        r = api.engine_stop()
        print("stop:", json.dumps(r, ensure_ascii=False))
    except Exception as exc:
        print("stop 异常:", exc)
    try:
        proxy.shutdown()
    except Exception:
        pass
    bad = [x for x in results if x[0] == "FAIL"]
    print(f"\nRESULT: {'ALL PASS' if not bad else f'{len(bad)} FAIL'} ({len(results)} 项)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
