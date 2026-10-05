"""聊天支持：1) 本地流式转发代理（前端 fetch -> 代理 -> 引擎 SSE 直通）
2) 聊天记录持久化：每会话一个 JSON 文件（~/.tensorfold-manager/chats/<conv_id>.json）。

v2 多实例：代理按请求体里的 model 解析到对应 ready 实例转发；
model 缺省时路由到任意一个 ready 实例。
旧版单文件 history.json 启动时移入 archive/（清空重开，不删）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_SUFFIX = "/v1/chat/completions"
CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ChatProxy(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, pool):
        super().__init__(("127.0.0.1", 0), self._handler(pool))
        self.pool = pool

    @staticmethod
    def _handler(pool):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _begin(self, code):
                """HTTP/1.1 下必须显式断链，否则客户端读不到 EOF 会挂死。"""
                self.send_response(code)
                self._cors()
                self.send_header("Connection", "close")
                self.close_connection = True

            def _err(self, code, msg):
                self._begin(code)
                self.send_header("Content-Type", "application/json")
                payload = json.dumps({"error": {"message": msg}}).encode()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _resolve(self, model: str):
                """model 指定则精确路由；缺省取任一 ready 实例。返回 ready 实例或 None。"""
                if model:
                    inst = pool.resolve(model)
                    return inst if inst and inst.state == "ready" else None
                ready = pool.ready_instances()
                return ready[0] if ready else None

            def do_POST(self):
                if not self.path.startswith("/chat"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                try:
                    req_body = json.loads(body)
                except ValueError:
                    req_body = {}
                model = req_body.get("model") or ""
                inst = self._resolve(model)
                if inst is None:
                    hint = f"模型 {model} 未加载" if model else "没有已加载的模型"
                    self._err(503, f"engine not ready: {hint}")
                    return
                req = urllib.request.Request(
                    inst.base_url() + ALLOWED_SUFFIX, data=body,
                    headers={"Content-Type": "application/json"})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    upstream = opener.open(req, timeout=600)
                except urllib.error.HTTPError as exc:
                    payload = exc.read()
                    self._begin(exc.code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                except (urllib.error.URLError, OSError) as exc:
                    self._err(502, f"upstream error: {exc}")
                    return
                with upstream:
                    if "text/event-stream" in (upstream.headers.get("Content-Type") or ""):
                        self._begin(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        try:
                            while True:
                                chunk = upstream.read(256)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                self.wfile.flush()
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    else:
                        payload = upstream.read()
                        self._begin(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)

            def do_GET(self):
                if self.path == "/status":
                    data = json.dumps({"instances": [
                        {"model": i.model, "state": i.state, "port": i.port}
                        for i in pool.instances()]}).encode()
                    self._begin(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)

        return Handler

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True, name="chat-proxy").start()


class ChatStore:
    """每会话一文件：chats_dir/<conv_id>.json。

    记录结构 {id, title, model, created, updated, messages: [{role, content, stats?}]}
    旧版单文件 history.json（v1）调用 migrate_legacy 归档，不做兼容读。
    """
    MAX_CHATS = 200

    def __init__(self, chats_dir: str):
        self.chats_dir = chats_dir
        self.lock = threading.Lock()

    # ---------- 底层 ----------
    def _path(self, conv_id: str) -> str:
        if not CHAT_ID_RE.match(conv_id or ""):
            raise ValueError(f"非法会话 id: {conv_id!r}")
        return os.path.join(self.chats_dir, f"{conv_id}.json")

    def _read(self, conv_id: str) -> dict | None:
        try:
            path = self._path(conv_id)
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, chat: dict):
        os.makedirs(self.chats_dir, exist_ok=True)
        path = self._path(chat["id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chat, f, ensure_ascii=False)
        os.replace(tmp, path)

    # ---------- API ----------
    def create(self, chat: dict | None = None) -> dict:
        with self.lock:
            chat = dict(chat or {})
            chat["id"] = chat.get("id") or f"c{int(time.time() * 1000):x}"
            chat.setdefault("title", "新对话")
            chat.setdefault("model", "")
            chat.setdefault("messages", [])
            chat["created"] = chat.get("created") or time.time()
            chat["updated"] = time.time()
            self._write(chat)
            return chat

    def list_chats(self) -> list[dict]:
        with self.lock:
            out = []
            try:
                names = os.listdir(self.chats_dir)
            except OSError:
                return out
            for n in names:
                if not n.endswith(".json"):
                    continue
                c = self._read(n[:-5])
                if c:
                    out.append({"id": c["id"], "title": c.get("title", "对话"),
                                "model": c.get("model", ""),
                                "updated": c.get("updated", c.get("created", 0))})
            out.sort(key=lambda x: x["updated"], reverse=True)
            # 超上限删最旧
            if len(out) > self.MAX_CHATS:
                for stale in out[self.MAX_CHATS:]:
                    self.delete_chat(stale["id"])
                out = out[:self.MAX_CHATS]
            return out

    def get_chat(self, chat_id: str) -> dict | None:
        with self.lock:
            return self._read(chat_id)

    def save_chat(self, chat: dict) -> dict:
        with self.lock:
            chat = dict(chat)
            if not chat.get("id"):
                chat["id"] = f"c{int(time.time() * 1000):x}"
            old = self._read(chat["id"])
            if old:
                chat["created"] = old.get("created", time.time())
            chat["updated"] = time.time()
            self._write(chat)
            return chat

    def rename_chat(self, chat_id: str, title: str) -> bool:
        with self.lock:
            c = self._read(chat_id)
            if not c:
                return False
            c["title"] = title
            c["updated"] = time.time()
            self._write(c)
            return True

    def delete_chat(self, chat_id: str) -> bool:
        try:
            os.remove(self._path(chat_id))
            return True
        except OSError:
            return False

    # ---------- 旧数据归档 ----------
    def migrate_legacy(self, legacy_path: str, archive_dir: str) -> bool:
        """v1 单文件 history.json → 移入 archive/（清空重开）。返回是否迁移了。"""
        if not legacy_path or not os.path.exists(legacy_path):
            return False
        os.makedirs(archive_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(archive_dir, f"history-{stamp}.json")
        shutil.move(legacy_path, dest)
        return True
