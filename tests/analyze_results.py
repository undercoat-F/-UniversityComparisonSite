#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
results.json を分析するスクリプト
レコード数、度合い数、重複、コース種別分布などを表示する
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

def analyze_json(filepath):
    """JSON ファイルを分析して統計情報を表示"""
    
    if not Path(filepath).exists():
        print(f'❌ ファイルが見つかりません: {filepath}')
        return
    
    # JSONを読み込む
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not isinstance(data, list):
        data = [data]
    
    print('=' * 70)
    print('📊 results.json 統計分析')
    print('=' * 70)
    
    # 基本統計
    record_count = len(data)
    print(f'\n📑 レコード数（ページ数）: {record_count}')
    
    # 度合い情報の収集
    all_degrees = []
    degree_by_course_type = defaultdict(int)
    degree_by_url = defaultdict(list)
    unique_titles = set()
    unique_urls = set()
    
    for record in data:
        url = record.get('url', '')
        title = record.get('title', '')
        unique_urls.add(url)
        unique_titles.add(title)
        
        degrees = record.get('degrees', [])
        for degree in degrees:
            all_degrees.append(degree)
            course_type = degree.get('course_type', 'unknown')
            degree_by_course_type[course_type] += 1
            
            degree_info = {
                'name': degree.get('name', ''),
                'price': degree.get('price'),
                'currency': degree.get('currency', ''),
                'course_type': course_type
            }
            key = f"{degree_info['name']}|{degree_info['price']}|{degree_info['currency']}"
            degree_by_url[key].append((url, title))
    
    degree_count = len(all_degrees)
    print(f'🎓 度合い総数: {degree_count}')
    print(f'🌐 URL数: {len(unique_urls)}')
    print(f'📝 ユニークなタイトル数: {len(unique_titles)}')
    
    # コース種別の分布
    print(f'\n📂 コース種別分布（トップ15）:')
    course_dist = sorted(degree_by_course_type.items(), key=lambda x: x[1], reverse=True)
    for course_type, count in course_dist[:15]:
        pct = (count / degree_count * 100) if degree_count > 0 else 0
        print(f'  • {course_type:20s}: {count:4d} 個 ({pct:5.1f}%)')
    
    # 重複度合い情報
    print(f'\n🔄 重複分析 (名前|価格|通貨 で判定):')
    duplicate_keys = {k: v for k, v in degree_by_url.items() if len(v) > 1}
    print(f'  重複キーの数: {len(duplicate_keys)}')
    print(f'  重複している度合いの総数: {sum(len(v) for v in duplicate_keys.values())}')
    print(f'  ユニークな度合い数: {degree_count - sum(len(v) for v in duplicate_keys.values())}')
    
    if duplicate_keys:
        print(f'\n  🔁 重複の多い度合い（トップ10）:')
        sorted_dups = sorted(duplicate_keys.items(), key=lambda x: len(x[1]), reverse=True)
        for key, occurrences in sorted_dups[:10]:
            print(f'    • {key}: {len(occurrences)} 回')
            for url, title in occurrences[:2]:
                print(f'      - {title[:60]}...' if len(title) > 60 else f'      - {title}')
    
    # 価格情報
    print(f'\n💷 価格情報:')
    currencies = Counter()
    prices = Counter()
    for degree in all_degrees:
        currency = degree.get('currency', 'unknown')
        price = degree.get('price', 0)
        currencies[currency] += 1
        if price:
            prices[f'{price}'] += 1
    
    print(f'  通貨の種類:')
    for currency, count in sorted(currencies.items(), key=lambda x: x[1], reverse=True):
        print(f'    • {currency}: {count} 個')
    
    print(f'  価格の種類（トップ10）:')
    for price, count in sorted(prices.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f'    • {price}: {count} 個')
    
    # オンライン/オフライン
    print(f'\n🖥️  学習形式:')
    online_count = sum(1 for d in all_degrees if d.get('is_online'))
    offline_count = degree_count - online_count
    print(f'  オンライン: {online_count} 個 ({online_count/degree_count*100:.1f}%)')
    print(f'  オフサイト: {offline_count} 個 ({offline_count/degree_count*100:.1f}%)')
    
    # サマリー
    print('\n' + '=' * 70)
    print('📈 サマリー')
    print('=' * 70)
    print(f'  ページ（レコード）: {record_count}')
    print(f'  度合い: {degree_count}')
    print(f'  ユニーク度合い (名前|価格|通貨): {degree_count - sum(len(v) for v in duplicate_keys.values())}')
    print(f'  国: {len(set(r.get("country", "") for r in data))}')
    print()

if __name__ == '__main__':
    import sys
    
    # デフォルトパスまたはコマンドラインで指定
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'crawler/results.json'
    
    # 作業ディレクトリを変更
    import os
    os.chdir(Path(__file__).parent)
    
    analyze_json(filepath)
