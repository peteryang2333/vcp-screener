#!/bin/bash
# VCP Screener 每日运行脚本
# 清除所有代理设置，直连雅虎财经

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy

# 创建专用文件夹
RESULT_DIR="$HOME/Desktop/VCP_扫描结果"
mkdir -p "$RESULT_DIR"

# 带日期的输出文件
OUTPUT_FILE="$RESULT_DIR/vcp_$(date +%Y%m%d).txt"

/usr/bin/python3 "$HOME/Desktop/vcp_screener.py" 2>&1 | tee "$OUTPUT_FILE"

echo "" >> "$OUTPUT_FILE"
echo "--- 运行时间: $(date '+%Y-%m-%d %H:%M:%S %Z') ---" >> "$OUTPUT_FILE"

# 同时更新最新链接（方便快速打开）
ln -sf "$OUTPUT_FILE" "$RESULT_DIR/最新.txt"
