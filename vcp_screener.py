#!/usr/bin/env python3
"""
VCP (Volatility Contraction Pattern) 扫描器 v3
支持多市场：🇺🇸 US / 🇯🇵 日本 / 🇰🇷 韩国
数据源: Yahoo Finance (yfinance)
v3 新增: +多段收缩评分 (scipy swing point detection)
"""
import os
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY',
          'ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:
    os.environ.pop(k, None)

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import sys
import time
import random
import argparse
from datetime import datetime
import requests as req

try:
    from scipy.signal import argrelextrema
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

warnings.filterwarnings('ignore')

# ================== 参数 ==================
TIGHT_DAYS = 5
TIGHTNESS_LIMIT = 0.10
VOL_RATIO = 0.75
MIN_PRICE = 2.0
MIN_VOLUME = 100000
MIN_DATA_DAYS = 250
BATCH_SIZE = 30
REQUEST_DELAY = 3.5          # 批次间基础延时（加大以避开 Yahoo 匿名限流）
SWING_ORDER = 5  # argrelextrema 邻域大小

# 注意：yfinance 1.2.0 要求使用 curl_cffi 会话，会拒绝外部传入的 requests.Session，
# 因此不能自定义 session；这里仅保留参数占位，实际下载交由 yfinance 内部处理。
_YF_SESSION = None

# 市场配置
MARKETS = {
    'us': {
        'name': '🇺🇸 美股',
        'region': 'us',
        'file_tag': 'US',
        'min_mcap': 2000000000,
        'min_day_vol': 5000000,
    },
    'jp': {
        'name': '🇯🇵 日本（东证）',
        'region': 'jp',
        'file_tag': 'JP',
        'min_mcap': 2000000000,
        'min_day_vol': 500000,
    },
    'kr': {
        'name': '🇰🇷 韩国（KOSPI）',
        'region': 'kr',
        'file_tag': 'KR',
        'min_mcap': 2000000000,
        'min_day_vol': 500000,
    }
}


def check_network():
    """检查到 Yahoo 数据接口的连通性（只测真正需要的数据源，避免被无关站点误杀）

    说明：原逻辑要求 Google / YouTube / Yahoo 主页全通才算“网络正常”，但 Google、
    YouTube 在国内等网络环境本就不可达，且 finance.yahoo.com 主页常返回 403，这会
    导致脚本在任何受限网络下直接 sys.exit(1)，走不到真正的数据抓取。这里只测 Yahoo
    行情数据接口；只要能拿到 HTTP 响应（含 401/403/429）即说明链路是通的——403/429
    只是服务端限流，并非断网。
    """
    sess = req.Session()
    sess.trust_env = False
    sess.proxies = None
    sess.headers.update({"User-Agent": "Mozilla/5.0"})

    test_url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
    try:
        r = sess.get(test_url, timeout=10)
        print("  [网络检测] Yahoo 数据接口: 可达 (HTTP %d)" % r.status_code)
        print("  ✅ 网络正常\n")
        return True
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
        print("  [网络检测] Yahoo 数据接口: ❌ %s" % reason)
        print("\n  ⚠️  无法连接 Yahoo 数据接口，请检查网络/VPN 后重试。")
        return False


def get_sp900_tickers():
    """读取本地 SP 500 + SP 400 CSV 文件（每行一个代码，无表头）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    all_tickers = []

    for name, fname in [("S&P 500", "sp500.csv"), ("S&P 400", "sp400.csv")]:
        fpath = os.path.join(script_dir, fname)
        print("    读取 %s..." % name)
        if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
            print("      ⚠️  文件不存在或为空，跳过" if name == "S&P 400" else "      ❌ 文件不存在")
            continue
        try:
            with open(fpath) as f:
                for line in f:
                    sym = line.strip()
                    if sym and not sym.startswith('^') and not sym.startswith('Symbol') and 'S&P' not in sym:
                        all_tickers.append(sym)
            print("      ✅ %s: 已加载" % name)
        except Exception as e:
            print("      ❌ 读取失败: %s" % e)

    all_tickers = list(dict.fromkeys(all_tickers))
    print("  ✅ SP 900 共 %d 只（去重后）" % len(all_tickers))
    if all_tickers:
        print("  前10: %s" % ", ".join(all_tickers[:10]))
    return all_tickers


def get_most_active(market_cfg, limit=100):
    """yfinance screener — 获取指定市场最活跃股票"""
    region = market_cfg['region']
    min_mcap = market_cfg['min_mcap']
    min_vol = market_cfg['min_day_vol']

    print("  正在获取 %s 最活跃 %d 强..." % (market_cfg['name'], limit))

    try:
        if region == 'us':
            data = yf.screen('most_actives', size=limit,
                             sortField='dayvolume', sortAsc=False)
        else:
            query = yf.EquityQuery('AND', [
                yf.EquityQuery('EQ', ['region', region]),
                yf.EquityQuery('GTE', ['intradaymarketcap', min_mcap]),
                yf.EquityQuery('GT', ['dayvolume', min_vol])
            ])
            data = yf.screen(query, size=limit,
                             sortField='dayvolume', sortAsc=False)

        if not data or 'quotes' not in data:
            print("  screener 返回异常: %s" % (list(data.keys()) if data else "空"))
            return []

        quotes = data['quotes']
        tickers = []
        for q in quotes:
            sym = q.get('symbol')
            if sym and sym != '^GSPC' and sym != '^N225':
                tickers.append(sym)

        print("  获取到 %d 只标的" % len(tickers))
        if tickers:
            print("  前5: %s" % ", ".join(tickers[:5]))
        return tickers

    except Exception as e:
        print("  screener 失败: %s" % e)
        return []


def get_spy_performance():
    """获取 SPY 最近 6 月涨幅（兼容 yfinance 1.x 的 MultiIndex 列）"""
    try:
        spy = yf.download("SPY", period="6mo", auto_adjust=True, progress=False)
        if spy is None or spy.empty or len(spy) < 20:
            return 0.0
        close = spy.xs("Close", level=0, axis=1) if isinstance(spy.columns, pd.MultiIndex) else spy["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100
    except Exception as e:
        print("     ⚠️  SPY 基准获取失败: %s" % str(e)[:60])
        return 0.0


def safe_download(tickers, period="1y", attempts=5):
    """带限流重试的 yfinance 下载封装（兼容 yfinance 1.x）

    yfinance 1.x 多标的下载返回 (ticker, field) 二级列。Yahoo 对匿名请求
    会返回 429 限流，这里改用持久会话 + 指数退避（带抖动）重试。
    """
    last_err = None
    for attempt in range(attempts):
        try:
            df = yf.download(tickers, period=period, auto_adjust=True,
                            progress=False)
            if df is None:
                return None
            return df
        except Exception as e:
            last_err = e
            msg = str(e)
            if "Rate" in msg or "429" in msg or "Too Many" in msg:
                # 指数退避 + 随机抖动，避免与固定节奏的请求共振被持续限流
                wait = REQUEST_DELAY * (2 ** attempt) + random.uniform(0, 3.0)
                print("    ⏳ 触发 Yahoo 限流，%.0f 秒后重试 (%d/%d)..." %
                      (wait, attempt + 1, attempts))
                time.sleep(wait)
            else:
                # 非限流错误直接抛出，便于排查
                raise
    print("    ⚠️  下载失败（限流）: %s" % str(last_err)[:80])
    return None


def extract_ticker_df(raw, ticker):
    """从 yfinance 1.x 的 MultiIndex 结果中安全取出单只股票的数据框"""
    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        # yfinance 1.x 的列层级为 (Price, Ticker)：ticker 在 level=1。
        # 旧版 group_by='ticker' 时 ticker 在 level=0。两种都要兼容。
        df = None
        names = list(raw.columns.names or [])
        order = [1, 0] if (len(names) > 1 and names[1] == 'Ticker') else [0, 1]
        for lv in order:
            try:
                df = raw.xs(ticker, level=lv, axis=1)
                break
            except Exception:
                continue
        if df is None:
            try:
                df = raw[ticker]
            except Exception:
                return None
    else:
        df = raw
    if df is None or (hasattr(df, "empty") and df.empty):
        return None
    if isinstance(df, pd.Series):
        df = df.to_frame().T
    return df


def calc_rs_rating(ticker_returns_pct, spy_returns_pct, all_returns=None):
    """简易 RS 评级代理 (0-99)"""
    if all_returns is not None and len(all_returns) > 5:
        rank = sum(1 for r in all_returns if r <= ticker_returns_pct)
        return int(rank / len(all_returns) * 99)
    excess = ticker_returns_pct - spy_returns_pct
    if excess > 20:
        return 90
    elif excess > 10:
        return 75
    elif excess > 5:
        return 60
    elif excess > 0:
        return 45
    else:
        return 25


# ================== 多段收缩检测 ==================

def detect_vcp_score(close, high, low):
    """
    检测多段 VCP 收缩并评分 (1-3)。
    
    返回: (score, contractions, details)
      score: 1=仅窄幅, 2=2段递减, 3=3+段递减
      contractions: 各段收缩幅度列表
      details: 描述字符串
    """
    if not HAS_SCIPY:
        return 1, [], "无 scipy，未检测多段"

    close_a = close.values
    high_a = high.values
    low_a = low.values

    # 找到摆动高点和低点
    high_idx = argrelextrema(high_a, np.greater, order=SWING_ORDER)[0]
    low_idx  = argrelextrema(low_a, np.less, order=SWING_ORDER)[0]

    # 合并所有拐点并按时间排序
    all_pivots = []
    for i in high_idx:
        all_pivots.append((i, 'H', high_a[i]))
    for i in low_idx:
        all_pivots.append((i, 'L', low_a[i]))
    all_pivots.sort(key=lambda x: x[0])

    if len(all_pivots) < 4:
        return 1, [], "拐点不足"

    # 提取序列：H → L → H → L → ... 计算每段跌幅
    # 只保留 H→L 配对（从高点到低点的回落）
    contractions = []
    i = 0
    while i < len(all_pivots) - 1:
        if all_pivots[i][1] == 'H' and all_pivots[i+1][1] == 'L':
            hi = all_pivots[i][2]
            lo = all_pivots[i+1][2]
            if hi > 0 and lo > 0:
                pct = (hi - lo) / hi * 100
                contractions.append(pct)
            i += 2
        else:
            i += 1

    # 只保留最近 3 段
    contractions = contractions[-3:]

    if len(contractions) < 1:
        return 1, [], "无完整回落段"

    # 评分
    # 3 分: 至少 3 段，且严格递减
    if len(contractions) >= 3 and contractions[-3] > contractions[-2] > contractions[-1]:
        # 同时最后一段 < 10%
        if contractions[-1] < 10:
            return 3, contractions, "3段递减收缩 ✓"
        return 2, contractions, "3段递减但末段>10%%"

    # 2 分: 2 段递减
    if len(contractions) >= 2 and contractions[-2] > contractions[-1]:
        return 2, contractions, "2段递减"

    # 1 分: 保底
    return 1, contractions, "单段或无序"


# ================== 主扫描逻辑 ==================

def scan_vcp(tickers, market_tag=""):
    """批量下载 + 趋势模板 + VCP 筛选 + 多段评分，返回结果列表"""
    if not tickers:
        return []

    print("  📊 获取 SPY 基准...")
    spy_ret = get_spy_performance()
    print("     SPY 6月涨幅: %.1f%%" % spy_ret)
    all_returns = []

    candidates = []
    parsed_ok = 0          # 成功解析出行情的标的数
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        print("  📥 %s 第 %d 批 (%d 只)..." % (market_tag, i//BATCH_SIZE + 1, len(batch)))

        raw = safe_download(batch, period="1y")
        if raw is None:
            time.sleep(REQUEST_DELAY)
            continue

        for ticker in batch:
            try:
                df = extract_ticker_df(raw, ticker)
                if df is None:
                    continue

                df = df.dropna()
                if len(df) < MIN_DATA_DAYS:
                    continue
                parsed_ok += 1

                close = df['Close'].squeeze()
                high = df['High'].squeeze()
                low = df['Low'].squeeze()
                vol = df['Volume'].squeeze()

                lc = float(close.iloc[-1])
                lv = float(vol.iloc[-1])
                if lc < MIN_PRICE or lv < MIN_VOLUME:
                    continue

                # ---- Trend Template ----
                sma50 = close.rolling(50).mean()
                sma150 = close.rolling(150).mean()
                sma200 = close.rolling(200).mean()

                sma50_v = float(sma50.iloc[-1])
                sma150_v = float(sma150.iloc[-1])
                sma200_v = float(sma200.iloc[-1])
                sma200_30ago = float(sma200.iloc[-30]) if len(sma200) >= 30 else sma200_v

                if np.isnan(sma150_v) or np.isnan(sma200_v):
                    continue
                if lc <= sma50_v or lc <= sma150_v or lc <= sma200_v:
                    continue
                if sma50_v <= sma150_v or sma150_v <= sma200_v:
                    continue
                if sma200_v <= sma200_30ago:
                    continue

                high_1y = float(high.max())
                if high_1y <= 0:
                    continue
                dist_52w = (high_1y - lc) / high_1y
                if dist_52w > 0.25:
                    continue

                ret_6m = (lc / float(close.iloc[0]) - 1) * 100 if len(close) > 20 else 0
                all_returns.append(ret_6m)

                # ---- VCP 窄幅条件 ----
                vol_avg = vol.rolling(50).mean()
                h5 = high.rolling(TIGHT_DAYS).max()
                l5 = low.rolling(TIGHT_DAYS).min()

                vol_avg_v = float(vol_avg.iloc[-1])
                h5_v = float(h5.iloc[-1])
                l5_v = float(l5.iloc[-1])

                if l5_v <= 0 or vol_avg_v <= 0:
                    continue
                amplitude = (h5_v - l5_v) / l5_v
                if amplitude > TIGHTNESS_LIMIT:
                    continue
                vol_ratio = lv / vol_avg_v
                if vol_ratio >= VOL_RATIO:
                    continue

                # ---- 多段收缩评分 ----
                vcp_score, contractions, vcp_detail = detect_vcp_score(close, high, low)

                # ---- 策略参考值 ----
                ema10 = close.ewm(span=10, adjust=False).mean()
                ema21 = close.ewm(span=21, adjust=False).mean()
                ema10_v = float(ema10.iloc[-1])
                ema21_v = float(ema21.iloc[-1])
                atr = (high.rolling(22).max() - low.rolling(22).min()) / 22
                atr_v = float(atr.iloc[-1])
                chandelier = float(high.rolling(22).max().iloc[-1]) - 2.5 * atr_v
                hard_stop = lc * (1 - 0.08)

                # 收缩幅度显示
                c_str = "/".join(f"{c:.1f}" for c in contractions[-3:]) if contractions else "-"

                candidates.append({
                    '代码': ticker,
                    'VCP分': vcp_score,
                    '收缩%': c_str,
                    '当前价格': round(lc, 2),
                    '6月收益%': round(ret_6m, 1),
                    '5日振幅%': round(amplitude * 100, 2),
                    '缩量比例%': round(vol_ratio * 100, 2),
                    '突破挂单价': round(h5_v, 2),
                    '距突破%': round((h5_v / lc - 1) * 100, 2),
                    '距52周高%': round(dist_52w * 100, 2),
                    'RS评级': 0,
                    '10EMA': round(ema10_v, 2),
                    '21EMA': round(ema21_v, 2),
                    '吊灯止损': round(chandelier, 2),
                    '硬止损价': round(hard_stop, 2),
                    '_ret_6m': ret_6m,
                })

            except Exception:
                continue

        time.sleep(REQUEST_DELAY)

    if not candidates:
        return []

    # 算 RS 评级
    for c in candidates:
        c['RS评级'] = calc_rs_rating(c['_ret_6m'], spy_ret, all_returns)
        del c['_ret_6m']

    # 按距突破%排序
    candidates.sort(key=lambda x: x['距突破%'])
    return candidates


def get_us_tickers(pool, cfg):
    if pool == 'sp900':
        tickers = get_sp900_tickers()
        if not tickers:
            print("  ⚠️ SP 900 获取失败，自动降级到最活跃 100...")
            return get_most_active(cfg, 100)
        return tickers
    else:
        return get_most_active(cfg, 100)


def main():
    parser = argparse.ArgumentParser(description='VCP 多市场扫描器 v3')
    parser.add_argument('--market', '-m', default='us',
                        choices=['us', 'jp', 'kr', 'all'],
                        help='市场: us(美股), jp(日本), kr(韩国), all(全部)')
    parser.add_argument('--pool', '-p', default='sp900',
                        choices=['active', 'sp900'],
                        help='美股池: active(最活跃100), sp900(标普500+400, 默认)')
    parser.add_argument('--fast', '-f', action='store_true',
                        help='快速模式：跳过 Trend Template 过滤')
    args = parser.parse_args()

    print("=" * 70)
    print("  VCP 扫描器 v3 | %s" % datetime.now().strftime('%Y-%m-%d %H:%M'))
    if args.market in ['us', 'all']:
        print("  美股池: %s" % ('最活跃100' if args.pool == 'active' else 'SP 900 (标普500+400)'))
    print("  模式: %s" % ('⚡ 快速' if args.fast else '🔍 标准（趋势模板 + 多段评分）'))
    if not HAS_SCIPY:
        print("  ⚠️  未安装 scipy，多段评分不可用。运行: pip3 install scipy")
    print("=" * 70)

    if not check_network():
        print("\n请先修复网络，然后再试。")
        sys.exit(1)

    if args.fast:
        global MIN_DATA_DAYS
        MIN_DATA_DAYS = 60

    market_list = ['us', 'jp', 'kr'] if args.market == 'all' else [args.market]
    all_found = {}

    for mkt in market_list:
        cfg = MARKETS[mkt]
        tag = cfg['file_tag']

        print("\n" + "=" * 70)
        print("  【%s】扫描开始" % cfg['name'])
        print("=" * 70)

        if mkt == 'us':
            tickers = get_us_tickers(args.pool, cfg)
        else:
            tickers = get_most_active(cfg, 100)

        if not tickers:
            print("  ❌ %s 无法获取标的列表，跳过。" % cfg['name'])
            all_found[mkt] = []
            continue

        print("\n📊 扫描 %d 只标的...\n" % len(tickers))
        found = scan_vcp(tickers, tag)
        all_found[mkt] = found

        print("\n" + "=" * 70)
        if found:
            df = pd.DataFrame(found)
            print("\n🎯 %s 发现 %d 只 VCP 形态标的：\n" % (cfg['name'], len(found)))
            pd.set_option('display.max_columns', 20)
            pd.set_option('display.width', 200)

            display_cols = ['VCP分', '代码', '当前价格', 'RS评级', '收缩%',
                            '5日振幅%', '缩量比例%', '突破挂单价', '距突破%',
                            '距52周高%', '10EMA', '21EMA', '吊灯止损', '硬止损价']
            # 按 VCP 分降序 + 距突破%升序
            df_sorted = df.sort_values(['VCP分', '距突破%'], ascending=[False, True])
            available = [c for c in display_cols if c in df_sorted.columns]
            print(df_sorted[available].to_string(index=False))
            print("\n  💡 VCP分: 3=3段递减 ✓  2=2段递减  1=仅窄幅整理")
        else:
            print("\n👀 %s 无符合 VCP 形态的标的。" % cfg['name'])
        print("=" * 70)

    total = sum(len(v) for v in all_found.values())
    print("\n" + "=" * 70)
    print("  📊 今日 VCP 扫描汇总")
    for mkt in market_list:
        cfg = MARKETS[mkt]
        cnt = len(all_found.get(mkt, []))
        print("  %s  %s: %d 只" % (cfg['name'], "🎯" if cnt else "👀", cnt))
    print("=" * 70)

    if args.market != 'all':
        return all_found.get(args.market, [])


if __name__ == "__main__":
    main()
