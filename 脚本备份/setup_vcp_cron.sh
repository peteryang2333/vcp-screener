#!/bin/bash
# ============================================
# VCP Screener 每日定时任务 — 一键安装
# 支持: 🇺🇸 美股 + 🇯🇵 日本 + 🇰🇷 韩国
# 在 Mac 终端运行: bash ~/Desktop/VCP/脚本备份/setup_vcp_cron.sh
# ============================================

VCP_DIR="$HOME/Claude/VCP"
WRAPPER="$VCP_DIR/run_vcp_screener.sh"
RESULT_DIR="$VCP_DIR/数据"

echo "=========================================="
echo "  📦 VCP 多市场定时扫描器 安装中..."
echo "=========================================="

# 1. 确保执行权限
chmod +x "$WRAPPER" 2>/dev/null
echo "  ✅ 脚本权限已设置"

# 2. 添加到 crontab
TMP_CRON=$(mktemp)
crontab -l > "$TMP_CRON" 2>/dev/null

# 删除旧版本
if grep -q "VCP_DailyScan\|VCP_JP\|VCP_KR" "$TMP_CRON" 2>/dev/null; then
    sed -i '' '/VCP_DailyScan\|VCP_JP\|VCP_KR/d' "$TMP_CRON"
    echo "  🔄 已移除旧版本"
fi

# 写入新任务（北京时间）
cat >> "$TMP_CRON" << CRONEOF
# VCP 定时扫描
# 日韩: 15:00（收盘后立即跑）
0 15 * * 1-5 /bin/bash $WRAPPER jp # VCP_JP
30 15 * * 1-5 /bin/bash $WRAPPER kr # VCP_KR
# 美股: 5:30（收盘后跑）
30 5 * * 2-6 /bin/bash $WRAPPER us # VCP_US
CRONEOF

crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "  ✅ crontab 已更新"

# 3. 确保结果文件夹存在
mkdir -p "$RESULT_DIR"
echo "  ✅ 结果文件夹已创建: $RESULT_DIR"

# 4. 打印信息
echo ""
echo "=========================================="
echo "  🎉 VCP 多市场定时任务安装成功！"
echo "=========================================="
echo ""
echo "  ⏰ 运行时间表（北京时间）："
echo "    15:00 🇯🇵 日本东证（周一~五）"
echo "    15:30 🇰🇷 韩国KOSPI（周一~五）"
echo "    05:30 🇺🇸 美股（周二~六）"
echo ""
echo "  📂 ~/Claude/VCP/ 结构："
echo "     ├── vcp_screener.py"
echo "     ├── run_vcp_screener.sh"
echo "     ├── 数据/"
echo "     │   ├── vcp_US_20260616.txt    ← 美股结果"
echo "     │   ├── vcp_JP_20260616.txt    ← 日本结果"
echo "     │   ├── vcp_KR_20260616.txt    ← 韩国结果"
echo "     │   ├── 最新_US.txt            ← 各市场最新链接"
echo "     │   ├── 最新_JP.txt"
echo "     │   └── 最新_KR.txt"
echo "     ├── 脚本备份/"
echo "     └── 最新分析报告.md"
echo ""
echo "常用命令:"
echo "  crontab -l                                    # 查看定时任务"
echo "  bash ~/Claude/VCP/run_vcp_screener.sh all     # 手动跑全部三个市场"
echo "  bash ~/Claude/VCP/run_vcp_screener.sh jp      # 只跑日本"
echo "  bash ~/Claude/VCP/run_vcp_screener.sh kr      # 只跑韩国"
echo ""
