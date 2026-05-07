#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
course_type が general に分類されているレコードを診断
なぜそう分類されているのかを調べる
"""
import json
from pathlib import Path
import re

def detect_course_type(text):
    """crawlAndSaver.py の detect_course_type 関数と同じロジック"""
    text_lower = text.lower()
    
    keywords = {
        "computer_science": [
            "computer science", "informatics", "computing", "software", "programming", "ai", "artificial intelligence",
            "machine learning", "data science", "cybersecurity", "information systems", "情報", "データ", "計算機",
            "ソフトウェア", "人工知能", "機械学習", "情報科学",
        ],
        "engineering": [
            "engineering", "engineer", "mechanical", "electrical", "civil", "chemical", "structural", "製造", "エンジニア"
        ],
        "business": [
            "business", "management", "mba", "finance", "accounting", "economics", "marketing", "商学", "経営", "経済"
        ],
        "health": [
            "health", "medicine", "nursing", "pharmacy", "psychology", "clinical", "医学", "看護", "薬学", "心理"
        ],
        "education": [
            "education", "teaching", "learning", "pedagogy", "teacher", "教育", "教学"
        ],
        "law": [
            "law", "legal", "jurisdiction", "法学", "法律"
        ],
        "social_science": [
            "sociology", "anthropology", "geography", "政治", "社会", "地理"
        ],
        "humanities": [
            "literature", "history", "philosophy", "languages", "文学", "歴史", "哲学", "言語"
        ],
        "arts_design": [
            "art", "design", "visual", "creative", "graphic", "美術", "デザイン"
        ],
        "science": [
            "science", "biology", "chemistry", "physics", "mathematics", "科学", "生物", "化学", "物理", "数学"
        ]
    }
    
    # スコアを計算
    scores = {}
    for course_type, kws in keywords.items():
        count = sum(1 for kw in kws if kw in text_lower)
        scores[course_type] = count
    
    # 最高スコアのカテゴリを返す
    max_score = max(scores.values())
    if max_score == 0:
        return "general"
    
    return max(scores, key=scores.get)

def analyze_general_records():
    """general に分類されたレコードを分析"""
    filepath = 'crawler/results.json'
    
    if not Path(filepath).exists():
        print(f'❌ {filepath} が見つかりません')
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    general_records = []
    
    for record in data:
        for degree in record.get('degrees', []):
            if degree.get('course_type') == 'general':
                general_records.append({
                    'url': record.get('url'),
                    'title': record.get('title'),
                    'degree_name': degree.get('name'),
                    'raw_text': record.get('raw_text', '')[:500]  # 最初の500文字
                })
    
    print('=' * 80)
    print(f'🔍 General に分類されたレコード分析（全{len(general_records)}件中、最初の10件）')
    print('=' * 80)
    
    for i, rec in enumerate(general_records[:10], 1):
        print(f'\n[{i}] {rec["title"]}')
        print(f'    URL: {rec["url"]}')
        print(f'    Degree: {rec["degree_name"]}')
        print(f'    テキスト先頭部分: {rec["raw_text"][:200]}...')
        
        # キーワードマッチングを分析
        text = rec['raw_text'].lower()
        
        keywords = {
            "computer_science": ["computer science", "computing", "software", "programming", "ai", "machine learning", "data science", "cybersecurity", "information systems", "情報", "データ"],
            "engineering": ["engineering", "engineer", "mechanical", "electrical", "civil", "chemical"],
            "business": ["business", "management", "mba", "finance", "accounting", "economics", "marketing"],
            "health": ["health", "medicine", "nursing", "pharmacy", "psychology", "clinical"],
            "education": ["education", "teaching", "learning", "pedagogy"],
            "law": ["law", "legal", "jurisdiction"],
            "humanities": ["literature", "history", "philosophy", "languages"],
            "arts_design": ["art", "design", "visual", "creative", "graphic"],
            "science": ["science", "biology", "chemistry", "physics", "mathematics"]
        }
        
        # 各カテゴリで何個キーワードがマッチしているか
        matches = {}
        for course_type, kws in keywords.items():
            match_count = sum(1 for kw in kws if kw in text)
            if match_count > 0:
                matches[course_type] = match_count
        
        if matches:
            print(f'    ✓ マッチしたキーワード: {matches}')
        else:
            print(f'    ✗ マッチするキーワードなし → general として分類された')
    
    print('\n' + '=' * 80)
    print(f'📊 一般統計')
    print('=' * 80)
    print(f'general に分類されたレコード: {len(general_records)} / 485')

if __name__ == '__main__':
    analyze_general_records()
