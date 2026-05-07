#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
detect_course_type の動作を詳細に診断
"""
import json
from pathlib import Path

def detect_course_type_with_debug(text, record_id=None):
    """デバッグ情報付き course_type 検出"""
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
    
    # スコアを計算し、マッチしたキーワードも保存
    scores = {}
    details = {}
    for course_type, kws in keywords.items():
        matched = [kw for kw in kws if kw in text_lower]
        scores[course_type] = len(matched)
        details[course_type] = matched
    
    # 最高スコアのカテゴリを返す
    max_score = max(scores.values())
    if max_score == 0:
        return "general", scores, details
    
    result = max(scores, key=scores.get)
    return result, scores, details

def debug_course_detection():
    """実際のレコードで detect_course_type がどう動作するかを診断"""
    filepath = 'crawler/results.json'
    
    if not Path(filepath).exists():
        print(f'❌ {filepath} が見つかりません')
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print('=' * 100)
    print('🔬 course_type 検出メカニズムの詳細診断')
    print('=' * 100)
    
    # 最初の5件を詳しく見る
    for idx, record in enumerate(data[:5], 1):
        title = record.get('title', '')
        raw_text = record.get('raw_text', '')
        
        print(f'\n[レコード {idx}]')
        print(f'タイトル: {title}')
        
        for deg_idx, degree in enumerate(record.get('degrees', []), 1):
            degree_name = degree.get('name')
            saved_type = degree.get('course_type')
            
            print(f'  度合い {deg_idx}: {degree_name} → 保存されている種別: {saved_type}')
            
            # 実際の検出を実行
            detected, scores, details = detect_course_type_with_debug(raw_text, idx)
            print(f'    実際の検出結果: {detected}')
            print(f'    スコア: {scores}')
            
            # max_score が複数あるかチェック
            max_score = max(scores.values())
            ties = [k for k, v in scores.items() if v == max_score]
            if len(ties) > 1:
                print(f'    ⚠️  複数カテゴリが同スコア（{max_score}）: {ties}')
            
            # マッチしたキーワードを表示
            matched_any = False
            for ctype, keywords in details.items():
                if keywords and scores[ctype] > 0:
                    print(f'      {ctype}: {keywords[:3]}...' if len(keywords) > 3 else f'      {ctype}: {keywords}')
                    matched_any = True
            if not matched_any:
                print(f'      マッチするキーワードなし')
    
    print('\n' + '=' * 100)
    print('🎯 診断結論')
    print('=' * 100)
    print('''
複数カテゴリが同じスコアを獲得した場合、max() 関数は「最初に出現した方」を返すため、
スコアが複数並ぶ場合の結果は予測不可能です。
    ''')

if __name__ == '__main__':
    debug_course_detection()
