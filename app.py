# -*- coding: utf-8 -*-
"""本地 HTTP 服务：JSON API + 静态文件托管。仅用 Python 标准库。

启动：python app.py  （端口默认 8765，可用环境变量 PORT 覆盖）
访问：http://localhost:8765
"""
import os
import sys
import json
import time
import shutil
import hashlib
import threading
import subprocess
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import logic
import sync
import sync_sheetmetal

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
DB_PATH = os.path.join(HERE, "data", "shortage.db")
SEED_PATH = os.path.join(HERE, "data", "seed.sql")
SHEETMETAL_DB = db.SHEETMETAL_DB
SHEETMETAL_SEED = db.SHEETMETAL_SEED
PORT = int(os.environ.get("PORT", "8765"))

AUTO_SYNC_INTERVAL = int(os.environ.get("AUTO_SYNC_INTERVAL", "30"))
AUTO_GIT_PUSH = os.environ.get("AUTO_GIT_PUSH", "1").lower() in ("1", "true", "yes")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "https://github.com/lol3235/shortage-app.git"


def _find_git():
    """定位 git 可执行文件：PATH 优先，其次 PortableGit 常见位置。

    pythonw 启动时 PATH 可能不包含 Bash 的 /mingw64/bin，需要主动探测。
    """
    found = shutil.which("git")
    if found:
        return found
    cands = [
        os.path.join(os.environ.get("USERPROFILE", ""), ".workbuddy",
                     "vendor", "PortableGit", "mingw64", "bin", "git.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".workbuddy",
                     "vendor", "PortableGit", "cmd", "git.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Git", "cmd", "git.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "cmd", "git.exe"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return "git"  # 兜底，让 subprocess 自己抛出更清晰的错误


GIT_EXE = _find_git()


def _win_subprocess_kwargs():
    """返回仅在 Windows 上可用的 subprocess 参数，避免 Linux/macOS 报错。"""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


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

# 钣金欠料（金山文档）同步状态
_sm_lock = threading.Lock()
sm_state = {"syncing": False, "last_sync": None, "last_count": 0, "error": None}


def _load_active():
    return logic.filter_active(db.get_all(DB_PATH))


def _parse_archived(raw):
    """把 meta 里归档分表的 JSON 字符串解析成列表（容错）。"""
    if not raw:
        return []
    try:
        import json as _json
        v = _json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


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
        if not sync.can_sync_online():
            # 云端 Render 无 wecom-cli、也无企微 API 凭证时，属预期「快照模式」，不是故障。
            # 返回 ok=False 且不写入 sync_state["error"]，避免前端把预期行为当成错误告警。
            return {"ok": False, "message": "云端快照模式：数据由本地 Windows app 自动同步推送"}
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


def do_sync_sheetmetal():
    with _sm_lock:
        if sm_state["syncing"]:
            return {"ok": False, "message": "同步进行中"}
        sm_state["syncing"] = True
        sm_state["error"] = None
    try:
        n, t = sync_sheetmetal.sync_to_db()
        with _sm_lock:
            sm_state["last_sync"] = t
            sm_state["last_count"] = n
        return {"ok": True, "count": n, "synced_at": t}
    except Exception as e:
        with _sm_lock:
            sm_state["error"] = str(e)
        return {"ok": False, "error": str(e)}
    finally:
        with _sm_lock:
            sm_state["syncing"] = False


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
    meta = db.get_meta(DB_PATH)
    st["db_last_sync"] = meta.get("last_sync")
    st["archived_sheets"] = _parse_archived(meta.get("archived_sheets"))
    st["syncable"] = sync.can_sync_online()
    st["cloud"] = not st["syncable"]
    if not st["syncable"]:
        st["error"] = None  # 云端快照模式属预期，不作为故障告警
    return st


def api_settings():
    meta = db.get_meta(DB_PATH)
    return {
        "source": sync.SHORTAGE_URL,
        "db_path": DB_PATH,
        "resolved_keywords": list(logic.RESOLVED_KEYWORDS),
        "sheets": meta.get("sheets", {}),
        "archived_sheets": _parse_archived(meta.get("archived_sheets")),
    }


def api_sheetmetal_overview():
    return logic.sheetmetal_overview(db.get_all_sheetmetal())


def api_sheetmetal_search(kw):
    return logic.sheetmetal_search(db.get_all_sheetmetal(), kw)


def api_sheetmetal_sync_status():
    with _sm_lock:
        st = dict(sm_state)
    meta = db.get_sheetmetal_meta()
    st["db_last_sync"] = meta.get("last_sync")
    st["db_last_count"] = meta.get("last_count")
    return st


def api_sheetmetal_settings():
    meta = db.get_sheetmetal_meta()
    return {
        "source": sync_sheetmetal.KDOCS_URL,
        "file_id": sync_sheetmetal.KDOCS_FILE_ID,
        "db_path": SHEETMETAL_DB,
        "sheets": meta.get("sheets", {}),
        "last_sync": meta.get("last_sync"),
        "last_count": meta.get("last_count"),
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
    "/api/sheetmetal_overview": api_sheetmetal_overview,
    "/api/sheetmetal_search": api_sheetmetal_search,
    "/api/sheetmetal_sync_status": api_sheetmetal_sync_status,
    "/api/sheetmetal_settings": api_sheetmetal_settings,
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length).decode("utf-8", errors="replace")

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
                elif path == "/api/sheetmetal_search":
                    self._send_json(api_sheetmetal_search(qs.get("kw", [""])[0]))
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
        if parsed.path == "/api/sheetmetal_sync":
            with _sm_lock:
                if sm_state["syncing"]:
                    self._send_json({"accepted": False, "message": "同步进行中", **api_sheetmetal_sync_status()})
                    return
            threading.Thread(target=do_sync_sheetmetal, daemon=True).start()
            self._send_json({"accepted": True, "message": "已开始同步钣金欠料"})
            return
        self._send_json({"error": "unknown post"}, 404)

    def log_message(self, *args):
        pass  # 静默


def _seed_if_empty():
    """云端环境无 wecom-cli，db 为空时从内置 seed.sql 快照初始化数据。"""
    # 欠料（企业微信）
    try:
        n = len(db.get_all(DB_PATH))
    except Exception:
        n = 0
    if n == 0:
        seed = os.path.join(HERE, "data", "seed.sql")
        if os.path.exists(seed):
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            try:
                conn.executescript(open(seed, encoding="utf-8").read())
                conn.commit()
                print("seed.sql 初始化完成（云端使用本地同步快照）")
            except Exception as e:
                conn.rollback()
                err = "seed 初始化失败: %s" % e
                print(err)
                with _sync_lock:
                    sync_state["error"] = err
            finally:
                conn.close()

    # 钣金欠料（金山文档）快照初始化
    try:
        sn = len(db.get_all_sheetmetal())
    except Exception:
        sn = 0
    if sn == 0:
        sm_seed = os.path.join(HERE, "data", "seed_sheetmetal.sql")
        if os.path.exists(sm_seed):
            import sqlite3
            conn = sqlite3.connect(SHEETMETAL_DB)
            try:
                conn.executescript(open(sm_seed, encoding="utf-8").read())
                conn.commit()
                print("seed_sheetmetal.sql 初始化完成（云端使用本地同步快照）")
            except Exception as e:
                conn.rollback()
                print("seed_sheetmetal 初始化失败: %s" % e)
            finally:
                conn.close()


def _ensure_meta():
    """兜底修复：db 已有数据但 meta 缺失时，从 shortage_items 反推 last_sync / last_count。"""
    try:
        meta = db.get_meta(DB_PATH)
        if meta.get("last_sync"):
            return
        conn = db._conn(DB_PATH)
        try:
            row = conn.execute(
                "SELECT MAX(synced_at) AS t, COUNT(*) AS c FROM shortage_items"
            ).fetchone()
            if row and row["t"]:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('last_sync', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (row["t"],),
                )
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('last_count', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(row["c"]),),
                )
                conn.commit()
                print("[meta] 已修复缺失的 last_sync:", row["t"])
        finally:
            conn.close()
    except Exception as e:
        print("[meta] 修复失败:", e)


def _file_hash(path):
    if not os.path.exists(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_git(cmd, check=True):
    """运行 git 命令，使用探测到的 GIT_EXE 绝对路径，避免 pythonw PATH 不全。

    同时用 sync._clean_env_for_subprocess() 清理失效代理环境变量，
    避免 git 因 HTTP_PROXY/HTTPS_PROXY 指向未运行代理而推送失败。
    """
    real_cmd = [GIT_EXE] + cmd[1:]
    r = subprocess.run(real_cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=sync._clean_env_for_subprocess(),
                       **_win_subprocess_kwargs())
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
        _run_git(["git", "add", "data/seed.sql", "data/seed_sheetmetal.sql"])
        msg = "sync: update seed data at %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_r = subprocess.run(
            [GIT_EXE, "commit", "-m", msg, "data/seed.sql", "data/seed_sheetmetal.sql"],
            cwd=HERE, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=sync._clean_env_for_subprocess(),
            **_win_subprocess_kwargs())
        if commit_r.returncode != 0:
            out = (commit_r.stdout + commit_r.stderr).lower()
            if "nothing to commit" in out or "no changes" in out:
                print("[auto-sync] seed 无变化，无需提交")
                return
            raise RuntimeError("git commit failed: %s" % (commit_r.stderr or commit_r.stdout))
        _run_git(["git", "push", "origin", "main"])
        print("[auto-sync] seed 已推送，Render 将自动重新部署")
    except Exception as e:
        print("[auto-sync] 推送失败: %s (git=%s PATH=%s)" % (
            e, GIT_EXE, os.environ.get("PATH", "")[:300]))
    finally:
        # 推送完成后恢复不含 token 的 remote URL
        # Windows 下带 CREATE_NO_WINDOW，避免弹出黑窗（git.exe 是控制台程序）
        subprocess.run([GIT_EXE, "remote", "set-url", "origin", GITHUB_REPO],
                       cwd=HERE, capture_output=True,
                       env=sync._clean_env_for_subprocess(),
                       **_win_subprocess_kwargs())


def _export_and_check_seed(path, exporter, db_path):
    """导出 seed 并比较 hash；返回是否有变化。"""
    old = _file_hash(path)
    exporter(db_path, path)
    return old != _file_hash(path)


def _auto_sync_loop():
    """后台循环：定时同步 -> 导出 seed -> 有变化则 push -> Render 自动重部署。

    同时处理「欠料（企业微信）」与「钣金欠料（金山文档）」两套独立数据。
    """
    if AUTO_SYNC_INTERVAL <= 0:
        return
    if (not os.path.exists(sync.WECOM_CMD) and not sync._use_api_mode()
            and not os.path.exists(sync_sheetmetal.KDOCS_CLI)):
        print("[auto-sync] 未检测到 wecom-cli / kdocs-cli，跳过自动同步")
        return
    print("[auto-sync] 每 %d 秒自动同步一次；数据变化时推送 seed" % AUTO_SYNC_INTERVAL)
    while True:
        time.sleep(AUTO_SYNC_INTERVAL)
        changed = False
        try:
            # —— 欠料（企业微信）——
            r1 = do_sync()
            if r1.get("ok"):
                if _export_and_check_seed(SEED_PATH, db.export_seed_sql, DB_PATH):
                    changed = True
            else:
                print("[auto-sync] 欠料同步未成功: %s" % (r1.get("error") or r1.get("message")))
            # —— 钣金欠料（金山文档）——
            r2 = do_sync_sheetmetal()
            if r2.get("ok"):
                if _export_and_check_seed(SHEETMETAL_SEED, db.export_sheetmetal_seed_sql, SHEETMETAL_DB):
                    changed = True
            else:
                print("[auto-sync] 钣金同步未成功: %s" % (r2.get("error") or r2.get("message")))
            if changed and AUTO_GIT_PUSH:
                _git_push_seed()
        except Exception as e:
            print("[auto-sync] 异常: %s" % e)


def _running_app_instance(pid):
    """判断给定 PID 是否确实是一个正在运行的 app.py 实例。

    不只看 PID 是否存活（避免 PID 复用/僵尸误判导致 app 起不来），
    而是校验其命令行确实包含 app.py。
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                data = f.read().decode("utf-8", "ignore")
            return "app.py" in data
        except OSError:
            return False
    try:
        import ctypes, struct
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
        if not h:
            return False
        try:
            ntdll = ctypes.windll.ntdll
            # 必须显式声明调用约定，否则在 app.py 运行环境下参数传递错误导致调用失败
            ntdll.NtQueryInformationProcess.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
            ntdll.NtQueryInformationProcess.restype = ctypes.c_long
            buf = ctypes.create_string_buffer(16384)
            rb = ctypes.c_ulong()
            if ntdll.NtQueryInformationProcess(h, 60, buf, 16384, ctypes.byref(rb)) != 0:
                return False
            length = struct.unpack_from('<H', buf, 0)[0]
            bufptr = struct.unpack_from('<Q', buf, 8)[0]
            off = bufptr - ctypes.addressof(buf)
            if off < 0 or off + length > 16384:
                return False
            cmd = buf[off:off + length].decode('utf-16-le', errors='ignore').lower()
            return "app.py" in cmd
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


def _single_instance():
    """单实例保护：已存在存活的 app.py 实例则立即退出，避免重复实例 / 端口冲突 / 黑窗。

    优先使用 Windows 命名互斥体（内核级）：创建即原子、无竞态、
    进程退出自动释放、无残留文件；即便用有窗口的 python.exe 启动也会瞬间退出，
    不会留下持续黑窗。非 Windows 或互斥体不可用时回退到 pid 文件 + 命令行校验。
    """
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.GetLastError.restype = ctypes.c_uint
            ERROR_ALREADY_EXISTS = 183
            h = kernel32.CreateMutexW(None, False, "Global\\ShortageAppSingleton")
            if not h or kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                # 已有实例持有互斥体：立即退出，不绑定端口、不弹窗
                sys.exit(0)
            # 持有互斥体，保持句柄到进程结束（存模块级变量防止被 GC 关闭）
            _single_instance._handle = h
            return
        except Exception:
            pass  # 互斥体不可用则回退到 pid 文件
    # 非 Windows 或互斥体异常：pid 文件兜底
    pid_path = os.path.join(HERE, "data", "app.pid")
    if not os.path.exists(pid_path):
        return
    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return
    if _running_app_instance(old_pid):
        # 已有 app.py 实例在跑：直接退出，不绑定端口、不弹窗
        sys.exit(0)
    # 旧 pid 已失效，允许本进程接管（下方 main 会重写 pid 文件）


def main():
    _single_instance()
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
    db.init_sheetmetal_db(SHEETMETAL_DB)
    _seed_if_empty()
    _ensure_meta()
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
