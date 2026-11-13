#!/usr/bin/env python3
"""VCP 信号结果回填（P1，2026-11-14 新建）。

项目跑了 5 个月，VCP_信号跟踪表.csv 却只有 103 行、停在 6-25，且没有
「后来涨没涨」这一列 —— 系统从没验证过自己推荐的票。本脚本补上闭环：

  数据/vcp_US_*.txt（历史扫描）+ 数据/最新_US.txt（当日）
      -> 数据/vcp_signals.jsonl（去重信号台账）
      -> 用 数据/vcp_cache.pkl 真实价格回填 T+5/T+10/T+20、突破触发、-8% 止损、SPY 超额
      -> 数据/VCP_结果回填.csv + 数据/vcp_outcome_summary.json + 数据/vcp_outcomes.md

设计原则：只做只读核算与落盘，不改筛选逻辑、不下单；数据不足标 pending，
绝不编造价格。rolling 60 日连续 4 周无超额 -> 自动给出「仅观察」结论，
供日报正文 1 行引用，避免把观察清单当买入清单。
"""
import csv
import glob
import json
import os
import pickle
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta, timezone

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "数据")
CACHE = os.path.join(DATA, "vcp_cache.pkl")
LEDGER = os.path.join(DATA, "vcp_signals.jsonl")
CSV_OUT = os.path.join(DATA, "VCP_结果回填.csv")
JSON_OUT = os.path.join(DATA, "vcp_outcome_summary.json")
MD_OUT = os.path.join(DATA, "vcp_outcomes.md")

FIXED = re.compile(
    r"^\s*([123])\s+([A-Z][A-Z0-9\-\.]{0,6})\s+([\d\.]+)\s+(\d+)\s+"
    r"([\d\./\-]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+"
    r"([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s*$")


def parse_archive(path):
    """固定宽度扫描结果 -> 信号列表。文件名日期 = 运行日（历史口径）。"""
    stem = os.path.basename(path)
    m = re.search(r"(\d{8})", stem)
    if not m:
        return []
    d = m.group(1)
    sig_date = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
    out = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        g = FIXED.match(line.rstrip())
        if not g:
            continue
        x = g.groups()
        try:
            out.append({"date": sig_date, "ticker": x[1], "score": int(x[0]),
                        "price": float(x[2]), "rs": int(x[3]),
                        "breakout": float(x[7]), "dist": float(x[8]),
                        "dist_52w": float(x[9]), "ema21": float(x[11]),
                        "date_basis": "archive_run_date", "source": stem})
        except (ValueError, IndexError):
            continue
    return out


def parse_latest(path):
    """markdown 表格 数据/最新_US.txt，扫描日 = 价缓存数据日（新口径）。"""
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    m = re.search(r"扫描日:\s*(\d{4}-\d{2}-\d{2})", text)
    sig_date = m.group(1) if m else date.today().isoformat()
    out = []
    for line in text.splitlines():
        if not line.startswith("|") or "VCP分" in line or "---" in line:
            continue
        c = [x.strip() for x in line.strip("|").split("|")]
        if len(c) < 15:
            continue
        try:
            out.append({"date": sig_date, "ticker": c[1], "score": int(c[0]),
                        "price": float(c[2]), "rs": int(c[3]),
                        "breakout": float(c[7]), "dist": float(c[8]),
                        "dist_52w": float(c[9]), "ema21": float(c[12]),
                        "date_basis": "cache_data_date", "source": "最新_US.txt"})
        except (ValueError, IndexError):
            continue
    return out


def import_signals():
    sigs = list(parse_latest(os.path.join(DATA, "最新_US.txt")))
    for p in sorted(glob.glob(os.path.join(DATA, "vcp_US_*.txt"))):
        sigs.extend(parse_archive(p))
    seen, unique = set(), []
    for s in sigs:
        k = (s["date"], s["ticker"])
        if k not in seen:
            seen.add(k)
            unique.append(s)
    unique.sort(key=lambda x: (x["date"], x["ticker"]))
    with open(LEDGER, "w", encoding="utf-8") as f:
        for s in unique:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print("信号台账: %d 条（去重后），日期 %s ~ %s"
          % (len(unique), unique[0]["date"] if unique else "-",
             unique[-1]["date"] if unique else "-"))
    return unique


def backfill(sigs):
    if not os.path.exists(CACHE):
        raise RuntimeError("缺少价缓存 %s，无法回填" % CACHE)
    D = pickle.load(open(CACHE, "rb"))
    spy = D.get("SPY")
    data_last = str(spy.index[-1].date()) if spy is not None and len(spy) else "UNKNOWN"

    def spy_fwd(dt, n):
        if spy is None:
            return None
        i = spy.index.searchsorted(pd.Timestamp(dt))
        j = i + n
        if j >= len(spy):
            return None
        return (float(spy["Close"].iloc[j]) / float(spy["Close"].iloc[i]) - 1) * 100

    rows = []
    for s in sigs:
        df = D.get(s["ticker"])
        rec = dict(s)
        rec.update({"status": "pending", "r5": None, "r10": None, "r20": None,
                    "spy20": None, "excess20": None, "breakout_hit": None,
                    "stop_hit": None, "entry": None})
        if df is None or len(df) < 30:
            rows.append(rec)
            continue
        i = df.index.searchsorted(pd.Timestamp(s["date"]))
        if i >= len(df) - 1:
            rows.append(rec)
            continue
        entry = float(df["Close"].iloc[i])
        rec["entry"] = round(entry, 4)
        j = i + 20
        if j >= len(df):
            # 未满 20 日：给出已有窗口的短周期结果，20 日仍标 pending
            for n in (5, 10):
                k = i + n
                if k < len(df):
                    rec["r%d" % n] = round((float(df["Close"].iloc[k]) / entry - 1) * 100, 2)
            rows.append(rec)
            continue
        seg = df.iloc[i + 1:j + 1]
        rec["status"] = "complete"
        for n in (5, 10, 20):
            rec["r%d" % n] = round((float(df["Close"].iloc[i + n]) / entry - 1) * 100, 2)
        rec["spy20"] = round(spy_fwd(s["date"], 20), 2) if spy_fwd(s["date"], 20) is not None else None
        if rec["spy20"] is not None:
            rec["excess20"] = round(rec["r20"] - rec["spy20"], 2)
        rec["breakout_hit"] = bool(float(seg["High"].max()) >= s["breakout"])
        rec["stop_hit"] = bool(float(seg["Low"].min()) <= entry * 0.92)
        rows.append(rec)

    cols = ["date", "ticker", "score", "rs", "dist", "price", "entry", "breakout",
            "dist_52w", "ema21", "r5", "r10", "r20", "spy20", "excess20",
            "breakout_hit", "stop_hit", "status", "date_basis", "source"]
    with open(CSV_OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows, data_last


def summarise(rows, data_last):
    done = [r for r in rows if r["status"] == "complete" and r["excess20"] is not None]
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    roll = [r for r in done if r["date"] >= cutoff]

    def stats(rs, label):
        if len(rs) < 8:
            return {"label": label, "n": len(rs), "status": "样本不足"}
        ex = [r["excess20"] for r in rs]
        return {"label": label, "n": len(rs),
                "avg_r20": round(statistics.mean(r["r20"] for r in rs), 2),
                "avg_excess20": round(statistics.mean(ex), 2),
                "median_excess20": round(statistics.median(ex), 2),
                "win_rate_pct": round(sum(1 for x in ex if x > 0) / len(ex) * 100, 1),
                "breakout_hit_pct": round(sum(1 for r in rs if r["breakout_hit"]) / len(rs) * 100, 1),
                "stop_hit_pct": round(sum(1 for r in rs if r["stop_hit"]) / len(rs) * 100, 1)}

    by_score = [stats([r for r in roll if r["score"] == s], "VCP分=%d" % s)
                for s in (1, 2, 3)]
    by_rs = [stats([r for r in roll if lo <= r["rs"] < hi], lab)
             for lo, hi, lab in ((0, 30, "RS<30"), (30, 50, "RS 30-49"),
                                 (50, 70, "RS 50-69"), (70, 101, "RS>=70"))]

    weekly = defaultdict(list)
    for r in done:
        try:
            d = date.fromisoformat(r["date"])
            weekly["%s-W%02d" % (d.isocalendar()[0], d.isocalendar()[1])].append(r["excess20"])
        except Exception:
            pass
    wk = sorted((w, statistics.mean(v)) for w, v in weekly.items() if len(v) >= 5)
    streak = 0
    for _, v in reversed(wk):
        if v <= 0:
            streak += 1
        else:
            break

    base = stats(roll, "rolling_60d")
    if base.get("status") == "样本不足" or base.get("n", 0) < 50:
        verdict, reason = "证据不足", "滚动 60 日可评估样本不足 50 条，不足以判断有效性"
    elif base["avg_excess20"] <= 0 and streak >= 4:
        verdict, reason = "仅观察", "滚动 60 日平均超额为负且连续 %d 周无超额" % streak
    elif base["avg_excess20"] <= 0:
        verdict, reason = "仅观察", "滚动 60 日平均超额为负（%.2f%%）" % base["avg_excess20"]
    else:
        verdict, reason = "有超额证据（样本内）", "滚动 60 日平均超额 %+.2f%%，仍须样本外持续验证" % base["avg_excess20"]

    one_liner = ("VCP 池近 60 日 n=%d，20 日超额 %+.2f%%，胜率 %.1f%% → %s"
                 % (base.get("n", 0), base.get("avg_excess20", 0),
                    base.get("win_rate_pct", 0), verdict))
    return {
        "schema": "vcp_outcomes/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cache_last_bar": data_last,
        "signal_date_basis": "历史 vcp_US_*.txt 用文件名运行日；2026-11-14 起 最新_US.txt 用价缓存数据日",
        "total_signals": len(rows),
        "complete": len(done),
        "pending": len(rows) - len(done),
        "rolling_60d": base,
        "by_score": by_score,
        "by_rs": by_rs,
        "weeks_without_excess": streak,
        "verdict": verdict,
        "verdict_reason": reason,
        "one_liner": one_liner,
        "caveats": "窗口重叠、未计交易成本、单一区间样本；为诊断性核算，不构成投资建议",
    }


def write_md(s):
    b = s["rolling_60d"]
    lines = [
        "# VCP 信号结果回填 · rolling 60 日",
        "",
        "- 生成：%s" % s["generated_at_utc"],
        "- 价缓存最后一根：%s" % s["cache_last_bar"],
        "- 台账 %d 条 / 可评估 %d 条 / 待成熟 %d 条" % (s["total_signals"], s["complete"], s["pending"]),
        "",
        "| 指标 | 值 |",
        "|---|---|",
        "| 20 日平均收益 | %s |" % b.get("avg_r20", "样本不足"),
        "| 20 日平均超额(vs SPY) | %s |" % b.get("avg_excess20", "样本不足"),
        "| 超额胜率 | %s%% |" % b.get("win_rate_pct", "-"),
        "| 20 日内触及突破价 | %s%% |" % b.get("breakout_hit_pct", "-"),
        "| 20 日内触及 -8%% 止损 | %s%% |" % b.get("stop_hit_pct", "-"),
        "| 连续无超额周数 | %d |" % s["weeks_without_excess"],
        "| 结论 | **%s**（%s） |" % (s["verdict"], s["verdict_reason"]),
        "",
        "## 按 VCP 分",
        "",
        "| 分组 | n | 平均超额 | 胜率 |",
        "|---|---|---|---|",
    ]
    for x in s["by_score"]:
        lines.append("| %s | %s | %s | %s |" % (x["label"], x["n"],
                     x.get("avg_excess20", "-"), x.get("win_rate_pct", "-")))
    lines += ["", "## 按 RS 分档", "", "| 分组 | n | 平均超额 | 胜率 |", "|---|---|---|---|"]
    for x in s["by_rs"]:
        lines.append("| %s | %s | %s | %s |" % (x["label"], x["n"],
                     x.get("avg_excess20", "-"), x.get("win_rate_pct", "-")))
    lines += ["", "> %s" % s["caveats"],
              "", "> 信号仅供参考，是否操作由你本人决策、风险自担。", ""]
    open(MD_OUT, "w", encoding="utf-8").write("\n".join(lines))


def main():
    os.makedirs(DATA, exist_ok=True)
    sigs = import_signals()
    rows, data_last = backfill(sigs)
    s = summarise(rows, data_last)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    write_md(s)
    print("回填完成: complete=%d pending=%d | %s" % (s["complete"], s["pending"], s["one_liner"]))


if __name__ == "__main__":
    main()
