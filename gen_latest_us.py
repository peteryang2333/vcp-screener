#!/usr/bin/env python3
# 用本地价缓存跑 VCP 扫描，并把结果写成 数据/最新_US.txt（markdown 表格，距突破%升序）
import os
import vcp_screener as v

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "数据", "最新_US.txt")

print("获取股票池 (SP500+SP400) ...")
tickers = v.get_sp900_tickers()
print("  共 %d 只" % len(tickers))

print("运行 VCP 扫描（缓存模式，绕开 Yahoo）...")
found = v.scan_vcp(tickers, "US")
found.sort(key=lambda x: x["距突破%"])

print("  命中 %d 只 VCP 标的" % len(found))

header = "| VCP分 | 代码 | 当前价格 | RS评级 | 收缩% | 5日振幅% | 缩量比例% | 突破挂单价 | 距突破% | 距52周高% | 放量突破 | 10EMA | 21EMA | 吊灯止损 | ATR止损 |"
sep = "|------|------|---------|-------|-------|---------|---------|-----------|--------|---------|---------|-------|-------|---------|--------|"

lines = []
lines.append("# VCP 美股扫描结果（最新）")
lines.append("# 数据来源: 本地价缓存扫描（SP500+SP400，共 %d 只，绕过 Yahoo 匿名限流）" % len(tickers))
lines.append("# 扫描日: %s" % v.datetime.now().strftime("%Y-%m-%d"))
lines.append("# 列: VCP分 代码 当前价格 RS评级 收缩% 5日振幅% 缩量比例% 突破挂单价 距突破% 距52周高% 放量突破 10EMA 21EMA 吊灯止损 ATR止损")
lines.append("")
lines.append("命中 %d 只，按距突破百分比升序（越靠前越接近突破）：" % len(found))
lines.append("")
lines.append(header)
lines.append(sep)
for c in found:
    lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | | %s | %s | %s | %s |" % (
        c["VCP分"], c["代码"], c["当前价格"], c["RS评级"], c["收缩%"],
        c["5日振幅%"], c["缩量比例%"], c["突破挂单价"], c["距突破%"], c["距52周高%"],
        c["10EMA"], c["21EMA"], c["吊灯止损"], c["硬止损价"],
    ))

with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print("已写入 %s (%d 行)" % (OUT, len(lines)))
