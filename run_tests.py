# -*- coding: utf-8 -*-
"""运行全部测试。用法：python run_tests.py
也可指定模块：python run_tests.py tests.test_core
"""
import sys
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = ["tests.test_core", "tests.test_api", "tests.test_archive"]
    suite = unittest.TestLoader()
    all_suites = []
    for n in names:
        try:
            all_suites.append(suite.loadTestsFromName(n))
        except Exception as e:
            print("加载测试失败 %s: %s" % (n, e))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestSuite(all_suites))
    sys.exit(0 if result.wasSuccessful() else 1)
