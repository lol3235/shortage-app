#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""欠料看板本地看门狗（watchdog）。

每轮探测本地 shortage_app（pythonw，端口 8765）是否存活：
- API 无响应 或 进程不存在 -> 判定死亡；
- 死亡时：精确杀掉 shortage_app 的 pythonw 进程并重新拉起（自愈）；
- 同时向你配置的企微 Webhook 发 markdown 告警（带 30 分钟冷却，避免刷屏）。
- app 健康时：什么都不做，不告警、不重启。

由 Windows 任务计划程序每 10 分钟触发一次（无窗口）。
Webhook 地址从环境变量 WEBHOOK_URL 读取（写在 .env，已被 gitignore）。
"""
import os
import sys
import json
import time
import subprocess
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PY = os.path.join(APP_DIR, "app.py")
# 与开机自启一致的 pythonw（受管运行时）
PYTHONW = os.environ.get(
    "WATCHDOG_PYTHONW",
    r"C:\Users\Apua\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe",
)
PORT = 8765
STATE_FILE = os.path.join(APP_DIR, "watchdog_state.json")
ALERT_COOLDOWN = 30 * 60  # 同一类告警 30 分钟内只发一次

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def _load_dotenv():
    """极简 dotenv：仅读取 .env 里的 WEBHOOK_URL（不依赖第三方库）。"""
    env_path = os.path.join(APP_DIR, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "WEBHOOK_URL" and v and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def is_api_alive():
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/api/sync_status" % PORT, timeout=5
        ) as r:
            return r.status == 200
    except Exception:
        return False


def find_app_pids():
    """用 wmic 精确找出命令行含 shortage_app 的 pythonw 进程 PID（避免误杀其他 pythonw）。"""
    pids = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='pythonw.exe'",
             "get", "processid,commandline", "/format:csv"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        for row in out.splitlines():
            if "shortage_app" in row and "pythonw.exe" in row:
                # CSV 形如: Node,CommandLine,ProcessId
                parts = [p.strip() for p in row.split(",")]
                for p in parts:
                    if p.isdigit():
                        pids.append(int(p))
    except Exception:
        pass
    return sorted(set(pids))


def restart():
    """杀掉现有 shortage_app 进程并重新拉起。"""
    for pid in find_app_pids():
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    time.sleep(2)
    # 无窗口 + 脱离父进程，真正后台常驻
    subprocess.Popen(
        [PYTHONW, APP_PY],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
    )
    time.sleep(4)  # 等服务起来


def send_webhook(content):
    url = os.environ.get("WEBHOOK_URL", "").strip()
    if not url:
        return False
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": content}}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print("[watchdog] webhook 发送失败: %s" % e)
        return False


def can_alert():
    now = time.time()
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        if now - st.get("last_alert", 0) < ALERT_COOLDOWN:
            return False
    except Exception:
        pass
    return True


def mark_alerted():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"last_alert": time.time()}, f)
    except Exception:
        pass


def main():
    _load_dotenv()
    alive = is_api_alive()
    if alive:
        print("[watchdog] %s 服务正常，无需处理" % time.strftime("%H:%M:%S"))
        return

    pids = find_app_pids()
    reason = "进程存在但 API 无响应(疑似卡死)" if pids else "进程不存在(已退出)"
    print("[watchdog] 检测到服务死亡: %s" % reason)

    restarted = False
    try:
        restart()
        restarted = is_api_alive() or bool(find_app_pids())
    except Exception as e:
        print("[watchdog] 重启失败: %s" % e)

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if restarted:
        msg = (
            "**🔄 欠料看板本地服务已自动恢复**\n"
            "> 时间：%s\n"
            "> 现象：%s\n"
            "> 处置：看门狗已自动拉起 `pythonw app.py`，线上将恢复自动同步"
        ) % (now, reason)
    else:
        msg = (
            "**⚠️ 欠料看板本地服务恢复失败**\n"
            "> 时间：%s\n"
            "> 现象：%s\n"
            "> 处置：自动拉起失败，请人工检查本地 app"
        ) % (now, reason)

    if can_alert():
        ok = send_webhook(msg)
        if ok:
            mark_alerted()
            print("[watchdog] 已发送企微告警")
    else:
        print("[watchdog] 告警处于冷却期，跳过发送")


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        # 常驻守护：每 WATCHDOG_INTERVAL 秒探活一次（默认 600=10 分钟）
        interval = int(os.environ.get("WATCHDOG_INTERVAL", "600"))
        print("[watchdog] 守护模式启动，间隔 %d 秒" % interval)
        while True:
            try:
                main()
            except Exception as e:
                print("[watchdog] daemon 异常: %s" % e)
            time.sleep(interval)
    else:
        main()
