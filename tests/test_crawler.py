import unittest
from crawler.crawlAndSaver import crawlAndSaver as crawler
import sys
import os
import builtins

class TestCrawler(unittest.TestCase):
    def test_crawler(self):
        # crawlAndSaver を import するために crawler/ をパスに追加
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))
        
        # crawlAndSaver は実行時に input() を呼ぶため、ここで差し替えておく
        _real_input = builtins.input
        builtins.input = lambda *a, **kw: "https://example.com"
        
        # 復元
        builtins.input = _real_input
        
        # ダミーのURLで実行してみる（ネット通信なし）
        try:
            crawler()
            self.assertTrue(True)  # エラーが出なければ成功
        except Exception as e:
            self.fail(f"crawlAndSaver が例外を投げました: {e}")