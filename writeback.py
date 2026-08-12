# -*- coding: utf-8 -*-
"""在线表写回：把本地确认的「已到货 / 已解决」同步写回企业微信在线表对应单元格。

定位思路（安全优先）：
- 每个本地条目都带 `sheet`（子表标题），据此在 sheet_get_info 中定位在线子表(sheet_id)。
- 重新拉取在线表 markdown，解析该子表，按 (物料编码 + 欠料数量 + 项目) 精确定位数据行，
  由行号推算网格坐标（表头=第 0 行 → 起始行 = 数据行序号 + 1）。
- 多重安全闸：子表必须单表连续、唯一命中、坐标在界内、状态列存在；否则跳过并告警。
- 写操作不可逆，调用方必须先「预览」并经用户确认后再调用 apply_online_write。
"""
import re
import sync

# 状态列候选名（与 sync.COL_ALIASES["状态"] 一致）
STATUS_ALIASES = sync.COL_ALIASES["状态"]  # ["状态","处理状态","进度","是否解决","备注"]
_MC_RE = re.compile(r'^[A-Za-z][A-Za-z0-9\-]{4,}$')


def _col_index(header, aliases):
    """返回表头中首个命中别名的列下标；未命中返回 -1。"""
    for a in aliases:
        if a in header:
            return header.index(a)
    return -1


def _extract_section(md, title):
    """从完整 markdown 中截取某个子表(title)段落，返回行列表（不含标题行）。"""
    lines = md.split("\n")
    start = None
    for i, l in enumerate(lines):
        s = l.strip()
        if s and not s.startswith("|") and not s.startswith("---") and len(s) <= 40:
            if s == title or s.lower() == title.lower():
                start = i
                break
    if start is None:
        return None
    out = []
    for l in lines[start + 1:]:
        s = l.strip()
        if s and not s.startswith("|") and not s.startswith("---") and len(s) <= 40:
            break  # 下一个子表标题，停止截取
        out.append(s)
    return out


def _parse_section(section):
    """解析子表 markdown 段落。

    返回 {"header", "rows"(单元格列表), "grid_rows"(每行对应的真实网格行号,0基),
    "table_count", "gap_detected"}。
    网格行号按「非分隔符的真实表格行」计数，自动容纳表头前的合并标题行等偏移，
    避免写到错误坐标。
    """
    sep = re.compile(r"^\|[\s:|-]+\|$")
    header = None
    rows = []
    grid_rows = []
    table_count = 0
    gap_detected = False
    seen_data = False
    grid_line = -1  # 真实网格行计数器（分隔符行不计）
    for s in section:
        if not s.startswith("|"):
            if seen_data and s:  # 数据区内的非空非表格行 → 疑似断层
                gap_detected = True
            continue
        if sep.match(s):
            continue  # 分隔符不是真实网格行
        grid_line += 1
        cells = [c.strip() for c in s.strip("|").split("|")]
        has_mc = "物料编码" in cells
        sq_idx = _col_index(cells, sync.COL_ALIASES["欠料数量"])
        if has_mc and sq_idx >= 0 and len(cells) >= 5:
            header = cells
            table_count += 1
            continue
        if header is None:
            continue
        mc_i = _col_index(header, ["物料编码"])
        sq_i = _col_index(header, sync.COL_ALIASES["欠料数量"])
        if mc_i < 0 or mc_i >= len(cells):
            continue
        mc = cells[mc_i]
        if not (_MC_RE.match(mc) and "-" in mc):
            continue
        sq = cells[sq_i].replace(",", "").strip() if 0 <= sq_i < len(cells) else ""
        if not re.match(r'^-?\d+(\.\d+)?$', sq):
            continue
        rows.append(cells)
        grid_rows.append(grid_line)
        seen_data = True
    return {"header": header, "rows": rows, "grid_rows": grid_rows,
            "table_count": table_count, "gap_detected": gap_detected}


def plan_online_write(matched_items, new_status="已到货"):
    """计算在线表写回计划（只读，不改任何数据）。

    返回 {"plan": [...], "warnings": [...]}。
    plan 每项含 sheet_title/sheet_id/start_row/start_column/old_status/new_status/
    project/material_code/qty，交由前端预览确认后传给 apply_online_write。
    """
    plan = []
    warnings = []
    if not matched_items:
        return {"plan": plan, "warnings": warnings}
    # 按子表分组
    by_sheet = {}
    for it in matched_items:
        sh = (it.get("sheet") or "").strip()
        if sh:
            by_sheet.setdefault(sh, []).append(it)
    if not by_sheet:
        warnings.append("匹配项均无子表信息，无法定位在线表")
        return {"plan": plan, "warnings": warnings}
    # 取在线表结构
    try:
        info = sync.sheet_get_info()
    except Exception as e:
        warnings.append("获取在线表结构失败（将仅本地更新）：%s" % e)
        return {"plan": plan, "warnings": warnings}
    titles = {s["title"]: s for s in info.get("sheets", [])}
    # 拉取在线表内容
    try:
        md = sync.fetch_markdown()
    except Exception as e:
        warnings.append("拉取在线表内容失败（将仅本地更新）：%s" % e)
        return {"plan": plan, "warnings": warnings}

    for sh, items in by_sheet.items():
        meta = titles.get(sh) or next((v for k, v in titles.items() if k.lower() == sh.lower()), None)
        if not meta:
            warnings.append("在线表未找到子表「%s」，跳过" % sh)
            continue
        section = _extract_section(md, sh)
        if section is None:
            warnings.append("在线表子表「%s」内容未定位，跳过" % sh)
            continue
        parsed = _parse_section(section)
        if parsed["header"] is None:
            warnings.append("子表「%s」未解析到表头，跳过" % sh)
            continue
        if parsed["table_count"] > 1:
            warnings.append("子表「%s」含多个不连续表格，为安全跳过在线写回" % sh)
            continue
        if parsed["gap_detected"]:
            warnings.append("子表「%s」检测到非连续空行，为安全跳过在线写回" % sh)
            continue
        header = parsed["header"]
        grid_rows = parsed["grid_rows"]
        status_col = _col_index(header, STATUS_ALIASES)
        if status_col < 0:
            warnings.append("子表「%s」未找到状态列(%s)，跳过" % (sh, "/".join(STATUS_ALIASES)))
            continue
        mc_i = _col_index(header, ["物料编码"])
        sq_i = _col_index(header, sync.COL_ALIASES["欠料数量"])
        proj_i = _col_index(header, ["项目", "项目名称"])
        rows = parsed["rows"]
        row_count = int(meta.get("row_count", 0))
        for it in items:
            mc = (it.get("物料编码") or "").strip()
            try:
                qty = int(float(it.get("欠料数量") or 0))
            except Exception:
                qty = None
            proj = (it.get("项目") or "").strip()
            cands = []
            for ri, cells in enumerate(rows):
                if cells[mc_i].strip() != mc:
                    continue
                try:
                    cq = int(float(cells[sq_i].replace(",", "").strip() or 0))
                except Exception:
                    cq = None
                if cq != qty:
                    continue
                if proj and proj_i >= 0 and cells[proj_i].strip() and cells[proj_i].strip() != proj:
                    continue
                cands.append((ri, cells))
            if not cands:
                warnings.append("子表「%s」未定位到 %s/%s 的行，跳过" % (sh, proj or "?", mc))
                continue
            if len(cands) > 1:
                warnings.append("子表「%s」中 %s/%s 命中多行，为安全跳过（请手动更新）" % (sh, proj or "?", mc))
                continue
            ri, cells = cands[0]
            start_row = grid_rows[ri]  # 真实网格行号（0基），已含表头前偏移
            if start_row < 0 or start_row + 1 > row_count:
                warnings.append("子表「%s」行号越界，跳过" % sh)
                continue
            old_status = cells[status_col] if status_col < len(cells) else ""
            plan.append({
                "sheet_title": sh,
                "sheet_id": meta["sheet_id"],
                "start_row": start_row,
                "start_column": status_col,
                "old_status": old_status,
                "new_status": new_status,
                "project": proj,
                "material_code": mc,
                "qty": qty,
            })
    return {"plan": plan, "warnings": warnings}


def apply_online_write(plan):
    """按 plan 把 new_status 写入在线表对应单元格。返回每条结果（成功/失败）。"""
    results = []
    for e in plan:
        grid_data = {
            "start_row": e["start_row"],
            "start_column": e["start_column"],
            "rows": [{"values": [{"cell_value": {"text": e["new_status"]}, "data_type": "TEXT"}]}],
        }
        try:
            sync.sheet_update_range_data(e["sheet_id"], grid_data)
            results.append({"ok": True, "sheet_title": e["sheet_title"],
                            "start_row": e["start_row"], "start_column": e["start_column"],
                            "old_status": e["old_status"], "new_status": e["new_status"]})
        except Exception as ex:
            msg = str(ex)
            # 区分权限类错误，给出可读提示
            if "851003" in msg or "no authority" in msg.lower():
                err_type = "no_authority"
                friendly = "智能机器人缺少该在线表的【编辑】权限（errcode 851003）"
            elif "851014" in msg:
                err_type = "no_auth"
                friendly = "智能机器人未授权访问该文档（errcode 851014），请重新授权"
            else:
                err_type = "other"
                friendly = msg[:200]
            results.append({"ok": False, "sheet_title": e["sheet_title"],
                            "start_row": e["start_row"], "start_column": e["start_column"],
                            "error": friendly, "error_type": err_type})
    return results
