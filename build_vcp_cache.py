#!/usr/bin/env python3
# 重建/增量更新 VCP 本地价缓存（DAILY, 1y）—— 绕开 Yahoo 匿名 bulk 限流
# 直接用 chart API 单只拉取，带 429 退避；产出 数据/vcp_cache.pkl
# （dict[ticker]=DataFrame[OHLCV]，datetime 索引），供 vcp_screener 离线使用。
#
# 更新策略：
#   - 默认增量：仅抓取「缓存中缺失」的标的（如新加入的 ADR）。
#   - 当缓存不存在 / --force / 超过 FRESH_DAYS 天时，对全宇宙做全量刷新。
#   - 全量刷新成功后写入；若几乎全失败（如 Yahoo 全挂），保留旧缓存，不覆盖。
#   - 路径相对脚本所在目录，可在 CI (ubuntu) 与本机通用。
import requests, time, os, sys, pickle
from datetime import datetime, date
import pandas as pd
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(SCRIPT_DIR, "数据")
CACHE_PATH = os.path.join(RESULT_DIR, "vcp_cache.pkl")
FRESH_FILE = os.path.join(RESULT_DIR, "cache_refresh.txt")  # 记录上次全量刷新日期
FRESH_DAYS = 7  # 超过该天数触发全量刷新


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
    syms = [s for s in syms if not (s in seen or seen.add(s))]
    return syms


force = "--force" in sys.argv
cache = load_cache()
universe = build_universe()
print("宇宙总数:", len(universe), "| 缓存已有:", len(cache))


def days_since_refresh():
    """读取上次全量刷新日期（提交进 git，避免 CI checkout 重置 mtime 误判新鲜度）"""
    if not os.path.exists(FRESH_FILE):
        return None
    try:
        d = datetime.strptime(open(FRESH_FILE).read().strip(), "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


since = days_since_refresh()
need_full = force or (not os.path.exists(CACHE_PATH)) or (since is None) or (since > FRESH_DAYS)
if need_full:
    targets = universe
    print("全量刷新（force=%s, pkl缺失=%s, 距上次全量=%s天）" % (force, not os.path.exists(CACHE_PATH), since))
else:
    targets = [t for t in universe if t not in cache]
    if targets:
        print("增量模式：仅抓取缺失的 %d 只" % len(targets))
    else:
        print("缓存完整且新鲜（上次全量 %s 天前），无需更新。退出。" % since)
        sys.exit(0)

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

ok = 0
fail = 0
for i, sym in enumerate(targets):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1y&interval=1d" % sym
    attempt = 0
    while attempt < 4:
        try:
            r = sess.get(url, timeout=25)
            if r.status_code == 429:
                wait = 2 ** attempt * 3 + np.random.uniform(0, 2)
                print("    ⏳ %s 429 限流，%.0fs 后重试 (%d/4)" % (sym, wait, attempt + 1))
                time.sleep(wait)
                attempt += 1
                continue
            if r.status_code != 200:
                fail += 1
                break
            d = r.json()["chart"]["result"][0]
            t = d["timestamp"]
            q = d["indicators"]["quote"][0]
            df = pd.DataFrame({
                "Open": q["open"], "High": q["high"], "Low": q["low"],
                "Close": q["close"], "Volume": q["volume"]
            }, index=pd.to_datetime(t, unit="s"))
            df = df.dropna(subset=["Close"])
            if len(df) < 200:   # 数据不足 1 年视为失败
                fail += 1
                break
            cache[sym] = df
            ok += 1
            break
        except Exception:
            fail += 1
            break
    time.sleep(0.25)
    if (i + 1) % 50 == 0:
        print("  进度 %d/%d | 成功 %d 失败 %d" % (i + 1, len(targets), ok, fail))
        sys.stdout.flush()

print("本次抓取: 成功 %d / 失败 %d (目标 %d)" % (ok, fail, len(targets)))

# 安全：未抓到任何数据则保留旧缓存
if ok == 0:
    print("⚠️ 本次未抓到任何数据，保留旧缓存，放弃写入")
    sys.exit(1)
# 全量刷新时若成功率过低（如 Yahoo 全挂），保留旧缓存，不覆盖
if need_full and ok < max(10, int(0.3 * len(targets))):
    print("⚠️ 全量刷新成功率过低，保留旧缓存，放弃本次写入")
    sys.exit(1)

os.makedirs(RESULT_DIR, exist_ok=True)
with open(CACHE_PATH, "wb") as f:
    pickle.dump(cache, f)
if need_full:
    with open(FRESH_FILE, "w") as f:
        f.write(date.today().strftime("%Y-%m-%d"))
print("已保存缓存 ->", CACHE_PATH, "| 总标的:", len(cache),
      (" | 已记录全量刷新日期 %s" % date.today()) if need_full else "")
