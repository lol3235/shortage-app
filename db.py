# -*- coding: utf-8 -*-
"""本地数据库层：SQLite 存储欠料条目，重启不丢。

仅用 Python 标准库。所有写操作在事务内提交；同步失败回滚并保留旧数据。
"""
import os
import sqlite3
import json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "shortage.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shortage_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    项目           TEXT,
    项目编码       TEXT,
    物料编码       TEXT,
    规格说明       TEXT,
    审核日期       TEXT,
    物料名称       TEXT,
    品牌           TEXT,
    产地           TEXT,
    欠料数量       INTEGER,
    预计到货时间    TEXT,
    期望交期        TEXT,
    状态           TEXT,
    eta_status    TEXT,
    sheet         TEXT,
    owner         TEXT,
    synced_at     TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

ITEM_FIELDS = [
    "项目", "项目编码", "物料编码", "规格说明", "审核日期", "物料名称",
    "品牌", "产地", "欠料数量", "预计到货时间", "期望交期", "状态",
    "eta_status", "sheet", "owner",
]


def init_db(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _conn(path=DEFAULT_DB):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_items(items, synced_at=None, path=DEFAULT_DB):
    """清空并批量写入（v1 简单可靠：整表替换）。事务提交，失败回滚保留旧数据。"""
    if synced_at is None:
        synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    init_db(path)  # 确保表结构存在（CREATE TABLE IF NOT EXISTS）
    conn = _conn(path)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM shortage_items")
        for it in items:
            row = {f: it.get(f) for f in ITEM_FIELDS}
            row["欠料数量"] = int(it.get("欠料数量") or 0)
            row["synced_at"] = synced_at
            placeholders = ", ".join("?" for _ in ITEM_FIELDS + ["synced_at"])
            cols = ", ".join(ITEM_FIELDS + ["synced_at"])
            conn.execute(
                "INSERT INTO shortage_items (%s) VALUES (%s)" % (cols, placeholders),
                [row[f] for f in ITEM_FIELDS] + [synced_at],
            )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (synced_at,),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('last_count', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(len(items)),),
        )
        conn.commit()
        return len(items)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all(path=DEFAULT_DB):
    conn = _conn(path)
    try:
        rows = conn.execute("SELECT * FROM shortage_items").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_meta(path=DEFAULT_DB):
    conn = _conn(path)
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        meta = {r["key"]: r["value"] for r in rows}
        # 各分表条数
        sheets = conn.execute(
            "SELECT sheet, COUNT(*) AS c FROM shortage_items GROUP BY sheet ORDER BY c DESC"
        ).fetchall()
        meta["sheets"] = {r["sheet"]: r["c"] for r in sheets}
        return meta
    finally:
        conn.close()


def row_to_item(r):
    return dict(r)


def export_seed_sql(db_path=DEFAULT_DB, seed_path=None):
    """把 shortage_items 与 meta 关键键导出为可重复执行的 INSERT SQL，供 GitHub/Render 初始化。

    按 id 排序，显式列名，一行一条，便于 diff 和版本控制。
    同时携带 meta.last_sync / last_count，让云端部署后能正确显示同步时间。
    """
    if seed_path is None:
        seed_path = os.path.join(HERE, "data", "seed.sql")
    cols = ITEM_FIELDS + ["synced_at"]
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT %s FROM shortage_items ORDER BY id" % ", ".join(cols)
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('last_sync', 'last_count')"
        ).fetchall()
        meta = {r["key"]: r["value"] for r in meta_rows}
        last_sync = meta.get("last_sync", "")
        lines = [
            "-- shortage-app seed.sql",
            "-- last_sync: %s" % last_sync,
            "-- rows: %d" % len(rows),
            "DELETE FROM shortage_items;",
        ]
        for r in rows:
            vals = []
            for c in cols:
                v = r[c]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    vals.append("'%s'" % str(v).replace("'", "''"))
            lines.append(
                "INSERT INTO shortage_items (%s) VALUES (%s);"
                % (", ".join(cols), ", ".join(vals))
            )
        # 同步 meta 关键键，确保云端从 seed.sql 初始化后也有 last_sync / last_count
        lines.append("DELETE FROM meta WHERE key IN ('last_sync', 'last_count');")
        if last_sync:
            lines.append(
                "INSERT INTO meta (key, value) VALUES ('last_sync', '%s');"
                % last_sync.replace("'", "''")
            )
        if meta.get("last_count"):
            lines.append(
                "INSERT INTO meta (key, value) VALUES ('last_count', '%s');"
                % meta["last_count"].replace("'", "''")
            )
        with open(seed_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
            f.write("\n")
        return len(rows)
    finally:
        conn.close()


# ---------------- 钣金欠料（箱体进度统计）独立库 ----------------
SHEETMETAL_DB = os.path.join(HERE, "data", "sheetmetal.db")
SHEETMETAL_SEED = os.path.join(HERE, "data", "seed_sheetmetal.sql")

SHEETMETAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sheetmetal_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet         TEXT,
    batch         TEXT,
    drawing_date  TEXT,
    delivery_date TEXT,
    project       TEXT,
    category      TEXT,
    supplier      TEXT,
    po_no         TEXT,
    material_code TEXT,
    name          TEXT,
    spec          TEXT,
    qty           INTEGER,
    arrival       TEXT,
    eta           TEXT,
    arrival_date  TEXT,
    note          TEXT,
    synced_at     TEXT
);
CREATE TABLE IF NOT EXISTS meta_sheetmetal (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

SHEETMETAL_FIELDS = [
    "sheet", "batch", "drawing_date", "delivery_date", "project", "category",
    "supplier", "po_no", "material_code", "name", "spec", "qty",
    "arrival", "eta", "arrival_date", "note",
]


def init_sheetmetal_db(path=SHEETMETAL_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SHEETMETAL_SCHEMA)
    conn.commit()
    return conn


def upsert_sheetmetal_items(items, synced_at=None, path=SHEETMETAL_DB):
    """清空并批量写入钣金欠料（整表替换）。事务提交，失败回滚。"""
    if synced_at is None:
        synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    init_sheetmetal_db(path)
    conn = _conn(path)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM sheetmetal_items")
        for it in items:
            row = {f: it.get(f) for f in SHEETMETAL_FIELDS}
            try:
                row["qty"] = int(it.get("qty") or 0)
            except (ValueError, TypeError):
                row["qty"] = 0
            row["synced_at"] = synced_at
            cols = ", ".join(SHEETMETAL_FIELDS + ["synced_at"])
            placeholders = ", ".join("?" for _ in SHEETMETAL_FIELDS + ["synced_at"])
            conn.execute(
                "INSERT INTO sheetmetal_items (%s) VALUES (%s)" % (cols, placeholders),
                [row[f] for f in SHEETMETAL_FIELDS] + [synced_at],
            )
        conn.execute(
            "INSERT INTO meta_sheetmetal(key, value) VALUES('last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (synced_at,),
        )
        conn.execute(
            "INSERT INTO meta_sheetmetal(key, value) VALUES('last_count', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(len(items)),),
        )
        conn.commit()
        return len(items)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_sheetmetal(path=SHEETMETAL_DB):
    conn = _conn(path)
    try:
        rows = conn.execute("SELECT * FROM sheetmetal_items").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sheetmetal_meta(path=SHEETMETAL_DB):
    conn = _conn(path)
    try:
        rows = conn.execute("SELECT key, value FROM meta_sheetmetal").fetchall()
        meta = {r["key"]: r["value"] for r in rows}
        sheets = conn.execute(
            "SELECT sheet, COUNT(*) AS c FROM sheetmetal_items GROUP BY sheet ORDER BY c DESC"
        ).fetchall()
        meta["sheets"] = {r["sheet"]: r["c"] for r in sheets}
        return meta
    finally:
        conn.close()


def export_sheetmetal_seed_sql(db_path=SHEETMETAL_DB, seed_path=None):
    """把 sheetmetal_items 与 meta_sheetmetal 导出为可重复执行的 INSERT SQL（供 Render 初始化）。"""
    if seed_path is None:
        seed_path = SHEETMETAL_SEED
    cols = SHEETMETAL_FIELDS + ["synced_at"]
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT %s FROM sheetmetal_items ORDER BY id" % ", ".join(cols)
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT key, value FROM meta_sheetmetal WHERE key IN ('last_sync', 'last_count')"
        ).fetchall()
        meta = {r["key"]: r["value"] for r in meta_rows}
        last_sync = meta.get("last_sync", "")
        lines = [
            "-- shortage-app sheetmetal seed.sql",
            "-- last_sync: %s" % last_sync,
            "-- rows: %d" % len(rows),
            "DELETE FROM sheetmetal_items;",
        ]
        for r in rows:
            vals = []
            for c in cols:
                v = r[c]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    vals.append("'%s'" % str(v).replace("'", "''"))
            lines.append(
                "INSERT INTO sheetmetal_items (%s) VALUES (%s);"
                % (", ".join(cols), ", ".join(vals))
            )
        lines.append("DELETE FROM meta_sheetmetal WHERE key IN ('last_sync', 'last_count');")
        if last_sync:
            lines.append(
                "INSERT INTO meta_sheetmetal (key, value) VALUES ('last_sync', '%s');"
                % last_sync.replace("'", "''")
            )
        if meta.get("last_count"):
            lines.append(
                "INSERT INTO meta_sheetmetal (key, value) VALUES ('last_count', '%s');"
                % meta["last_count"].replace("'", "''")
            )
        with open(seed_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
            f.write("\n")
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    c = init_db()
    c.close()
    print("db ok:", DEFAULT_DB)
