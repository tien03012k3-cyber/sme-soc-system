#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SME SOC - Windows CVE & Software Inventory Agent
Tự động quét danh mục phần mềm đã cài đặt trên Windows và gửi báo cáo về Máy chủ SOC để đối chiếu lỗ hổng CVE.
"""

import sys
import os
import json
import socket
import argparse
import time
import urllib.request
import urllib.error

# Danh sách URL máy chủ SOC (ưu tiên IP LAN, fallback về VPS Public)
SOC_SERVERS = [
    "http://192.168.21.136:8888",
    "http://70.153.83.137"
]

def get_installed_apps():
    """Đọc danh sách phần mềm từ Windows Registry siêu tốc (<0.1s)"""
    apps = []
    seen = set()

    if sys.platform != "win32":
        # Giả lập cho môi trường non-windows (nếu chạy test)
        return [
            {"name": "WinRAR 6.22 (x64)", "version": "6.22.0", "publisher": "win.rar GmbH"},
            {"name": "Notepad++ (64-bit x64)", "version": "8.5.6", "publisher": "Notepad++ Team"},
            {"name": "Git", "version": "2.44.0", "publisher": "The Git Development Community"}
        ]

    import winreg
    reg_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
    ]

    for root, subkey in reg_keys:
        try:
            with winreg.OpenKey(root, subkey) as key:
                num_subkeys = winreg.QueryInfoKey(key)[0]
                for i in range(num_subkeys):
                    try:
                        name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, name) as sub:
                            try:
                                disp, _ = winreg.QueryValueEx(sub, "DisplayName")
                            except:
                                continue

                            if not disp or not str(disp).strip():
                                continue

                            ver = ""
                            try:
                                ver, _ = winreg.QueryValueEx(sub, "DisplayVersion")
                            except:
                                pass

                            pub = ""
                            try:
                                pub, _ = winreg.QueryValueEx(sub, "Publisher")
                            except:
                                pass

                            item_key = f"{disp}_{ver}".lower()
                            if item_key not in seen:
                                seen.add(item_key)
                                apps.append({
                                    "name": str(disp).strip(),
                                    "version": str(ver).strip(),
                                    "publisher": str(pub).strip()
                                })
                    except:
                        continue
        except:
            continue

    return apps

def get_local_ip():
    """Lấy IP cục bộ của máy trạm Windows"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.21.153"

def send_cve_report(apps, client_ip=None, hostname=None):
    """Gửi danh sách phần mềm lên máy chủ SOC"""
    if not client_ip:
        client_ip = get_local_ip()
    if not hostname:
        hostname = os.environ.get("COMPUTERNAME", socket.gethostname())

    payload = {
        "client_ip": client_ip,
        "hostname": hostname,
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_apps": len(apps),
        "apps": apps
    }

    data = json.dumps(payload).encode("utf-8")
    success = False
    last_err = ""

    for srv in SOC_SERVERS:
        url = f"{srv}/api/cve/report"
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as res:
                if res.status == 200:
                    body = json.loads(res.read().decode("utf-8"))
                    print(f"✅ Đã gửi báo cáo thành công tới SOC: {url}")
                    return body
        except Exception as e:
            last_err = str(e)
            continue

    print(f"❌ Không thể kết nối tới máy chủ SOC. Lỗi: {last_err}")
    return None

def main():
    parser = argparse.ArgumentParser(description="SME SOC Windows CVE Scanner Agent")
    parser.add_argument("--demo", action="store_true", help="Gửi kèm phần mềm mẫu dính CVE (WinRAR 6.22, PuTTY 0.80) để kiểm thử")
    parser.add_argument("--watch", type=int, default=0, help="Chạy chế độ giám sát ngầm, quét lại sau mỗi N giây (mặc định 0: chạy 1 lần)")
    args = parser.parse_args()

    print("=" * 65)
    print("🛡️  SME SOC - WINDOWS CVE & SOFTWARE INVENTORY AGENT")
    print("=" * 65)

    client_ip = get_local_ip()
    hostname = os.environ.get("COMPUTERNAME", socket.gethostname())
    print(f"💻 Máy trạm: {hostname} | IP: {client_ip}")

    while True:
        print("\n🔍 Đang rà soát phần mềm đã cài đặt trên Windows...")
        apps = get_installed_apps()
        print(f"📊 Đã tìm thấy {len(apps)} phần mềm/dịch vụ.")

        if args.demo:
            print("🧪 [CHẾ ĐỘ KIỂM THỬ] Thêm 2 ứng dụng mẫu có lỗ hổng CVE nghiêm trọng:")
            print("   -> WinRAR phiên bản 6.22.0 (Dính CVE-2023-38831, CVSS 7.8 - HIGH)")
            print("   -> PuTTY phiên bản 0.80 (Dính CVE-2024-31497, CVSS 8.1 - HIGH)")
            apps.insert(0, {"name": "WinRAR 6.22 (64-bit)", "version": "6.22.0", "publisher": "win.rar GmbH"})
            apps.insert(1, {"name": "PuTTY release 0.80", "version": "0.80", "publisher": "Simon Tatham"})

        print("📡 Đang gửi danh mục phần mềm về Trung tâm điều hành SOC...")
        res = send_cve_report(apps, client_ip, hostname)

        if res and res.get("status") == "ok":
            v_cnt = res.get("vulnerabilities_found", 0)
            stats = res.get("stats", {})
            print(f"🎯 Kết quả đối chiếu CVE từ SOC:")
            print(f"   - Tổng phần mềm kiểm tra: {len(apps)}")
            print(f"   - Lỗ hổng phát hiện: {v_cnt}")
            print(f"   - 🔴 Critical: {stats.get('critical', 0)} | 🟠 High: {stats.get('high', 0)} | 🟡 Medium: {stats.get('medium', 0)}")
            
            vulns = res.get("vulnerabilities", [])
            if vulns:
                print("\n⚠️  DANH SÁCH LỖ HỔNG PHÁT HIỆN TRÊN MÁY BẠN:")
                for v in vulns:
                    print(f"   • [{v.get('severity')}] {v.get('app')} (v{v.get('version')})")
                    print(f"     Mã: {v.get('cve')} | CVSS: {v.get('cvss')}")
                    print(f"     Mô tả: {v.get('description')}")
                    print(f"     Khắc phục: {v.get('recommendation')}\n")
            else:
                print("   ✅ Không phát hiện lỗ hổng CVE nguy hiểm nào trên máy tính.")
        
        if args.watch <= 0:
            break
        print(f"⏳ Chờ {args.watch} giây trước lần rà soát tiếp theo...")
        time.sleep(args.watch)

if __name__ == "__main__":
    main()
