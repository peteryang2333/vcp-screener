#!/bin/bash
# ============================================================
#  VCP Sentinel Pro - 一键安装脚本
#  基于 EMMA019/US-stocks 改造，面向最活跃 100 强美股
#  功能: 网络检测 + VCP扫描 + 桌面结果保存 + 每日定时
# ============================================================

set -e

RESULT_DIR="$HOME/Desktop/VCP_扫描结果"
TARGET_DIR="$HOME/Desktop/VCP_SentinelPro"

echo "=========================================="
echo "  📦 VCP Sentinel Pro 安装中..."
echo "=========================================="

# ---------- 1. 检测网络 ----------
echo ""
echo "  [1/5] 检测网络连接..."
for site in google.com github.com finance.yahoo.com; do
    if ping -c 1 -t 3 "$site" &>/dev/null; then
        echo "    ✅ $site 可达"
    else
        echo "    ❌ $site 不可达 - 请检查 VPN/代理"
    fi
done

# ---------- 2. 安装 Python 依赖 ----------
echo ""
echo "  [2/5] 安装 Python 依赖..."
pip3 install -q yfinance pandas requests streamlit plotly 2>/dev/null || \
pip3 install --user -q yfinance pandas requests streamlit plotly 2>/dev/null || true
echo "    ✅ 依赖安装完成"

# ---------- 3. 下载项目 ----------
echo ""
echo "  [3/5] 下载 EMMA019/US-stocks..."

if [ -d "$TARGET_DIR" ]; then
    echo "    ⚠️  目录已存在，更新中..."
    cd "$TARGET_DIR" && git pull 2>/dev/null || true
else
    cd "$HOME/Desktop"
    git clone --depth 1 https://github.com/EMMA019/US-stocks.git VCP_SentinelPro
fi

cd "$TARGET_DIR"
echo "    ✅ 项目已下载到 $TARGET_DIR"

# ---------- 4. 打补丁 ----------
echo ""
echo "  [4/5] 应用补丁..."

# 创建 custom 目录
mkdir -p "$TARGET_DIR/custom"

# ---- 4a. 网络检测模块 ----
cat > "$TARGET_DIR/custom/network_check.py" << 'NETEOF'
"""网络连通性检测"""
import requests
import sys

def check_network():
    sites = [
        ("Google", "https://www.google.com"),
        ("YouTube", "https://www.youtube.com"),
        ("Yahoo", "https://finance.yahoo.com"),
        ("GitHub", "https://github.com"),
    ]
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = None
    sess.headers.update({"User-Agent": "Mozilla/5.0"})

    print("  [网络检测] 测试以下站点...")
    all_ok = True
    for name, url in sites:
        try:
            r = sess.get(url, timeout=5)
            status = "OK" if r.status_code < 400 else "HTTP %d" % r.status_code
            print("    %-10s [%s]" % (name, status))
        except Exception as e:
            reason = str(e)
            if "resolve" in reason.lower() or "dns" in reason.lower():
                reason = "DNS 解析失败"
            elif "timeout" in reason.lower():
                reason = "连接超时"
            elif "proxy" in reason.lower() or "tunnel" in reason.lower():
                reason = "代理拦截"
            else:
                reason = reason.split(".")[0][:40]
            print("    %-10s ❌ %s" % (name, reason))
            all_ok = False

    if not all_ok:
        print("\n  ⚠️  部分站点无法访问，请检查 VPN/代理/网络后重试。")
        return False
    print("  ✅ 网络正常\n")
    return True

if __name__ == "__main__":
    sys.exit(0 if check_network() else 1)
NETEOF
echo "    ✅ network_check.py 已创建"

# ---- 4b. 创建最活跃100强扫描器（独立增强版）- ----
cat > "$TARGET_DIR/custom/vcp_scanner_most_active.py" << 'SCANEOF'
"""
VCP 扫描器 — 最活跃 100 强版
基于 yfinance 的 screener API 获取当日最活跃股票 + VCP 检测
"""

import os
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy']:
    os.environ.pop(k, None)

import yfinance as yf
import pandas as pd
import warnings
from datetime import datetime
from . import network_check

warnings.filterwarnings('ignore')

TIGHT_DAYS = 5
TIGHTNESS_LIMIT = 0.10
VOL_RATIO = 0.75
MIN_PRICE = 2.0
MIN_VOLUME = 100000
MIN_DATA_DAYS = 60

def get_most_active(limit=100):
    """Yahoo Finance screener — 当日最活跃美股"""
    try:
        data = yf.screen('most_actives', size=limit,
                         sortField='dayvolume', sortAsc=False)
        if not data or 'quotes' not in data:
            return []
        return [q['symbol'] for q in data['quotes']
                if q.get('symbol') and q['symbol'] != '^GSPC']
    except Exception as e:
        print("  Screener 失败: %s" % e)
        return []

def scan_batch(tickers):
    """批量下载 + VCP 筛选"""
    if not tickers:
        return []

    joined = ' '.join(tickers)
    raw = yf.download(joined, period="6mo", group_by='ticker',
                      auto_adjust=True, progress=False)

    results = []
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = raw
            elif isinstance(raw.columns, pd.MultiIndex):
                df = raw[ticker]
            else:
                continue

            df = df.dropna()
            if len(df) < MIN_DATA_DAYS:
                continue

            close = df['Close'].squeeze()
            high = df['High'].squeeze()
            low = df['Low'].squeeze()
            vol = df['Volume'].squeeze()

            lc = float(close.iloc[-1])
            lv = float(vol.iloc[-1])
            if lc < MIN_PRICE or lv < MIN_VOLUME:
                continue

            sma50 = close.rolling(50).mean()
            vol_avg = vol.rolling(50).mean()
            h5 = high.rolling(TIGHT_DAYS).max()
            l5 = low.rolling(TIGHT_DAYS).min()

            sma50_v = float(sma50.iloc[-1])
            vol_avg_v = float(vol_avg.iloc[-1])
            h5_v = float(h5.iloc[-1])
            l5_v = float(l5.iloc[-1])

            if lc <= sma50_v or l5_v <= 0 or vol_avg_v <= 0:
                continue
            amplitude = (h5_v - l5_v) / l5_v
            if amplitude > TIGHTNESS_LIMIT:
                continue
            vol_ratio = lv / vol_avg_v
            if vol_ratio >= VOL_RATIO:
                continue

            results.append({
                '代码': ticker,
                '当前价格': round(lc, 2),
                '50日均线': round(sma50_v, 2),
                '5日振幅%%': round(amplitude * 100, 2),
                '缩量比例%%': round(vol_ratio * 100, 2),
                '突破挂单价': round(h5_v, 2),
                '距突破%%': round((h5_v / lc - 1) * 100, 2),
            })
        except Exception:
            continue

    return results

def run_scan():
    """主入口：网络检测 → 最活跃100 → VCP 扫描 → 输出"""
    if not network_check.check_network():
        return []

    all_tickers = get_most_active(100)
    if not all_tickers:
        print("❌ 无法获取活跃名单")
        return []

    print("\n📊 扫描 %d 只标的..." % len(all_tickers))
    all_found = []
    batch_size = 50
    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i:i+batch_size]
        print("  第%d批 (%d只)..." % (i//batch_size+1, len(batch)))
        found = scan_batch(batch)
        for r in found:
            all_found.append(r)
            print("  ✅ %s: 振幅%s%% 缩量%s%%" % (r['代码'], r['5日振幅%%'], r['缩量比例%%']))

    return all_found


if __name__ == "__main__":
    results = run_scan()
    print("\n" + "=" * 60)
    if results:
        df = pd.DataFrame(results).sort_values('距突破%%')
        print("\n🎯 发现 %d 只 VCP 形态标的：\n" % len(results))
        print(df.to_string(index=False))
    else:
        print("👀 今日无符合 VCP 形态的标的")
    print("=" * 60)
SCANEOF
echo "    ✅ vcp_scanner_most_active.py 已创建"

# ---- 4c. 修改 sentinel.py 插入网络检测 + 最活跃100获取 ----
SENTINEL="$TARGET_DIR/sentinel.py"
if [ -f "$SENTINEL" ]; then
    cp "$SENTINEL" "$SENTINEL.bak" 2>/dev/null || true

    python3 -c "
path = '$SENTINEL'
with open(path) as f:
    c = f.read()

if 'network_check' not in c:
    c = c.replace(
        'import pandas as pd',
        'import pandas as pd\nimport sys\nsys.path.insert(0, \"custom\")\nfrom network_check import check_network'
    )
    c = c.replace(
        'def main():',
        'def get_most_active_tickers():\n'
        '    import yfinance as yf\n'
        '    try:\n'
        '        data = yf.screen(\"most_actives\", size=100, sortField=\"dayvolume\", sortAsc=False)\n'
        '        if data and \"quotes\" in data:\n'
        '            return [q[\"symbol\"] for q in data[\"quotes\"] if q.get(\"symbol\") and q[\"symbol\"] != \"^GSPC\"]\n'
        '    except Exception as e:\n'
        '        print(\"Screener:\", e)\n'
        '    return []\n\n'
        'def main():\n'
        '    print(\"\\n[网络检测] 启动前检查连通性...\")\n'
        '    if not check_network():\n'
        '        sys.exit(1)\n'
        '    print(\"[活跃池] 获取当日最活跃 100 强...\")\n'
        '    active = get_most_active_tickers()\n'
        '    if active:\n'
        '        print(\"获取到 %d 只标的: %s\\n\" % (len(active), \", \".join(active[:5])))\n'
    )

    with open(path, 'w') as f:
        f.write(c)
    print('    ✅ sentinel.py 补丁完成')
    "
else
    echo "    ⚠️  sentinel.py 未找到，跳过补丁"
fi

# ---- 4d. 创建每日运行包装脚本 ----
cat > "$TARGET_DIR/run_daily.sh" << 'RUNEOF'
#!/bin/bash
# VCP Sentinel 每日运行包装脚本
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy NO_PROXY no_proxy

RESULT_DIR="$HOME/Desktop/VCP_扫描结果"
mkdir -p "$RESULT_DIR"
OUTPUT_FILE="$RESULT_DIR/vcp_$(date +%Y%m%d).txt"

cd "$HOME/Desktop/VCP_SentinelPro"

echo "========================================================================"
echo "  VCP 扫描器 | $(date '+%Y-%m-%d %H:%M')"
echo "  数据源: Yahoo Finance (yfinance)"
echo "========================================================================

" > "$OUTPUT_FILE"

# 运行自定义扫描器（最活跃100强版）
python3 -c "
import sys
sys.path.insert(0, '.')
from custom.vcp_scanner_most_active import run_scan
results = run_scan()
import pandas as pd
print()
print('=' * 60)
if results:
    df = pd.DataFrame(results).sort_values('距突破%%')
    print('\n🎯 发现 %d 只 VCP 形态标的：\n' % len(results))
    print(df.to_string(index=False))
    print()
    print('💡 距突破%% 越接近 0 越好，放量突破挂单价时考虑介入')
else:
    print('\n👀 今日活跃池中无符合 VCP 形态的标的')
print('=' * 60)
" 2>&1 | tee -a "$OUTPUT_FILE"

echo "" >> "$OUTPUT_FILE"
echo "--- 运行时间: $(date '+%Y-%m-%d %H:%M:%S %Z') ---" >> "$OUTPUT_FILE"

# 更新最新链接
ln -sf "$OUTPUT_FILE" "$RESULT_DIR/最新.txt"
RUNEOF

chmod +x "$TARGET_DIR/run_daily.sh"
echo "    ✅ run_daily.sh 已创建"

# ---------- 5. 安装 crontab 定时任务 ----------
echo ""
echo "  [5/5] 安装定时任务 (每天 5:30 AM 北京时间)..."

TMP_CRON=$(mktemp)
crontab -l > "$TMP_CRON" 2>/dev/null || true

# 删除旧版本
if grep -q "VCP_Sentinel\|VCP_DailyScan" "$TMP_CRON" 2>/dev/null; then
    sed -i '' '/VCP_Sentinel\|VCP_DailyScan/d' "$TMP_CRON"
    echo "    🔄 已移除旧版本"
fi

# 写入新任务
echo "30 5 * * 2-6 /bin/bash $TARGET_DIR/run_daily.sh # VCP_DailyScan" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"
echo "    ✅ 定时任务已安装"

# ---------- 完成 ----------
echo ""
echo "=========================================="
echo "  🎉 VCP Sentinel Pro 安装完成！"
echo "=========================================="
echo ""
echo "  📂 项目位置: $TARGET_DIR"
echo "  📂 桌面结果: $RESULT_DIR/"
echo "     ├── vcp_20260612.txt    ← 每日结果"
echo "     └── 最新.txt            ← 快捷方式"
echo ""
echo "  手动运行:"
echo "    bash $TARGET_DIR/run_daily.sh"
echo ""
echo "  查看仪表盘 (原版):"
echo "    cd $TARGET_DIR && streamlit run app.py"
echo ""
echo "  查看定时任务:"
echo "    crontab -l"
echo "  取消定时:"
echo "    crontab -e   (删掉 VCP_DailyScan 那行)"
echo ""
