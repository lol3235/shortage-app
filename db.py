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
    """把 shortage_items 全表导出为可重复执行的 INSERT SQL，供 GitHub/Render 初始化。

    按 id 排序，显式列名，一行一条，便于 diff 和版本控制。
    """
    if seed_path is None:
        seed_path = os.path.join(HERE, "data", "seed.sql")
    cols = ITEM_FIELDS + ["synced_at"]
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT %s FROM shortage_items ORDER BY id" % ", ".join(cols)
        ).fetchall()
        lines = [
            "-- shortage-app seed.sql",
            "-- generated: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
