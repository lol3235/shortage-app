# -*- coding: utf-8 -*-
"""查询与汇总逻辑（纯函数，便于测试）。移植自原 shortage_tool/bot_logic.py。

所有函数接收 items 列表（建议先用 filter_active 过滤已解决/归档）。
新增 cmd_brand_summary（品牌汇总）。
"""
import re
import datetime
from collections import Counter, defaultdict


# 已解决/归档/到货/关闭等状态关键字：命中即视为「不计入」。
RESOLVED_KEYWORDS = ("已解决", "归档", "已完成", "完成", "已关闭", "关闭",
                     "已领", "已到货", "已到", "取消", "作废")


def is_resolved(item):
    s = (item.get("状态") or "").strip()
    return bool(s and any(k in s for k in RESOLVED_KEYWORDS))


def filter_active(items):
    """过滤掉已解决/归档的条目（隐藏行/分表的可靠代理）。"""
    return [i for i in items if not is_resolved(i)]


def _fmt_sheets(counter):
    """把 sheet 出现次数格式化为 '表名:行数 / 表名:行数'。"""
    if not counter:
        return "—"
    return " / ".join(f"{k}:{v}" for k, v in counter.most_common())


def _parse_date(s):
    """尽力把交期文本解析成 (年,月,日)；无法识别或日期非法返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if re.search(r"现货|已发|今天|已到|马上|即时", s):
        return datetime.date.today().timetuple()[:3]
    # 优先：YYYY-MM-DD / YYYY/M/D
    m = re.search(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", s)
    if m:
        try:
            datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # 中文：X月X日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", s)
    if m:
        try:
            datetime.date(2026, int(m.group(1)), int(m.group(2)))
            return (2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    # 其余：M/D 或 M-D（按当年）
    m = re.search(r"(\d{1,2})\s*[./-]\s*(\d{1,2})", s)
    if m:
        try:
            datetime.date(2026, int(m.group(1)), int(m.group(2)))
            return (2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def overview(items):
    """总览聚合：指标 + 紧急度分布 + 项目 TOP。"""
    if not items:
        return {"total": 0, "total_qty": 0, "urgent": 0, "sheets": 0,
                "by_status": {}, "by_project": []}
    by_status = Counter(i.get("eta_status", "其他") for i in items)
    by_project = defaultdict(lambda: {"count": 0, "sheets": Counter()})
    for i in items:
        proj = i.get("项目") or i.get("项目编码") or "未命名"
        by_project[proj]["count"] += 1
        by_project[proj]["sheets"][i.get("sheet") or "未知"] += 1
    urgent = sum(by_status.get(s, 0) for s in ("空白", "无交期", "付款瓶颈"))
    sheets = len(set(i.get("sheet") for i in items if i.get("sheet")))
    return {
        "total": len(items),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in items),
        "urgent": urgent,
        "sheets": sheets,
        "by_status": dict(by_status),
        "by_project": sorted(
            [{"project": p, "count": info["count"], "sheets": _fmt_sheets(info["sheets"])}
             for p, info in by_project.items()],
            key=lambda x: -x["count"])[:10],
    }


def search(items, kw):
    kw = (kw or "").strip()
    if not kw:
        return []
    k = kw.lower()
    rows = [i for i in items if any(k in str(i.get(f, "")).lower()
            for f in ["项目", "项目编码", "物料编码", "物料名称", "品牌", "规格说明"])]
    return rows


def project_summary(items, kw):
    kw = (kw or "").strip()
    k = kw.lower()
    if kw:
        rows = [i for i in items if k in str(i.get("项目") or i.get("项目编码") or "").lower()]
        if not rows:
            return {"error": "未找到项目「%s」的欠料" % kw}
    else:
        rows = items
    if not rows:
        return {"error": "当前无欠料数据"}

    by_material = defaultdict(lambda: {"qty": 0, "name": "", "status": Counter(), "brands": Counter(), "sheets": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        by_material[mc]["sheets"][i.get("sheet") or "未知"] += 1
        b = (i.get("品牌") or "").strip()
        if b:
            by_material[mc]["brands"][b] += 1

    def _pick_brand(counter):
        if not counter:
            return "—"
        top = counter.most_common(2)
        if len(top) == 2 and top[0][1] == top[1][1]:
            return "/".join(sorted([top[0][0], top[1][0]]))
        return top[0][0]

    # keyword 为空时返回「全部项目汇总」供默认展示
    if not kw:
        by_project = defaultdict(lambda: {"qty": 0, "status": Counter(), "sheets": Counter()})
        for i in rows:
            proj = i.get("项目") or i.get("项目编码") or "未命名"
            by_project[proj]["qty"] += int(i.get("欠料数量") or 0)
            by_project[proj]["status"][i.get("eta_status", "其他")] += 1
            by_project[proj]["sheets"][i.get("sheet") or "未知"] += 1
        return {
            "keyword": "",
            "mode": "all_projects",
            "rows": len(rows),
            "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
            "by_status": dict(Counter(i.get("eta_status", "其他") for i in rows)),
            "by_project": sorted(
                [{"project": p, "qty": info["qty"],
                  "status": dict(info["status"]), "sheets": _fmt_sheets(info["sheets"])}
                 for p, info in by_project.items()],
                key=lambda x: -x["qty"])[:50],
        }

    return {
        "keyword": kw,
        "mode": "single_project",
        "rows": len(rows),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
        "by_status": dict(Counter(i.get("eta_status", "其他") for i in rows)),
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"], "brand": _pick_brand(info["brands"]),
              "status": dict(info["status"]), "sheets": _fmt_sheets(info["sheets"])} for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
    }


def material_summary(items, kw):
    kw = (kw or "").strip()
    k = kw.lower()
    if kw:
        rows = [i for i in items if any(
            k in str(i.get(f, "")).lower()
            for f in ["物料名称", "物料编码", "规格说明", "品牌"]
        )]
        if not rows:
            return {"error": "未找到物料「%s」的缺货记录" % kw}
    else:
        rows = items
    if not rows:
        return {"error": "当前无欠料数据"}

    by_material = defaultdict(lambda: {"qty": 0, "name": "", "projects": set(), "status": Counter(), "sheets": Counter()})
    by_project = defaultdict(lambda: {"qty": 0, "status": Counter(), "sheets": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        sheet = i.get("sheet") or "未知"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["projects"].add(i.get("项目") or i.get("项目编码") or "未命名")
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        by_material[mc]["sheets"][sheet] += 1
        proj = i.get("项目") or i.get("项目编码") or "未命名"
        by_project[proj]["qty"] += int(i.get("欠料数量") or 0)
        by_project[proj]["status"][i.get("eta_status", "其他")] += 1
        by_project[proj]["sheets"][sheet] += 1

    result = {
        "keyword": kw,
        "mode": "search" if kw else "all_materials",
        "rows": len(rows),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"],
              "projects": len(info["projects"]), "status": dict(info["status"]),
              "sheets": _fmt_sheets(info["sheets"])}
             for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
    }
    # 带 keyword 时额外展示项目分布与明细；默认全部物料只给物料列表（防信息过载）
    if kw:
        result["by_project"] = sorted(
            [{"project": p, "qty": info["qty"], "status": dict(info["status"]),
              "sheets": _fmt_sheets(info["sheets"])}
             for p, info in by_project.items()],
            key=lambda x: -x["qty"])[:15]
        result["details"] = rows[:30]
    return result


def brand_summary(items, kw):
    """按品牌汇总欠料（新增）。keyword 为空时返回全部品牌汇总。"""
    kw = (kw or "").strip()
    k = kw.lower()
    if kw:
        rows = [i for i in items if k in str(i.get("品牌", "")).lower()]
        if not rows:
            return {"error": "未找到品牌「%s」的欠料记录" % kw}
    else:
        rows = items
    if not rows:
        return {"error": "当前无欠料数据"}

    # keyword 为空：直接按品牌聚合
    if not kw:
        by_brand = defaultdict(lambda: {"qty": 0, "materials": set(), "status": Counter(), "sheets": Counter()})
        for i in rows:
            b = (i.get("品牌") or "").strip() or "未填品牌"
            by_brand[b]["qty"] += int(i.get("欠料数量") or 0)
            by_brand[b]["materials"].add(i.get("物料编码") or i.get("物料名称") or "—")
            by_brand[b]["status"][i.get("eta_status", "其他")] += 1
            by_brand[b]["sheets"][i.get("sheet") or "未知"] += 1
        return {
            "keyword": "",
            "mode": "all_brands",
            "rows": len(rows),
            "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
            "by_status": dict(Counter(i.get("eta_status", "其他") for i in rows)),
            "by_brand": sorted(
                [{"brand": b, "qty": info["qty"], "materials": len(info["materials"]),
                  "status": dict(info["status"]), "sheets": _fmt_sheets(info["sheets"])}
                 for b, info in by_brand.items()],
                key=lambda x: -x["qty"])[:50],
        }

    total_qty = sum(int(i.get("欠料数量") or 0) for i in rows)
    by_material = defaultdict(lambda: {"qty": 0, "name": "", "projects": set(), "status": Counter(), "sheets": Counter()})
    by_project = defaultdict(lambda: {"qty": 0, "status": Counter(), "sheets": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        sheet = i.get("sheet") or "未知"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["projects"].add(i.get("项目") or i.get("项目编码") or "未命名")
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        by_material[mc]["sheets"][sheet] += 1
        proj = i.get("项目") or i.get("项目编码") or "未命名"
        by_project[proj]["qty"] += int(i.get("欠料数量") or 0)
        by_project[proj]["status"][i.get("eta_status", "其他")] += 1
        by_project[proj]["sheets"][sheet] += 1
    return {
        "keyword": kw,
        "mode": "single_brand",
        "rows": len(rows),
        "total_qty": total_qty,
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"],
              "projects": len(info["projects"]), "status": dict(info["status"]),
              "sheets": _fmt_sheets(info["sheets"])}
             for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
        "by_project": sorted(
            [{"project": p, "qty": info["qty"], "status": dict(info["status"]),
              "sheets": _fmt_sheets(info["sheets"])}
             for p, info in by_project.items()],
            key=lambda x: -x["qty"])[:15],
        "details": rows[:30],
    }


def eta_check(items, kw):
    kw = (kw or "").strip()
    k = kw.lower()
    if kw:
        rows = [i for i in items if any(
            k in str(i.get(f, "")).lower()
            for f in ["项目", "项目编码", "物料编码", "物料名称", "品牌", "规格说明"]
        )]
        if not rows:
            return {"error": "未找到「%s」相关的欠料，无法判定交期" % kw}
    else:
        rows = items
    if not rows:
        return {"error": "当前无欠料数据"}

    today = datetime.date.today()

    def _verdict(eta, exp):
        pe = _parse_date(eta)
        xe = _parse_date(exp)
        if not pe and not xe:
            return "无交期信息", None, None, None
        if pe and not xe:
            return "缺期望交期", None, datetime.date(*pe), None
        if not pe and xe:
            return "无预计到货时间", None, None, datetime.date(*xe)
        d_pe = datetime.date(*pe)
        d_xe = datetime.date(*xe)
        diff = (d_pe - d_xe).days
        if diff <= 0:
            return "来得及", diff, d_pe, d_xe
        return "来不及", diff, d_pe, d_xe

    results = []
    late = on_time = no_date = 0
    for i in rows:
        verdict, diff, d_pe, d_xe = _verdict(i.get("预计到货时间"), i.get("期望交期"))
        if verdict == "来不及":
            late += 1
        elif verdict == "来得及":
            on_time += 1
        else:
            no_date += 1
        results.append({
            "项目": i.get("项目", ""),
            "物料编码": i.get("物料编码", ""),
            "物料名称": i.get("物料名称", ""),
            "预计": i.get("预计到货时间") or "—",
            "期望": i.get("期望交期") or "—",
            "预计日期": d_pe.isoformat() if d_pe else None,
            "期望日期": d_xe.isoformat() if d_xe else None,
            "预计剩余天": (d_pe - today).days if d_pe else None,
            "期望剩余天": (d_xe - today).days if d_xe else None,
            "相差天": diff,
            "判定": verdict,
        })

    # 按物料编码聚合，方便前端做卡片式交期对比
    by_material = defaultdict(lambda: {"name": "", "entries": [], "late": 0, "on_time": 0, "no_date": 0, "projects": set()})
    for r in results:
        mc = r["物料编码"]
        by_material[mc]["name"] = r["物料名称"] or by_material[mc]["name"]
        by_material[mc]["entries"].append(r)
        by_material[mc]["projects"].add(r["项目"] or "未命名")
        if r["判定"] == "来不及":
            by_material[mc]["late"] += 1
        elif r["判定"] == "来得及":
            by_material[mc]["on_time"] += 1
        else:
            by_material[mc]["no_date"] += 1

    by_material_list = sorted(
        [{"mc": mc, "name": info["name"], "entries": info["entries"],
          "late": info["late"], "on_time": info["on_time"], "no_date": info["no_date"],
          "projects": sorted(info["projects"])}
         for mc, info in by_material.items()],
        key=lambda x: (-x["late"], -len(x["entries"]), x["mc"]))[:30]

    return {
        "keyword": kw,
        "rows": len(rows),
        "late": late,
        "on_time": on_time,
        "no_date": no_date,
        "results": results[:30],
        "by_material": by_material_list,
    }


# ---------------- 钣金欠料（箱体进度统计）----------------
def sheetmetal_is_arrived(item):
    """到货情况含「已到货」视为已到货；未到货 / 空 / 其它为欠料。"""
    a = (item.get("arrival") or "").strip()
    if not a:
        return False
    return "已到货" in a


_TODAY = datetime.date.today


def _parse_eta_days(eta):
    """解析 ETA 文本为距离今天的天数（可负表示逾期）。无法解析返回 None。"""
    today = _TODAY()
    text = (eta or "").strip()
    if not text:
        return None
    # 已到货 / 空值 / 无意义占位
    if "已到货" in text:
        return None
    # 优先匹配 M.D / M/D / M月D日，允许尾部范围如 8.19/20
    m = re.match(r"(\d{1,2})\s*[./月]\s*(\d{1,2})\s*日?(?:\s*[-~/]\s*\d{1,2})?\s*$", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            y = today.year
            d = datetime.date(y, month, day)
            # 若解析出的日期比今天早超过 90 天，视为明年
            if (today - d).days > 90:
                d = datetime.date(y + 1, month, day)
            return (d - today).days
        except ValueError:
            pass
    # 兜底：XX天内 / XX天
    m = re.search(r"(\d+)\s*天", text)
    if m:
        return int(m.group(1))
    return None


def sheetmetal_active(items):
    """钣金欠料：未到货（不含「已到货」）视为欠料。"""
    return [i for i in items if not sheetmetal_is_arrived(i)]


def _sheetmetal_project_stats(proj_groups):
    """项目分布：按项目名聚合，拆分已到货/未到货，并按「预计到货(ETA)」计算剩余/逾期天数。

    剩余天数 = 该项目未到货条目中，最早 ETA 距今天的天数（负值=逾期）。
    全部到货（shortage==0）时不显示剩余时间（返回 None）。
    """
    out = []
    for p, items in proj_groups.items():
        arr = [i for i in items if sheetmetal_is_arrived(i)]
        sh = [i for i in items if not sheetmetal_is_arrived(i)]
        if sh:
            sh_days = [_parse_eta_days(i.get("eta")) for i in sh]
            sh_days = [d for d in sh_days if d is not None]
            remaining_days = min(sh_days) if sh_days else None
        else:
            remaining_days = None
        out.append({
            "project": p,
            "count": len(items),
            "arrived": len(arr),
            "shortage": len(sh),
            "remaining_days": remaining_days,
        })
    return sorted(out, key=lambda x: -x["count"])


def sheetmetal_overview(items):
    """钣金欠料总览：总量 / 已到货 / 欠料 / 项目与维度分布。

    分布口径（按用户 2026-08-19 要求）：
    - 不再按「分表」单独统计；项目维度用 项目名称(project) 区分（巨茂只是其中一个项目）。
    - 供应商分布按整表聚合（跨所有项目）。
    - 批次(batch) 仅巨茂有，取发货批次表头。
    """
    if not items:
        return {"total": 0, "total_qty": 0, "arrived": 0, "shortage": 0,
                "shortage_qty": 0, "by_project": [],
                "by_category": [], "by_supplier": [], "by_batch": []}
    arrived = [i for i in items if sheetmetal_is_arrived(i)]
    shortage = [i for i in items if not sheetmetal_is_arrived(i)]
    proj_groups = defaultdict(list)
    for i in items:
        proj_groups[i.get("project") or "未填项目"].append(i)
    by_cat = Counter(i.get("category") for i in items if i.get("category"))
    by_sup = Counter(i.get("supplier") for i in items if i.get("supplier"))

    # 发货批次分布：按批次聚合，并拆分已到货/未到货 + 剩余需求时间
    # 剩余时间按「批次交期(批次名)」计算；批次名解析不到日期时，
    # 才 fallback 到未到货条目中最近的 ETA。已到货(可提前交货)不计入剩余时间。
    batch_groups = defaultdict(list)
    for i in items:
        b = i.get("batch") or ""
        if b and b != "合计":
            batch_groups[b].append(i)
    by_batch = []
    for b, batch_items in sorted(batch_groups.items(), key=lambda kv: -len(kv[1])):
        arr = [i for i in batch_items if sheetmetal_is_arrived(i)]
        sh = [i for i in batch_items if not sheetmetal_is_arrived(i)]
        if sh:
            bd = _parse_date(b)
            if bd:
                remaining_days = (datetime.date(*bd) - _TODAY()).days
            else:
                sh_days = [_parse_eta_days(i.get("eta")) for i in sh]
                sh_days = [d for d in sh_days if d is not None]
                remaining_days = min(sh_days) if sh_days else None
        else:
            remaining_days = None
        by_batch.append({
            "batch": b,
            "count": len(batch_items),
            "arrived": len(arr),
            "shortage": len(sh),
            "remaining_days": remaining_days,
        })

    return {
        "total": len(items),
        "total_qty": sum(int(i.get("qty") or 0) for i in items),
        "arrived": len(arrived),
        "shortage": len(shortage),
        "shortage_qty": sum(int(i.get("qty") or 0) for i in shortage),
        "by_project": _sheetmetal_project_stats(proj_groups),
        "by_category": [{"category": k, "count": v} for k, v in by_cat.most_common()],
        "by_supplier": [{"supplier": k, "count": v} for k, v in by_sup.most_common()],
        "by_batch": by_batch,
    }


def sheetmetal_search(items, kw):
    """钣金欠料查询：跨全部字段模糊匹配；kw 为空返回全部。附 arrived 标记。"""
    kw = (kw or "").strip().lower()
    if kw:
        fields = ["sheet", "batch", "drawing_batch", "drawing_date", "delivery_date", "project",
                  "category", "supplier", "po_no", "material_code", "name",
                  "spec", "arrival", "eta", "arrival_date", "note"]
        rows = [i for i in items if any(kw in str(i.get(f, "")).lower() for f in fields)]
    else:
        rows = list(items)
    out = []
    for i in rows:
        r = dict(i)
        r["arrived"] = sheetmetal_is_arrived(i)
        out.append(r)
    return {"keyword": kw, "rows": len(out), "items": out}


# ---- 口语尾缀剥离（前端查询框使用）----
TAIL_SUFFIX = r"(?:品牌|材料|物料|型号|系列|规格|配件|零件|项目|公司|厂家)\s*$"
HEAD_PREFIX = (r"(?:请问一下|请问|查一下|查询|查看|看看|看一下|看下|"
               r"展示|列一下|能给我|给我|当前|目前|现在|最新)")


def normalize_keyword(text):
    """把用户口语查询清洗成可搜索关键词：去@、去前后虚词、去填充词、剥离分类尾缀。"""
    t = (text or "").strip()
    t = re.sub(r"^@[^\s]+\s*", "", t)
    t = t.replace("，", ",").replace("。", ".").replace("？", "?").replace("！", "!")
    t = re.sub(r"^" + HEAD_PREFIX + r"\s*", "", t)
    # 去除填充短语（任意位置）：有哪些缺料 / 缺料情况 / 品牌 / 项目 ...
    t = re.sub(r"(?:有哪些缺料|有哪些欠料|欠料有哪些|缺料有哪些|的?缺料|的?欠料|缺货|"
               r"情况|汇总|信息|明细|清单|列表|有哪些)", "", t)
    t = re.sub(r"\s+", " ", t).strip().strip(" ,.?!")
    # 剥离残留的分类尾缀（品牌/材料/物料/项目...）
    t = re.sub(TAIL_SUFFIX, "", t).strip()
    return t


if __name__ == "__main__":
    import db
    items = db.get_all()
    items = filter_active(items)
    print("active:", len(items))
