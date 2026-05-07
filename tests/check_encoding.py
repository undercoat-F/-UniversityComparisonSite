import sys

def check_encoding(filepath):
    """ファイルのエンコーディングを判定"""
    encodings = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso-2022-jp']
    
    print(f"ファイル: {filepath}")
    print("-" * 50)
    
    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                content = f.read()
            # 読み込み成功
            print(f"✓ {encoding:12s} - 読み込み成功 ({len(content)}文字)")
            
            # 先頭を表示
            lines = content.split('\n')[:5]
            for line in lines:
                if line.strip():
                    print(f"    {line[:60]}")
                    break
                    
        except (UnicodeDecodeError, UnicodeError) as e:
            print(f"✗ {encoding:12s} - エラー")
        except Exception as e:
            print(f"? {encoding:12s} - {e}")
    
    print("\n" + "=" * 50)
    print("推奨: 最初に成功したエンコーディングを使用してください")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = input("ファイルパスを入力: ")
    
    check_encoding(filepath)
