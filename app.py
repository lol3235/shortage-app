# -*- coding: utf-8 -*-
"""本地 HTTP 服务：JSON API + 静态文件托管。仅用 Python 标准库。

启动：python app.py  （端口默认 8765，可用环境变量 PORT 覆盖）
访问：http://localhost:8765
"""
import os
import sys
import json
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import logic
import sync

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
DB_PATH = os.path.join(HERE, "data", "shortage.db")
PORT = int(os.environ.get("PORT", "7860"))

# 同步状态（线程安全）
_sync_lock = threading.Lock()
sync_state = {"syncing": False, "last_sync": None, "last_count": 0, "error": None}


def _load_active():
    return logic.filter_active(db.get_all(DB_PATH))


def _update_sync_state():
    meta = db.get_meta(DB_PATH)
    sync_state["last_sync"] = meta.get("last_sync")
    sync_state["last_count"] = int(meta.get("last_count") or 0)


def do_sync():
    with _sync_lock:
        if sync_state["syncing"]:
            return False
        sync_state["syncing"] = True
        sync_state["error"] = None
    try:
        n, t = sync.sync_to_db(db_path=DB_PATH)
        with _sync_lock:
            sync_state["last_sync"] = t
            sync_state["last_count"] = n
    except Exception as e:
        with _sync_lock:
            sync_state["error"] = str(e)
    finally:
        with _sync_lock:
            sync_state["syncing"] = False
    return True


# ---------------- API ----------------
def api_overview():
    return logic.overview(_load_active())


def api_search(kw):
    kw = logic.normalize_keyword(kw)
    return {"keyword": kw, "rows": logic.search(_load_active(), kw)}


def api_project(kw):
    return logic.project_summary(_load_active(), logic.normalize_keyword(kw))


def api_material(kw):
    return logic.material_summary(_load_active(), logic.normalize_keyword(kw))


def api_brand(kw):
    return logic.brand_summary(_load_active(), logic.normalize_keyword(kw))


def api_eta(kw):
    return logic.eta_check(_load_active(), logic.normalize_keyword(kw))


def api_sync_status():
    with _sync_lock:
        st = dict(sync_state)
    st["db_last_sync"] = db.get_meta(DB_PATH).get("last_sync")
    return st


def api_settings():
    meta = db.get_meta(DB_PATH)
    return {
        "source": sync.SHORTAGE_URL,
        "db_path": DB_PATH,
        "resolved_keywords": list(logic.RESOLVED_KEYWORDS),
        "sheets": meta.get("sheets", {}),
    }


ROUTES = {
    "/api/overview": api_overview,
    "/api/search": api_search,
    "/api/project": api_project,
    "/api/material": api_material,
    "/api/brand": api_brand,
    "/api/eta": api_eta,
    "/api/sync_status": api_sync_status,
    "/api/settings": api_settings,
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ROUTES:
            try:
                if path == "/api/search":
                    self._send_json(api_search(qs.get("kw", [""])[0]))
                elif path == "/api/project":
                    self._send_json(api_project(qs.get("kw", [""])[0]))
                elif path == "/api/material":
                    self._send_json(api_material(qs.get("kw", [""])[0]))
                elif path == "/api/brand":
                    self._send_json(api_brand(qs.get("kw", [""])[0]))
                elif path == "/api/eta":
                    self._send_json(api_eta(qs.get("kw", [""])[0]))
                else:
                    self._send_json(ROUTES[path]())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return
        # 静态文件
        if path == "/" or path == "":
            self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
            return
        rel = path.lstrip("/")
        fpath = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not fpath.startswith(STATIC_DIR):
            self._send_json({"error": "forbidden"}, 403)
            return
        ctype = "text/plain; charset=utf-8"
        if fpath.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif fpath.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif fpath.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        self._send_file(fpath, ctype)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            started = do_sync() if not sync_state["syncing"] else False
            if not started and sync_state["syncing"]:
                self._send_json({"accepted": False, "message": "同步进行中", **api_sync_status()})
            else:
                # 后台线程执行
                threading.Thread(target=do_sync, daemon=True).start()
                self._send_json({"accepted": True, "message": "已开始同步"})
            return
        self._send_json({"error": "unknown post"}, 404)

    def log_message(self, *args):
        pass  # 静默


def main():
    # pythonw has no console/stdout; redirect to app.log so diagnostics survive.
    if sys.stdout is None or getattr(sys.stdout, "write", None) is None:
        try:
            log_path = os.path.join(HERE, "app.log")
            fh = open(log_path, "a", encoding="utf-8")
            sys.stdout = fh
            sys.stderr = fh
        except Exception:
            pass

    db.init_db(DB_PATH)
    _update_sync_state()

    # Write PID file for stop.bat
    try:
        with open(os.path.join(HERE, "data", "app.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    # Bind to 0.0.0.0 so the app is reachable beyond localhost (LAN / PaaS).
    # PORT is taken from $PORT (PaaS injects this); falls back to 8765 locally.
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("欠料看板 APP 已启动： http://0.0.0.0:%d" % PORT)
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
