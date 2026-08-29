#!/bin/bash
# VCP Screener 多市场每日运行脚本
# 兼容 Mac 本地与 GitHub Actions 云端

# 遇到错误立即退出，绝不向 Git 推送残缺数据
set -e 

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy

MARKET="${1:-all}"
POOL="${2:-sp900}"  
FAST="${3:-}"       

# ====== 🚀 修复核心 1：使用动态相对路径 ======
VCP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULT_DIR="$VCP_DIR/数据"
TRACKER="$VCP_DIR/vcp_tracker.py"
mkdir -p "$RESULT_DIR"

# 🚀 修复核心 2：确保环境依赖完整
pip3 install requests pandas lxml scipy yfinance -q 2>/dev/null || true

# 如果 SP 900 模式且本地没有 CSV，自动从 Wikipedia 下载并缓存
if [ "$POOL" = "sp900" ]; then
  if [ ! -f "$VCP_DIR/sp500.csv" ] || [ ! -f "$VCP_DIR/sp400.csv" ]; then
    echo "📥 发现缺少股票池文件，正在从 Wikipedia 下载 SP 500 / SP 400 成分股列表..."

    /usr/bin/python3 -c "
import requests as req, pandas as pd, os
from io import StringIO
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def save_wiki(url, fpath, col='Symbol'):
    try:
        r = req.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        tables = pd.read_html(StringIO(r.text))
        for t in tables:
            if col in t.columns:
                tickers = t[col].dropna().astype(str).str.replace('.', '-').str.strip().tolist()
                tickers = [s for s in tickers if s and not s.startswith('^') and 'S&P' not in s]
                with open(fpath, 'w') as f:
                    for sym in tickers:
                        f.write(sym + '\n')
                print('      ✅ 保存 %d 只到 %s' % (len(tickers), os.path.basename(fpath)))
                return True
        print('      ⚠️ 未找到 %s 列的表格' % col)
    except Exception as e:
        print('      ❌ 失败: %s' % e)
    return False

dir = '$VCP_DIR'
save_wiki('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', dir + '/sp500.csv')
save_wiki('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', dir + '/sp400.csv')
" 2>&1

    if [ -f "$VCP_DIR/sp500.csv" ] && [ -s "$VCP_DIR/sp500.csv" ]; then
      echo "  ✅ sp500.csv: $(wc -l < "$VCP_DIR/sp500.csv") 只"
    fi
  else
      echo "  ✅ 已检测到本地 sp500/sp400.csv 缓存，跳过抓取。"
  fi
fi

# 🚀 修复核心 4：扫描前自动刷新本地价缓存（增量；超过 FRESH_DAYS 自动全量）
# 避免缓存冻结导致持续 0 命中（2026-08 曾因此停更）
echo "🔄 刷新本地价缓存 (build_vcp_cache.py) ..."
/usr/bin/python3 "$VCP_DIR/build_vcp_cache.py" >/dev/null 2>&1 && echo "  ✅ 缓存已刷新" || echo "  ⚠️ 缓存刷新失败，沿用旧缓存继续扫描"

# 映射市场到文件标签
case "$MARKET" in
  us) TAG="US" ;;
  jp) TAG="JP" ;;
  kr) TAG="KR" ;;
  all) TAG="" ;;
esac

if [ "$MARKET" = "all" ]; then
  echo "=========================================="
  echo "  🌏 多市场 VCP 扫描 | $(date '+%Y-%m-%d %H:%M')"
  echo "=========================================="

  for m in us jp kr; do
    case $m in
      us) label="US" ; name="🇺🇸 美股" ;;
      jp) label="JP" ; name="🇯🇵 日本" ;;
      kr) label="KR" ; name="🇰🇷 韩国" ;;
    esac

    OUTFILE="$RESULT_DIR/vcp_${label}_$(date +%Y%m%d).txt"
    echo "" | tee -a "$OUTFILE"
    echo ">>> $name <<<" | tee -a "$OUTFILE"

    /usr/bin/python3 "$VCP_DIR/vcp_screener.py" --market "$m" --pool "$POOL" $FAST 2>&1 | tee -a "$OUTFILE"
    echo "" >> "$OUTFILE"
    echo "--- 运行时间: $(date '+%Y-%m-%d %H:%M:%S %Z') ---" >> "$OUTFILE"
    
    # 🚀 修复核心 3：硬拷贝生成 Markdown 报告
    if [ "$m" = "us" ]; then
        cp "$OUTFILE" "$VCP_DIR/最新分析报告.md"
        echo "  📝 已生成美股 最新分析报告.md"
        /usr/bin/python3 "$VCP_DIR/gen_latest_us.py" 2>&1 | tail -2
        echo "  📝 已刷新 最新_US.txt（每日提醒读取用）"
    fi

    # 记录到跟踪表
    /usr/bin/python3 "$TRACKER" --scan-all 2>/dev/null
  done

  echo ""
  echo "=========================================="
  echo "  ✅ 全部市场扫描完成"
  echo "=========================================="
else
  OUTFILE="$RESULT_DIR/vcp_${TAG}_$(date +%Y%m%d).txt"
  /usr/bin/python3 "$VCP_DIR/vcp_screener.py" --market "$MARKET" --pool "$POOL" $FAST 2>&1 | tee "$OUTFILE"
  echo "" >> "$OUTFILE"
  echo "--- 运行时间: $(date '+%Y-%m-%d %H:%M:%S %Z') ---" >> "$OUTFILE"
  
  if [ "$MARKET" = "us" ]; then
      cp "$OUTFILE" "$VCP_DIR/最新分析报告.md"
      /usr/bin/python3 "$VCP_DIR/gen_latest_us.py" 2>&1 | tail -2
      echo "  📝 已刷新 最新_US.txt（每日提醒读取用）"
  fi

  # 记录到跟踪表
  /usr/bin/python3 "$TRACKER" --scan-all 2>/dev/null
fi
