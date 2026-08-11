# -*- coding: utf-8 -*-
import os
import unittest

import sync
import db
import logic

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.md")
TMP_DB = os.path.join(os.path.dirname(__file__), "..", "data", "test_tmp.db")


class TestParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = sync.parse_markdown(open(FIXTURE, encoding="utf-8").read())

    def test_count(self):
        # 巨茂报告3行 + 0810子表2行 = 5 数据行（表头行不计）
        self.assertEqual(len(self.items), 5)

    def test_column_aliases(self):
        # 子表2 用 待领数量 / 材料预计到货时间 / 期望交期 / 处理状态
        tk = [i for i in self.items if i["物料编码"] == "TK-99-88-77"][0]
        self.assertEqual(int(tk["欠料数量"]), 2)
        self.assertEqual(tk["预计到货时间"], "待定")
        self.assertEqual(tk["期望交期"], "2026-08-10")
        self.assertEqual(tk["状态"], "未解决")

    def test_expected_eta_separate(self):
        b = [i for i in self.items if i["物料编码"] == "B07-05-00-03-10"][0]
        self.assertEqual(b["预计到货时间"], "2026-08-10")   # 供方承诺
        self.assertEqual(b["期望交期"], "2026-08-03")        # 需求方，单独存
        self.assertEqual(b["eta_status"], "有交期")

    def test_spot_qty_classified(self):
        a = [i for i in self.items if i["物料编码"] == "A01-02-03-04-05"][0]
        self.assertEqual(a["eta_status"], "有交期")  # 现货 -> 今天 -> 有交期


class TestDb(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TMP_DB):
            try:
                os.remove(TMP_DB)
            except OSError:
                pass
        db.init_db(TMP_DB)

    def tearDown(self):
        if os.path.exists(TMP_DB):
            try:
                os.remove(TMP_DB)
            except OSError:
                pass

    def test_upsert_and_read(self):
        items = sync.parse_markdown(open(FIXTURE, encoding="utf-8").read())
        n, t = sync.sync_to_db(offline_md=FIXTURE, db_path=TMP_DB)
        self.assertEqual(n, 5)
        all_items = db.get_all(TMP_DB)
        self.assertEqual(len(all_items), 5)
        meta = db.get_meta(TMP_DB)
        self.assertEqual(meta.get("last_count"), "5")
        self.assertIn("巨茂报告", meta["sheets"])


class TestLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = sync.parse_markdown(open(FIXTURE, encoding="utf-8").read())

    def test_filter_active_excludes_resolved(self):
        active = logic.filter_active(self.items)
        # 仅 A01-02-03-04-05 状态=已解决 被排除；「未解决」(TK) 不应被误过滤
        self.assertEqual(len(active), 4)
        mc = [i["物料编码"] for i in active]
        self.assertNotIn("A01-02-03-04-05", mc)
        self.assertIn("TK-99-88-77", mc)  # 状态=未解决，应保留

    def test_search_tail_suffix(self):
        # 富士金品牌 -> 搜 富士金
        rows = logic.search(self.items, logic.normalize_keyword("富士金品牌有哪些欠料"))
        self.assertEqual(len(rows), 2)
        # 巨茂项目 -> 模糊匹配 合肥巨茂材料科技有限公司
        rows2 = logic.search(self.items, logic.normalize_keyword("巨茂项目有哪些欠料"))
        self.assertTrue(any("巨茂" in (i["项目"] or "") for i in rows2))

    def test_project_summary(self):
        r = logic.project_summary(self.items, "巨茂")
        self.assertNotIn("error", r)
        self.assertEqual(r["total_qty"], 8)  # 5 + 3
        self.assertEqual(r["rows"], 2)

    def test_material_summary_cross_project(self):
        r = logic.material_summary(self.items, "SIE-12345-AB")
        self.assertNotIn("error", r)
        # 跨两个子表：8 + 4 = 12
        self.assertEqual(r["total_qty"], 12)
        self.assertEqual(r["by_material"][0]["projects"], 2)

    def test_brand_summary(self):
        r = logic.brand_summary(self.items, "富士金")
        self.assertNotIn("error", r)
        self.assertEqual(r["total_qty"], 8)  # 5 + 3
        self.assertEqual(r["rows"], 2)

    def test_eta_check_late(self):
        r = logic.eta_check(self.items, "B07-05-00-03-10")
        self.assertNotIn("error", r)
        # 预计 8.10 晚于 期望 8.3 -> 来不及
        self.assertEqual(r["results"][0]["判定"], "来不及")
        self.assertEqual(r["results"][0]["相差天"], 7)

    def test_eta_not_read_expected_as_actual(self):
        # 预计到货时间 必须是供方列，不能是期望交期列
        b = [i for i in self.items if i["物料编码"] == "B07-05-00-03-10"][0]
        self.assertEqual(b["预计到货时间"], "2026-08-10")
        self.assertNotEqual(b["预计到货时间"], b["期望交期"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
