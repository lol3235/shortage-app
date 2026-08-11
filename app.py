# -*- coding: utf-8 -*-
"""本地 HTTP 服务：JSON API + 静态文件托管。仅用 Python 标准库。

启动：python app.py  （端口默认 8765，可用环境变量 PORT 覆盖）
访问：http://localhost:8765
"""
import os
import sys
import json
import time
import hashlib
import threading
import subprocess
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import logic
import sync

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
DB_PATH = os.path.join(HERE, "data", "shortage.db")
SEED_PATH = os.path.join(HERE, "data", "seed.sql")
PORT = int(os.environ.get("PORT", "7860"))

AUTO_SYNC_INTERVAL = int(os.environ.get("AUTO_SYNC_INTERVAL", "30"))
AUTO_GIT_PUSH = os.environ.get("AUTO_GIT_PUSH", "1").lower() in ("1", "true", "yes")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "https://github.com/lol3235/shortage-app.git"


def _load_dotenv():
    """读取项目根目录 .env 文件（KEY=VALUE）注入环境变量，不依赖第三方库。"""
    env_path = os.path.join(HERE, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv()
# .env 里的值优先级低于已存在的环境变量；如果 .env 里写了 GITHUB_TOKEN，重新加载
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", GITHUB_TOKEN)

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
            return {"ok": False, "message": "同步进行中"}
        sync_state["syncing"] = True
        sync_state["error"] = None
    try:
        n, t = sync.sync_to_db(db_path=DB_PATH)
        with _sync_lock:
            sync_state["last_sync"] = t
            sync_state["last_count"] = n
        return {"ok": True, "count": n, "synced_at": t}
    except Exception as e:
        with _sync_lock:
            sync_state["error"] = str(e)
        return {"ok": False, "error": str(e)}
    finally:
        with _sync_lock:
            sync_state["syncing"] = False


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
            if sync_state["syncing"]:
                self._send_json({"accepted": False, "message": "同步进行中", **api_sync_status()})
                return
            # 后台线程执行
            threading.Thread(target=do_sync, daemon=True).start()
            self._send_json({"accepted": True, "message": "已开始同步"})
            return
        self._send_json({"error": "unknown post"}, 404)

    def log_message(self, *args):
        pass  # 静默


def _seed_if_empty():
    """云端环境无 wecom-cli，db 为空时从内置 seed.sql 快照初始化数据。"""
    try:
        n = len(db.get_all(DB_PATH))
    except Exception:
        n = 0
    if n > 0:
        return
    seed = os.path.join(HERE, "data", "seed.sql")
    if not os.path.exists(seed):
        return
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(open(seed, encoding="utf-8").read())
        conn.commit()
        conn.close()
        print("seed.sql 初始化完成（云端使用本地同步快照）")
    except Exception as e:
        print("seed 初始化失败:", e)


def _file_hash(path):
    if not os.path.exists(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_git(cmd, check=True):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (cmd[1], r.stderr or r.stdout))
    return r


def _git_push_seed():
    """把 data/seed.sql 提交并推送到 GitHub，触发 Render 重新部署。"""
    token = GITHUB_TOKEN
    if not token:
        print("[auto-sync] 未配置 GITHUB_TOKEN，跳过自动推送")
        return
    authed_repo = GITHUB_REPO.replace("https://", "https://%s@" % token)
    try:
        _run_git(["git", "config", "user.email", "app@local.dev"], check=False)
        _run_git(["git", "config", "user.name", "shortage-app"], check=False)
        _run_git(["git", "remote", "set-url", "origin", authed_repo])
        _run_git(["git", "add", "data/seed.sql"])
        msg = "sync: update seed.sql at %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_r = subprocess.run(
            ["git", "commit", "-m", msg, "data/seed.sql"],
            cwd=HERE, capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if commit_r.returncode != 0:
            out = (commit_r.stdout + commit_r.stderr).lower()
            if "nothing to commit" in out or "no changes" in out:
                print("[auto-sync] seed.sql 无变化，无需提交")
                return
            raise RuntimeError("git commit failed: %s" % (commit_r.stderr or commit_r.stdout))
        _run_git(["git", "push", "origin", "main"])
        print("[auto-sync] seed.sql 已推送，Render 将自动重新部署")
    except Exception as e:
        print("[auto-sync] 推送失败: %s" % e)
    finally:
        # 推送完成后恢复不含 token 的 remote URL
        subprocess.run(["git", "remote", "set-url", "origin", GITHUB_REPO],
                       cwd=HERE, capture_output=True)


def _auto_sync_loop():
    """后台循环：定时同步 -> 导出 seed.sql -> 有变化则 push -> Render 自动重部署。"""
    if AUTO_SYNC_INTERVAL <= 0:
        return
    if not os.path.exists(sync.WECOM_CMD):
        print("[auto-sync] 未检测到 wecom-cli，跳过自动同步（云端 Render 无需此步骤）")
        return
    print("[auto-sync] 每 %d 秒自动同步一次；数据变化时推送 seed.sql" % AUTO_SYNC_INTERVAL)
    while True:
        time.sleep(AUTO_SYNC_INTERVAL)
        try:
            result = do_sync()
            if not result.get("ok"):
                err = result.get("error") or result.get("message")
                print("[auto-sync] 同步未成功: %s" % err)
                continue
            old_hash = _file_hash(SEED_PATH)
            db.export_seed_sql(DB_PATH, SEED_PATH)
            new_hash = _file_hash(SEED_PATH)
            if old_hash == new_hash:
                print("[auto-sync] 数据无变化，跳过推送")
                continue
            print("[auto-sync] 数据已更新 (%d 条)，准备推送 seed.sql" % result.get("count", 0))
            if AUTO_GIT_PUSH:
                _git_push_seed()
        except Exception as e:
            print("[auto-sync] 异常: %s" % e)


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
    _seed_if_empty()
    _update_sync_state()

    # 启动后台自动同步（仅本地有 wecom-cli 时生效）
    threading.Thread(target=_auto_sync_loop, daemon=True).start()

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
