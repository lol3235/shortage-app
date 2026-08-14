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


def _parse_date(s):
    """尽力把交期文本解析成 (年,月,日)；无法识别返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if re.search(r"现货|已发|今天|已到|马上|即时", s):
        return datetime.date.today().timetuple()[:3]
    # 优先：YYYY-MM-DD / YYYY/M/D
    m = re.search(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 中文：X月X日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", s)
    if m:
        return (2026, int(m.group(1)), int(m.group(2)))
    # 其余：M/D 或 M-D（按当年）
    m = re.search(r"(\d{1,2})\s*[./-]\s*(\d{1,2})", s)
    if m:
        return (2026, int(m.group(1)), int(m.group(2)))
    return None


def overview(items):
    """总览聚合：指标 + 紧急度分布 + 项目 TOP。"""
    if not items:
        return {"total": 0, "total_qty": 0, "urgent": 0, "sheets": 0,
                "by_status": {}, "by_project": []}
    by_status = Counter(i.get("eta_status", "其他") for i in items)
    by_project = defaultdict(int)
    for i in items:
        by_project[i.get("项目") or i.get("项目编码") or "未命名"] += 1
    urgent = sum(by_status.get(s, 0) for s in ("空白", "无交期", "付款瓶颈"))
    sheets = len(set(i.get("sheet") for i in items if i.get("sheet")))
    return {
        "total": len(items),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in items),
        "urgent": urgent,
        "sheets": sheets,
        "by_status": dict(by_status),
        "by_project": sorted(
            [{"project": p, "count": c} for p, c in by_project.items()],
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
    if not kw:
        return {"error": "请输入项目名称或项目编码"}
    k = kw.lower()
    rows = [i for i in items if k in str(i.get("项目") or i.get("项目编码") or "").lower()]
    if not rows:
        return {"error": "未找到项目「%s」的欠料" % kw}
    by_material = defaultdict(lambda: {"qty": 0, "name": "", "status": Counter(), "brands": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        b = (i.get("品牌") or "").strip()
        if b:
            by_material[mc]["brands"][b] += 1

    def _pick_brand(counter):
        if not counter:
            return "—"
        # 取数量最多的品牌；若前两名并列，则并列显示
        top = counter.most_common(2)
        if len(top) == 2 and top[0][1] == top[1][1]:
            return "/".join(sorted([top[0][0], top[1][0]]))
        return top[0][0]

    return {
        "keyword": kw,
        "rows": len(rows),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
        "by_status": dict(Counter(i.get("eta_status", "其他") for i in rows)),
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"], "brand": _pick_brand(info["brands"]),
              "status": dict(info["status"])} for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
    }


def material_summary(items, kw):
    kw = (kw or "").strip()
    if not kw:
        return {"error": "请输入物料名称或物料编码"}
    k = kw.lower()
    rows = [i for i in items if any(
        k in str(i.get(f, "")).lower()
        for f in ["物料名称", "物料编码", "规格说明", "品牌"]
    )]
    if not rows:
        return {"error": "未找到物料「%s」的缺货记录" % kw}
    by_material = defaultdict(lambda: {"qty": 0, "name": "", "projects": set(), "status": Counter()})
    by_project = defaultdict(lambda: {"qty": 0, "status": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["projects"].add(i.get("项目") or i.get("项目编码") or "未命名")
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        proj = i.get("项目") or i.get("项目编码") or "未命名"
        by_project[proj]["qty"] += int(i.get("欠料数量") or 0)
        by_project[proj]["status"][i.get("eta_status", "其他")] += 1
    return {
        "keyword": kw,
        "rows": len(rows),
        "total_qty": sum(int(i.get("欠料数量") or 0) for i in rows),
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"],
              "projects": len(info["projects"]), "status": dict(info["status"])}
             for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
        "by_project": sorted(
            [{"project": p, "qty": info["qty"], "status": dict(info["status"])}
             for p, info in by_project.items()],
            key=lambda x: -x["qty"])[:15],
        "details": rows[:30],
    }


def brand_summary(items, kw):
    """按品牌汇总欠料（新增）。"""
    kw = (kw or "").strip()
    if not kw:
        return {"error": "请输入品牌名称，如 富士金 / Siemens"}
    k = kw.lower()
    rows = [i for i in items if k in str(i.get("品牌", "")).lower()]
    if not rows:
        return {"error": "未找到品牌「%s」的欠料记录" % kw}
    total_qty = sum(int(i.get("欠料数量") or 0) for i in rows)
    by_material = defaultdict(lambda: {"qty": 0, "name": "", "projects": set(), "status": Counter()})
    by_project = defaultdict(lambda: {"qty": 0, "status": Counter()})
    for i in rows:
        mc = i.get("物料编码") or "未知编码"
        by_material[mc]["qty"] += int(i.get("欠料数量") or 0)
        by_material[mc]["name"] = i.get("物料名称") or ""
        by_material[mc]["projects"].add(i.get("项目") or i.get("项目编码") or "未命名")
        by_material[mc]["status"][i.get("eta_status", "其他")] += 1
        proj = i.get("项目") or i.get("项目编码") or "未命名"
        by_project[proj]["qty"] += int(i.get("欠料数量") or 0)
        by_project[proj]["status"][i.get("eta_status", "其他")] += 1
    return {
        "keyword": kw,
        "rows": len(rows),
        "total_qty": total_qty,
        "by_material": sorted(
            [{"mc": mc, "name": info["name"], "qty": info["qty"],
              "projects": len(info["projects"]), "status": dict(info["status"])}
             for mc, info in by_material.items()],
            key=lambda x: -x["qty"])[:50],
        "by_project": sorted(
            [{"project": p, "qty": info["qty"], "status": dict(info["status"])}
             for p, info in by_project.items()],
            key=lambda x: -x["qty"])[:15],
        "details": rows[:30],
    }


def eta_check(items, kw):
    kw = (kw or "").strip()
    if not kw:
        return {"error": "请问要查谁的到货？例如 西安项目 / B07-05-00-03-10"}
    k = kw.lower()
    rows = [i for i in items if any(
        k in str(i.get(f, "")).lower()
        for f in ["项目", "项目编码", "物料编码", "物料名称", "品牌", "规格说明"]
    )]
    if not rows:
        return {"error": "未找到「%s」相关的欠料，无法判定交期" % kw}

    def _verdict(eta, exp):
        pe = _parse_date(eta)
        xe = _parse_date(exp)
        if not pe and not xe:
            return "无交期信息", None
        if pe and not xe:
            return "缺期望交期", None
        if not pe and xe:
            return "无预计到货时间", None
        d_pe = datetime.date(*pe)
        d_xe = datetime.date(*xe)
        diff = (d_pe - d_xe).days
        if diff <= 0:
            return "来得及", diff
        return "来不及", diff

    results = []
    late = 0
    for i in rows:
        verdict, diff = _verdict(i.get("预计到货时间"), i.get("期望交期"))
        if verdict == "来不及":
            late += 1
        results.append({
            "项目": i.get("项目", ""),
            "物料编码": i.get("物料编码", ""),
            "物料名称": i.get("物料名称", ""),
            "预计": i.get("预计到货时间") or "—",
            "期望": i.get("期望交期") or "—",
            "判定": verdict,
            "相差天": diff,
        })
    return {"keyword": kw, "rows": len(rows), "late": late, "results": results[:30]}


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
