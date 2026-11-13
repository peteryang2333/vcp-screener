#!/usr/bin/env python3
# 生成 results/最新.txt（早报任务说明 step1.1 读取的 VCP 信号文件）
#
# 2026-11-14 修复：`VCP 扫描器 v3 | YYYY-MM-DD` 原先写脚本运行日，
# 缓存刷新失败沿用 T-2/T-3 旧价时仍自称当天，早报第一步之二的新鲜度闸门
# 因此永远放行。现在该行 = 价缓存最后一根（数据日），另列生成日。
import os
import vcp_screener as v
from vcp_data_date import cache_data_date

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "最新.txt")
DATA_DATE = cache_data_date() or v.datetime.now().strftime("%Y-%m-%d")
GEN_DATE = v.datetime.now().strftime("%Y-%m-%d")

print("获取股票池 (SP500+SP400) ...")
tickers = v.get_sp900_tickers()
print("  共 %d 只" % len(tickers))

print("运行 VCP 扫描（缓存模式）...")
found = v.scan_vcp(tickers, "US")
found.sort(key=lambda x: x["距突破%"])
print("  命中 %d 只" % len(found))

lines = []
lines.append("======================================================================")
lines.append("SP500+SP400 VCP 信号 (sp900)")
lines.append("======================================================================")
lines.append("")
lines.append("  VCP 扫描器 v3 | %s" % DATA_DATE)
lines.append("  生成日: %s" % GEN_DATE)
lines.append("  数据口径: 上一行日期为价缓存最后一根（最近一个已完成的美东交易日），非脚本运行日")
lines.append("  数据源: 本地价缓存 | 市场: us | 股票池: sp900 (SP500+SP400) | 命中: %d 只" % len(found))
lines.append("")
if found:
    lines.append("  VCP 形态标的（按距突破%升序，越靠前越接近突破）：")
    lines.append("")
    lines.append("| VCP分 | 代码 | 当前价格 | RS评级 | 收缩% | 5日振幅% | 缩量比例% | 突破挂单价 | 距突破% | 距52周高% | 10EMA | 21EMA | 吊灯止损 | ATR止损 |")
    lines.append("|------|------|---------|-------|-------|---------|---------|-----------|--------|---------|-------|-------|---------|--------|")
    for c in found:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            c["VCP分"], c["代码"], c["当前价格"], c["RS评级"], c["收缩%"],
            c["5日振幅%"], c["缩量比例%"], c["突破挂单价"], c["距突破%"], c["距52周高%"],
            c["10EMA"], c["21EMA"], c["吊灯止损"], c["硬止损价"],
        ))
else:
    lines.append("  无符合 VCP 形态的标的（缩量基底尚未成型）。")

with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print("已写入 %s | 数据日 %s 生成日 %s" % (OUT, DATA_DATE, GEN_DATE))
