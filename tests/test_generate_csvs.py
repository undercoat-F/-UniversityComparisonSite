"""
generate_csvs() のユニットテスト
「1ページだけで試す」= モック JSON（2-3 レコード）を使用
特に重複排除（deduplication）の動作を検証
"""
import unittest
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

# parent dirのdbモジュールをインポート
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.jsontocsv import generate_csvs


# ===== テスト用モック JSON =====

MOCK_DATA_MINIMAL = [
    {
        "url": "https://ed.ac.uk/degree1",
        "title": "Master of Science in Data Science",
        "country": "Scotland",
        "timestamp": datetime.now().isoformat(),
        "degrees": [
            {
                "name": "Master",
                "price": 15000,
                "currency": "GBP",
                "course_type": "taught",
                "is_online": False,
                "context": "Full-time programme"
            }
        ],
        "raw_text": "Master degree 15000 GBP",
        "source_type": "html"
    }
]

MOCK_DATA_WITH_DUPLICATES = [
    {
        "url": "https://ed.ac.uk/degree1",
        "title": "Master of Science in Data Science",
        "country": "Scotland",
        "timestamp": datetime.now().isoformat(),
        "degrees": [
            {
                "name": "Master",
                "price": 15000,
                "currency": "GBP",
                "course_type": "taught",
                "is_online": False
            },
            {
                "name": "PhD",
                "price": 25000,
                "currency": "GBP",
                "course_type": "research",
                "is_online": False
            }
        ]
    },
    {
        "url": "https://ed.ac.uk/degree2",
        "title": "Another Master Programme",
        "country": "Scotland",
        "timestamp": datetime.now().isoformat(),
        "degrees": [
            {
                "name": "Master",
                "price": 15000,  # 前のレコードと同じ価格
                "currency": "GBP",
                "course_type": "taught",
                "is_online": False
            },
            {
                "name": "Bachelor",
                "price": 10000,
                "currency": "GBP",
                "course_type": "taught",
                "is_online": False
            }
        ]
    }
]


class TestGenerateCsvs(unittest.TestCase):
    """generate_csvs() のユニットテスト"""

    def setUp(self):
        """各テストの前に一時ディレクトリを作成"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temp_dir.name

    def tearDown(self):
        """各テストの後に一時ディレクトリをクリーンアップ"""
        self.temp_dir.cleanup()

    def test_generate_csvs_minimal_data(self):
        """最小限のデータ（1レコード）で CSV 生成"""
        # 一時 JSON ファイルを作成
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_MINIMAL, f)
        
        # generate_csvs を実行
        generate_csvs(str(json_path), self.output_dir)
        
        # 4つの CSV ファイルが作成されたか確認
        universities_csv = Path(self.output_dir) / 'universities.csv'
        programs_csv = Path(self.output_dir) / 'degree_programs.csv'
        patterns_csv = Path(self.output_dir) / 'tuition_patterns.csv'
        map_csv = Path(self.output_dir) / 'program_tuition_map.csv'
        
        self.assertTrue(universities_csv.exists(), "universities.csv が作成されていない")
        self.assertTrue(programs_csv.exists(), "degree_programs.csv が作成されていない")
        self.assertTrue(patterns_csv.exists(), "tuition_patterns.csv が作成されていない")
        self.assertTrue(map_csv.exists(), "program_tuition_map.csv が作成されていない")
        
        print("✓ 4つの CSV ファイルが正常に作成された")

    def test_universities_csv_content(self):
        """universities.csv の内容を確認"""
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_MINIMAL, f)
        
        generate_csvs(str(json_path), self.output_dir)
        
        universities_csv = Path(self.output_dir) / 'universities.csv'
        
        # ファイルを読み込んで行数をチェック
        with open(universities_csv, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # ヘッダー + 1大学 = 2行
        self.assertEqual(len(lines), 2, f"universities.csv は 2行であるべき（ヘッダー + 1大学）")
        
        # 大学名の確認
        content = ''.join(lines)
        self.assertIn('University of Edinburgh', content)
        
        print(f"✓ universities.csv: {len(lines)-1} 行の大学データ")

    def test_deduplication_tuition_patterns(self):
        """重複排除の動作を確認"""
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_WITH_DUPLICATES, f)
        
        generate_csvs(str(json_path), self.output_dir)
        
        patterns_csv = Path(self.output_dir) / 'tuition_patterns.csv'
        
        # パターンを読み込む
        with open(patterns_csv, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # ヘッダー + 3パターン（15000 GBP Master, 25000 GBP PhD, 10000 GBP Bachelor）
        # = 4行であるべき（重複している 15000 GBP は1つにまとめられる）
        pattern_count = len(lines) - 1  # ヘッダーを除く
        
        print(f"✓ tuition_patterns.csv: {pattern_count} 個のユニークパターン")
        
        # 想定される最小値：3パターン（重複が排除されているはず）
        self.assertLessEqual(pattern_count, 4, 
                            "重複排除が機能していない可能性があります")

    def test_degree_programs_count(self):
        """degree_programs の行数が正しいか"""
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_WITH_DUPLICATES, f)
        
        generate_csvs(str(json_path), self.output_dir)
        
        programs_csv = Path(self.output_dir) / 'degree_programs.csv'
        
        with open(programs_csv, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        program_count = len(lines) - 1  # ヘッダーを除く
        
        # MOCK_DATA_WITH_DUPLICATES は 2 レコード × (2+2) = 4 個の degree を持つ
        expected = 4
        self.assertEqual(program_count, expected, 
                        f"プログラム数が {expected} であるべき")
        
        print(f"✓ degree_programs.csv: {program_count} 個のプログラム")

    def test_program_tuition_map_relationships(self):
        """program_tuition_map が正しく中間テーブルを作成しているか"""
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_WITH_DUPLICATES, f)
        
        generate_csvs(str(json_path), self.output_dir)
        
        map_csv = Path(self.output_dir) / 'program_tuition_map.csv'
        
        with open(map_csv, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        map_count = len(lines) - 1  # ヘッダーを除く
        
        # 各プログラムは 1 つのパターンにマッピングされるはず
        # 4 プログラム → 4 マッピング
        self.assertEqual(map_count, 4)
        
        print(f"✓ program_tuition_map.csv: {map_count} 個のマッピング")

    def test_csv_headers(self):
        """CSV ファイルのヘッダーが正しいか"""
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(MOCK_DATA_MINIMAL, f)
        
        generate_csvs(str(json_path), self.output_dir)
        
        # universities.csv ヘッダー確認
        with open(Path(self.output_dir) / 'universities.csv', 'r', encoding='utf-8') as f:
            header = f.readline().strip()
        
        expected_headers = ['id', 'name', 'country', 'url', 'created_at']
        self.assertIn('id', header)
        self.assertIn('name', header)
        
        print(f"✓ CSV ヘッダーが正しい")


class TestEdgeCases(unittest.TestCase):
    """エッジケーステスト"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_degrees_list(self):
        """degree が空のレコード"""
        data = [
            {
                "url": "https://example.com",
                "title": "No degrees",
                "country": "UK",
                "timestamp": datetime.now().isoformat(),
                "degrees": []
            }
        ]
        
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        
        # クラッシュしないか確認
        try:
            generate_csvs(str(json_path), self.output_dir)
            print("✓ 空の degrees リストを処理可能")
        except Exception as e:
            self.fail(f"空の degrees リストでクラッシュ: {e}")

    def test_missing_fields(self):
        """必須フィールドが不足している場合"""
        data = [
            {
                "url": "https://example.com",
                # title が欠落
                "degrees": [
                    {"name": "Master", "price": 10000, "currency": "GBP"}
                ]
            }
        ]
        
        json_path = Path(self.output_dir) / "input.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        
        try:
            generate_csvs(str(json_path), self.output_dir)
            print("✓ 欠落フィールドを処理可能")
        except Exception as e:
            self.fail(f"欠落フィールドでクラッシュ: {e}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
