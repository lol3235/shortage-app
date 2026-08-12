# -*- coding: utf-8 -*-
"""数据管道：拉企微在线表 -> 解析(多子表自适应) -> 写入本地 SQLite。

逻辑移植自原 shortage_tool/refresh_data.py（仅复制逻辑，未改动原文件）。
新增 sync_to_db() 把解析结果写入 db.py 的 SQLite。

数据源策略（v1.1）：
- 默认：本地 wecom-cli（依赖企业微信桌面端登录态）。
- 云端直连模式：当配置了企微开放 API 凭证
  (WECOM_API_CORP_ID / WECOM_API_CORP_SECRET / WECOM_TABLE_DOCID) 时，
  优先用 API 拉取，失败自动回退 wecom-cli；无凭证时行为与旧版完全一致。
"""
import json
import re
import os
import sys
import subprocess
import time
from collections import Counter, defaultdict

import db

SHORTAGE_URL = "https://doc.weixin.qq.com/sheet/e3_AMoAPwakAAsCNQYtN09SBSmC1ve5p?scode=AD4A2AeHABEs5wHQYX"


def _detect_wecom_cli():
    """探测 wecom-cli 路径：环境变量 WECOM_CLI 优先，其次候选路径，最后回退原路径。

    避免 wecom-cli 升级或移动路径后，本地自动同步因 WECOM_CMD 失效而静默跳过。
    """
    env = os.environ.get("WECOM_CLI", "").strip()
    if env and os.path.exists(env):
        return env
    cands = [
        r"C:\Users\Apua\.workbuddy\binaries\node\cli-connector-packages\wecom-cli.cmd",
        os.path.join(os.environ.get("USERPROFILE", ""), ".workbuddy", "binaries",
                     "node", "cli-connector-packages", "wecom-cli.cmd"),
        "wecom-cli.cmd",  # PATH 中的可执行
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return cands[0]  # 都不存在时回退原路径，保持原有行为（_auto_sync_loop 会因 exists 跳过）


WECOM_CMD = _detect_wecom_cli()
SYSTEM_CMD = r"C:\Windows\System32\cmd.exe"
CREATE_NO_WINDOW = 0x08000000

# 逻辑字段 -> 候选列名（按优先级），用于适配不同子表的表头差异
COL_ALIASES = {
    "项目": ["项目", "项目名称", "申请部门", "领用车间"],
    "项目编码": ["项目编码"],
    "物料编码": ["物料编码"],
    "规格说明": ["规格说明"],
    "审核日期": ["审核日期"],
    "物料名称": ["物料名称"],
    "品牌": ["品牌"],
    "产地": ["产地", "单位"],
    "欠料数量": ["欠料数量", "待领数量"],
    # 预计交期：仅取「供方承诺」列，不读需求方的「期望到货时间」
    "预计到货时间": ["预计到货时间", "材料预计到货时间"],
    # 期望交期：需求方在「期望到货时间」写的，单独存，仅用于「来不来得及」对比
    "期望交期": ["期望到货时间", "期望交期"],
    # 状态列：用于标记 已解决/归档 等，机器人据此过滤（应对隐藏行/分表）
    "状态": ["状态", "处理状态", "进度", "是否解决", "备注"],
}


def _run_wecom(args, timeout=60):
    """用 cmd /c 调用 wecom-cli.cmd，隐藏窗口，避免黑窗。"""
    cmd = [SYSTEM_CMD, "/c", WECOM_CMD] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
    except Exception as e:
        r = type('R', (), {'returncode': -1, 'stdout': '', 'stderr': str(e)})()
    try:
        with open(os.path.join(os.path.dirname(__file__), "wecom_debug.log"), "a", encoding="utf-8") as f:
            f.write("[%.3f] rc=%s stdout_len=%s stderr=%s\n" % (
                time.time(), r.returncode, len(r.stdout or ""), (r.stderr or "")[:200]))
    except Exception:
        pass
    return r


def _start_task():
    payload = {"url": SHORTAGE_URL, "type": 2}
    r = _run_wecom(["doc", "get_doc_content", "--json", json.dumps(payload)])
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise RuntimeError("创建任务失败: rc=%s err=%s" % (
            r.returncode, (r.stderr or "")[:200]))
    outer = json.loads(r.stdout)
    inner = json.loads(outer["result"]["content"][0]["text"])
    return inner["task_id"]


def _poll_task(tid, max_empty=10, max_wait=90):
    empty_cnt = 0
    waited = 0
    interval = 2
    while waited < max_wait:
        r = _run_wecom(["doc", "get_doc_content", "--json",
                       json.dumps({"url": SHORTAGE_URL, "type": 2, "task_id": tid})])
        if r.returncode != 0:
            raise RuntimeError("轮询失败: rc=%s err=%s" % (
                r.returncode, (r.stderr or "")[:200]))
        if not (r.stdout or "").strip():
            empty_cnt += 1
            if empty_cnt > max_empty:
                raise RuntimeError("轮询空输出超过%d次" % max_empty)
            time.sleep(interval)
            waited += interval
            continue
        empty_cnt = 0
        outer = json.loads(r.stdout)
        inner = json.loads(outer["result"]["content"][0]["text"])
        if inner.get("task_done"):
            return inner["content"]
        time.sleep(interval)
        waited += interval
    raise RuntimeError("拉取欠料表轮询超时")


def fetch_markdown(max_retry=3):
    last = None
    for attempt in range(1, max_retry + 1):
        try:
            tid = _start_task()
            return _poll_task(tid)
        except Exception as e:
            last = e
            if attempt < max_retry:
                time.sleep(2)
                continue
    raise RuntimeError("拉取欠料表失败(重试%d次): %s" % (max_retry, last))


def _classify_eta(eta):
    e = (eta or "").strip()
    if e == "":
        return "空白"
    if re.search(r"付款|额度|确认付款|需.*付款", e):
        return "付款瓶颈"
    if re.search(r"待定|未定|未回复|货期待定|暂无|不确定|等通知", e):
        return "无交期"
    if re.search(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./月]\d{1,2}|预计|月|日|现货|已发|生产", e):
        return "有交期"
    return "其他"


def _is_material_code(s):
    return bool(re.match(r'^[A-Za-z][A-Za-z0-9\-]{4,}$', s)) and '-' in s


def _resolve_columns(cells):
    mapping = {}
    cells = [c.strip() for c in cells]
    for logic_field, aliases in COL_ALIASES.items():
        for alias in aliases:
            if alias in cells:
                mapping[logic_field] = cells.index(alias)
                break
        if logic_field not in mapping:
            mapping[logic_field] = -1
    return mapping


def _fix_columns(cells, cur):
    """修正表头错位：当表头无「项目」列、但出现两个「项目编码」列时，
    第二个「项目编码」列实际存的是项目名（如某些巨茂批次分表把项目名
    塞进了名为「项目编码」的第二列）。此时把 项目 指向第二个「项目编码」，
    项目编码 指向第一个，避免把物料错挂到「领用车间/申请部门」名下。
    """
    if cur.get("项目", -1) >= 0 and cells[cur["项目"]] == "项目":
        return  # 已有正确的「项目」列，无需修正
    pc = [i for i, c in enumerate(cells) if c == "项目编码"]
    if len(pc) >= 2:
        cur["项目"] = pc[1]      # 第二列「项目编码」实为项目名
        cur["项目编码"] = pc[0]  # 第一列才是真正的项目编码


def parse_markdown(md):
    """多子表自适应解析：遇到含 物料编码+欠料数量 的表头行就重置列映射。"""
    lines = md.split("\n")
    sep = re.compile(r"^\|[\s:|-]+\|")
    cur = {}
    items = []
    current_sheet = ""
    for l in lines:
        s = l.strip()
        if s and not s.startswith("|") and not s.startswith("---") and len(s) <= 40:
            current_sheet = s
            continue
        if not s.startswith("|"):
            continue
        if sep.match(s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        joined = "".join(cells)
        has_mc = "物料编码" in joined
        has_qty = any(alias in joined for alias in COL_ALIASES["欠料数量"])
        if has_mc and has_qty and len(cells) >= 5:
            cur = _resolve_columns(cells)
            _fix_columns(cells, cur)
            continue
        mc_i = cur.get("物料编码", -1)
        if mc_i < 0 or mc_i >= len(cells):
            continue
        mc = cells[mc_i]
        if not _is_material_code(mc):
            continue
        sq_i = cur.get("欠料数量", -1)
        sq = cells[sq_i].replace(",", "") if 0 <= sq_i < len(cells) else ""
        if not re.match(r'^-?\d+(\.\d+)?$', sq):
            continue

        def g(f):
            i = cur.get(f, -1)
            return cells[i].strip() if 0 <= i < len(cells) else ""

        project = g("项目") or g("项目编码") or ""
        project_code = g("项目编码")
        eta = g("预计到货时间")
        items.append({
            "项目": project,
            "项目编码": project_code,
            "物料编码": mc,
            "规格说明": g("规格说明"),
            "审核日期": g("审核日期"),
            "物料名称": g("物料名称"),
            "品牌": g("品牌"),
            "产地": g("产地"),
            "欠料数量": int(float(sq)),
            "预计到货时间": eta,
            "期望交期": g("期望交期"),
            "状态": g("状态"),
            "eta_status": _classify_eta(eta),
            "sheet": current_sheet,
            "owner": "",
        })
    return items


def _use_api_mode():
    """是否配置了企微开放 API 凭证（corpid/secret/表 docid），用于云端直连。"""
    cid = os.environ.get("WECOM_API_CORP_ID", "").strip()
    sec = os.environ.get("WECOM_API_CORP_SECRET", "").strip()
    did = os.environ.get("WECOM_TABLE_DOCID", "").strip()
    return bool(cid and sec and did)


def _fetch_via_api(timeout=30):
    """企微开放 API 拉取在线表内容（云端直连模式）。

    流程：corpid+corpsecret 换取 access_token -> 读取文档内容。
    注意：在线表格(sheet)的读取接口以凭证到位后实测为准；此处为可插拔骨架，
    失败时抛异常，由 sync_to_db 回退 wecom-cli 或保留旧数据，绝不静默污染。
    """
    import urllib.request
    cid = os.environ.get("WECOM_API_CORP_ID", "").strip()
    sec = os.environ.get("WECOM_API_CORP_SECRET", "").strip()
    did = os.environ.get("WECOM_TABLE_DOCID", "").strip()
    if not (cid and sec and did):
        raise RuntimeError("缺少企微 API 凭证环境变量(WECOM_API_CORP_ID/SECRET/TABLE_DOCID)")
    # 1) 获取 access_token
    token_url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=%s&corpsecret=%s" % (cid, sec)
    try:
        with urllib.request.urlopen(token_url, timeout=timeout) as resp:
            tj = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError("获取 access_token 失败: %s" % e)
    if tj.get("errcode", 0) != 0:
        raise RuntimeError("获取 access_token 错误: %s %s" % (tj.get("errcode"), tj.get("errmsg")))
    token = tj["access_token"]
    # 2) 读取文档内容（在线表接口以实测为准，先按文档内容接口尝试）
    doc_url = "https://qyapi.weixin.qq.com/cgi-bin/doc/v2/get_doc_content?access_token=%s" % token
    payload = json.dumps({"docid": did}).encode("utf-8")
    req = urllib.request.Request(doc_url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dj = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError("读取文档内容失败: %s" % e)
    if dj.get("errcode", 0) != 0:
        raise RuntimeError("读取文档内容错误: %s %s" % (dj.get("errcode"), dj.get("errmsg")))
    # 返回文本/markdown 供 parse_markdown 解析
    return dj.get("content", "") or dj.get("markdown", "")


def sync_to_db(offline_md=None, db_path=None):
    """拉取(或离线)并解析，写入 SQLite。返回 (条数, synced_at)。失败抛异常（保留旧数据）。

    数据源：offline_md(测试) > 企微 API(若配凭证) > 本地 wecom-cli。
    """
    if db_path is None:
        db_path = db.DEFAULT_DB
    if offline_md:
        md = open(offline_md, encoding="utf-8", errors="replace").read()
    elif _use_api_mode():
        try:
            md = _fetch_via_api()
        except Exception as e:
            print("[sync] 企微 API 拉取失败，回退 wecom-cli: %s" % e)
            md = fetch_markdown()
    else:
        md = fetch_markdown()
    items = parse_markdown(md)
    from datetime import datetime
    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.upsert_items(items, synced_at, path=db_path)
    return len(items), synced_at


if __name__ == "__main__":
    offline = None
    for a in sys.argv[1:]:
        if a.startswith("--offline="):
            offline = a.split("=", 1)[1]
    n, t = sync_to_db(offline_md=offline)
    print("同步完成：%d 条 @ %s" % (n, t))
