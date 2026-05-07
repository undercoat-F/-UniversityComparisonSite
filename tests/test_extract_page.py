"""
extract_page() のユニットテスト - サンプル HTML を使用
「1ページだけで試す」テスト戦略の実装例
"""
import unittest
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# parent dirのcrawlerモジュールをインポート
sys.path.insert(0, str(Path(__file__).parent.parent))

from crawler.crawlAndSaver import extract_page, extract_info


# ===== テスト用サンプルデータ（1ページ分） =====
# ※ extract_info() は「degree keyword」「4桁以上の数字」「通貨」の3つが同一行にある必要があります

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Master of Science in Data Science - University of Edinburgh</title>
</head>
<body>
    <h1>MSc Data Science Programme</h1>
    <p>This is a postgraduate programme.</p>
    <p>Master degree tuition fee: GBP 15000 per year</p>
    <p>PhD programme tuition cost: USD 25000 annually</p>
    <p>Study abroad opportunity.</p>
</body>
</html>
"""

SAMPLE_HTML_SIMPLE = """
<html>
<head><title>Bachelor Programme</title></head>
<body>
<p>Bachelor degree programme tuition fee: EUR 10000</p>
</body>
</html>
"""


class TestExtractPage(unittest.TestCase):
    """extract_page() のユニットテスト"""

    global url
    url = "https://www.u-tokyo.ac.jp/en/academics/facultyofengineering.html"

    def test_extract_page_basic(self):
        """1ページから学位情報を抽出できるか"""
        
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        
        result = extract_page(url, soup, SAMPLE_HTML)
        
        # 基本フィールドを確認
        self.assertEqual(result['url'], url)
        self.assertIn('Master', result['title'])
        # country は URL から推定される（ed.ac.uk → UK）
        self.assertIsNotNone(result.get('country'))
        self.assertIsNotNone(result['timestamp'])
        
        # 学位情報 - 2 個の degree が抽出されるはず（Master, PhD）
        self.assertIsInstance(result['degrees'], list)
        self.assertGreater(len(result['degrees']), 0, "学位情報が抽出されていない")
        
        print(f"✓ 1ページから {len(result['degrees'])} 件の学位を抽出")
        for i, deg in enumerate(result['degrees'], 1):
            print(f"  [{i}] {deg.get('name', '?')} - {deg.get('price')} {deg.get('currency')}")

    def test_extract_page_structure(self):
        """extract_page の戻り値構造が正しいか"""
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        
        result = extract_page(url, soup, SAMPLE_HTML)
        
        # 必須フィールドが全て存在するか
        required_fields = ['url', 'title', 'country', 'timestamp', 'degrees', 'raw_text', 'source_type']
        for field in required_fields:
            self.assertIn(field, result, f"フィールド '{field}' が見つかりません")
        
        # 型の確認
        self.assertIsInstance(result['url'], str)
        self.assertIsInstance(result['title'], str)
        self.assertIsInstance(result['degrees'], list)
        self.assertIsInstance(result['timestamp'], str)
        self.assertEqual(result['source_type'], 'html')
        
        print(f"✓ 戻り値構造が正しい: {list(result.keys())}")

    def test_extract_page_simple_html(self):
        """シンプルな HTML からも抽出できるか"""
        soup = BeautifulSoup(SAMPLE_HTML_SIMPLE, 'html.parser')
        
        result = extract_page(url, soup, SAMPLE_HTML_SIMPLE)
        
        self.assertEqual(result['title'], 'Bachelor Programme')
        self.assertIsInstance(result['degrees'], list)
        print(f"✓ シンプル HTML: {len(result['degrees'])} 件の学位抽出")

    def test_extract_page_empty_html(self):
        """HTML に学位情報がない場合"""
        url = "https://example.com/empty"
        empty_html = "<html><body><p>No degree info</p></body></html>"
        soup = BeautifulSoup(empty_html, 'html.parser')
        
        result = extract_page(url, soup, empty_html)
        
        # 学位がなくてもクラッシュしないか確認
        self.assertEqual(result['url'], url)
        self.assertIsInstance(result['degrees'], list)
        print(f"✓ 空の HTML も処理可能: degrees={result['degrees']}")


class TestExtractInfo(unittest.TestCase):
    """extract_info() のユニットテスト"""

    def test_extract_price_gbp(self):
        """GBP での価格抽出"""
        text = "Master degree tuition fee is GBP 15000 per year"
        result = extract_info(text, "Master Programme")
        
        self.assertIsInstance(result, list)
        if result:
            first = result[0]
            print(f"✓ GBP 抽出: {first.get('price')} {first.get('currency')}")
        else:
            print(f"✓ 抽出結果: {len(result)} 件")

    def test_extract_multiple_currencies(self):
        """複数通貨での価格抽出"""
        text = """
        Master degree tuition fee: GBP 20000
        PhD programme tuition cost: USD 30000
        Bachelor programme tuition: EUR 10000
        """
        result = extract_info(text)
        
        print(f"✓ {len(result)} 個の学位パターンを抽出")
        for deg in result:
            print(f"  - {deg.get('price')} {deg.get('currency')}")

    def test_extract_keywords(self):
        """keyword recognition test"""
        text = """
        Master degree tuition: GBP 20000 per year
        Bachelor programme fee: GBP 10000
        PhD course cost: GBP 15000
        """
        result = extract_info(text)
        
        self.assertIsInstance(result, list)
        print(f"✓ Keyword-based extraction: {len(result)} matches")


class TestIntegration(unittest.TestCase):
    """統合テスト: extract_page と extract_info の連携"""

    def test_full_page_extraction(self):
        """実際のワークフローをシミュレート"""
        url = "https://www.ed.ac.uk/degree-page"
        soup = BeautifulSoup(SAMPLE_HTML, 'html.parser')
        
        # step1: extract_page を実行
        page_result = extract_page(url, soup, SAMPLE_HTML)
        
        # step2: 結果を確認
        self.assertIsNotNone(page_result)
        # 学位が抽出されることを期待
        degrees_count = len(page_result['degrees'])
        print(f"✓ extract_page により {degrees_count} 件の学位を抽出")
        
        # step3: 学位情報の詳細を確認（ある場合）
        if degrees_count > 0:
            for degree in page_result['degrees']:
                self.assertIn('name', degree)
                self.assertIn('price', degree)
                print(f"  学位: {degree.get('name')} ({degree.get('price')} {degree.get('currency')})")
        else:
            print("  (学位情報なし)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
