#!/usr/bin/env python3
# 重建 VCP 本地价缓存（DAILY，1y）—— 绕开 Yahoo 匿名 bulk 限流
# 直接用 chart API 单只拉取，带 429 退避；产出 数据/vcp_cache.pkl（供 vcp_screener 离线使用）
import requests, time, os, sys, pickle
import pandas as pd
import numpy as np

VCP_DIR = "/Users/a1/Claude/VCP"
RESULT_DIR = os.path.join(VCP_DIR, "数据")
CACHE_PATH = os.path.join(RESULT_DIR, "vcp_cache.pkl")

# 标的宇宙：SP500 + SP400 + SPY（基准）
syms = []
for f in ["sp500.csv", "sp400.csv"]:
    p = os.path.join(VCP_DIR, f)
    if os.path.exists(p):
        with open(p) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("^") and "S&P" not in s and s != "Symbol":
                    syms.append(s)
if "SPY" not in syms:
    syms.append("SPY")
# 去重保序
seen = set(); syms = [s for s in syms if not (s in seen or seen.add(s))]
print("待抓取 ticker 数:", len(syms))

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else len(syms)
syms = syms[:LIMIT]

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

cache = {}
ok = 0
fail = 0
for i, sym in enumerate(syms):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
    attempt = 0
    while attempt < 4:
        try:
            r = sess.get(url, timeout=25)
            if r.status_code == 429:
                wait = 2 ** attempt * 3 + np.random.uniform(0, 2)
                print(f"    ⏳ {sym} 429 限流，{wait:.0f}s 后重试 ({attempt+1}/4)")
                time.sleep(wait); attempt += 1; continue
            if r.status_code != 200:
                fail += 1; break
            d = r.json()["chart"]["result"][0]
            t = d["timestamp"]
            q = d["indicators"]["quote"][0]
            df = pd.DataFrame({
                "Open": q["open"], "High": q["high"], "Low": q["low"],
                "Close": q["close"], "Volume": q["volume"]
            }, index=pd.to_datetime(t, unit="s"))
            df = df.dropna(subset=["Close"])
            if len(df) < 200:   # 数据不足 1 年视为失败
                fail += 1; break
            cache[sym] = df
            ok += 1; break
        except Exception as e:
            fail += 1; break
    time.sleep(0.25)
    if (i + 1) % 50 == 0:
        print(f"  进度 {i+1}/{len(syms)} | 成功 {ok} 失败 {fail}")
        sys.stdout.flush()

print(f"完成: 成功 {ok} / 失败 {fail} (共 {len(syms)})")
os.makedirs(RESULT_DIR, exist_ok=True)
with open(CACHE_PATH, "wb") as f:
    pickle.dump(cache, f)
print("已保存缓存 ->", CACHE_PATH)
