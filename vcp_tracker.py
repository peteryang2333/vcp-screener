#!/usr/bin/env python3
"""
VCP 信号跟踪器
每次扫描结果自动记录到跟踪表，便于回测验证策略有效性
"""

import os
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY',
          'ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:
    os.environ.pop(k, None)

import pandas as pd
import sys
from datetime import datetime

TRACKER_FILE = os.path.expanduser("~/Claude/VCP/数据/VCP_信号跟踪表.csv")
COLUMNS = [
    '信号日期', '市场', '代码', '当前价格', '50日均线',
    '5日振幅%', '缩量比例%', '突破挂单价', '距突破%',
    '记录日期'
]


def load_tracker():
    """加载已有跟踪表"""
    try:
        df = pd.read_csv(TRACKER_FILE)
        # 去重键
        df['_key'] = df['信号日期'].astype(str) + '_' + df['市场'].astype(str) + '_' + df['代码'].astype(str)
        return df
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=COLUMNS + ['_key'])


def parse_results_file(filepath, market_tag):
    """解析结果文件，提取VCP信号"""
    signals = []
    try:
        with open(filepath) as f:
            content = f.read()
    except FileNotFoundError:
        return signals

    # 解析文本表格 — 找"🎯"之后的数据行
    lines = content.split('\n')
    in_results = False
    header_line = None

    for i, line in enumerate(lines):
        if '🎯' in line and '发现' in line and '只' in line:
            in_results = True
            continue
        if in_results:
            # 跳过空行和分隔线
            if not line.strip() or line.startswith('---') or line.startswith('==='):
                continue
            # 找表头行
            if '代码' in line and '当前价格' in line:
                header_line = line.strip()
                continue
            # 数据行：包含股票代码和数字
            if header_line and line.strip() and not line.startswith('💡'):
                parts = line.strip().split()
                if len(parts) >= 6 and any(c.isdigit() for c in parts[0]):
                    signals.append(parts)
                    continue
        # 重置
        if in_results and (line.startswith('=') or line.startswith('💡')):
            in_results = False

    # 如果上面解析失败，用更简单的方法：找"代码"和"当前价格"开头的行
    if not signals:
        lines_clean = [l.strip() for l in lines if l.strip()
                       and not l.startswith('=')
                       and not l.startswith('---')
                       and not l.startswith('💡')
                       and not l.startswith('🎯')
                       and not l.startswith('⚠')
                       and not l.startswith('---')]
        for i, line in enumerate(lines_clean):
            if line.startswith('代码') and '当前价格' in line:
                # 下一行开始是数据
                for data_line in lines_clean[i+1:]:
                    parts = data_line.split()
                    if len(parts) >= 6:
                        # 检查是否有股票代码特征
                        if any(c.isdigit() for c in parts[0]) or '.' in parts[0]:
                            signals.append(parts)
                        else:
                            break
                    else:
                        break

    result = []
    for parts in signals:
        try:
            row = {
                '代码': parts[0],
                '当前价格': float(parts[1]) if '.' in parts[1] else int(parts[1]),
                '50日均线': float(parts[2]) if '.' in parts[2] else int(parts[2]),
                '5日振幅%': float(parts[3].replace('%', '')),
                '缩量比例%': float(parts[4].replace('%', '')),
                '突破挂单价': float(parts[5]) if '.' in parts[5] else int(parts[5]),
                '距突破%': float(parts[6].replace('%', '')),
            }
            result.append(row)
        except (ValueError, IndexError):
            continue

    return result


def append_signals(market_tag, signals, signal_date):
    """追加信号到跟踪表"""
    if not signals:
        return 0

    df_existing = load_tracker()
    date_str = signal_date.strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    new_count = 0
    new_rows = []
    for s in signals:
        key = '%s_%s_%s' % (date_str, market_tag, s['代码'])
        if key in df_existing['_key'].values:
            continue  # 已存在，跳过

        new_rows.append({
            '信号日期': date_str,
            '市场': market_tag,
            '代码': s['代码'],
            '当前价格': s['当前价格'],
            '50日均线': s['50日均线'],
            '5日振幅%': s['5日振幅%'],
            '缩量比例%': s['缩量比例%'],
            '突破挂单价': s['突破挂单价'],
            '距突破%': s['距突破%'],
            '记录日期': now_str,
            '_key': key,
        })
        new_count += 1

    if new_rows:
        df_new = pd.DataFrame(new_rows)
        df_all = pd.concat([df_existing, df_new], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=['_key'], keep='last')
        df_all = df_all[COLUMNS]  # 去掉_key列
        df_all = df_all.sort_values(['信号日期', '市场', '距突破%'])
        df_all.to_csv(TRACKER_FILE, index=False)
        print("  ✅ 跟踪表已更新: 新增 %d 条记录" % new_count)
    else:
        print("  📎 无新信号，跟踪表不变")

    return new_count


def review_tracker():
    """显示跟踪表内容"""
    df = load_tracker()
    if df.empty:
        print("跟踪表为空")
        return

    df = df.sort_values(['信号日期', '市场', '距突破%'])
    pd.set_option('display.max_columns', 15)
    pd.set_option('display.width', 150)
    pd.set_option('display.max_rows', 100)

    print("\n" + "=" * 90)
    print("  📊 VCP 信号跟踪总表（共 %d 条记录）" % len(df))
    print("=" * 90)
    print(df.to_string(index=False))
    print("=" * 90)
    print("  保存位置: %s" % TRACKER_FILE)
    print()


def get_market_tag(filename):
    """从文件名判断市场"""
    fn = filename.replace('.txt', '')
    if fn.startswith('vcp_JP'): return 'JP'
    if fn.startswith('vcp_KR'): return 'KR'
    if fn.startswith('vcp_'): return 'US'
    return None


def get_file_date(filename):
    """从文件名提取日期"""
    fn = filename.replace('.txt', '')
    try:
        if fn.startswith('vcp_JP_'):
            return datetime.strptime(fn.replace('vcp_JP_', ''), '%Y%m%d')
        if fn.startswith('vcp_KR_'):
            return datetime.strptime(fn.replace('vcp_KR_', ''), '%Y%m%d')
        if fn.startswith('vcp_'):
            return datetime.strptime(fn.replace('vcp_', ''), '%Y%m%d')
    except ValueError:
        return None
    return None


def scan_old_results():
    """扫描已有结果文件，一次性补录历史信号"""
    data_dir = os.path.expanduser("~/Claude/VCP/数据")

    total = 0
    for root, dirs, files in os.walk(data_dir):
        for f in sorted(files):
            if not f.endswith('.txt') or f.startswith('最新') or f.startswith('VCP'):
                continue

            filepath = os.path.join(root, f)
            market_tag = get_market_tag(f)
            file_date = get_file_date(f)

            if market_tag is None or file_date is None:
                continue

            signals = parse_results_file(filepath, market_tag)
            if signals:
                n = append_signals(market_tag, signals, file_date)
                total += n

    if total > 0:
        print("\n  📊 历史信号补录完成，共新增 %d 条" % total)
    return total


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--review':
        review_tracker()
    elif len(sys.argv) > 1 and sys.argv[1] == '--scan-all':
        scan_old_results()
    else:
        print("用法:")
        print("  python3 vcp_tracker.py --scan-all   # 扫描历史结果并补录")
        print("  python3 vcp_tracker.py --review     # 查看跟踪表")
