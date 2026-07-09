#!/usr/bin/env python3
"""
VCP 扫描器 - 快速测试脚本
测试依赖和基本功能
"""

import sys

print("=" * 70)
print("  VCP 扫描器 - 环境检测和快速测试")
print("=" * 70)

# 1. 检查 Python 版本
print("\n✅ Python 版本:", sys.version.split()[0])

# 2. 检查依赖
print("\n📦 检查依赖...\n")
deps = {
    'yfinance': '>=0.34',
    'pandas': '>=2.0',
    'lxml': '>=4.9',
    'requests': '>=2.31',
}

all_ok = True
for pkg, required in deps.items():
    try:
        mod = __import__(pkg)
        version = getattr(mod, '__version__', 'unknown')
        print(f"  ✅ {pkg:<15} {version}")
    except ImportError as e:
        print(f"  ❌ {pkg:<15} 未安装")
        all_ok = False

if not all_ok:
    print("\n⚠️  有缺失的依赖，正在安装...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                   capture_output=True)
    print("  ✅ 安装完成\n")

# 3. 测试网络连接
print("🌐 网络连接测试...\n")
import requests as req
sess = req.Session()
sess.trust_env = False
sess.proxies = None
sess.headers.update({"User-Agent": "Mozilla/5.0"})

test_sites = [
    ("Yahoo Finance", "https://finance.yahoo.com"),
]

for name, url in test_sites:
    try:
        r = sess.get(url, timeout=5)
        if r.status_code < 400:
            print(f"  ✅ {name:<20} 可访问")
        else:
            print(f"  ⚠️  {name:<20} HTTP {r.status_code}")
    except Exception as e:
        print(f"  ❌ {name:<20} {str(e)[:40]}")

# 4. 快速功能测试
print("\n📊 快速功能测试...\n")
try:
    import yfinance as yf
    import pandas as pd
    
    # 下载单支股票最近一个月数据
    print("  正在下载 AAPL 最近 30 天数据作为测试...")
    data = yf.download("AAPL", period="1mo", progress=False)
    
    if len(data) > 0:
        print(f"  ✅ 成功获取 {len(data)} 行数据")
        print(f"     最新收盘价: ${data['Close'].iloc[-1]:.2f}")
        print(f"     成交量: {int(data['Volume'].iloc[-1]):,}")
    else:
        print("  ❌ 获取数据失败")
        
except Exception as e:
    print(f"  ❌ 测试失败: {e}")

print("\n" + "=" * 70)
print("✅ 测试完成！现在可以运行实际扫描了")
print("=" * 70)
print("\n运行方式:")
print("  1. 单市场: python3 vcp_screener.py --market us --pool sp500")
print("  2. 快速模式: python3 vcp_screener.py --fast")
print("  3. 运行脚本: bash run_vcp_screener.sh")
print("=" * 70)
