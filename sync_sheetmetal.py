# -*- coding: utf-8 -*-
"""钣金欠料（箱体进度统计）同步模块。

数据来源：金山文档「箱体进度统计.xls」（kdocs file_id=HeqbtFcx3rMqYYFRpA9n1xZrPzbTeaL4X）。
两个明细分表：
  - 5A-巨茂箱体进度8.17 (worksheet_id=8)  —— 11 列
  - 箱体进度统计（非巨茂）(worksheet_id=10) —— 12 列
统一映射到 db.SHEETMETAL_FIELDS。

自动同步：通过本地 kdocs-cli 拉取（需先执行 `kdocs-cli auth login`）。
一键初始化：用连接器已拉取的数据跑 tools/bootstrap_sheetmetal.py（见仓库说明）。
"""
import os
import sys
import json
import subprocess
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db  # noqa: E402

KDOCS_FILE_ID = "HeqbtFcx3rMqYYFRpA9n1xZrPzbTeaL4X"
KDOCS_URL = "https://www.kdocs.cn/l/csUkRQG8wIXk"
KDOCS_CLI = os.environ.get("KDOCS_CLI", r"C:/Users/Apua/.local/bin/kdocs-cli.exe")

# 两个明细分表配置（仅这两个分表是「条目级」明细，计入欠料；其余为汇总表，不计入）
DETAIL_SHEETS = [
    {"name": "5A-巨茂箱体进度8.17", "worksheet_id": 8, "kind": "jumao"},
    {"name": "箱体进度统计（非巨茂）", "worksheet_id": 10, "kind": "feijuma"},
]

# 列布局（0-based 索引）
# 巨茂：图纸批次/图纸时间/交货时间/設備類別/品名规格/图纸编号/数量/到货情况/预计到货时间/实际到货时间/壹月发货批次
JUMAO_COLS = {
    "batch": 0, "drawing_date": 1, "delivery_date": 2, "category": 3,
    "name": 4, "material_code": 5, "qty": 6, "arrival": 7,
    "eta": 8, "arrival_date": 9, "note": 10,
}
# 非巨茂：序号/图纸时间/项目名称/供应商/采购订单号/物料编码/品名/规格型号/数量/到货情况/预计到货时间/实际到货时间
FEIJUMA_COLS = {
    "drawing_date": 1, "project": 2, "supplier": 3, "po_no": 4,
    "material_code": 5, "name": 6, "spec": 7, "qty": 8,
    "arrival": 9, "eta": 10, "arrival_date": 11,
}


def is_arrived(arrival):
    """到货情况含「已到货」视为已到货；未到货 / 空 / 其它为欠料。"""
    a = (arrival or "").strip()
    if not a:
        return False
    return "已到货" in a


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v).strip()


def _safe_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def normalize_jumao(rows):
    """rows: 含表头的 2D 网格（list of list）。返回统一字段记录列表。"""
    recs = []
    for r in rows[1:]:
        batch = _cell(r, JUMAO_COLS["batch"])
        if batch == "合计":
            continue  # 跳过合计/汇总脚注行
        name = _cell(r, JUMAO_COLS["name"])
        material = _cell(r, JUMAO_COLS["material_code"])
        qty = _cell(r, JUMAO_COLS["qty"])
        if _safe_int(qty) is None:
            continue  # 数量非数字（合计/标签行）跳过
        if not name and not material:
            continue
        recs.append({
            "sheet": "5A-巨茂箱体进度8.17",
            "batch": batch,
            "drawing_date": _cell(r, JUMAO_COLS["drawing_date"]),
            "delivery_date": _cell(r, JUMAO_COLS["delivery_date"]),
            "project": "",
            "category": _cell(r, JUMAO_COLS["category"]),
            "supplier": "",
            "po_no": "",
            "material_code": material,
            "name": name,
            "spec": "",
            "qty": qty,
            "arrival": _cell(r, JUMAO_COLS["arrival"]),
            "eta": _cell(r, JUMAO_COLS["eta"]),
            "arrival_date": _cell(r, JUMAO_COLS["arrival_date"]),
            "note": _cell(r, JUMAO_COLS["note"]),
        })
    return recs


def normalize_feijuma(rows):
    """rows: 含表头的 2D 网格。返回统一字段记录列表。"""
    recs = []
    for r in rows[1:]:
        name = _cell(r, FEIJUMA_COLS["name"])
        material = _cell(r, FEIJUMA_COLS["material_code"])
        if not name and not material:
            continue
        recs.append({
            "sheet": "箱体进度统计（非巨茂）",
            "batch": "",
            "drawing_date": _cell(r, FEIJUMA_COLS["drawing_date"]),
            "delivery_date": "",
            "project": _cell(r, FEIJUMA_COLS["project"]),
            "category": "",
            "supplier": _cell(r, FEIJUMA_COLS["supplier"]),
            "po_no": _cell(r, FEIJUMA_COLS["po_no"]),
            "material_code": material,
            "name": name,
            "spec": _cell(r, FEIJUMA_COLS["spec"]),
            "qty": _cell(r, FEIJUMA_COLS["qty"]),
            "arrival": _cell(r, FEIJUMA_COLS["arrival"]),
            "eta": _cell(r, FEIJUMA_COLS["eta"]),
            "arrival_date": _cell(r, FEIJUMA_COLS["arrival_date"]),
            "note": "",
        })
    return recs


def _find_range_data(o):
    """在 kdocs 返回的任意嵌套 JSON 中定位 rangeData 单元格列表。"""
    if isinstance(o, list):
        if o and isinstance(o[0], dict) and "originRow" in o[0]:
            return o
        for v in o:
            r = _find_range_data(v)
            if r:
                return r
    elif isinstance(o, dict):
        for v in o.values():
            r = _find_range_data(v)
            if r:
                return r
    return None


def parse_range_json(obj):
    """把 kdocs read_file / get_range_data 返回的 JSON 解析成 2D 网格（含表头）。"""
    rd = _find_range_data(obj)
    if not rd:
        raise ValueError("未在返回结果中找到 rangeData 单元格数据")
    grid = {}
    for c in rd:
        grid[(c.get("originRow"), c.get("originCol"))] = c.get("originalCellValue")
    if not grid:
        return []
    maxr = max(k[0] for k in grid)
    maxc = max(k[1] for k in grid)
    rows = []
    for rr in range(maxr + 1):
        rows.append([grid.get((rr, cc), "") for cc in range(maxc + 1)])
    return rows


def _cli_to_rows(stdout):
    return parse_range_json(json.loads(stdout))


def fetch_via_kdocs_cli():
    """通过本地 kdocs-cli 拉取两个明细分表，返回 [(sheet_name, rows), ...]。

    需要已 `kdocs-cli auth login`。失败时抛异常（由 sync_to_db 捕获，保留旧数据）。
    """
    out = []
    for s in DETAIL_SHEETS:
        params = {
            "file_id": KDOCS_FILE_ID,
            "sheetId": s["worksheet_id"],
            "range": {"rowFrom": 0, "rowTo": 200, "colFrom": 0, "colTo": 13},
        }
        cmd = [KDOCS_CLI, "sheet", "get-range-data", "--output", "json",
               "--args", json.dumps(params, ensure_ascii=False)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise RuntimeError("未找到 kdocs-cli（%s），请先安装并 `kdocs-cli auth login`" % KDOCS_CLI)
        if p.returncode != 0:
            raise RuntimeError("kdocs-cli 拉取 %s 失败: %s" % (
                s["name"], (p.stderr or p.stdout or "")[:400]))
        out.append((s["name"], _cli_to_rows(p.stdout)))
    return out


def sync_to_db():
    """生产自动同步入口：拉取 -> 归一化 -> 写入 -> 导出 seed。返回 (写入条数, 同步时间)。"""
    pairs = fetch_via_kdocs_cli()
    items = []
    for name, rows in pairs:
        kind = next((s["kind"] for s in DETAIL_SHEETS if s["name"] == name), None)
        if kind == "jumao":
            items += normalize_jumao(rows)
        else:
            items += normalize_feijuma(rows)
    n = db.upsert_sheetmetal_items(items)
    db.export_sheetmetal_seed_sql()
    meta = db.get_sheetmetal_meta()
    t = meta.get("last_sync") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return n, t


if __name__ == "__main__":
    n, t = sync_to_db()
    print("钣金欠料同步完成：%d 条，时间 %s" % (n, t))
