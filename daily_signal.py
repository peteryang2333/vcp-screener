#!/usr/bin/env python3
"""每日 VCP 信号：运行扫描器并将结果写入 result.txt（可选邮件推送）

由 .github/workflows/daily-signal.yml 调用。原来工作流引用了并不存在的
daily_signal.py 导致 CI 直接失败，这里补齐它：复用 vcp_screener.py 的扫描逻辑，
输出 result.txt 供工作流提交；若配置了 SMTP 凭据则顺带发邮件。
"""
import os
import sys
import subprocess
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "result.txt")


def main():
    market = os.environ.get("MARKET", "us")
    cmd = [
        sys.executable,
        os.path.join(REPO, "vcp_screener.py"),
        "--market", market,
        "--pool", "sp900",
    ]
    print(">>> 运行: %s" % " ".join(cmd))
    with open(OUT, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)

    size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    print("已生成 %s (%d 字节)" % (OUT, size))

    # 可选：邮件推送（仅在 4 个 SMTP 环境变量齐全时才发送）
    sender = os.environ.get("SENDER_EMAIL")
    password = os.environ.get("SENDER_PASSWORD")
    receiver = os.environ.get("RECEIVER_EMAIL")
    server = os.environ.get("SMTP_SERVER")
    if sender and password and receiver and server:
        try:
            with open(OUT, encoding="utf-8") as f:
                body = f.read()
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = "VCP 每日信号 %s" % datetime.now().strftime("%Y-%m-%d")
            msg["From"] = sender
            msg["To"] = receiver
            with smtplib.SMTP(server, 587, timeout=20) as s:
                s.starttls()
                s.login(sender, password)
                s.sendmail(sender, [receiver], msg.as_string())
            print("邮件已发送至 %s" % receiver)
        except Exception as e:
            print("邮件发送失败（不影响结果文件）: %s" % e)
    else:
        print("未配置邮件凭据，跳过推送")


if __name__ == "__main__":
    main()
