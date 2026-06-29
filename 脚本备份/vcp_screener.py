#!/usr/bin/env python3
"""
VCP (Volatility Contraction Pattern) 扫描器
每日扫描美股最活跃 100 强，筛选缩量整理形态
数据源: Yahoo Finance (yfinance — 内置 cookie/crumb 验证，避免 429)
"""

import os
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY',
          'ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:
    os.environ.pop(k, None)

import yfinance as yf
import pandas as pd
import warnings
import sys
import time
from datetime import datetime
import requests as req

warnings.filterwarnings('ignore')

# ================== 参数 ==================
TIGHT_DAYS = 5
TIGHTNESS_LIMIT = 0.10
VOL_RATIO = 0.75
MIN_PRICE = 2.0
MIN_VOLUME = 100000
MIN_DATA_DAYS = 60
BATCH_SIZE = 50
REQUEST_DELAY = 1.5  # 每次请求间隔，防 429


def check_network():
    """检查网络连通性"""
    sites = [
        ("Google",  "https://www.google.com"),
        ("YouTube", "https://www.youtube.com"),
        ("Yahoo",   "https://finance.yahoo.com"),
        ("GitHub",  "https://github.com"),
    ]
    sess = req.Session()
    sess.trust_env = False
    sess.proxies = None
    sess.headers.update({"User-Agent": "Mozilla/5.0"})

    print("  [网络检测] 测试以下站点...")
    all_ok = True
    for name, url in sites:
        try:
            r = sess.get(url, timeout=5)
            status = "OK" if r.status_code < 400 else "HTTP %d" % r.status_code
            print("    %-10s [%s]" % (name, status))
        except Exception as e:
            reason = str(e)
            if "resolve" in reason.lower() or "dns" in reason.lower():
                reason = "DNS 解析失败"
            elif "timeout" in reason.lower():
                reason = "连接超时"
            elif "proxy" in reason.lower() or "tunnel" in reason.lower():
                reason = "代理拦截"
            else:
                reason = reason.split(".")[0][:40]
            print("    %-10s ❌ %s" % (name, reason))
            all_ok = False
    if not all_ok:
        print("\n  ⚠️  部分站点无法访问，请检查 VPN/代理/网络后重试。")
        return False
    print("  ✅ 网络正常\n")
    return True


def get_most_active(limit=100):
    """yfinance 内置 screener — 当日最活跃美股"""
    print("  正在获取雅虎最活跃 %d 强..." % limit)
    try:
        data = yf.screen('most_actives', size=limit,
                         sortField='dayvolume', sortAsc=False)
        if not data or 'quotes' not in data:
            print("  screener 返回异常: %s" % (list(data.keys()) if data else "空"))
            return []
        tickers = [q['symbol'] for q in data['quotes']
                   if q.get('symbol') and q['symbol'] != '^GSPC']
        print("  获取到 %d 只标的" % len(tickers))
        if tickers:
            print("  前5: %s" % ", ".join(tickers[:5]))
        return tickers
    except Exception as e:
        print("  screener 失败: %s" % e)
        return []


def scan_vcp(tickers):
    """批量下载 + VCP 筛选"""
    if not tickers:
        return []

    results = []
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        print("  📥 第 %d 批 (%d 只)..." % (i//BATCH_SIZE + 1, len(batch)))

        try:
            raw = yf.download(" ".join(batch), period="6mo",
                              group_by='ticker', auto_adjust=True,
                              progress=False)
        except Exception as e:
            print("    ⚠️  批次下载失败: %s" % str(e)[:60])
            time.sleep(REQUEST_DELAY)
            continue

        for ticker in batch:
            try:
                if len(batch) == 1:
                    df = raw
                elif isinstance(raw.columns, pd.MultiIndex):
                    df = raw[ticker]
                else:
                    continue

                df = df.dropna()
                if len(df) < MIN_DATA_DAYS:
                    continue

                close = df['Close'].squeeze()
                high = df['High'].squeeze()
                low = df['Low'].squeeze()
                vol = df['Volume'].squeeze()

                lc = float(close.iloc[-1])
                lv = float(vol.iloc[-1])
                if lc < MIN_PRICE or lv < MIN_VOLUME:
                    continue

                sma50 = close.rolling(50).mean()
                vol_avg = vol.rolling(50).mean()
                h5 = high.rolling(TIGHT_DAYS).max()
                l5 = low.rolling(TIGHT_DAYS).min()

                sma50_v = float(sma50.iloc[-1])
                vol_avg_v = float(vol_avg.iloc[-1])
                h5_v = float(h5.iloc[-1])
                l5_v = float(l5.iloc[-1])

                if lc <= sma50_v or l5_v <= 0 or vol_avg_v <= 0:
                    continue
                amplitude = (h5_v - l5_v) / l5_v
                if amplitude > TIGHTNESS_LIMIT:
                    continue
                vol_ratio = lv / vol_avg_v
                if vol_ratio >= VOL_RATIO:
                    continue

                results.append({
                    '代码': ticker,
                    '当前价格': round(lc, 2),
                    '50日均线': round(sma50_v, 2),
                    '5日振幅%': round(amplitude * 100, 2),
                    '缩量比例%': round(vol_ratio * 100, 2),
                    '突破挂单价': round(h5_v, 2),
                    '距突破%': round((h5_v / lc - 1) * 100, 2),
                })
                print("    ✅ %s: 振幅 %.1f%%  缩量 %.1f%%" % (
                    ticker, amplitude*100, vol_ratio*100))

            except Exception:
                continue

        time.sleep(REQUEST_DELAY)  # 批次间隔，防 429

    return results


def main():
    print("=" * 70)
    print("  VCP 扫描器 | %s" % datetime.now().strftime('%Y-%m-%d %H:%M'))
    print("  数据源: Yahoo Finance (yfinance)")
    print("=" * 70)

    if not check_network():
        print("\n请先修复网络，然后再试。")
        sys.exit(1)

    print("📡 获取最活跃股票列表...")
    all_tickers = get_most_active(100)
    if not all_tickers:
        print("\n❌ 无法获取活跃名单，退出。")
        sys.exit(1)

    print("\n📊 开始扫描 %d 只标的...\n" % len(all_tickers))
    found = scan_vcp(all_tickers)

    print("\n" + "=" * 70)
    if found:
        df = pd.DataFrame(found).sort_values('距突破%')
        print("\n🎯 发现 %d 只 VCP 形态标的：\n" % len(found))
        pd.set_option('display.max_columns', 10)
        pd.set_option('display.width', 120)
        print(df.to_string(index=False))
        print("\n" + "-" * 70)
        print("💡 距突破% 越接近 0 越好，放量突破挂单价时考虑介入")
    else:
        print("\n👀 今日活跃池中无符合 VCP 形态的标的。")
    print("=" * 70)


if __name__ == "__main__":
    main()
