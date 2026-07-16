#!/usr/bin/env python3
"""
每日信号生成器 - 基于 VCP 扫描器结果生成交易信号
"""

import os
import sys
from datetime import datetime
import subprocess
import json

# 清除代理环境变量
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY',
          'ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:
    os.environ.pop(k, None)

def run_vcp_scan():
    """运行 VCP 扫描器"""
    print("=" * 70)
    print("  每日 VCP 信号 | %s" % datetime.now().strftime('%Y-%m-%d %H:%M'))
    print("=" * 70)
    
    # 运行 SP500 扫描
    print("\n📊 正在扫描 SP500...")
    result_sp500 = subprocess.run([sys.executable, 'vcp_screener.py', 
                                   '--market', 'us', '--pool', 'sp500'],
                                  capture_output=True, text=True)
    
    # 运行 SP400 扫描
    print("\n📊 正在扫描 SP400...")
    result_sp400 = subprocess.run([sys.executable, 'vcp_screener.py', 
                                   '--market', 'us', '--pool', 'sp400'],
                                  capture_output=True, text=True)
    
    # 保存结果
    with open('result.txt', 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("SP500 VCP 信号\n")
        f.write("=" * 70 + "\n")
        f.write(result_sp500.stdout)
        f.write("\n\n")
        f.write("=" * 70 + "\n")
        f.write("SP400 VCP 信号\n")
        f.write("=" * 70 + "\n")
        f.write(result_sp400.stdout)
    
    print("\n✅ 信号已保存到 result.txt")
    
    # 如果定义了邮件参数，发送邮件
    if all(os.getenv(k) for k in ['SENDER_EMAIL', 'SENDER_PASSWORD', 'RECEIVER_EMAIL', 'SMTP_SERVER']):
        try:
            send_email()
        except Exception as e:
            print(f"⚠️  邮件发送失败: {e}")

def send_email():
    """发送邮件"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    sender = os.getenv('SENDER_EMAIL')
    password = os.getenv('SENDER_PASSWORD')
    receiver = os.getenv('RECEIVER_EMAIL')
    smtp_server = os.getenv('SMTP_SERVER')
    
    print("\n📧 正在发送邮件...")
    
    with open('result.txt', 'r', encoding='utf-8') as f:
        body = f.read()
    
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = f"[VCP 信号] {datetime.now().strftime('%Y-%m-%d')}"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    with smtplib.SMTP(smtp_server, 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
    
    print("✅ 邮件已发送")

if __name__ == "__main__":
    run_vcp_scan()
