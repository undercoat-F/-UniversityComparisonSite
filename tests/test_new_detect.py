#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
改善された detect_course_type 関数をテスト
"""

def detect_course_type(text):
    """スコアリング方式: キーワード出現回数が最多のカテゴリを返す"""
    course_type_keywords = {
        "computer_science": [
            "computer science", "informatics", "computing", "software", "programming", "ai", "artificial intelligence",
            "machine learning", "data science", "cybersecurity", "information systems", "情報", "データ", "計算機",
            "ソフトウェア", "人工知能", "機械学習", "情報科学",
        ],
        "engineering": [
            "engineering", "mechanical", "electrical", "electronic", "civil", "chemical engineering", "aerospace", "robotics",
            "materials", "industrial engineering", "工学", "機械", "電気", "電子", "土木", "化学工学", "材料", "ロボティクス",
        ],
        "business": [
            "business", "management", "finance", "mba", "accounting", "marketing", "economics and management",
            "entrepreneurship", "international business", "経営", "会計", "ビジネス", "ファイナンス", "マーケティング",
        ],
        "health": [
            "medicine", "medical", "nursing", "public health", "pharmacy", "biomedical", "clinical", "dentistry",
            "看護", "医学", "医療", "公衆衛生", "薬学", "歯学",
        ],
        "education": [
            "education", "teaching", "pedagogy", "curriculum", "teacher training", "educational", "教育", "教職", "教育学",
        ],
        "law": [
            "law", "legal", "jurisprudence", "llb", "llm", "法学", "法律", "司法",
        ],
        "social_science": [
            "psychology", "sociology", "politics", "political science", "economics", "international relations",
            "anthropology", "public policy", "社会", "心理", "経済", "政治", "国際関係", "社会学",
        ],
        "humanities": [
            "history", "philosophy", "literature", "language", "linguistics", "classics", "religion",
            "人文", "文学", "哲学", "歴史", "言語", "言語学",
        ],
        "science": [
            "biology", "chemistry", "physics", "mathematics", "science", "environmental science", "geology",
            "statistics", "生物", "化学", "物理", "数学", "理学", "統計", "地学", "環境科学",
        ],
        "arts_design": [
            "art", "design", "music", "fine art", "architecture", "media", "film", "theatre",
            "芸術", "デザイン", "音楽", "建築", "メディア", "映像", "演劇",
        ],
    }

    text_lower = text.lower()
    # 各カテゴリのスコア（キーワード出現回数）を計算
    scores = {}
    for course_type, words in course_type_keywords.items():
        scores[course_type] = sum(1 for word in words if word in text_lower)
    
    # 最高スコアを取得（スコア0なら"general"を返す）
    max_score = max(scores.values())
    if max_score == 0:
        return "general"
    
    # スコアが最高のカテゴリを返す
    return max(scores, key=scores.get)

# テストケース
test_cases = [
    ("Textiles BA (Hons)", "テキスタイル学位：art, design, visual などが豊富 → arts_design 期待"),
    ("Artificial Intelligence MSc", "AI学位：ai, machine learning などが豊富 → computer_science 期待"),
    ("Clinical Psychology DClinPsychol", "心理学：psychology, clinical などが豊富 → health またはsocial_science 期待"),
    ("Food Security MSc", "食料安全保障：business, management などが豊富 → business 期待"),
    ("Offshore Renewable Energy EngD", "再生可能エネルギー工学：engineering, mechanical などが豊富 → engineering 期待"),
]

print('=' * 80)
print('🧪 改善された detect_course_type 関数の動作テスト')
print('=' * 80)

for title, description in test_cases:
    result = detect_course_type(title)
    print(f'\n📝 {title}')
    print(f'   説明: {description}')
    print(f'   ✓ 判定結果: {result}')
