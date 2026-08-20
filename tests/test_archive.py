# -*- coding: utf-8 -*-
"""整表归档规则回归测试：子表末尾标注「已归档」页脚 -> 整表不计入统计。"""
import io
import csv as _csvmod
import unittest

import sync
import logic


def _build_csv(header_cols, data_rows, footer=None):
    """构造 wecom-cli 风格 CSV 文本（RFC4180，与 _csv_to_markdown 输入一致）。"""
    buf = io.StringIO()
    w = _csvmod.writer(buf)
    w.writerow(header_cols)
    for row in data_rows:
        w.writerow(row)
    if footer is not None:
        w.writerow(footer)
    return buf.getvalue()


HEADER = ["项目", "项目编码", "物料编码", "物料名称", "品牌",
          "规格说明", "欠料数量", "预计到货时间", "期望到货时间", "状态"]


def _data_rows():
    return [
        ["测试项目", "P100", "A01-01-01-01-01", "阀门", "富士金", "DN15", "5", "2026-08-20", "2026-08-15", "跟进中"],
        ["测试项目", "P100", "A01-01-01-01-02", "法兰", "富士金", "PN16", "3", "现货", "2026-08-10", "未解决"],
    ]


class TestSheetArchive(unittest.TestCase):

    def test_archived_footer_detected_and_tagged(self):
        """末尾「已归档」页脚 -> 整表标记，filter_active 全排除。"""
        csv = _build_csv(HEADER, _data_rows(), footer=["已归档"])
        md, archived = sync._csv_to_markdown("归档测试", csv)
        self.assertTrue(archived)
        items = sync.parse_markdown(md)
        self.assertEqual(len(items), 2)
        # 整表归档后所有行状态被改写为「已归档」
        self.assertTrue(all(i["状态"] == "已归档" for i in items))
        # filter_active 全部排除
        self.assertEqual(len(logic.filter_active(items)), 0)

    def test_no_footer_not_archived(self):
        """无页脚 -> 不触发整表归档，正常数据保留。"""
        csv = _build_csv(HEADER, _data_rows())
        md, archived = sync._csv_to_markdown("普通测试", csv)
        self.assertFalse(archived)
        items = sync.parse_markdown(md)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(logic.filter_active(items)), 2)

    def test_data_row_with_archived_status_not_whole_sheet(self):
        """逐行标注已归档（物料编码有效）-> 仅该行排除，不触发整表归档。"""
        data = _data_rows()
        data[0][-1] = "已归档"  # 仅第一行逐行归档
        csv = _build_csv(HEADER, data)
        md, archived = sync._csv_to_markdown("逐行归档", csv)
        self.assertFalse(archived)
        items = sync.parse_markdown(md)
        self.assertEqual(len(items), 2)
        # 逐行归档的 1 行被排除，另 1 行保留
        self.assertEqual(len(logic.filter_active(items)), 1)

    def test_footer_with_material_code_not_archived(self):
        """页脚行若含有效物料编码 -> 不误判为整表归档。"""
        csv = _build_csv(HEADER, _data_rows(),
                         footer=["注", "P100", "A01-01-01-01-99", "备注", "x", "y", "1", "z", "z", "已归档"])
        md, archived = sync._csv_to_markdown("误触测试", csv)
        self.assertFalse(archived)


if __name__ == "__main__":
    unittest.main(verbosity=2)
