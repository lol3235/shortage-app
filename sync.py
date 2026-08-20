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
import csv
import io
import socket
from urllib.parse import urlparse
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


def _win_subprocess_kwargs():
    """返回仅在 Windows 上可用的 subprocess 参数，避免在 Linux/macOS 上报错。"""
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def _proxy_is_alive(proxy_url):
    """检测代理 URL 是否真正可连接（避免环境变量里遗留失效代理导致外部命令连不上网）。"""
    if not proxy_url:
        return False
    try:
        p = urlparse(proxy_url.strip())
        host = p.hostname or "127.0.0.1"
        port = p.port or (443 if p.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


def _clean_env_for_subprocess():
    """复制当前环境变量，并剔除指向不可用端口的 HTTP/HTTPS/ALL_PROXY。

    很多用户机器上残留着旧代理软件设置的环境变量（如 127.0.0.1:7897），
    但该代理并未运行；外部命令（wecom-cli / git / kdocs-cli）默认会走这些代理，
    结果出现 "ConnectionRefused" / "Failed to connect to github.com over proxy" 等报错。
    本函数在调用外部命令前做一次清理，可一次性解决这类问题。
    """
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        val = env.get(key, "")
        if val and not _proxy_is_alive(val):
            env.pop(key, None)
    return env


def can_sync_online():
    """当前环境是否可以在线拉取企微欠料表（本地 wecom-cli 或云端 API 凭证）。"""
    if _use_api_mode():
        return True
    if sys.platform != "win32":
        return False
    return os.path.exists(WECOM_CMD)


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
    # 状态列：用于标记 已解决/归档 等，机器人据此过滤（应对隐藏行/分表）。
    # 严格限定 4 个标准名，避免误匹配「备注/采购方/采购者/库存量」等业务列。
    # 历史教训：把「备注」当 状态 会把"供应商现货待付款"等备注文字误判为 状态。
    "状态": ["状态", "处理状态", "进度", "是否解决", "解决状态"],
}

# 在线表中常被纵向合并单元格的列；解析时空值按项目/单据做前向填充
FILL_FORWARD_FIELDS = {"项目编码", "项目", "单据日期", "申请部门", "单据编号", "期望交期", "预计到货时间"}
# 日期/交期类列更敏感，仅在同一个单据编号内前向填充，避免跨单据污染
DATE_LIKE_FIELDS = {"期望交期", "预计到货时间"}

# 本次同步中检测到的「整表归档」子表名称（供前端/日志透明展示，便于核对规则是否误触发）
ARCHIVED_SHEETS = []


def _run_wecom(args, timeout=60):
    """用 cmd /c 调用 wecom-cli.cmd，隐藏窗口，避免黑窗。

    非 Windows 平台不强行传 creationflags，否则 subprocess 直接抛
    "creationflags is only supported on Windows platforms"。
    同时清理失效代理环境变量，避免 wecom-cli 走不可用的本地代理。
    """
    cmd = [SYSTEM_CMD, "/c", WECOM_CMD] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL,
                           env=_clean_env_for_subprocess(),
                           **_win_subprocess_kwargs())
    except Exception as e:
        r = type('R', (), {'returncode': -1, 'stdout': '', 'stderr': str(e)})()
    try:
        with open(os.path.join(os.path.dirname(__file__), "wecom_debug.log"), "a", encoding="utf-8") as f:
            f.write("[%.3f] rc=%s stdout_len=%s stderr=%s\n" % (
                time.time(), r.returncode, len(r.stdout or ""), (r.stderr or "")[:200]))
    except Exception:
        pass
    return r


def _list_sheets(timeout=90, retry=3):
    """列出欠料表所有子表 (sheet_id, title, row_count, column_count)。

    对 rc=1 等企微频率限制做 retry 次退避重试（2s/4s/8s），避免偶发限流导致整次同步失败。
    """
    last_err = None
    for attempt in range(1, retry + 1):
        r = _run_wecom(["sheet", "get", "--docid", SHORTAGE_URL], timeout=timeout)
        if r.returncode == 0 and (r.stdout or "").strip():
            try:
                data = json.loads(r.stdout)
            except Exception as e:
                last_err = RuntimeError("子表列表响应解析异常: %s | 原始=%s" % (
                    e, (r.stdout or "")[:300]))
                time.sleep(2 * attempt)
                continue
            if data.get("errcode", 0) == 0:
                sheets = data.get("sheets") or []
                if sheets:
                    return sheets
                raise RuntimeError("欠料表无子表可读（sheets 为空）")
            last_err = RuntimeError("子表列表接口错误: errcode=%s errmsg=%s" % (
                data.get("errcode"), data.get("errmsg")))
        else:
            # rc=1 通常是企微频率限制；err 为空时补充可读提示
            rc = r.returncode
            err = (r.stderr or "").strip()
            hint = ""
            if rc == 1 and not err:
                hint = "（企微频率限制，请稍后再试）"
            last_err = RuntimeError("获取子表列表失败: rc=%s err=%s%s" % (
                rc, err[:200], hint))
        if attempt < retry:
            wait = 2 * (2 ** (attempt - 1))  # 2s, 4s, 8s
            print("[sync] 获取子表列表失败(第%d次)，%ds 后重试: %s" % (
                attempt, wait, last_err))
            time.sleep(wait)
    raise last_err


def _fetch_sheet_csv(sheet_id, timeout=120, retry=3):
    """读取单个子表全部数据（CSV 格式，同步接口，无 task_id 轮询）。

    单子表读取会按 retry 次重试（每次重试间隔递增 2s/4s/8s），应对偶发的频率限制。
    """
    last_err = None
    for attempt in range(1, retry + 1):
        r = _run_wecom(["sheet", "ranges", "get", "--docid", SHORTAGE_URL,
                        "--sheet-id", sheet_id, "--mode", "csv"], timeout=timeout)
        if r.returncode == 0 and (r.stdout or "").strip():
            try:
                data = json.loads(r.stdout)
            except Exception as e:
                last_err = RuntimeError("子表 %s 响应解析异常: %s | 原始=%s" % (
                    sheet_id, e, (r.stdout or "")[:300]))
                time.sleep(2 * attempt)
                continue
            if data.get("errcode", 0) == 0:
                return data.get("content", "")
            last_err = RuntimeError("子表 %s 错误: errcode=%s errmsg=%s" % (
                sheet_id, data.get("errcode"), data.get("errmsg")))
        else:
            last_err = RuntimeError("子表 %s 失败: rc=%s err=%s" % (
                sheet_id, r.returncode, (r.stderr or "")[:200]))
        if attempt < retry:
            wait = 2 * (2 ** (attempt - 1))  # 2s, 4s, 8s
            print("[sync] 子表 %s 失败(第%d次)，%ds 后重试: %s" % (
                sheet_id, attempt, wait, last_err))
            time.sleep(wait)
    raise last_err


def _sheet_is_archived(header, ncols, norm_rows):
    """判断子表是否「整表归档」：扫描表尾行，若存在「无有效物料编码」且文本含「已归档」的页脚行即命中。

    页脚行特征（区别于普通数据行）：物料编码列为空或不满足物料编码格式，且整行几乎为空
    （非空白单元格 ≤ 3 个，仅承载「已归档」注解）。

    这样不会把「逐行标注已归档」的正常数据行（物料编码列有效）误判，
    也不会把「物料编码列因合并单元格走漏而变空、但其余列仍填满」的逐行已归档数据行误判为整表归档
    （这类行非空白单元格远多于 3 个）。仅在表尾 15 行内扫描，匹配用户
    「分表后面标注已归档」的语义，并进一步降低误触发概率。
    """
    mc_idx = -1
    for j, h in enumerate(header[:ncols]):
        if h == "物料编码":
            mc_idx = j
            break
    if mc_idx < 0:
        return False  # 无物料编码列的子表本身不产生条目，无需归档判定
    tail = norm_rows[-15:] if len(norm_rows) > 15 else norm_rows
    for r in tail:
        mc = r[mc_idx].strip() if mc_idx < len(r) else ""
        if _is_material_code(mc):
            continue  # 普通数据行（含有效物料编码的逐行已归档行），跳过
        non_empty = [c.strip() for c in r if c.strip()]
        if not non_empty:
            continue  # 全空行（表尾间隔行），跳过
        # 必须是「页脚注解」性质：几乎为空，仅含「已归档」
        if len(non_empty) <= 3 and any("已归档" in c for c in non_empty):
            return True
    return False


def _csv_to_markdown(sheet_title, csv_text):
    """将单子表 CSV 转成 markdown 表格，复用 parse_markdown 的解析逻辑。

    输入：子表标题 + wecom-cli sheet ranges get --mode csv 返回的 content 字段。
    输出：(markdown 字符串, archived 布尔)。markdown 首行为子表标题，后续为表格；
    若整表归档，则所有数据行的「状态」改写为「已归档」，由下游 filter_active 统一过滤
    （与「逐行标注已归档」走同一套查询期过滤逻辑，行为一致、可逆：去掉页脚即恢复）。

    CSV 解析用 Python 标准 csv 模块，支持：
    - 双引号包裹的字段（含逗号、换行、引号）
    - 双引号转义（"" 表示一个 "）
    """
    if not csv_text.strip():
        return "", False
    # wecom-cli 返回的 CSV 已经是 RFC 4180 标准格式，csv 模块可正确解析
    reader = csv.reader(io.StringIO(csv_text))
    rows = [r for r in reader if r]  # 过滤空行

    if not rows:
        return "", False

    # 找列头行：含 "物料编码" 且含 欠料数量 候选
    header_idx = -1
    for i, r in enumerate(rows):
        joined = "|".join(r)
        if "物料编码" in joined and any(alias in joined for alias in COL_ALIASES["欠料数量"]):
            header_idx = i
            break
    if header_idx < 0:
        # 找不到表头行（极少见：子表全空或格式特殊），整块跳过
        return "", False

    header = rows[header_idx]
    # 真实列数 = 表头中非空 cell 数。处理 0810 类「表头后段全空」sheet：
    # 它的 CSV 每行 24 cell 但只有 14 列是有效列；剩余 10 列常被错误填充为下行走漏。
    ncols = sum(1 for h in header if h.strip())
    if ncols < len(header):
        # 把表头后段空 cell 替换为明确的空字符串（保持索引）
        header = [h if h.strip() else "" for h in header]
    # 规范化：先检测走漏再截断，避免误丢下行走漏数据
    norm_rows = []
    for r in rows[header_idx + 1:]:
        # 检测「下行走漏」：状态/处理状态列出现 9 位项目编码（260xxxxxx），
        # 说明这是下一行的项目编码漏到本行。把当前状态列清空，
        # 后续 cell 整体左移 1 位作为新行追加。
        status_col = -1
        for j, h in enumerate(header[:ncols]):
            if h in ("处理状态", "状态", "进度", "是否解决", "解决状态"):
                status_col = j
                break
        if 0 <= status_col < len(r) and re.match(r"^2\d{8}$", r[status_col].strip()):
            tail = r[status_col + 1:]
            if any(c.strip() for c in tail):
                # 当前行：状态列清空
                fixed = r[:status_col] + [""] + r[status_col + 1:]
                norm_rows.append(fixed[:ncols] if len(fixed) >= ncols else fixed + [""] * (ncols - len(fixed)))
                # 下一行：tail 是不完整的下一行（缺前 status_col 个 cell）
                # 直接作为新行追加，parse_markdown 会按物料编码位置自动左对齐补空
                next_row = tail
                if len(next_row) < ncols:
                    next_row = next_row + [""] * (ncols - len(next_row))
                norm_rows.append(next_row[:ncols])
                continue
        # 常规：截断到 ncols
        r = r[:ncols]
        if len(r) < ncols:
            r = r + [""] * (ncols - len(r))
        norm_rows.append(r)

    # --- 整表归档检测（v1.6.4）：子表末尾出现「已归档」页脚行，则整表不计入统计 ---
    # 命中后把该子表所有数据行的「状态」改写为「已归档」，复用 filter_active 统一过滤，
    # 与「逐行标注已归档」走同一套查询期过滤逻辑，行为一致、可逆（去掉页脚即恢复）。
    archived = _sheet_is_archived(header, ncols, norm_rows)
    if archived:
        st_idx = -1
        for j, h in enumerate(header[:ncols]):
            if h in ("状态", "处理状态", "进度", "是否解决", "解决状态"):
                st_idx = j
                break
        if st_idx >= 0:
            norm_rows = [[("已归档" if j == st_idx else c) for j, c in enumerate(r)]
                         for r in norm_rows]
            print("[sync] 子表 %r 检测到整表归档页脚，整表 %d 行标记为已归档（不计入任何统计）"
                  % (sheet_title, len(norm_rows)))
        else:
            # 无状态列时无法标记，整表直接排除（不入库）
            print("[sync] 子表 %r 整表归档但无状态列，整表排除（不入库）" % sheet_title)
            return "", True

    lines = [sheet_title]
    # 用安全的转义：把 markdown 表格中的 | 转义为 \|，避免字段值里的 | 破坏表格结构
    def _esc(v):
        return str(v).replace("|", "\\|").replace("\n", " ")
    lines.append("| " + " | ".join(_esc(c) for c in header) + " |")
    lines.append("|" + "|".join(["---"] * ncols) + "|")
    for r in norm_rows:
        lines.append("| " + " | ".join(_esc(c) for c in r) + " |")
    return "\n".join(lines), archived


def fetch_markdown(max_retry=3, inter_sheet_delay=2.0):
    """新版：用 wecom-cli sheet API 拉取所有子表，CSV → markdown → parse_markdown。

    失败时整体重试 max_retry 次（任一子表读取失败都触发整次重试）。
    子表之间默认停顿 1.5s，避免触发企微的瞬时频率限制。
    单子表读取失败会内部重试 3 次，3 次都失败才跳过该子表继续。
    返回 markdown 字符串，与旧版同接口兼容，parse_markdown 不用改。
    同时把检测到的「整表归档」子表名收集到 ARCHIVED_SHEETS，供前端/日志透明展示。
    """
    last_err = None
    ARCHIVED_SHEETS.clear()
    for attempt in range(1, max_retry + 1):
        try:
            sheets = _list_sheets()
            md_chunks = []
            ok_sids = []
            failed_sids = []
            for idx, s in enumerate(sheets):
                sid = s.get("sheet_id")
                title = s.get("title") or sid or "未命名子表"
                if not sid:
                    print("[sync] 跳过无 sheet_id 的子表: %s" % s)
                    continue
                try:
                    csv = _fetch_sheet_csv(sid)
                except Exception as e:
                    # 单个子表失败不阻断整体，仅记录并跳过（保证最差也有 90% 数据）
                    print("[sync] 子表 %s(%s) 跳过: %s" % (title, sid, e))
                    failed_sids.append(sid)
                    continue
                md, archived = _csv_to_markdown(title, csv)
                if archived:
                    ARCHIVED_SHEETS.append(title)
                if md:
                    md_chunks.append(md)
                    ok_sids.append(sid)
                # 最后一个子表不 sleep（避免无意义等待）
                if inter_sheet_delay > 0 and idx < len(sheets) - 1:
                    time.sleep(inter_sheet_delay)
            if not md_chunks:
                raise RuntimeError("所有子表都为空/失败，无法解析（失败子表: %s）" % failed_sids)
            if failed_sids:
                print("[sync] 警告：%d 个子表读取失败被跳过: %s" % (len(failed_sids), failed_sids))
            print("[sync] 成功拉取 %d/%d 个子表；整表归档 %d 个：%s"
                  % (len(ok_sids), len(sheets), len(ARCHIVED_SHEETS), ARCHIVED_SHEETS))
            return "\n\n".join(md_chunks)
        except Exception as e:
            last_err = e
            print("[sync] 拉取失败(第%d次): %s" % (attempt, e))
            if attempt < max_retry:
                time.sleep(5)
                continue
    raise RuntimeError("拉取欠料表失败(重试%d次): %s" % (max_retry, last_err))


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
    """多子表自适应解析：遇到含 物料编码+欠料数量 的表头行就重置列映射。

    额外处理纵向合并单元格：wecom-cli 导出 markdown 时，合并单元格只在首行保留值，
    后续行该列会变成空字符串。解析时对 项目编码/项目/单据编号/申请部门/单据日期/
    期望交期/预计到货时间 做前向填充，但日期类字段仅在同一个 单据编号 内填充，
    避免跨单据污染。
    """
    lines = md.split("\n")
    # 分隔行：整行仅由 |、-、:、空白组成，避免把纵向合并单元格后的空值行误判为分隔行
    sep = re.compile(r"^\|(\s*[-:]+\s*\|)+$")
    cur = {}
    items = []
    current_sheet = ""
    num_cols = 0            # 当前子表表头列数（用于修正合并单元格导致的列错位）
    last_values = {}        # 当前项目分组内最近非空值
    last_doc_no = ""        # 当前单据编号（用于日期类字段分组）

    def _raw(f, cells):
        i = cur.get(f, -1)
        return cells[i].strip() if 0 <= i < len(cells) else ""

    def _maybe_reset(raw_code, raw_project, raw_doc_no):
        """项目切换时重置前向缓存；单据切换时仅重置日期类缓存。"""
        nonlocal last_doc_no
        code_changed = bool(raw_code and raw_code != last_values.get("项目编码"))
        project_changed = bool(raw_project and raw_project != last_values.get("项目"))
        if code_changed or project_changed:
            last_values.clear()
            last_doc_no = ""
        if raw_doc_no and raw_doc_no != last_doc_no:
            for f in DATE_LIKE_FIELDS:
                last_values.pop(f, None)
            last_doc_no = raw_doc_no

    def _g(f, cells):
        """取单元格值；空值且在填充列表中时，使用 last_values 前向填充。"""
        v = _raw(f, cells)
        if v:
            last_values[f] = v
            return v
        if f in FILL_FORWARD_FIELDS and f in last_values:
            return last_values[f]
        return ""

    for l in lines:
        s = l.strip()
        if s and not s.startswith("|") and not s.startswith("---") and len(s) <= 40:
            current_sheet = s
            # 切换 sheet 时清空缓存（理论上 sheet 内会重置表头，保险起见）
            last_values.clear()
            last_doc_no = ""
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
            num_cols = len(cells)
            last_values.clear()
            last_doc_no = ""
            continue
        mc_i = cur.get("物料编码", -1)
        # 修正纵向合并单元格导致的列错位：后续行前面空列可能被省略，
        # 根据物料编码列位置做左补空，使后续数据对齐表头。
        if 0 <= mc_i < num_cols and len(cells) < num_cols:
            for k, c in enumerate(cells):
                if _is_material_code(c):
                    pad = mc_i - k
                    if pad > 0:
                        cells = [""] * pad + cells
                    break
        if mc_i < 0 or mc_i >= len(cells):
            continue
        mc = cells[mc_i]
        if not _is_material_code(mc):
            continue
        sq_i = cur.get("欠料数量", -1)
        sq = cells[sq_i].replace(",", "") if 0 <= sq_i < len(cells) else ""
        if not re.match(r'^-?\d+(\.\d+)?$', sq):
            continue

        raw_code = _raw("项目编码", cells)
        raw_project = _raw("项目", cells)
        raw_doc_no = _raw("单据编号", cells)
        _maybe_reset(raw_code, raw_project, raw_doc_no)

        project = _g("项目", cells) or _g("项目编码", cells) or ""
        project_code = _g("项目编码", cells)
        eta = _g("预计到货时间", cells)
        items.append({
            "项目": project,
            "项目编码": project_code,
            "物料编码": mc,
            "规格说明": _g("规格说明", cells),
            "审核日期": _g("审核日期", cells),
            "物料名称": _g("物料名称", cells),
            "品牌": _g("品牌", cells),
            "产地": _g("产地", cells),
            "欠料数量": int(float(sq)),
            "预计到货时间": eta,
            "期望交期": _g("期望交期", cells),
            "状态": _g("状态", cells),
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


def _item_key(item):
    """业务标识：项目编码|物料编码；项目编码为空时用项目名称兜底。"""
    pc = (item.get("项目编码") or item.get("项目") or "").strip()
    mc = (item.get("物料编码") or "").strip()
    return "%s|%s" % (pc, mc)


def sync_to_db(offline_md=None, db_path=None):
    """拉取(或离线)并解析，写入 SQLite。返回 (条数, synced_at)。失败抛异常（保留旧数据）。

    数据源：offline_md(测试) > 企微 API(若配凭证) > 本地 wecom-cli。
    同步完成后对比上次快照，识别真正新增的条目并记录到 weekly_new_items。
    """
    if db_path is None:
        db_path = db.DEFAULT_DB
    # 每条同步开始时重置（覆盖 offline 路径不会调用 fetch_markdown 的情况）
    ARCHIVED_SHEETS.clear()
    if not offline_md and not can_sync_online():
        raise RuntimeError(
            "当前环境无法在线同步企业微信欠料表：未配置企微开放 API 凭证，"
            "且未检测到 wecom-cli（仅本地 Windows 可用）。"
            "云端 Render 显示的是最近一次本地同步推送的 seed.sql 快照。"
            "如需云端实时同步，请在 Render 环境变量中配置 WECOM_API_CORP_ID、"
            "WECOM_API_CORP_SECRET、WECOM_TABLE_DOCID。"
        )
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
    from datetime import datetime, timedelta
    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.upsert_items(items, synced_at, path=db_path)

    # --- 识别真正新增条目 ---
    try:
        last_keys = db.get_last_snapshot(path=db_path)
        current_keys = {_item_key(i) for i in items}
        new_keys = current_keys - last_keys
        if new_keys:
            new_items = [i for i in items if _item_key(i) in new_keys]
            today = datetime.now().date()
            week_start = (today - timedelta(days=today.weekday())).isoformat()
            db.record_weekly_new_items(new_items, week_start, synced_at, path=db_path)
            print("[sync] 本周新增 %d 条材料" % len(new_items))
        db.save_snapshot(items, synced_at, path=db_path)
        db.clean_old_weekly_items(path=db_path)
    except Exception as e:
        # 快照/新增记录失败不影响主同步，仅打印日志
        print("[sync] 新增快照记录失败: %s" % e)

    # --- 持久化「整表归档」子表名单，供前端透明展示 / 核对是否误触发 ---
    try:
        db.set_meta("archived_sheets", json.dumps(ARCHIVED_SHEETS, ensure_ascii=False), path=db_path)
    except Exception as e:
        print("[sync] archived_sheets 持久化失败（不影响主同步）: %s" % e)

    return len(items), synced_at


if __name__ == "__main__":
    offline = None
    for a in sys.argv[1:]:
        if a.startswith("--offline="):
            offline = a.split("=", 1)[1]
    n, t = sync_to_db(offline_md=offline)
    print("同步完成：%d 条 @ %s" % (n, t))
