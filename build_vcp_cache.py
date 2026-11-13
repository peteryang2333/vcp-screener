#!/usr/bin/env python3
# 重建/增量更新 VCP 本地价缓存（DAILY, 1y），产出 数据/vcp_cache.pkl
# （dict[ticker]=DataFrame[OHLCV]，datetime 索引），供 vcp_screener 离线使用。
#
# 2026-11-14 修复（P0-2）：
#   1) 单源 Yahoo chart 在匿名出口常被 403/429 限流，旧版刷新失败后被 workflow
#      的 `|| echo` 吞掉，于是「11-13 的扫描」实际用的是 11-11 的收盘价。
#      现在加 stockanalysis.com 免费日线兜底，Yahoo 失败逐只切换。
#   2) 新增 --assert-fresh：写盘前断言「SPY 最后一根 = 最近交易日」且
#      ≥80% 标的末根同日，任一不满足直接 exit 2，绝不把陈旧缓存写成新缓存。
#   3) 保留原有「几乎全失败就不覆盖旧缓存」的安全逻辑。
import os
import sys
import time
import pickle
from datetime import datetime, date

import numpy as np
import pandas as pd
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(SCRIPT_DIR, "数据")
CACHE_PATH = os.path.join(RESULT_DIR, "vcp_cache.pkl")
FRESH_FILE = os.path.join(RESULT_DIR, "cache_refresh.txt")
FRESH_DAYS = 7

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "rb") as f:
                c = pickle.load(f)
            if isinstance(c, dict):
                return c
        except Exception as e:
            print("  ⚠️  读取旧缓存失败: %s" % e)
    return {}


def build_universe():
    syms = []
    for f in ["sp500.csv", "sp400.csv"]:
        p = os.path.join(SCRIPT_DIR, f)
        if os.path.exists(p):
            with open(p) as fh:
                for line in fh:
                    s = line.strip()
                    if s and not s.startswith("^") and "S&P" not in s and s != "Symbol":
                        syms.append(s)
    adr_path = os.path.join(RESULT_DIR, "adr_list.txt")
    if os.path.exists(adr_path):
        with open(adr_path) as fh:
            for line in fh:
                s = line.strip().upper()
                if s and not s.startswith("#"):
                    syms.append(s)
    if "SPY" not in syms:
        syms.append("SPY")
    seen = set()
    return [s for s in syms if not (s in seen or seen.add(s))]


def days_since_refresh():
    if not os.path.exists(FRESH_FILE):
        return None
    try:
        d = datetime.strptime(open(FRESH_FILE).read().strip(), "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def _norm(df):
    df = df.dropna(subset=["Close"])
    if len(df) < 200:
        return None
    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def fetch_yahoo(sym, sess):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=1y&interval=1d" % sym)
    r = sess.get(url, timeout=20)
    if r.status_code == 429:
        return "RATE_LIMIT", None
    if r.status_code != 200:
        return "HTTP_%d" % r.status_code, None
    d = r.json()["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    df = pd.DataFrame({
        "Open": q["open"], "High": q["high"], "Low": q["low"],
        "Close": q["close"], "Volume": q["volume"],
    }, index=pd.to_datetime(d["timestamp"], unit="s"))
    return "yahoo", _norm(df)


def fetch_stockanalysis(sym, sess):
    """Free daily-history fallback. stockanalysis returns newest-first rows
    with t/o/h/l/c/v. Try both '-' and '.' share-class spellings."""
    for cand in (sym.lower(), sym.lower().replace("-", ".")):
        url = ("https://stockanalysis.com/api/symbol/s/%s/history"
               "?range=2Y&period=Daily" % cand)
        try:
            r = sess.get(url, timeout=20)
            ct = r.headers.get("Content-Type", "")
            if r.status_code != 200 or "json" not in ct and not r.text.lstrip().startswith("{"):
                continue
            rows = (r.json() or {}).get("data") or []
            if len(rows) < 200:
                continue
            df = pd.DataFrame([{
                "Open": x.get("o"), "High": x.get("h"), "Low": x.get("l"),
                "Close": x.get("c"), "Volume": x.get("v"),
            } for x in rows], index=pd.to_datetime([x["t"] for x in rows]))
            n = _norm(df)
            if n is not None:
                return "stockanalysis", n
        except Exception:
            continue
    return "FAIL", None


def fetch_one(sym, sess):
    for attempt in range(3):
        try:
            status, df = fetch_yahoo(sym, sess)
        except Exception:
            status, df = "FAIL", None
        if status == "RATE_LIMIT":
            wait = 2 ** attempt * 2 + np.random.uniform(0, 1)
            time.sleep(wait)
            continue
        if df is not None:
            return df, "yahoo"
        break
    df, src = None, "FAIL"
    try:
        status, df = fetch_stockanalysis(sym, sess)
        if df is not None:
            src = "stockanalysis"
    except Exception:
        pass
    return df, src


def assert_fresh(cache, min_coverage=0.80, max_lag_days=4):
    """Fail-closed: refuse to persist a cache whose last bar is stale.
    SPY is the market calendar (handles holidays without a hardcoded list)."""
    spy = cache.get("SPY")
    if spy is None or len(spy) == 0:
        raise RuntimeError("缓存缺少 SPY，无法判定市场日历")
    last = spy.index[-1].date()
    lag = (date.today() - last).days
    if lag > max_lag_days:
        raise RuntimeError("SPY 最后一根 %s 距今 %d 自然日（阈值 %d），疑似行情未刷新"
                           % (last, lag, max_lag_days))
    same = sum(1 for df in cache.values()
               if df is not None and len(df) and df.index[-1].date() == last)
    cov = same / max(1, len(cache))
    if cov < min_coverage:
        raise RuntimeError("仅 %.1f%% 标的末根与 SPY 同日（阈值 %.0f%%），拒绝写入混合陈旧缓存"
                           % (cov * 100, min_coverage * 100))
    print("OK freshness: last_bar=%s lag=%dd coverage=%.1f%% (%d/%d)"
          % (last, lag, cov * 100, same, len(cache)))
    return str(last)


def main():
    force = "--force" in sys.argv
    need_assert = "--assert-fresh" in sys.argv
    cache = load_cache()
    universe = build_universe()
    print("宇宙总数:", len(universe), "| 缓存已有:", len(cache),
          "| assert_fresh:", need_assert)

    since = days_since_refresh()
    need_full = (force or not os.path.exists(CACHE_PATH)
                 or since is None or since > FRESH_DAYS)
    if need_full:
        targets = universe
        print("全量刷新（force=%s, pkl缺失=%s, 距上次全量=%s天）"
              % (force, not os.path.exists(CACHE_PATH), since))
    else:
        targets = [t for t in universe if t not in cache]
        if targets:
            print("增量模式：仅抓取缺失的 %d 只" % len(targets))
        else:
            print("缓存完整且新鲜（上次全量 %s 天前），无需更新。" % since)
            if need_assert:
                assert_fresh(cache)
            return

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})

    ok, fail = 0, 0
    sources = {}
    for i, sym in enumerate(targets):
        df, src = fetch_one(sym, sess)
        if df is None:
            fail += 1
        else:
            cache[sym] = df
            ok += 1
            sources[src] = sources.get(src, 0) + 1
        time.sleep(0.2)
        if (i + 1) % 50 == 0:
            print("  进度 %d/%d | 成功 %d 失败 %d | 源 %s"
                  % (i + 1, len(targets), ok, fail, sources))
            sys.stdout.flush()

    print("本次抓取: 成功 %d / 失败 %d (目标 %d) | 来源 %s"
          % (ok, fail, len(targets), sources))

    if ok == 0:
        print("[FATAL] 本次未抓到任何数据，保留旧缓存，放弃写入")
        sys.exit(2)
    if need_full and ok < max(10, int(0.3 * len(targets))):
        print("[FATAL] 全量刷新成功率过低，保留旧缓存，放弃本次写入")
        sys.exit(2)

    if need_assert:
        try:
            last_bar = assert_fresh(cache)
        except RuntimeError as e:
            print("[FATAL] 新鲜度断言失败: %s" % e)
            sys.exit(2)
        with open(os.path.join(RESULT_DIR, "cache_data_date.txt"), "w") as f:
            f.write(last_bar)

    os.makedirs(RESULT_DIR, exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(cache, f)
    os.replace(tmp, CACHE_PATH)
    if need_full:
        with open(FRESH_FILE, "w") as f:
            f.write(date.today().strftime("%Y-%m-%d"))
    print("已保存缓存 ->", CACHE_PATH, "| 总标的:", len(cache))


if __name__ == "__main__":
    main()
