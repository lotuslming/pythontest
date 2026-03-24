#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import csv
import argparse
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from datetime import timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    BEIJING_TZ = timezone(timedelta(hours=8))


IPV4_RE = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
IPV6_RE = re.compile(r'(?<![:\w])(?:[A-Fa-f0-9]{0,4}:){2,7}[A-Fa-f0-9]{0,4}(?![:\w])')


def extract_ips(text: str):
    """从文本中提取 IPv4/IPv6 地址，去重后返回。"""
    if not text:
        return []

    ips = []

    for ip in IPV4_RE.findall(text):
        parts = ip.split(".")
        if all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            ips.append(ip)

    for ip in IPV6_RE.findall(text):
        # 过滤掉明显不是 IPv6 的情况
        if ":" in ip and len(ip.replace(":", "")) > 0:
            ips.append(ip)

    # 去重并保持顺序
    seen = set()
    result = []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            result.append(ip)
    return result


def parse_address_field(msg, field_name):
    """解析发件人/收件人字段，返回 '姓名 <邮箱>' 或邮箱列表。"""
    values = msg.get_all(field_name, [])
    if not values:
        return ""

    addrs = getaddresses(values)
    formatted = []
    for name, addr in addrs:
        if name and addr:
            formatted.append(f"{name} <{addr}>")
        elif addr:
            formatted.append(addr)
        elif name:
            formatted.append(name)

    return "; ".join(formatted)


def parse_mail_datetime_to_beijing(msg):
    """解析 Date 头并转为北京时间。"""
    date_value = msg.get("Date", "")
    if not date_value:
        return ""

    try:
        dt = parsedate_to_datetime(date_value)
        if dt is None:
            return ""

        # 如果原始时间没有时区，尽量按 UTC 处理
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        bj_dt = dt.astimezone(BEIJING_TZ)
        return bj_dt.strftime("%Y-%m-%d %H:%M:%S %z")
    except Exception:
        return ""


def get_received_headers(msg):
    """返回所有 Received 头，顺序与邮件头一致（通常最新的在前，最早的在后）。"""
    return msg.get_all("Received", [])


def extract_sender_ip(msg):
    """
    提取发件 IP：
    1. 优先 X-Originating-IP
    2. 再取最早一条 Received 中的第一个 IP
    """
    x_origin = msg.get("X-Originating-IP", "") or msg.get("X-Original-IP", "")
    if x_origin:
        ips = extract_ips(x_origin)
        if ips:
            return ips[0]

    received_list = get_received_headers(msg)
    if received_list:
        # 通常最后一条 Received 最接近发件源头
        earliest_received = received_list[-1]
        ips = extract_ips(earliest_received)
        if ips:
            return ips[0]

    return ""


def extract_receiver_ip(msg):
    """
    提取收件 IP：
    从最新一条 Received 中推断接收服务器 IP。
    一般最新一条 Received 在最前面。
    """
    received_list = get_received_headers(msg)
    if received_list:
        latest_received = received_list[0]
        ips = extract_ips(latest_received)
        if ips:
            return ips[0]
    return ""


def parse_eml_file(file_path):
    """解析单个 eml 文件，返回字典。"""
    with open(file_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    from_addr = parse_address_field(msg, "From")
    to_addr = parse_address_field(msg, "To")
    cc_addr = parse_address_field(msg, "Cc")
    bcc_addr = parse_address_field(msg, "Bcc")

    # 合并收件人
    recipients = "; ".join([x for x in [to_addr, cc_addr, bcc_addr] if x])

    beijing_time = parse_mail_datetime_to_beijing(msg)
    sender_ip = extract_sender_ip(msg)
    receiver_ip = extract_receiver_ip(msg)

    return {
        "文件路径": file_path,
        "发件人": from_addr,
        "收件人": recipients,
        "邮件时间_北京时间": beijing_time,
        "发件IP": sender_ip,
        "收件IP": receiver_ip,
    }


def scan_eml_files(root_dir):
    """递归扫描目录下所有 .eml 文件。"""
    eml_files = []
    for current_root, _, files in os.walk(root_dir):
        for filename in files:
            if filename.lower().endswith(".eml"):
                eml_files.append(os.path.join(current_root, filename))
    return eml_files


def write_csv(rows, output_csv):
    """写入 CSV 文件。"""
    fieldnames = ["文件路径", "发件人", "收件人", "邮件时间_北京时间", "发件IP", "收件IP"]

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="批量读取目录及子目录中的 EML 邮件，并导出收发件信息到 CSV")
    parser.add_argument("input_dir", help="包含 .eml 邮件的目录")
    parser.add_argument("output_csv", help="输出 CSV 文件路径")
    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"输入目录不存在：{args.input_dir}")
        return

    eml_files = scan_eml_files(args.input_dir)
    if not eml_files:
        print("未找到任何 .eml 文件")
        return

    rows = []
    for file_path in eml_files:
        try:
            row = parse_eml_file(file_path)
            rows.append(row)
        except Exception as e:
            rows.append({
                "文件路径": file_path,
                "发件人": "",
                "收件人": "",
                "邮件时间_北京时间": "",
                "发件IP": "",
                "收件IP": f"解析失败: {e}",
            })

    write_csv(rows, args.output_csv)
    print(f"处理完成，共 {len(eml_files)} 封邮件，结果已写入：{args.output_csv}")


if __name__ == "__main__":
    main()
