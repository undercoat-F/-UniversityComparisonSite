#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
results.json を 3つのテーブルCSVに分割する ETLスクリプト
確認用：手動でフィルタリング・品質判定を追加できるように。
"""

import json
import csv
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
import sys

def extract_university_name(url):
    """URL ドメインから大学名を推定"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # よくあるドメインマッピング
    domain_map = {
        "study.ed.ac.uk": "University of Edinburgh",
        "ed.ac.uk": "University of Edinburgh",
        "athabascau.ca": "Athabasca University",
        "open.ac.uk": "The Open University",
        "london.ac.uk": "University of London",
        "ignou.ac.in": "Indira Gandhi National Open University",
        # 他大学を追加する際はここに加える
    }
    
    for domain_pattern, name in domain_map.items():
        if domain_pattern in domain:
            return name
    
    # フォールバック：www等のサブドメインを除いた主要部分を使用
    parts = domain.split('.')
    # www, study, apply などの一般的サブドメインをスキップ
    skip_prefixes = {"www", "study", "apply", "admissions", "courses", "portal"}
    for part in parts:
        if part not in skip_prefixes and part:
            return part.title()
    return domain.title()

def extract_program_name(title):
    """ページタイトルからプログラム名を抽出"""
    # "Program Name - Postgraduate taught programmes | The University of Edinburgh" 形式を想定
    if " - " in title:
        parts = title.split(" - ")
        return parts[0].strip()
    return title.strip()

def parse_timestamp(iso_string):
    """ISO形式をシンプルな日付に変換"""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return iso_string

def normalize_degree_level(raw_degree_name):
    """degree_levelを正規化: 母数値を統一させる"""
    if not raw_degree_name:
        return "Other"
    
    name_lower = raw_degree_name.lower().strip()
    
    # PhD 系
    if "phd" in name_lower or "doctorate" in name_lower or "博士" in name_lower:
        return "PhD"
    
    # Master 系
    if "master" in name_lower or "postgraduate" in name_lower or "graduate" in name_lower or "msc" in name_lower or "ma" in name_lower or "meng" in name_lower or "修士" in name_lower:
        return "Master"
    
    # Bachelor 系
    if "bachelor" in name_lower or "undergraduate" in name_lower or "ba" in name_lower or "bsc" in name_lower or "beng" in name_lower or "学士" in name_lower:
        return "Bachelor"
    
    # 不明
    return "Other"


def as_nullable_text(value):
    if value is None:
        return ""
    return str(value)

def generate_csvs(json_path, output_dir="csv_output"):
    """JSONを3つのテーブルCSVに分割"""
    
    # 出力ディレクトリを作成
    Path(output_dir).mkdir(exist_ok=True)
    
    # JSONを読み込む
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not isinstance(data, list):
        data = [data]
    
    # テーブル用の一時ストレージ
    universities = {}         # {name: {id, url, country}}
    programs = []             # [{id, university_id, program_name, ...}]
    # [旧] fees = []          # [{program_id, degree_level, amount, currency, ...}]
    patterns = {}             # {(degree_level, amount, currency, fee_type, tuition_type, amount_min, amount_max, normalized_monthly_amount, normalization_note): id}
    program_tuition_map = []  # [{degree_program_id, tuition_pattern_id}]
    
    program_id_counter = 1
    university_id_counter = 1
    pattern_id_counter = 1
    
    # JSONを処理
    for record in data:
        url = record.get('url', '')
        title = record.get('title', '')
        country = record.get('country', '')
        timestamp = record.get('timestamp', '')
        
        # 大学情報を抽出
        uni_name = extract_university_name(url)
        if uni_name not in universities:
            universities[uni_name] = {
                'id': university_id_counter,
                'url': url,
                'country': country
            }
            university_id_counter += 1
        
        # プログラム情報を抽出
        program_name = extract_program_name(title)

        degrees = record.get('degrees', [])
        # 学費抽出に失敗してもコース自体は保存する
        if not degrees:
            degrees = [{
                'name': program_name,
                'course_type': 'general',
                'is_online': False,
                'price': '',
                'currency': '',
                'tuition_type': 'unknown',
                'amount_min': '',
                'amount_max': '',
                'normalized_monthly_amount': '',
                'normalization_note': 'unknown_not_normalized',
            }]

        for degree in degrees:
            # プログラム1件ごとに1レコード作成
            course_type = degree.get('course_type', 'general')
            amount_preview = degree.get('price', '')
            currency_preview = degree.get('currency', '')
            # 品質判定: 授業料欠損 または フォールバック(course_type==general) の場合は low
            quality_flag = 'low' if (
                course_type == 'general'
                or amount_preview in ('', None)
                or currency_preview in ('', None)
            ) else 'high'
            program_rec = {
                'id': program_id_counter,
                'university_id': universities[uni_name]['id'],
                'program_name': program_name,
                'course_type': course_type,
                'is_online': 1 if degree.get('is_online') else 0,
                'source_url': url,
                'last_seen': parse_timestamp(timestamp),
                'quality_flag': quality_flag,
            }
            programs.append(program_rec)
            
            # [旧] 料金情報を抽出（tuition_fees テーブル用）
            # fee_rec = {
            #     'program_id': program_id_counter,
            #     'degree_level': normalize_degree_level(degree.get('name', '')),
            #     'amount': degree.get('price', ''),
            #     'currency': degree.get('currency', ''),
            #     'fee_type': 'tuition',
            #     'observed_at': parse_timestamp(timestamp),
            #     'note': degree.get('context', '')[:100] if degree.get('context') else '',
            # }
            # fees.append(fee_rec)

            # [新] 料金パターンを重複排除して登録
            degree_level = normalize_degree_level(degree.get('name', ''))
            amount = degree.get('price', '')
            currency = degree.get('currency', '')
            fee_type = 'tuition'
            tuition_type = degree.get('tuition_type', 'unknown')
            amount_min = degree.get('amount_min', '')
            amount_max = degree.get('amount_max', '')
            normalized_monthly_amount = degree.get('normalized_monthly_amount', '')
            normalization_note = degree.get('normalization_note', 'unknown_not_normalized')

            # 授業料が欠損している場合はコースのみ保存し、料金パターンは作らない
            if amount in ('', None) or currency in ('', None):
                program_id_counter += 1
                continue

            pattern_key = (
                degree_level,
                as_nullable_text(amount),
                currency,
                fee_type,
                tuition_type,
                as_nullable_text(amount_min),
                as_nullable_text(amount_max),
                as_nullable_text(normalized_monthly_amount),
                normalization_note,
            )

            if pattern_key not in patterns:
                patterns[pattern_key] = pattern_id_counter
                pattern_id_counter += 1

            # 中間テーブルに登録
            program_tuition_map.append({
                'degree_program_id': program_id_counter,
                'tuition_pattern_id': patterns[pattern_key],
            })

            program_id_counter += 1
    
    # -------- CSVを出力 --------
    
    # 1. Universities CSV
    uni_csv_path = Path(output_dir) / 'universities.csv'
    with open(uni_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'name', 'country', 'url', 'created_at'])
        writer.writeheader()
        for uni_name, info in universities.items():
            writer.writerow({
                'id': info['id'],
                'name': uni_name,
                'country': info['country'],
                'url': info['url'],
                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    
    # 2. Degree Programs CSV
    prog_csv_path = Path(output_dir) / 'degree_programs.csv'
    with open(prog_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'id', 'university_id', 'program_name', 'course_type', 'is_online', 
            'source_url', 'last_seen', 'quality_flag'
        ])
        writer.writeheader()
        for prog in programs:
            writer.writerow({
                **prog,
            })
    
    # [旧] 3. Tuition Fees CSV
    # fees_csv_path = Path(output_dir) / 'tuition_fees.csv'
    # with open(fees_csv_path, 'w', newline='', encoding='utf-8') as f:
    #     writer = csv.DictWriter(f, fieldnames=[
    #         'id', 'program_id', 'degree_level', 'amount', 'currency',
    #         'fee_type', 'observed_at', 'note'
    #     ])
    #     writer.writeheader()
    #     for idx, fee in enumerate(fees, 1):
    #         writer.writerow({'id': idx, **fee})

    # [新] 3. Tuition Patterns CSV（重複排除済み）
    patterns_csv_path = Path(output_dir) / 'tuition_patterns.csv'
    with open(patterns_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                'id',
                'degree_level',
                'amount',
                'currency',
                'fee_type',
                'tuition_type',
                'amount_min',
                'amount_max',
                'normalized_monthly_amount',
                'normalization_note',
            ]
        )
        writer.writeheader()
        for (
            degree_level,
            amount,
            currency,
            fee_type,
            tuition_type,
            amount_min,
            amount_max,
            normalized_monthly_amount,
            normalization_note,
        ), pid in patterns.items():
            writer.writerow({
                'id': pid,
                'degree_level': degree_level,
                'amount': amount,
                'currency': currency,
                'fee_type': fee_type,
                'tuition_type': tuition_type,
                'amount_min': amount_min,
                'amount_max': amount_max,
                'normalized_monthly_amount': normalized_monthly_amount,
                'normalization_note': normalization_note,
            })

    # [新] 4. Program Tuition Map CSV（中間テーブル）
    map_csv_path = Path(output_dir) / 'program_tuition_map.csv'
    with open(map_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['degree_program_id', 'tuition_pattern_id'])
        writer.writeheader()
        for row in program_tuition_map:
            writer.writerow(row)

    print(' CSV変換完了')
    print('=' * 10)
    print(f' 出力先: {output_dir}/')
    print(f'  • universities.csv ({len(universities)} 件)')
    print(f'  • degree_programs.csv ({len(programs)} 件)')
    print(f'  • tuition_patterns.csv ({len(patterns)} 件 ※重複排除済み)')
    print(f'  • program_tuition_map.csv ({len(program_tuition_map)} 件)')
    print()
    print('次のステップ:')
    print('  1. 各CSVを確認してください（ExcelやテキストエディタOK）')
    print('  2. 不要な行はコメント化（行頭に # を付ける）')
    print('  3. 大学名やプログラム名に修正が必要なら修正してください')
    print('  4. その後、DB投入スクリプトを実行してください')
    print()

def main(json_path='crawler/results.json', output_dir='db/csv_output'):
    generate_csvs(json_path, output_dir)

if __name__ == '__main__':
    
    json_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\81701\Pythonプロジェクト\学位ソート検索サイト\crawler\results.json'
    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'csv_output'
    
    generate_csvs(json_path, output_dir)
