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
    manual_status TEXT,
    eta_status    TEXT,
    sheet         TEXT,
    owner         TEXT,
    synced_at     TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS manual_overrides (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project       TEXT NOT NULL,
    material_code TEXT NOT NULL,
    brand         TEXT,
    action        TEXT DEFAULT 'resolved',
    note          TEXT,
    created_at    TEXT,
    UNIQUE(project, material_code)
);
"""

ITEM_FIELDS = [
    "项目", "项目编码", "物料编码", "规格说明", "审核日期", "物料名称",
    "品牌", "产地", "欠料数量", "预计到货时间", "期望交期", "状态",
    "manual_status", "eta_status", "sheet", "owner",
]


def init_db(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # 兼容旧库：若表已存在但缺少新列/新表，则追加
    try:
        conn.execute("ALTER TABLE shortage_items ADD COLUMN manual_status TEXT")
    except Exception:
        pass
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS manual_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                material_code TEXT NOT NULL,
                brand TEXT,
                action TEXT DEFAULT 'resolved',
                note TEXT,
                created_at TEXT,
                UNIQUE(project, material_code)
            )
        """)
    except Exception:
        pass
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


def apply_manual_overrides(path=DEFAULT_DB):
    """同步后调用：把 manual_overrides 里记录的行标记为 manual_status，使其在看板中被过滤。"""
    conn = _conn(path)
    try:
        cur = conn.execute(
            "UPDATE shortage_items SET manual_status = '已到货（人工）' "
            "WHERE manual_status IS NULL AND (项目, 物料编码) IN "
            "(SELECT project, material_code FROM manual_overrides WHERE action = 'resolved')"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def add_manual_override(project, material_code, brand="", note="", action="resolved", path=DEFAULT_DB):
    """新增一条人工到货/解决记录，并立即应用到现有数据。"""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn(path)
    try:
        conn.execute(
            "INSERT INTO manual_overrides(project, material_code, brand, action, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(project, material_code) DO UPDATE SET "
            "brand=excluded.brand, action=excluded.action, note=excluded.note, created_at=excluded.created_at",
            (project or "", material_code or "", brand or "", action, note or "", created_at),
        )
        conn.commit()
    finally:
        conn.close()
    return apply_manual_overrides(path)


def add_manual_overrides_batch(overrides, path=DEFAULT_DB):
    """批量插入人工覆盖记录，并统一应用一次。"""
    if not overrides:
        return 0
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn(path)
    try:
        for ov in overrides:
            conn.execute(
                "INSERT INTO manual_overrides(project, material_code, brand, action, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project, material_code) DO UPDATE SET "
                "brand=excluded.brand, action=excluded.action, note=excluded.note, created_at=excluded.created_at",
                (ov.get("project") or "", ov.get("material_code") or "", ov.get("brand") or "",
                 ov.get("action", "resolved"), ov.get("note") or "", created_at),
            )
        conn.commit()
    finally:
        conn.close()
    return apply_manual_overrides(path)


def list_manual_overrides(path=DEFAULT_DB):
    conn = _conn(path)
    try:
        rows = conn.execute(
            "SELECT id, project, material_code, brand, action, note, created_at "
            "FROM manual_overrides ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_manual_override(oid, path=DEFAULT_DB):
    """删除人工覆盖；删除后把 shortage_items 里对应 manual_status 清空，再重新应用其余覆盖。"""
    conn = _conn(path)
    try:
        conn.execute("DELETE FROM manual_overrides WHERE id = ?", (oid,))
        conn.execute(
            "UPDATE shortage_items SET manual_status = NULL "
            "WHERE (项目, 物料编码) NOT IN "
            "(SELECT project, material_code FROM manual_overrides WHERE action = 'resolved')"
        )
        conn.commit()
    finally:
        conn.close()
    return apply_manual_overrides(path)


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
        # 同步人工覆盖记录，确保云端/新实例也能继承本地确认结果
        override_rows = conn.execute(
            "SELECT project, material_code, brand, action, note, created_at FROM manual_overrides ORDER BY id"
        ).fetchall()
        lines.append("DELETE FROM manual_overrides;")
        for r in override_rows:
            vals = []
            for c in ["project", "material_code", "brand", "action", "note", "created_at"]:
                v = r[c]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    vals.append("'%s'" % str(v).replace("'", "''"))
            lines.append(
                "INSERT INTO manual_overrides (project, material_code, brand, action, note, created_at) VALUES (%s);"
                % ", ".join(vals)
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
