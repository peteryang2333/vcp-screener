#!/usr/bin/env python3
"""单一真源：返回 VCP 价缓存「最后一根」的美东交易日。

2026-11-14 之前 gen_latest_us.py / gen_results_latest.py 都把 datetime.now()
写成「扫描日」，于是刷新失败沿用 T-2/T-3 旧价时，产物仍自称当天，
早报的新鲜度闸门因此形同虚设。此模块把「运行日」与「数据日」彻底分开。
"""
import os
import pickle

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "数据")
MARKER = os.path.join(DATA, "cache_data_date.txt")   # build_vcp_cache.py --assert-fresh 写入
CACHE = os.path.join(DATA, "vcp_cache.pkl")


def cache_data_date():
    if os.path.exists(MARKER):
        try:
            v = open(MARKER, encoding="utf-8").read().strip()
            if len(v) == 10 and v[4] == "-":
                return v
        except Exception:
            pass
    try:
        c = pickle.load(open(CACHE, "rb"))
        spy = c.get("SPY")
        if spy is not None and len(spy):
            return str(spy.index[-1].date())
        dates = [str(df.index[-1].date()) for df in c.values()
                 if df is not None and len(df)]
        if dates:
            from collections import Counter
            return Counter(dates).most_common(1)[0][0]
    except Exception:
        pass
    return None


if __name__ == "__main__":
    print(cache_data_date() or "UNKNOWN")
