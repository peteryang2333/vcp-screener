#!/usr/bin/env python3
"""下载 SP 500 + SP 400 成分股并保存为 CSV"""
import pandas as pd, os, sys, requests

def save_wiki(url, fpath, col='Symbol'):
    # 用 requests + 浏览器标头绕过 Wikipedia 403
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(resp.text, flavor='lxml')
    for t in tables:
        if col in t.columns:
            tickers = t[col].dropna().astype(str).str.replace('.', '-').str.strip().tolist()
            tickers = [s for s in tickers if s and not s.startswith('^') and 'S&P' not in s]
            with open(fpath, 'w') as f:
                for sym in tickers:
                    f.write(sym + '\n')
            print('%s: %d 只' % (os.path.basename(fpath), len(tickers)))
            return True
    return False

if __name__ == '__main__':
    save_wiki('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'sp500.csv')
    save_wiki('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', 'sp400.csv')
