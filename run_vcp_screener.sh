#!/bin/bash
# VCP Screener 多市场每日运行脚本
# 支持: US(美股) JP(日本) KR(韩国)
# 用法: bash run_vcp_screener.sh [market]
#       market: us / jp / kr / all（默认all）

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy

MARKET="${1:-all}"
POOL="${2:-sp900}"  # 默认 SP900，可指定 active
FAST="${3:-}"       # 第三参数: -f / --fast 快速模式（跳过 Trend Template）
VCP_DIR="$HOME/Claude/VCP"
RESULT_DIR="$VCP_DIR/数据"
TRACKER="$VCP_DIR/vcp_tracker.py"
mkdir -p "$RESULT_DIR"

# 如果 SP 900 模式且本地没有 CSV，自动从 Wikipedia 下载并缓存
if [ "$POOL" = "sp900" ]; then
  if [ ! -f "$VCP_DIR/sp500.csv" ] || [ ! -f "$VCP_DIR/sp400.csv" ]; then
    echo "📥 下载 SP 500 / SP 400 成分股列表..."

    # 安装依赖（一次性）
    pip3 install lxml -q 2>/dev/null || true

    # 从 Wikipedia 抓取并保存为本地 CSV
    # 🔧 修复: pd.read_html 直接请求 Wikipedia 被 403 封禁，改为 requests + StringIO
    /usr/bin/python3 -c "
import requests as req, pandas as pd, os
from io import StringIO
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

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
    if [ -f "$VCP_DIR/sp400.csv" ] && [ -s "$VCP_DIR/sp400.csv" ]; then
      echo "  ✅ sp400.csv: $(wc -l < "$VCP_DIR/sp400.csv") 只"
    else
      echo "  ⚠️ sp400.csv 获取失败，仅用 S&P 500"
    fi
  fi
fi

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
    ln -sf "$OUTFILE" "$RESULT_DIR/最新_${label}.txt"

    # 记录到跟踪表
    /usr/bin/python3 "$TRACKER" --scan-all 2>/dev/null
  done

  echo ""
  echo "=========================================="
  echo "  ✅ 全部市场扫描完成"
  ls -lh "$RESULT_DIR"/vcp_*_$(date +%Y%m%d).txt 2>/dev/null
  echo "=========================================="
else
  OUTFILE="$RESULT_DIR/vcp_${TAG}_$(date +%Y%m%d).txt"
  /usr/bin/python3 "$VCP_DIR/vcp_screener.py" --market "$MARKET" --pool "$POOL" $FAST 2>&1 | tee "$OUTFILE"
  echo "" >> "$OUTFILE"
  echo "--- 运行时间: $(date '+%Y-%m-%d %H:%M:%S %Z') ---" >> "$OUTFILE"
  ln -sf "$OUTFILE" "$RESULT_DIR/最新_${TAG}.txt"

  # 记录到跟踪表
  /usr/bin/python3 "$TRACKER" --scan-all 2>/dev/null
fi
