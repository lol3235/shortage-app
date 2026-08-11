# -*- coding: utf-8 -*-
import os
import sys
import time
import unittest
import threading
import json
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import app as app_mod
import db
import sync

FIXTURE = os.path.join(HERE, "fixtures", "sample.md")
TMP_DB = os.path.join(HERE, "..", "data", "api_test.db")
TEST_PORT = 8799


def _safe_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _safe_remove(TMP_DB)
        db.init_db(TMP_DB)
        sync.sync_to_db(offline_md=FIXTURE, db_path=TMP_DB)
        # 让 app 使用测试库
        app_mod.DB_PATH = TMP_DB
        cls.server = app_mod.ThreadingHTTPServer(("127.0.0.1", TEST_PORT), app_mod.Handler)
        t = threading.Thread(target=cls.server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        _safe_remove(TMP_DB)

    def _get(self, path, params=None):
        url = "http://127.0.0.1:%d%s" % (TEST_PORT, path)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_overview(self):
        d = self._get("/api/overview")
        self.assertEqual(d["total"], 4)  # 5 条中 1 条已解决被过滤
        self.assertIn("by_status", d)
        self.assertIn("by_project", d)

    def test_search_brand(self):
        d = self._get("/api/search", {"kw": "富士金品牌有哪些欠料"})
        self.assertEqual(len(d["rows"]), 1)  # A01 已解决被过滤，仅 B07

    def test_project(self):
        d = self._get("/api/project", {"kw": "巨茂"})
        self.assertNotIn("error", d)
        self.assertEqual(d["total_qty"], 5)  # 仅 B07（A01 已解决）

    def test_material_cross(self):
        d = self._get("/api/material", {"kw": "SIE-12345-AB"})
        self.assertEqual(d["total_qty"], 12)
        self.assertEqual(d["by_material"][0]["projects"], 2)

    def test_brand(self):
        d = self._get("/api/brand", {"kw": "富士金"})
        self.assertEqual(d["total_qty"], 5)  # 仅 B07（A01 已解决）

    def test_eta(self):
        d = self._get("/api/eta", {"kw": "B07-05-00-03-10"})
        self.assertEqual(d["results"][0]["判定"], "来不及")

    def test_sync_status(self):
        d = self._get("/api/sync_status")
        self.assertIn("last_sync", d)

    def test_settings(self):
        d = self._get("/api/settings")
        self.assertIn("resolved_keywords", d)
        self.assertIn("sheets", d)

    def test_index_html(self):
        with urllib.request.urlopen("http://127.0.0.1:%d/" % TEST_PORT, timeout=5) as r:
            body = r.read().decode("utf-8")
        self.assertIn("<title>欠料看板</title>", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
