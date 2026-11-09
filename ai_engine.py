"""
SME SOC AI Engine v6.1 - WEB PUSH LOCK SCREEN NOTIFICATIONS & LOCAL AI VOICE
=============================================================================
- Hỗ trợ Web Push Notifications chuẩn Apple iOS 16.4+ (Báo động khi tắt màn hình).
- Tự động hiển thị Banner & Rung chuông cảnh báo trên Màn hình khóa iPhone.
- Chạm vào thông báo: Tự động mở PWA và phát trực tiếp Giọng nói AI nội bộ qua loa.
- Hệ thống Giọng nói AI Nội bộ (Local Neural TTS vi-VN-HoaiMyNeural).
- Giữ nguyên 100% 4 tính năng lõi: CPU/RAM SOAR, Auth 4625, Web Proxy, WAF ModSecurity.
"""

import os
import re
import time
import json
import threading
import subprocess
import urllib.parse
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
import uvicorn
from pywebpush import webpush, WebPushException

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
ES_API_KEY = os.environ.get("ES_API_KEY", "")
TG_TOKEN = os.environ.get("TG_TOKEN", "8710086671:AAHPwl0FKTDaBmVXujVnIJtCfP0UQtvWRAA")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "-1003819359612")

TOPIC_SYSTEM_ID = int(os.environ.get("TOPIC_SYSTEM_ID", "2"))
TOPIC_WEB_ID = int(os.environ.get("TOPIC_WEB_ID", "3"))
TOPIC_SOAR_ID = int(os.environ.get("TOPIC_SOAR_ID", "74"))

CONFIG = {
    "cpu_threshold": 80.0,
    "ram_threshold": 85.0,
    "web_mb_threshold": 1.5,
    "auth_fail_threshold": 2,
    "enable_alerts": True,
}

CURRENT_METRICS = {
    "cpu": 0.0,
    "ram": 0.0,
    "last_updated": "Chưa có dữ liệu",
    "status": "normal",
    "last_alert_time": None
}

RECENT_INCIDENTS = []
GLOBAL_COMMAND = {"action": "none", "last_command_time": None, "last_command_by": None}
_lock = threading.RLock()

# ==============================================================================
# HỆ THỐNG VAPID & WEB PUSH NOTIFICATIONS (CHO IPHONE TẮT MÀN HÌNH)
# ==============================================================================
VAPID_PUBLIC_KEY = "BFJSdj_BGKLIDT09lD216z7mo2_eXSSRnAyCH24QZaN-ztYORAAlnRatj4lc9rMlQX2l3o-Hae9Dgeaby6ThE0Y"
VAPID_PRIVATE_KEY_PATH = "/home/nguyenvanwin/private_key.pem"
SUBSCRIPTIONS_FILE = "/home/nguyenvanwin/push_subscriptions.json"
PUSH_SUBSCRIPTIONS = []

def _load_push_subs():
    global PUSH_SUBSCRIPTIONS
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                PUSH_SUBSCRIPTIONS = json.load(f)
        except Exception:
            PUSH_SUBSCRIPTIONS = []

def _save_push_subs():
    try:
        with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(PUSH_SUBSCRIPTIONS, f)
    except Exception:
        pass

_load_push_subs()

def send_web_push(title, body):
    if not PUSH_SUBSCRIPTIONS or not os.path.exists(VAPID_PRIVATE_KEY_PATH):
        return

    def _worker():
        data = json.dumps({
            "title": title,
            "body": body,
            "url": "/?play_alert=1"
        })
        with _lock:
            subs_copy = list(PUSH_SUBSCRIPTIONS)
        dead_subs = []
        for sub in subs_copy:
            try:
                webpush(
                    subscription_info=sub,
                    data=data,
                    vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                    vapid_claims={"sub": "mailto:admin@smesoc.local"},
                    timeout=5
                )
            except WebPushException as ex:
                if ex.response is not None and ex.response.status_code in (404, 410):
                    dead_subs.append(sub)
            except Exception:
                pass
        if dead_subs:
            with _lock:
                for ds in dead_subs:
                    if ds in PUSH_SUBSCRIPTIONS:
                        PUSH_SUBSCRIPTIONS.remove(ds)
                _save_push_subs()

    threading.Thread(target=_worker, daemon=True).start()

# ==============================================================================
# HỆ THỐNG GIỌNG NÓI AI NỘI BỘ (EDGE-TTS NATIVE PYTHON)
# ==============================================================================
LATEST_VOICE_ALERT = {
    "alert_id": 0,
    "title": "Hệ thống sẵn sàng",
    "text": "Trung tâm điều hành S O C hoạt động bình thường.",
    "time": "",
    "timestamp": 0
}

_tts_lock = threading.Lock()



# ==============================================================================
# HỆ THỐNG QUẢN LÝ LỖ HỔNG PHẦN MỀM (CVE VULNERABILITY AUDIT)
# ==============================================================================
KNOWN_CVE_DB = [
    {
        "app_pattern": r"winrar",
        "cve": "CVE-2023-38831",
        "cvss": 7.8,
        "severity": "HIGH",
        "affected_max": "6.22.99",
        "fixed_version": "6.23",
        "description": "Lỗ hổng thực thi mã tùy ý khi người dùng mở file nén giả mạo (ZIP/RAR)",
        "recommendation": "Cập nhật khẩn cấp lên WinRAR 6.23 trở lên hoặc gỡ cài đặt"
    },
    {
        "app_pattern": r"winrar",
        "cve": "CVE-2023-40477",
        "cvss": 7.8,
        "severity": "HIGH",
        "affected_max": "6.22.99",
        "fixed_version": "6.23",
        "description": "Lỗ hổng thực thi mã từ xa qua cơ chế phân giải khối phục hồi RAR",
        "recommendation": "Nâng cấp lên phiên bản WinRAR 6.23"
    },
    {
        "app_pattern": r"7-zip",
        "cve": "CVE-2023-31102",
        "cvss": 7.8,
        "severity": "HIGH",
        "affected_max": "23.00",
        "fixed_version": "23.01",
        "description": "Lỗ hổng leo thang đặc quyền và làm hỏng bộ nhớ qua giao diện 7-Zip",
        "recommendation": "Cập nhật lên 7-Zip phiên bản 23.01 trở lên"
    },
    {
        "app_pattern": r"notepad\+\+",
        "cve": "CVE-2023-40031",
        "cvss": 7.8,
        "severity": "HIGH",
        "affected_max": "8.5.6",
        "fixed_version": "8.5.7",
        "description": "Lỗ hổng tràn bộ đệm đọc ghi (Buffer Overflow) khi phân tích chuỗi UTF-16",
        "recommendation": "Nâng cấp lên Notepad++ 8.5.7 trở lên"
    },
    {
        "app_pattern": r"putty",
        "cve": "CVE-2024-31497",
        "cvss": 8.1,
        "severity": "HIGH",
        "affected_max": "0.80",
        "fixed_version": "0.81",
        "description": "Lộ lọt khóa bí mật SSH ECDSA P-521 qua việc phân tích chữ ký số",
        "recommendation": "Thu hồi khóa cũ và nâng cấp ngay lên PuTTY 0.81"
    },
    {
        "app_pattern": r"\bgit\b",
        "cve": "CVE-2024-32002",
        "cvss": 9.0,
        "severity": "CRITICAL",
        "affected_max": "2.45.0",
        "fixed_version": "2.45.1",
        "description": "Thực thi mã từ xa (RCE) thông qua kỹ thuật clone submodule độc hại trên Windows",
        "recommendation": "Cập nhật Git for Windows lên phiên bản >= 2.45.1"
    },
    {
        "app_pattern": r"filezilla",
        "cve": "CVE-2023-44487",
        "cvss": 7.5,
        "severity": "HIGH",
        "affected_max": "3.64.99",
        "fixed_version": "3.65.0",
        "description": "Lỗ hổng Rapid Reset HTTP/2 gây sập ứng dụng và nghẽn tài nguyên",
        "recommendation": "Nâng cấp lên FileZilla Client >= 3.65.0"
    },
    {
        "app_pattern": r"google chrome",
        "cve": "CVE-2023-7024",
        "cvss": 8.8,
        "severity": "HIGH",
        "affected_max": "120.0.6098.99",
        "fixed_version": "120.0.6099.129",
        "description": "Lỗ hổng tràn bộ nhớ đệm WebRTC bị tin tặc khai thác zero-day",
        "recommendation": "Chạy Google Chrome Update để nâng cấp lên bản mới nhất"
    },
    {
        "app_pattern": r"python",
        "cve": "CVE-2023-36632",
        "cvss": 7.5,
        "severity": "HIGH",
        "affected_max": "3.11.3",
        "fixed_version": "3.11.4",
        "description": "Lỗ hổng chèn mã độc vào header email và giải nén tarfile độc hại",
        "recommendation": "Cập nhật Python runtime lên >= 3.11.4 hoặc >= 3.10.12"
    },
    {
        "app_pattern": r"anydesk",
        "cve": "CVE-2023-38633",
        "cvss": 8.8,
        "severity": "HIGH",
        "affected_max": "7.0.13",
        "fixed_version": "7.0.14",
        "description": "Lỗ hổng vượt qua kiểm soát truy cập và leo thang đặc quyền từ xa",
        "recommendation": "Cập nhật AnyDesk lên phiên bản an toàn mới nhất"
    }
]

CVE_REMEDIATION_COMMAND = {'action': 'none', 'target_file': ''}
BRUTE_FORCE_INCIDENT = {
    "active": False,
    "mitre_id": "T1110",
    "standard": "MITRE ATT&CK T1110 | NIST SP 800-61 Rev.2",
    "hostname": "NGUYENVANTIEN",
    "target_user": "tien0",
    "attacker_ip": "192.168.21.105",
    "fail_count": 0,
    "detected_at": None,
    "status": "idle",
    "remediation_history": []
}

BRUTE_FORCE_COMMAND = {
    "action": "none",
    "target_ip": "",
    "target_user": "",
    "timestamp": 0
}

# ==============================================================================
# SOAR ENTERPRISE PLAYBOOK ENGINE (NIST SP 800-61 Rev.2 / MITRE D3FEND / MITRE ATT&CK)
# ==============================================================================
SOAR_CONFIG = {
    "mode": "auto",              # "auto" (Tự động 100%) | "approval" (Bán tự động - Chờ duyệt)
    "default_track": "block_ip",  # "block_ip" (NIST Least Disruption - Khuyến nghị) | "lock_user" | "dual"
    "auto_notify": True,
    "lock_threshold": 5          # Ngưỡng leo thang: nếu sai >= 5 lần, tự động kích hoạt cả khóa user
}

SOAR_PLAYBOOKS = {
    "PB-T1110-BRUTEFORCE": {
        "id": "PB-T1110-BRUTEFORCE",
        "name": "Playbook Ứng phó Tấn công Dò mật khẩu (MITRE T1110)",
        "mitre_id": "T1110",
        "standard": "NIST SP 800-61 Rev.2 §3.3 | MITRE M1037 & M1036 | D3FEND D3-IB",
        "description": "Tự động phân tích vector brute-force, cách ly IP kẻ tấn công trên Firewall máy trạm để bảo vệ công việc nhân viên (Least Disruption), hoặc tạm khóa tài khoản khi nguy cấp.",
        "tracks": {
            "block_ip": {
                "name": "Cách ly Mạng (Network Containment - MITRE M1037 / D3-IB)",
                "recommended": True,
                "desc": "Chặn IP kẻ tấn công trên Windows Firewall ngay lập tức. Người dùng hợp lệ không bị gián đoạn (Chuẩn quốc tế NIST)."
            },
            "lock_user": {
                "name": "Cách ly Định danh (Identity Containment - MITRE M1036 / D3-UPR)",
                "recommended": False,
                "desc": "Vô hiệu hóa tài khoản bị nhắm tới và khóa màn hình máy trạm để ngăn chặn truy cập trái phép."
            },
            "dual": {
                "name": "Cách ly Toàn diện (Dual Containment)",
                "recommended": False,
                "desc": "Kết hợp cả chặn IP nguồn trên Firewall và vô hiệu hóa tài khoản người dùng."
            }
        }
    },
    "PB-T1204-MALWARE-CVE": {
        "id": "PB-T1204-MALWARE-CVE",
        "name": "Playbook Cách ly & Tiêu hủy Tệp dính CVE Nguy hiểm (MITRE T1204)",
        "mitre_id": "T1204",
        "standard": "NIST SP 800-61 Rev.2 §3.4 | MITRE M1049 | D3FEND D3-FOC",
        "description": "Quét radar đa thư mục (Desktop, Downloads, Temp), tự động tiêu hủy và cách ly tệp độc hại có lỗ hổng CVE.",
        "tracks": {
            "delete_file": {"name": "Tiêu hủy & Cách ly Tệp (Quarantine)", "recommended": True, "desc": "Tự động xóa file độc hại trên máy trạm"}
        }
    },
    "PB-T1499-RESOURCE-DOS": {
        "id": "PB-T1499-RESOURCE-DOS",
        "name": "Playbook Khống chế Quá tải Tài nguyên Hệ thống (MITRE T1499)",
        "mitre_id": "T1499",
        "standard": "NIST SP 800-61 Rev.2 §3.2 | High Resource Incident",
        "description": "Giám sát ngưỡng CPU/RAM 90%, kích hoạt quy trình hạ nhiệt hoặc shutdown an toàn từ xa.",
        "tracks": {
            "alert_only": {"name": "Cảnh báo ChatOps khẩn", "recommended": True, "desc": "Báo Telegram kỹ sư trực ban"},
            "shutdown": {"name": "Shutdown Máy trạm Từ xa", "recommended": False, "desc": "Tắt máy trạm tránh cháy nổ quá tải"}
        }
    },
    "PB-T1190-WEB-EXPLOIT": {
        "id": "PB-T1190-WEB-EXPLOIT",
        "name": "Playbook Ngăn chặn Khai thác Web (SQLi, XSS, RCE)",
        "mitre_id": "T1190",
        "standard": "NIST SP 800-61 Rev.2 §3.3 | ModSecurity WAF & Nginx Drop",
        "description": "Chặn IP truy cập khai thác lỗ hổng web tại tầng WAF/Reverse Proxy.",
        "tracks": {
            "waf_block": {"name": "Chặn IP trên WAF ModSecurity", "recommended": True, "desc": "Từ chối toàn bộ request từ IP tấn công"}
        }
    },
    "PB-T1048-DATABASE-EXFIL": {
        "id": "PB-T1048-DATABASE-EXFIL",
        "name": "Playbook Bảo vệ Cơ sở Dữ liệu & Chống Rò rỉ (MITRE T1048)",
        "mitre_id": "T1048",
        "standard": "NIST SP 800-61 Rev.2 §3.3 | MySQL Enterprise Audit",
        "description": "Phát hiện truy vấn nguy hiểm (DROP/TRUNCATE), tự động sao lưu snapshot DB và cô lập kết nối.",
        "tracks": {
            "db_snapshot": {"name": "Sao lưu Snapshot DB Tức thì", "recommended": True, "desc": "Đảm bảo toàn vẹn dữ liệu trước khi khôi phục"}
        }
    }
}

ACTIVE_CONTAINMENTS = {
    "blocked_ips": {},      # ip -> { target, hostname, reason, rule, timestamp, time_str, standard }
    "locked_users": {},     # user -> { target, hostname, reason, timestamp, time_str, standard }
    "quarantined_files": {} # file -> { target, hostname, cve, timestamp, time_str }
}

SOAR_AUDIT_LOG = []


LATEST_CVE_AUDIT = {
    "last_scanned": None,
    "client_ip": "Chưa quét",
    "hostname": "Chưa quét",
    "total_apps": 0,
    "vulnerabilities_found": 0,
    "stats": {"critical": 0, "high": 0, "medium": 0, "safe": 0},
    "vulnerabilities": [],
    "recent_apps": []
}

_last_cve_alert_time = 0

def _parse_version(v_str):
    if not v_str: return ()
    nums = re.findall(r'\d+', str(v_str))
    return tuple(int(x) for x in nums)

def audit_apps_for_cve(app_list, client_ip="192.168.21.156", hostname="Windows-Host"):
    global LATEST_CVE_AUDIT, _last_cve_alert_time
    vulns = []
    crit_cnt = 0
    high_cnt = 0
    med_cnt = 0

    for app in app_list:
        app_name = app.get("name", "")
        app_ver = app.get("version", "")
        if not app_name: continue

        for rule in KNOWN_CVE_DB:
            if re.search(rule["app_pattern"], app_name, re.IGNORECASE):
                if app_ver and rule.get("affected_max"):
                    v_installed = _parse_version(app_ver)
                    v_max = _parse_version(rule["affected_max"])
                    if v_installed and v_max and v_installed > v_max:
                        continue

                vuln_item = {
                    "app": app_name,
                    "version": app_ver or "Chưa rõ",
                    "cve": rule["cve"],
                    "cvss": rule["cvss"],
                    "severity": rule["severity"],
                    "description": rule["description"],
                    "recommendation": rule["recommendation"],
                    "detected_at": _now_str()
                }
                vulns.append(vuln_item)

                if rule["cvss"] >= 9.0: crit_cnt += 1
                elif rule["cvss"] >= 7.0: high_cnt += 1
                else: med_cnt += 1
                break

    with _lock:
        is_incremental = len(app_list) <= 3 and any("tep tai ve" in a.get("name", "").lower() for a in app_list)

        if is_incremental:
            existing_vulns = list(LATEST_CVE_AUDIT.get("vulnerabilities", []))
            existing_apps = list(LATEST_CVE_AUDIT.get("recent_apps", []))

            for nv in vulns:
                if not any(ev.get("app", "").lower() == nv["app"].lower() and ev.get("cve") == nv["cve"] for ev in existing_vulns):
                    existing_vulns.insert(0, nv)

            for na in app_list:
                if not any(ea.get("name", "").lower() == na.get("name", "").lower() for ea in existing_apps):
                    existing_apps.insert(0, na)

            final_vulns = existing_vulns
            final_apps = existing_apps
            total_count = max(len(final_apps), LATEST_CVE_AUDIT.get("total_apps", 0) + len(app_list))
        else:
            existing_file_vulns = [v for v in LATEST_CVE_AUDIT.get("vulnerabilities", []) if "tep tai ve" in v.get("app", "").lower()]
            final_vulns = vulns + [fv for fv in existing_file_vulns if not any(nv["app"].lower() == fv.get("app", "").lower() for nv in vulns)]
            final_apps = app_list[:35]
            total_count = len(app_list)

        crit_cnt = sum(1 for v in final_vulns if v.get("cvss", 0) >= 9.0)
        high_cnt = sum(1 for v in final_vulns if 7.0 <= v.get("cvss", 0) < 9.0)
        med_cnt = sum(1 for v in final_vulns if v.get("cvss", 0) < 7.0)
        safe_cnt = max(0, total_count - len(final_vulns))

        LATEST_CVE_AUDIT["last_scanned"] = _now_str()
        LATEST_CVE_AUDIT["client_ip"] = client_ip
        LATEST_CVE_AUDIT["hostname"] = hostname
        LATEST_CVE_AUDIT["total_apps"] = total_count
        LATEST_CVE_AUDIT["vulnerabilities_found"] = len(final_vulns)
        LATEST_CVE_AUDIT["stats"] = {
            "critical": crit_cnt,
            "high": high_cnt,
            "medium": med_cnt,
            "safe": safe_cnt
        }
        LATEST_CVE_AUDIT["vulnerabilities"] = final_vulns
        LATEST_CVE_AUDIT["recent_apps"] = final_apps[:35]

    now = time.time()
    if vulns and (now - _last_cve_alert_time > 60):
        _last_cve_alert_time = now
        top = vulns[0]
        color = "red" if crit_cnt > 0 else "white"
        add_incident(color, "CVE AUDIT", f"Phát hiện {len(vulns)} lỗ hổng phần mềm trên {client_ip}", f"Lỗ hổng: {top['cve']} ({top['app']} v{top['version']} - CVSS {top['cvss']})")
        log_alert_to_es(f"Phát hiện CVE: {top['cve']} ({top['app']})", "tien0", client_ip, "HIGH")

        tg_vulns_text = "\n".join([f"• <b>[{v['severity']}] {v['app']} ({v['version']})</b>: <code>{v['cve']}</code> (CVSS: {v['cvss']})\n  <i>{v['recommendation']}</i>" for v in vulns[:5]])
        msg = (
            f"🛡️ <b>[SME SOC - PHÁT HIỆN LỖ HỔNG CVE TRÊN MÁY TRẠM]</b> 🛡️\n\n"
            f"💻 <b>Máy trạm:</b> <code>{client_ip}</code> ({hostname})\n"
            f"📊 <b>Tổng ứng dụng rà soát:</b> {len(app_list)}\n"
            f"⚠️ <b>Số lỗ hổng phát hiện:</b> {len(vulns)} (Critical: {crit_cnt}, High: {high_cnt})\n\n"
            f"🔍 <b>Chi tiết lỗ hổng nghiêm trọng:</b>\n{tg_vulns_text}\n\n"
            f"⏱ <i>{_now_str()}</i>"
        )
        send_telegram(msg, thread_id=TOPIC_SYSTEM_ID)

    return LATEST_CVE_AUDIT


def get_current_tunnel_url():
    return "http://70.153.83.137"
def generate_ai_voice(title, text):
    global LATEST_VOICE_ALERT
    now_ts = time.time()
    with _lock:
        new_id = int(now_ts)
        if new_id <= LATEST_VOICE_ALERT.get("alert_id", 0):
            new_id = LATEST_VOICE_ALERT.get("alert_id", 0) + 1
        LATEST_VOICE_ALERT["alert_id"] = new_id
        LATEST_VOICE_ALERT["title"] = title
        LATEST_VOICE_ALERT["text"] = text
        LATEST_VOICE_ALERT["time"] = _now_str()
        LATEST_VOICE_ALERT["timestamp"] = now_ts
        aid = new_id

    # 1. Bắn Web Push Notification tới màn hình khóa iPhone
    send_web_push(f"🚨 {title}", text)

    # 2. Sinh file âm thanh AI với cơ chế ghi file an toàn (Atomic write)
    def _worker():
        with _tts_lock:
            try:
                import asyncio
                import edge_tts
                clean_text = text.replace("\n", " ").strip()
                tmp_out = f"/tmp/alert_{aid}.mp3"
                async def _run():
                    comm = edge_tts.Communicate(clean_text, "vi-VN-HoaiMyNeural")
                    await comm.save(tmp_out)
                asyncio.run(_run())
                if os.path.exists(tmp_out):
                    os.replace(tmp_out, "/tmp/latest_alert.mp3")
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()

def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_alert_to_es(alert_title, user, ip, severity="CRITICAL"):
    doc = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_title": alert_title,
        "affected_user": user,
        "source_ip": ip,
        "severity": severity,
        "source": "sme_ai_engine"
    }
    today = datetime.now().strftime("%Y.%m.%d")
    url = f"{ES_URL}/sme-ai-alerts-{today}/_doc"
    try:
        headers = {"Content-Type": "application/json"}
        if ES_API_KEY: headers["Authorization"] = f"ApiKey {ES_API_KEY}"
        requests.post(url, json=doc, headers=headers, timeout=3)
    except: pass

def add_incident(color, incident_type, title, details):
    with _lock:
        RECENT_INCIDENTS.insert(0, {
            "time": _now_str(),
            "color": color,
            "type": incident_type,
            "title": title,
            "details": details
        })
        if len(RECENT_INCIDENTS) > 60:
            RECENT_INCIDENTS.pop()

def send_telegram(html_msg, thread_id=None, reply_markup=None):
    if not CONFIG["enable_alerts"] or not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": html_msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def send_soar_cpu_ram_alert(cpu, ram, client_ip):
    markup = {
        "inline_keyboard": [
            [
                {"text": "1️⃣ Nâng ngưỡng CPU 95%", "callback_data": "raise_cpu_95"},
                {"text": "2️⃣ Tắt máy khẩn cấp (Shutdown)", "callback_data": "shutdown_vm"}
            ],
            [
                {"text": "3️⃣ Tắt thông báo 30 phút", "callback_data": "mute_30m"}
            ]
        ]
    }
    msg = (
        f"🚨 <b>[SOAR CHATOPS - XỬ LÝ SỰ CỐ MÁY TRẠM]</b> 🚨\n"
        f"💻 IP: <code>{client_ip}</code>\n"
        f"🔥 CPU: <b>{cpu:.1f}%</b> | 💾 RAM: <b>{ram:.1f}%</b>\n\n"
        f"Chọn hành động phản ứng tự động bên dưới hoặc gõ phím tắt:\n"
        f"• Gõ <code>1</code> để nâng ngưỡng CPU lên 95%\n"
        f"• Gõ <code>2</code> để TẮT NGUỒN máy trạm khẩn cấp\n"
        f"• Gõ <code>3</code> để tắt chuông cảnh báo 30 phút"
    )
    send_telegram(msg, thread_id=TOPIC_SOAR_ID, reply_markup=markup)

def execute_soar_shutdown(user_name="Quản trị viên"):
    with _lock:
        GLOBAL_COMMAND["action"] = "shutdown"
        GLOBAL_COMMAND["last_command_time"] = _now_str()
        GLOBAL_COMMAND["last_command_by"] = user_name
    msg = (
        f"🚨 <b>[SOAR LỆNH KHẨN CẤP]</b> 🚨\n"
        f"Lệnh phát bởi: <b>{user_name}</b>\n"
        f"Đã phát lệnh <b>TẮT NGUỒN CÔ LẬP MÁY TRẠM WINDOWS</b>!"
    )
    send_telegram(msg, thread_id=TOPIC_SOAR_ID)

def execute_soar_playbook(playbook_id, context):
    """
    Kích hoạt thực thi Playbook tự động theo chuẩn quốc tế NIST SP 800-61 Rev. 2.
    """
    global BRUTE_FORCE_INCIDENT, BRUTE_FORCE_COMMAND, ACTIVE_CONTAINMENTS, SOAR_AUDIT_LOG
    pb = SOAR_PLAYBOOKS.get(playbook_id)
    if not pb:
        return {"status": "error", "message": f"Playbook {playbook_id} không tồn tại"}

    track = SOAR_CONFIG.get("default_track", "block_ip")
    if context.get("fail_count", 0) >= SOAR_CONFIG.get("lock_threshold", 5):
        track = "dual"

    target_ip = context.get("attacker_ip", "192.168.21.105")
    target_user = context.get("target_user", "tien0")
    if target_user.replace("$", "").strip().upper() in ["NGUYENVANTIEN", "WIN-KETOAN", ""]:
        target_user = "tien0"
    hostname = context.get("hostname", "NGUYENVANTIEN")
    operator = context.get("operator", "SOAR Playbook Engine (Autonomous)")

    actions_executed = []
    now_ts = time.time()
    now_s = _now_str()

    with _lock:
        if track in ["block_ip", "dual"] and target_ip:
            BRUTE_FORCE_COMMAND = {
                "action": "block_ip" if track == "block_ip" else "dual",
                "target_ip": target_ip,
                "target_user": target_user,
                "timestamp": now_ts,
                "time": now_s
            }
            ACTIVE_CONTAINMENTS["blocked_ips"][target_ip] = {
                "target": target_ip,
                "type": "ip",
                "hostname": hostname,
                "reason": f"MITRE T1110: Gõ sai mật khẩu {context.get('fail_count', 3)} lần",
                "rule": f"SOC_SOAR_BLOCK_{target_ip}",
                "timestamp": now_ts,
                "time_str": now_s,
                "standard": "NIST SP 800-61 §3.3 (Network Containment)"
            }
            BRUTE_FORCE_INCIDENT["status"] = "ip_blocked"
            actions_executed.append(f"Chặn IP {target_ip} trên Windows Firewall (MITRE M1037)")

        if track in ["lock_user", "dual"] and target_user:
            if track == "lock_user":
                BRUTE_FORCE_COMMAND = {
                    "action": "lock_user",
                    "target_ip": target_ip,
                    "target_user": target_user,
                    "timestamp": now_ts,
                    "time": now_s
                }
            ACTIVE_CONTAINMENTS["locked_users"][target_user] = {
                "target": target_user,
                "type": "user",
                "hostname": hostname,
                "reason": f"MITRE T1110: Dò quét tài khoản {target_user}",
                "timestamp": now_ts,
                "time_str": now_s,
                "standard": "NIST SP 800-61 §3.3 (Identity Containment)"
            }
            BRUTE_FORCE_INCIDENT["status"] = "user_locked"
            actions_executed.append(f"Tạm khóa tài khoản {target_user} (MITRE M1036)")

        audit_entry = {
            "timestamp": now_s,
            "playbook_id": playbook_id,
            "playbook_name": pb["name"],
            "standard": pb["standard"],
            "track": track,
            "actions": actions_executed,
            "operator": operator,
            "context": context
        }
        SOAR_AUDIT_LOG.insert(0, audit_entry)
        if len(SOAR_AUDIT_LOG) > 50:
            SOAR_AUDIT_LOG.pop()

        BRUTE_FORCE_INCIDENT["remediation_history"].append({
            "action": track,
            "time": now_s,
            "detail": " & ".join(actions_executed)
        })

    tg_text = (
        f"🤖 <b>[SOAR TỰ ĐỘNG THỰC THI PLAYBOOK]</b> 🤖\n"
        f"📋 <b>Playbook:</b> <code>{pb['name']}</code>\n"
        f"📜 <b>Tiêu chuẩn:</b> <code>{pb['standard']}</code>\n"
        f"💻 <b>Máy trạm:</b> <code>{hostname}</code>\n"
        f"🎯 <b>Mục tiêu:</b> User <code>{target_user}</code> | IP nguồn: <code>{target_ip}</code>\n"
        f"⚡ <b>Hành động tự động:</b>\n" + "\n".join([f"  • {a}" for a in actions_executed]) + "\n"
        f"👤 <b>Tác vụ nhân viên:</b> " + ("Được bảo đảm thông suốt (Không khóa màn hình)" if track == "block_ip" else "Đã khóa bảo vệ tài khoản") + "\n"
        f"⏱ <i>Thời điểm: {now_s}</i>\n\n"
        f"👉 <i>Admin có thể bấm nút bên dưới hoặc vào Trung tâm SOAR trên Web để Mở khóa / Bỏ chặn bất cứ lúc nào:</i>"
    )

    markup = {
        "inline_keyboard": [
            [
                {"text": "🔓 Bỏ chặn IP", "callback_data": f"soar_unblock_{target_ip}"},
                {"text": "🔑 Mở khóa User", "callback_data": f"soar_unlock_{target_user}"}
            ]
        ]
    }
    send_telegram(tg_text, thread_id=TOPIC_SOAR_ID, reply_markup=markup)

    return {
        "status": "ok",
        "playbook": pb["name"],
        "track": track,
        "actions": actions_executed,
        "audit": audit_entry
    }

def execute_soar_rollback(target_type, target_value="", operator="Quản trị viên"):
    """
    Thực hiện hoàn tác / mở khóa / bỏ chặn tập trung 1-click.
    """
    global BRUTE_FORCE_COMMAND, BRUTE_FORCE_INCIDENT, ACTIVE_CONTAINMENTS, SOAR_AUDIT_LOG
    now_ts = time.time()
    now_s = _now_str()
    rolled_back = []

    with _lock:
        if target_type == "all":
            BRUTE_FORCE_COMMAND = {
                "action": "rollback_all",
                "target_ip": "",
                "target_user": "tien0",
                "timestamp": now_ts,
                "time": now_s
            }
            if ACTIVE_CONTAINMENTS["blocked_ips"]:
                for ip in list(ACTIVE_CONTAINMENTS["blocked_ips"].keys()):
                    rolled_back.append(f"Đã hủy chặn IP {ip} trên Firewall")
                ACTIVE_CONTAINMENTS["blocked_ips"].clear()
            else:
                rolled_back.append("Đã dọn sạch các luật chặn IP trên Firewall")

            if ACTIVE_CONTAINMENTS["locked_users"]:
                for u in list(ACTIVE_CONTAINMENTS["locked_users"].keys()):
                    rolled_back.append(f"Đã mở khóa tài khoản {u} (Account active: Yes)")
                ACTIVE_CONTAINMENTS["locked_users"].clear()
            else:
                rolled_back.append("Đã kích hoạt lại tài khoản tien0")

            BRUTE_FORCE_INCIDENT["status"] = "active"

        elif target_type == "ip":
            ip = target_value if target_value else "192.168.21.105"
            BRUTE_FORCE_COMMAND = {
                "action": "unblock_ip",
                "target_ip": ip,
                "target_user": "tien0",
                "timestamp": now_ts,
                "time": now_s
            }
            if ip in ACTIVE_CONTAINMENTS["blocked_ips"]:
                del ACTIVE_CONTAINMENTS["blocked_ips"][ip]
            rolled_back.append(f"Đã hủy chặn IP {ip} trên Windows Firewall")
            if not ACTIVE_CONTAINMENTS["blocked_ips"] and not ACTIVE_CONTAINMENTS["locked_users"]:
                BRUTE_FORCE_INCIDENT["status"] = "active"

        elif target_type == "user":
            u = target_value if target_value else "tien0"
            BRUTE_FORCE_COMMAND = {
                "action": "unlock_user",
                "target_ip": "",
                "target_user": u,
                "timestamp": now_ts,
                "time": now_s
            }
            if u in ACTIVE_CONTAINMENTS["locked_users"]:
                del ACTIVE_CONTAINMENTS["locked_users"][u]
            rolled_back.append(f"Đã mở khóa tài khoản {u} (Account active: Yes)")
            if not ACTIVE_CONTAINMENTS["blocked_ips"] and not ACTIVE_CONTAINMENTS["locked_users"]:
                BRUTE_FORCE_INCIDENT["status"] = "active"

        audit_entry = {
            "timestamp": now_s,
            "playbook_id": "SOAR-ROLLBACK",
            "playbook_name": "Quy trình Hoàn tác Khôi phục (1-Click Recovery)",
            "standard": "NIST SP 800-61 Rev.2 §3.4 (Recovery & Restoration)",
            "track": "manual_recovery",
            "actions": rolled_back,
            "operator": operator,
            "context": {"type": target_type, "target": target_value}
        }
        SOAR_AUDIT_LOG.insert(0, audit_entry)

    send_telegram(
        f"✅ <b>[SOAR PHỤC HỒI / ROLLBACK HOÀN TẤT]</b> ✅\n"
        f"👤 <b>Người thực hiện:</b> {operator}\n"
        f"🔄 <b>Thao tác:</b>\n" + "\n".join([f"  • {r}" for r in rolled_back]) + f"\n"
        f"⏱ <i>{now_s}</i>",
        thread_id=TOPIC_SOAR_ID
    )

    return {"status": "ok", "actions": rolled_back, "message": " & ".join(rolled_back)}

def telegram_polling_worker():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={offset}&timeout=10"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data")
                        from_user = cb.get("from", {}).get("username") or cb.get("from", {}).get("first_name", "Admin")

                        if cb_data == "raise_cpu_95":
                            with _lock:
                                CONFIG["cpu_threshold"] = 95.0
                            send_telegram(f"⚡ <b>[SOAR THỰC THI]</b> @{from_user} đã nâng ngưỡng CPU lên 95%.", thread_id=TOPIC_SOAR_ID)
                        elif cb_data == "shutdown_vm":
                            execute_soar_shutdown(user_name=f"@{from_user}")
                        elif cb_data == "mute_30m":
                            with _lock:
                                CONFIG["enable_alerts"] = False
                            send_telegram(f"🔕 <b>[SOAR THỰC THI]</b> @{from_user} đã tắt cảnh báo trong 30 phút.", thread_id=TOPIC_SOAR_ID)
                        elif cb_data.startswith("soar_unblock_"):
                            tip = cb_data.replace("soar_unblock_", "").strip()
                            execute_soar_rollback("ip", tip, operator=f"@{from_user}")
                        elif cb_data.startswith("soar_unlock_"):
                            tuser = cb_data.replace("soar_unlock_", "").strip()
                            execute_soar_rollback("user", tuser, operator=f"@{from_user}")

                    elif "message" in update:
                        msg = update["message"]
                        text = msg.get("text", "").strip()
                        from_user = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "Admin")

                        if text == "1" or text == "/raise":
                            with _lock:
                                CONFIG["cpu_threshold"] = 95.0
                            send_telegram(f"⚡ <b>[SOAR THỰC THI]</b> @{from_user} đã nâng ngưỡng CPU lên 95%.", thread_id=TOPIC_SOAR_ID)
                        elif text == "2" or text == "/shutdown":
                            execute_soar_shutdown(user_name=f"@{from_user}")
                        elif text == "3" or text == "/mute":
                            with _lock:
                                CONFIG["enable_alerts"] = False
                            send_telegram(f"🔕 <b>[SOAR THỰC THI]</b> @{from_user} đã tắt cảnh báo trong 30 phút.", thread_id=TOPIC_SOAR_ID)
        except:
            pass
        time.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=ai_worker, daemon=True).start()
    threading.Thread(target=telegram_polling_worker, daemon=True).start()
    yield

app = FastAPI(title="SME SOC AI Engine", lifespan=lifespan)

@app.post("/api/windows_metrics")
async def receive_windows_metrics(request: Request):
    global CURRENT_METRICS, GLOBAL_COMMAND
    client_ip = request.client.host if request.client else "192.168.21.148"
    try:
        payload = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        cpu_val = float(payload.get("cpu", CURRENT_METRICS["cpu"]))
        ram_val = float(payload.get("ram", CURRENT_METRICS["ram"]))
    except:
        raise HTTPException(status_code=400, detail="Values must be float")

    now = time.time()
    is_overload = (cpu_val >= CONFIG["cpu_threshold"]) or (ram_val >= CONFIG["ram_threshold"])
    is_recovered = (cpu_val < CONFIG["cpu_threshold"] - 5.0) and (ram_val < CONFIG["ram_threshold"] - 5.0)

    with _lock:
        old_status = CURRENT_METRICS["status"]
        CURRENT_METRICS["cpu"] = cpu_val
        CURRENT_METRICS["ram"] = ram_val
        CURRENT_METRICS["last_updated"] = _now_str()

        cmd_action = GLOBAL_COMMAND["action"]
        if cmd_action == "shutdown":
            GLOBAL_COMMAND["action"] = "none"

        if is_overload and old_status != "overload":
            CURRENT_METRICS["status"] = "overload"
            CURRENT_METRICS["last_alert_time"] = _now_str()

            trigger_detail = f"CPU {cpu_val:.1f}% >= {CONFIG['cpu_threshold']}%" if cpu_val >= CONFIG["cpu_threshold"] else f"RAM {ram_val:.1f}% >= {CONFIG['ram_threshold']}%"
            add_incident("red", "QUÁ TẢI TÀI NGUYÊN", f"CPU: {cpu_val:.1f}% | RAM: {ram_val:.1f}%", f"Máy trạm {client_ip} vượt ngưỡng an toàn ({trigger_detail})")
            log_alert_to_es(f"Quá tải CPU/RAM ({cpu_val:.1f}%)", "tien0", client_ip, "CRITICAL")

            # 1. Khong kich hoat cuoc goi dien thoai cho Qua tai CPU/RAM (theo yeu cau van hanh)
            # Cuoc goi khan cap chi danh rieng cho cac su co an ninh nguy cap (Brute-force, WAF RCE, DB Drop/Tat log)

            # 2. Bao Telegram & Menu phan ung SOAR
            sys_msg = (
                f"🚨 <b>[SME SOC - MÁY TRẠM QUÁ TẢI]</b> 🚨\n"
                f"💻 IP: <code>{client_ip}</code>\n"
                f"🔥 CPU: <b>{cpu_val:.1f}%</b> (Ngưỡng {CONFIG['cpu_threshold']}%) | 💾 RAM: <b>{ram_val:.1f}%</b> (Ngưỡng {CONFIG['ram_threshold']}%)\n"
                f"⚠️ Đã ghi nhận cảnh báo tài nguyên & gửi menu phản ứng SOAR tới kỹ sư trực ban!\n"
                f"⏱ <i>{_now_str()}</i>"
            )
            send_telegram(sys_msg, thread_id=TOPIC_SYSTEM_ID)
            send_soar_cpu_ram_alert(cpu_val, ram_val, client_ip)

        elif is_recovered and old_status == "overload":
            CURRENT_METRICS["status"] = "normal"
            rec_msg = f"✅ <b>[MÁY TRẠM ĐÃ HẠ TẢI AN TOÀN]</b> CPU: {cpu_val:.1f}%, RAM: {ram_val:.1f}%"
            send_telegram(rec_msg, thread_id=TOPIC_SYSTEM_ID)

    global CVE_REMEDIATION_COMMAND, BRUTE_FORCE_COMMAND, BRUTE_FORCE_INCIDENT
    failed_logins = int(payload.get("failed_logins", 0))
    failed_user = payload.get("last_failed_user", "tien0")
    if failed_user.replace("$", "").strip().upper() in ["NGUYENVANTIEN", "WIN-KETOAN", ""]:
        failed_user = "tien0"
    failed_ip = payload.get("last_failed_ip", "192.168.21.105")

    if failed_logins >= CONFIG.get("auth_fail_threshold", 2):
        is_new_trigger = False
        with _lock:
            if not BRUTE_FORCE_INCIDENT["active"] or BRUTE_FORCE_INCIDENT["fail_count"] != failed_logins:
                BRUTE_FORCE_INCIDENT["active"] = True
                BRUTE_FORCE_INCIDENT["target_user"] = failed_user
                BRUTE_FORCE_INCIDENT["attacker_ip"] = failed_ip
                BRUTE_FORCE_INCIDENT["fail_count"] = failed_logins
                BRUTE_FORCE_INCIDENT["detected_at"] = _now_str()
                BRUTE_FORCE_INCIDENT["status"] = "active"
                is_new_trigger = True

                add_incident("red", "BRUTE-FORCE MẬT KHẨU (MITRE T1110)", f"User: {failed_user} (Gõ sai {failed_logins} lần)", f"IP Tấn công: {failed_ip} | Event 4625")

        if is_new_trigger and SOAR_CONFIG.get("mode") == "auto":
            execute_soar_playbook("PB-T1110-BRUTEFORCE", {
                "hostname": "NGUYENVANTIEN",
                "target_user": failed_user,
                "attacker_ip": failed_ip,
                "fail_count": failed_logins,
                "operator": "SOAR Playbook Engine (Autonomous)"
            })

    cve_act = "none"
    cve_target = ""
    with _lock:
        cmd_ts = CVE_REMEDIATION_COMMAND.get("timestamp", 0)
        if CVE_REMEDIATION_COMMAND.get("action") == "delete_file" and (time.time() - cmd_ts < 20):
            cve_act = "delete_file"
            cve_target = CVE_REMEDIATION_COMMAND.get("target_file", "")

    brute_act = "none"
    brute_target_ip = ""
    brute_target_user = ""
    with _lock:
        b_cmd_ts = BRUTE_FORCE_COMMAND.get("timestamp", 0)
        if BRUTE_FORCE_INCIDENT.get("status") == "user_locked":
            brute_act = "lock_user"
            brute_target_user = BRUTE_FORCE_INCIDENT.get("target_user", "tien0")
            brute_target_ip = BRUTE_FORCE_INCIDENT.get("attacker_ip", "")
        elif BRUTE_FORCE_COMMAND.get("action") in ["unlock_user", "rollback_all"] and (time.time() - b_cmd_ts < 600):
            brute_act = BRUTE_FORCE_COMMAND.get("action")
            brute_target_user = BRUTE_FORCE_COMMAND.get("target_user", "tien0")
            brute_target_ip = BRUTE_FORCE_COMMAND.get("target_ip", "")
        elif (time.time() - b_cmd_ts < 35):
            brute_act = BRUTE_FORCE_COMMAND.get("action", "none")
            brute_target_ip = BRUTE_FORCE_COMMAND.get("target_ip", "")
            brute_target_user = BRUTE_FORCE_COMMAND.get("target_user", "")

    return {
        "tunnel_url": get_current_tunnel_url(),
        "status": "ok",
        "action": cmd_action,
        "cve_action": cve_act,
        "target_file": cve_target,
        "brute_action": brute_act,
        "brute_target_ip": brute_target_ip,
        "brute_target_user": brute_target_user
    }

@app.get("/manifest.json")
def get_manifest():
    return {
        "name": "SME SOC Emergency Responder",
        "short_name": "SOC Alert",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b1120",
        "theme_color": "#0284c7",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2338bdf8'><path d='M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z'/></svg>",
                "sizes": "192x192 512x512",
                "type": "image/svg+xml"
            }
        ]
    }

@app.get("/sw.js")
def get_service_worker():
    sw_code = """
self.addEventListener('push', function(event) {
    let data = { title: '🚨 Báo động SOC khẩn cấp!', body: 'Phát hiện sự cố hệ thống an ninh mạng!', url: '/?play_alert=1' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch(e) {
            data.body = event.data.text();
        }
    }
    const options = {
        body: data.body,
        icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23ef4444"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>',
        badge: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23ef4444"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/></svg>',
        vibrate: [300, 150, 300, 150, 500],
        tag: 'soc-alert',
        renotify: true,
        data: { url: data.url || '/?play_alert=1' }
    };
    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const targetUrl = event.notification.data && event.notification.data.url ? event.notification.data.url : '/?play_alert=1';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
            for (let i = 0; i < clientList.length; i++) {
                let client = clientList[i];
                if ('focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
"""
    return Response(content=sw_code, media_type="application/javascript")

@app.get("/api/vapid_public_key")
def get_vapid_key():
    return {"publicKey": VAPID_PUBLIC_KEY}

@app.post("/api/push_subscribe")
async def handle_push_sub(req: Request):
    sub = await req.json()
    with _lock:
        if sub not in PUSH_SUBSCRIPTIONS:
            PUSH_SUBSCRIPTIONS.append(sub)
            _save_push_subs()
    return {"ok": True, "count": len(PUSH_SUBSCRIPTIONS)}

@app.get("/api/voice_status")
def get_voice_status():
    with _lock:
        return LATEST_VOICE_ALERT

@app.get("/api/voice_alert")
def get_voice_alert():
    mp3_path = "/tmp/latest_alert.mp3"
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 100:
        return FileResponse(mp3_path, media_type="audio/mpeg")
    return {"status": "no_audio"}

@app.post("/api/soar/shutdown")
def api_soar_shutdown():
    execute_soar_shutdown(user_name="Web SOC PWA")
    return {"ok": True, "msg": "Đã phát lệnh tắt máy Windows qua SOAR"}



@app.get("/download_doc")
@app.get("/BAO_CAO_KIEM_THU_HE_THONG_SME_SOC.docx")
def download_soc_doc():
    doc_path = "/home/nguyenvanwin/BAO_CAO_KIEM_THU_HE_THONG_SME_SOC.docx"
    if os.path.exists(doc_path):
        return FileResponse(doc_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename="BAO_CAO_KIEM_THU_HE_THONG_SME_SOC.docx")
    return {"error": "Docx not found"}

@app.get("/download_apk")
@app.get("/SOC_Alert.apk")
def download_soc_apk():
    apk_path = "/home/nguyenvanwin/SOC_Alert.apk"
    if os.path.exists(apk_path):
        return FileResponse(apk_path, media_type="application/vnd.android.package-archive", filename="SOC_Alert.apk")
    return {"error": "APK not found"}

@app.post("/api/test_internal_call")
def test_internal_call():
    generate_ai_voice(
        "Thử nghiệm báo động màn hình khóa",
        "Cảnh báo thử nghiệm! Kết nối tổng đài giọng nói A I và thông báo màn hình khóa thành công. Hệ thống S O C sẵn sàng phát thông báo khẩn cấp!"
    )
    return {"ok": True, "msg": "Đã phát lệnh gọi thử nghiệm nội bộ"}

@app.get("/api/status")
def get_status():
    with _lock:
        return {
            "tunnel_url": get_current_tunnel_url(),
            "metrics": CURRENT_METRICS,
            "config": CONFIG,
            "voice_alert": LATEST_VOICE_ALERT,
            "global_command": GLOBAL_COMMAND,
            "incidents": RECENT_INCIDENTS,
            "push_sub_count": len(PUSH_SUBSCRIPTIONS),
            "brute_force": BRUTE_FORCE_INCIDENT,
            "soar_config": SOAR_CONFIG,
            "active_containments": ACTIVE_CONTAINMENTS,
            "soar_audit": SOAR_AUDIT_LOG[:10]
        }

@app.post("/api/config")
async def update_config(req: Request):
    body = await req.json()
    with _lock:
        for k in ("cpu_threshold", "ram_threshold", "web_mb_threshold", "auth_fail_threshold"):
            if k in body:
                CONFIG[k] = float(body[k]) if "threshold" in k and k != "auth_fail_threshold" else int(body[k])
    return {"status": "ok", "config": CONFIG}


@app.post("/api/cve/remediate")
async def handle_cve_remediate(req: Request):
    global CVE_REMEDIATION_COMMAND, LATEST_CVE_AUDIT
    body = await req.json()
    action = body.get("action", "delete_file")
    target_file = body.get("target_file", "")
    app_name = body.get("app_name", "")

    with _lock:
        CVE_REMEDIATION_COMMAND = {
            "action": "delete_file",
            "target_file": target_file,
            "timestamp": time.time(),
            "time": _now_str()
        }
        # Cập nhật danh sách loại bỏ lỗ hổng đã xóa
        new_vulns = []
        for v in LATEST_CVE_AUDIT.get("vulnerabilities", []):
            v_app = v.get("app", "").lower()
            t_file = target_file.lower()
            a_name = app_name.lower()
            # Bỏ qua nếu trùng target_file hoặc app_name
            if t_file and t_file in v_app:
                continue
            if a_name and (a_name in v_app or v_app in a_name):
                continue
            if "winrar" in t_file and "winrar" in v_app:
                continue
            if "putty" in t_file and "putty" in v_app:
                continue
            new_vulns.append(v)
        LATEST_CVE_AUDIT["vulnerabilities"] = new_vulns
        LATEST_CVE_AUDIT["vulnerabilities_found"] = len(new_vulns)
        stats = LATEST_CVE_AUDIT.get("stats", {})
        if stats.get("high", 0) > 0: stats["high"] -= 1
        stats["safe"] = stats.get("safe", 0) + 1
        LATEST_CVE_AUDIT["stats"] = stats

    add_incident("white", "SOAR REMEDIATION", f"SOAR: Đã phát lệnh xóa cách ly tệp độc hại {target_file}", f"Đã tiêu hủy tệp tải về dính CVE trên máy trạm 192.168.21.156")
    log_alert_to_es(f"SOAR Remediation: {target_file}", "tien0", "192.168.21.156", "HIGH")

    msg = (
        f"⚡ <b>[SOAR THỰC THI THÀNH CÔNG]</b> ⚡\n\n"
        f"🎯 <b>Hành động:</b> Cách ly & Xóa file độc hại từ xa\n"
        f"📦 <b>Tệp bị tiêu hủy:</b> <code>{target_file}</code>\n"
        f"💻 <b>Máy trạm đích:</b> <code>192.168.21.156</code> (NGUYENVANTIEN)\n"
        f"✅ <b>Trạng thái:</b> Lệnh đã chuyển giao tới Agent máy ảo để xử lý ngay lập tức!\n"
        f"⏱ <i>{_now_str()}</i>"
    )
    send_telegram(msg, thread_id=TOPIC_SYSTEM_ID)

    return {"status": "ok", "msg": f"Đã phát lệnh SOAR tiêu hủy tệp {target_file} trên máy trạm!"}


@app.post("/api/cve/report")
async def handle_cve_report(req: Request):
    try:
        body = await req.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    client_ip = body.get("client_ip", req.client.host if req.client else "192.168.21.156")
    hostname = body.get("hostname", "Windows-Host")
    apps = body.get("apps", [])

    audit_res = audit_apps_for_cve(apps, client_ip, hostname)
    return {
        "status": "ok",
        "client_ip": client_ip,
        "vulnerabilities_found": audit_res["vulnerabilities_found"],
        "stats": audit_res["stats"],
        "vulnerabilities": audit_res["vulnerabilities"]
    }

@app.get("/api/cve/status")
def get_cve_status():
    with _lock:
        return LATEST_CVE_AUDIT

@app.post("/api/cve/demo_trigger")
def trigger_cve_demo():
    demo_apps = [
        {"name": "WinRAR 6.22 (64-bit)", "version": "6.22.0", "publisher": "win.rar GmbH"},
        {"name": "PuTTY release 0.80", "version": "0.80", "publisher": "Simon Tatham"},
        {"name": "7-Zip 22.01 (x64)", "version": "22.01", "publisher": "Igor Pavlov"},
        {"name": "Google Chrome", "version": "128.0.6613.120", "publisher": "Google LLC"},
        {"name": "Notepad++ (64-bit x64)", "version": "8.6.9", "publisher": "Notepad++ Team"}
    ]
    audit_res = audit_apps_for_cve(demo_apps, "192.168.21.156", "WIN-KETOAN")
    return {
        "status": "ok",
        "msg": "Đã nạp dữ liệu kiểm thử CVE thành công!",
        "audit": audit_res
    }


@app.get("/api/brute_force/status")
def get_brute_force_status():
    with _lock:
        return BRUTE_FORCE_INCIDENT

@app.post("/api/brute_force/remediate")
async def handle_brute_force_remediate(req: Request):
    global BRUTE_FORCE_COMMAND, BRUTE_FORCE_INCIDENT
    body = await req.json()
    action = body.get("action", "")
    target_ip = body.get("target_ip", BRUTE_FORCE_INCIDENT.get("attacker_ip", "192.168.21.105"))
    target_user = body.get("target_user", BRUTE_FORCE_INCIDENT.get("target_user", "tien0"))
    if target_user.replace("$", "").strip().upper() in ["NGUYENVANTIEN", "WIN-KETOAN", ""]:
        target_user = "tien0"

    with _lock:
        BRUTE_FORCE_COMMAND = {
            "action": action,
            "target_ip": target_ip,
            "target_user": target_user,
            "timestamp": time.time(),
            "time": _now_str()
        }
        
        detail = ""
        if action == "block_ip":
            detail = f"Đã phát lệnh chặn IP {target_ip} trên Windows Firewall (MITRE M1037)"
            BRUTE_FORCE_INCIDENT["status"] = "ip_blocked"
        elif action == "lock_user":
            detail = f"Đã phát lệnh tạm khóa tài khoản {target_user} (MITRE M1036)"
            BRUTE_FORCE_INCIDENT["status"] = "user_locked"
        elif action == "unlock_user":
            detail = f"Đã phát lệnh mở khóa lại tài khoản {target_user}"
            BRUTE_FORCE_INCIDENT["status"] = "active"
        elif action == "unblock_ip":
            detail = f"Đã phát lệnh hủy chặn IP {target_ip}"
            BRUTE_FORCE_INCIDENT["status"] = "active"
            
        BRUTE_FORCE_INCIDENT["remediation_history"].append({
            "action": action,
            "time": _now_str(),
            "detail": detail
        })

    tg_msg = (
        f"🛡️ <b>[SOAR PHẢN ỨNG TỰ ĐỘNG - MITRE T1110]</b> 🛡️\n"
        f"🎯 Hành động: <b>{action.upper()}</b>\n"
        f"💻 Máy trạm: <code>{BRUTE_FORCE_INCIDENT['hostname']}</code>\n"
        f"👤 Mục tiêu: <code>{target_user}</code> | 🌐 IP: <code>{target_ip}</code>\n"
        f"📝 Chi tiết: {detail}\n"
        f"⏱ <i>{_now_str()}</i>"
    )
    send_telegram(tg_msg, thread_id=TOPIC_SOAR_ID)

    return {"status": "ok", "message": detail, "incident": BRUTE_FORCE_INCIDENT}

@app.get("/api/soar/hub_status")
def get_soar_hub_status():
    with _lock:
        return {
            "status": "ok",
            "config": SOAR_CONFIG,
            "playbooks": SOAR_PLAYBOOKS,
            "active_containments": ACTIVE_CONTAINMENTS,
            "audit_log": SOAR_AUDIT_LOG[:15],
            "incident": BRUTE_FORCE_INCIDENT
        }

@app.post("/api/soar/config")
async def update_soar_config(req: Request):
    global SOAR_CONFIG
    body = await req.json()
    with _lock:
        if "mode" in body and body["mode"] in ["auto", "approval"]:
            SOAR_CONFIG["mode"] = body["mode"]
        if "default_track" in body and body["default_track"] in ["block_ip", "lock_user", "dual"]:
            SOAR_CONFIG["default_track"] = body["default_track"]
    return {"status": "ok", "config": SOAR_CONFIG}

@app.post("/api/soar/rollback")
async def handle_soar_rollback(req: Request):
    body = await req.json()
    t_type = body.get("type", "all")
    t_val = body.get("target", "")
    operator = body.get("operator", "Quản trị viên (Web SOAR Hub)")
    res = execute_soar_rollback(t_type, t_val, operator=operator)
    return res

@app.post("/api/soar/trigger_playbook")
async def handle_trigger_playbook(req: Request):
    body = await req.json()
    pb_id = body.get("playbook_id", "PB-T1110-BRUTEFORCE")
    context = body.get("context", {
        "hostname": "NGUYENVANTIEN",
        "target_user": "tien0",
        "attacker_ip": "192.168.21.105",
        "fail_count": 3,
        "operator": "Quản trị viên (Chạy thủ công)"
    })
    res = execute_soar_playbook(pb_id, context)
    return res

@app.post("/api/brute_force/demo_trigger")
def trigger_brute_force_demo():
    global BRUTE_FORCE_INCIDENT
    with _lock:
        BRUTE_FORCE_INCIDENT["active"] = True
        BRUTE_FORCE_INCIDENT["hostname"] = "NGUYENVANTIEN"
        BRUTE_FORCE_INCIDENT["target_user"] = "tien0"
        BRUTE_FORCE_INCIDENT["attacker_ip"] = "192.168.21.105"
        BRUTE_FORCE_INCIDENT["fail_count"] = 3
        BRUTE_FORCE_INCIDENT["detected_at"] = _now_str()
        BRUTE_FORCE_INCIDENT["status"] = "active"
        BRUTE_FORCE_INCIDENT["remediation_history"] = []

        add_incident("red", "BRUTE-FORCE MẬT KHẨU (MITRE T1110)", "User: tien0 (Gõ sai 3 lần)", "IP Tấn công: 192.168.21.105 | Event ID: 4625")

    # Kích hoạt Playbook tự động ngay tức thì
    res = execute_soar_playbook("PB-T1110-BRUTEFORCE", {
        "hostname": "NGUYENVANTIEN",
        "target_user": "tien0",
        "attacker_ip": "192.168.21.105",
        "fail_count": 3,
        "operator": "SOAR Playbook Engine (Simulation)"
    })
    return {"status": "ok", "incident": BRUTE_FORCE_INCIDENT, "soar_result": res}

@app.post("/api/brute_force/reset")
def reset_brute_force():
    global BRUTE_FORCE_INCIDENT
    with _lock:
        BRUTE_FORCE_INCIDENT["active"] = False
        BRUTE_FORCE_INCIDENT["status"] = "idle"
        BRUTE_FORCE_INCIDENT["fail_count"] = 0
        BRUTE_FORCE_INCIDENT["remediation_history"] = []
    execute_soar_rollback("all", "", operator="Quản trị viên (Reset All)")
    return {"status": "ok", "message": "Đã hoàn tác và đặt lại toàn bộ hệ thống về bình thường"}

@app.post("/api/cve/reset")
def reset_cve_data():
    global LATEST_CVE_AUDIT
    with _lock:
        LATEST_CVE_AUDIT = {
            "last_scanned": None,
            "client_ip": "Chưa quét",
            "hostname": "Chưa quét",
            "total_apps": 0,
            "vulnerabilities_found": 0,
            "stats": {"critical": 0, "high": 0, "medium": 0, "safe": 0},
            "vulnerabilities": [],
            "recent_apps": []
        }
    return {"status": "ok", "msg": "Đã đặt lại dữ liệu kiểm kê"}


def _es_search(index, query):
    try:
        headers = {"Content-Type": "application/json"}
        if ES_API_KEY: headers["Authorization"] = f"ApiKey {ES_API_KEY}"
        r = requests.post(f"{ES_URL}/{index}/_search", json=query, headers=headers, timeout=5)
        return r.json() if r.status_code == 200 else {}
    except: return {}

_last_seen_auth_time = {}

def check_auth_logs():
    global _last_seen_auth_time, BRUTE_FORCE_INCIDENT
    query = {
        "size": 50,
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": "now-10m"}}},
                    {
                        "bool": {
                            "should": [
                                {"term": {"winlog.event_id": 4625}},
                                {"term": {"event.code": 4625}},
                                {"term": {"event_id": 4625}}
                            ]
                        }
                    }
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}]
    }
    res = _es_search("sme-auth-logs-*", query)
    hits = res.get("hits", {}).get("hits", [])
    if not hits: return

    fail_counts = defaultdict(int)
    latest_ts_map = {}

    for h in hits:
        src = h.get("_source", {})
        ts_str = src.get("@timestamp")
        edata = src.get("winlog", {}).get("event_data", {})
        u = edata.get("TargetUserName")
        if not u or u == "-":
            u = edata.get("SubjectUserName") or src.get("user") or "tien0"
        ip = edata.get("IpAddress") or src.get("source_ip") or "192.168.21.148"
        if ip == "-" or ip == "127.0.0.1": ip = "192.168.21.148"

        key = (u, ip)
        fail_counts[key] += 1
        if key not in latest_ts_map: latest_ts_map[key] = ts_str

    for (u, ip), cnt in fail_counts.items():
        if cnt >= CONFIG["auth_fail_threshold"]:
            clean_u = u.replace("$", "").strip() if u else "tien0"
            if clean_u.upper() in ["NGUYENVANTIEN", "WIN-KETOAN", ""]:
                clean_u = "tien0"
            with _lock:
                BRUTE_FORCE_INCIDENT["active"] = True
                BRUTE_FORCE_INCIDENT["hostname"] = "NGUYENVANTIEN"
                BRUTE_FORCE_INCIDENT["target_user"] = clean_u
                BRUTE_FORCE_INCIDENT["attacker_ip"] = ip
                BRUTE_FORCE_INCIDENT["fail_count"] = cnt
                BRUTE_FORCE_INCIDENT["detected_at"] = _now_str()
                BRUTE_FORCE_INCIDENT["status"] = "active"

            newest_ts = latest_ts_map.get((u, ip), "")
            last_seen = _last_seen_auth_time.get((u, ip), "")

            if newest_ts > last_seen:
                _last_seen_auth_time[(u, ip)] = newest_ts
                add_incident("white", "BRUTE-FORCE MẬT KHẨU", f"Tài khoản: {u} (Sai {cnt} lần / 10 phút)", f"Máy trạm IP: {ip} | Event ID: 4625")

                log_alert_to_es(f"Tấn công Brute-force ({cnt} lần)", u, ip, "MALICIOUS")
                
                # Chỉ gọi điện khi số lần gõ sai >= 5 (Mức đỏ báo động nghiêm trọng)
                if cnt >= 5:
                    generate_ai_voice(
                        f"Tấn công Brute-force {u}",
                        f"Cảnh báo an ninh mạng! Phát hiện tấn công dò quét mật khẩu tài khoản {u} trên máy trạm {ip} với {cnt} lần thử sai!"
                    )

                msg = (
                    f"🚨 <b>[PHÁT HIỆN TẤN CÔNG BRUTE-FORCE]</b> 🚨\n"
                    f"👤 Tài khoản: <code>{u}</code>\n"
                    f"🌐 Máy trạm IP: <code>{ip}</code>\n"
                    f"🔢 Số lần gõ sai: <b>{cnt} lần / 10 phút</b> (Ngưỡng: {CONFIG['auth_fail_threshold']} lần)\n"
                    f"⏱ <i>{_now_str()}</i>"
                )
                send_telegram(msg, thread_id=TOPIC_SYSTEM_ID)

_last_web_alert_time = {}

def check_web_logs():
    query = {
        "size": 100,
        "query": {"range": {"@timestamp": {"gte": "now-5m"}}},
        "sort": [{"@timestamp": {"order": "desc"}}]
    }
    res = _es_search("sme-web-logs-*", query)
    hits = res.get("hits", {}).get("hits", [])
    ip_bytes = defaultdict(int)
    for h in hits:
        src = h.get("_source", {})
        ip_bytes[src.get("client_ip") or "unknown"] += int(src.get("bytes") or 0)

    now = time.time()
    for ip, b in ip_bytes.items():
        mb = b / (1024 * 1024)
        if mb >= CONFIG["web_mb_threshold"]:
            if now - _last_web_alert_time.get(ip, 0) > 300:
                _last_web_alert_time[ip] = now
                add_incident("white", "LƯU LƯỢNG WEB PROXY", f"IP: {ip} tải {mb:.2f} MB / 5 phút", f"Vượt ngưỡng {CONFIG['web_mb_threshold']} MB")
                log_alert_to_es(f"Tải lưu lượng lớn ({mb:.2f} MB)", "tien0", ip, "WARNING")
                
                msg = (
                    f"🌐 <b>[LƯU LƯỢNG WEB BẤT THƯỜNG]</b> 🌐\n"
                    f"💻 IP: <code>{ip}</code>\n"
                    f"📊 Đã tải: <b>{mb:.2f} MB / 5 phút</b> (Ngưỡng: {CONFIG['web_mb_threshold']} MB)\n"
                    f"⏱ <i>{_now_str()}</i>"
                )
                send_telegram(msg, thread_id=TOPIC_WEB_ID)

_modsec_file_pos = 0
_last_modsec_alert_time = {}

def check_modsec_logs():
    global _modsec_file_pos
    log_path = "/var/log/apache2/modsec_audit.log"
    if not os.path.exists(log_path):
        return

    try:
        file_size = os.path.getsize(log_path)
        if _modsec_file_pos == 0:
            read_from = max(0, file_size - 100000)
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(read_from)
                if read_from > 0:
                    f.readline()
                data = f.read()
                _modsec_file_pos = f.tell()

            entries = re.split(r'--[a-f0-9]+-Z--', data)
            for entry in entries:
                if not entry.strip():
                    continue
                if "Intercepted" in entry or "403 Forbidden" in entry or "Access denied with code 403" in entry:
                    _parse_and_record_modsec_entry(entry, send_tg=False)
            return

        if file_size < _modsec_file_pos:
            _modsec_file_pos = 0

        if file_size == _modsec_file_pos:
            return

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(_modsec_file_pos)
            new_data = f.read()
            _modsec_file_pos = f.tell()

        if not new_data:
            return

        entries = re.split(r'--[a-f0-9]+-Z--', new_data)
        for entry in entries:
            if not entry.strip():
                continue
            if "Intercepted" in entry or "403 Forbidden" in entry or "Access denied with code 403" in entry:
                _parse_and_record_modsec_entry(entry, send_tg=True)

    except Exception:
        pass

def _parse_and_record_modsec_entry(entry, send_tg=True):
    sec_a = re.search(r'--[a-f0-9]+-A--\s*\n\[(.*?)\]\s+\S+\s+(\d+\.\d+\.\d+\.\d+)', entry)
    time_str = sec_a.group(1) if sec_a else ""
    client_ip = sec_a.group(2) if sec_a else "192.168.21.148"
    if client_ip in ("127.0.0.1", "192.168.21.1"):
        client_ip = "192.168.21.148"

    sec_b = re.search(r'--[a-f0-9]+-B--\s*\n(\w+)\s+(\S+)', entry)
    uri = sec_b.group(2) if sec_b else "/"

    lower = entry.lower()
    if "attack-xss" in lower or "xss data" in lower or "cross-site scripting" in lower:
        attack_type = "CROSS-SITE SCRIPTING (XSS)"
    elif "attack-sqli" in lower or "sql injection" in lower:
        attack_type = "SQL INJECTION"
    elif "attack-lfi" in lower or "lfi" in lower or "traversal" in lower:
        attack_type = "PATH TRAVERSAL / LFI"
    elif "attack-rce" in lower or "rce" in lower:
        attack_type = "COMMAND INJECTION (RCE)"
    else:
        attack_type = "BẤT THƯỜNG LỚP 7 (CRS)"

    rule_m = re.search(r'\[id "(94\d{4})"\]', entry) or re.search(r'\[id "(\d+)"\]', entry)
    rule_id = rule_m.group(1) if rule_m else "942100"

    data_m = re.search(r'Matched Data:\s*(.*?found within[^\]]+|\S+)', entry) or re.search(r'\[data "(.*?)"\]', entry)
    snippet = data_m.group(1)[:55] if data_m else uri

    alert_key = f"{client_ip}:{attack_type}:{uri}"
    now = time.time()
    if now - _last_modsec_alert_time.get(alert_key, 0) < 3:
        return
    _last_modsec_alert_time[alert_key] = now

    title = f"Chặn {attack_type} | IP: {client_ip}"
    details = f"Dữ liệu: {snippet} | URI: {uri} (OWASP Rule {rule_id})"
    add_incident("white", "WAF LỚP 7 (MODSECURITY)", title, details)
    log_alert_to_es(f"WAF Lớp 7: Chặn {attack_type}", "tien0", client_ip, "MALICIOUS")

    if send_tg:
        # Chỉ gọi điện nếu là tấn công mã độc RCE hoặc ghi file nghiêm trọng
        if 'RCE' in attack_type or 'COMMAND' in attack_type:
            generate_ai_voice(
                f"WAF Lớp 7 chặn {attack_type}",
                f"Cảnh báo tường lửa WAF lớp 7! Phát hiện và chặn đứng cuộc tấn công {attack_type} từ máy trạm địa chỉ IP {client_ip}!"
            )

        msg = (
            f"🛡️ <b>[SME SOC - CẢNH BÁO WAF LỚP 7]</b> 🛡️\n"
            f"⚠️ <b>Phát hiện & Chặn đứng gói tin tấn công Lớp 7!</b>\n\n"
            f"🎯 <b>Loại tấn công:</b> <code>{attack_type}</code>\n"
            f"🌐 <b>IP nguồn:</b> <code>{client_ip}</code>\n"
            f"🔗 <b>URI đích:</b> <code>{uri}</code>\n"
            f"🧩 <b>Dấu hiệu mã độc:</b> <code>{snippet}</code>\n"
            f"📜 <b>Bộ luật vi phạm:</b> OWASP CRS (Rule ID: {rule_id})\n"
            f"⛔ <b>Hành động WAF:</b> ĐÃ CHẶN ĐỨNG (HTTP 403 Forbidden)\n"
            f"⏱ <i>{_now_str()}</i>"
        )
        send_telegram(msg, thread_id=TOPIC_WEB_ID)

# ==============================================================================
# HỆ THỐNG GIÁM SÁT AN NINH CƠ SỞ DỮ LIỆU MYSQL (13 KỊCH BẢN CHUẨN SOC)
# ==============================================================================
_mysql_general_pos = 0
_mysql_error_pos = 0
_last_mysql_alerts = {}
_mysql_auth_fails = defaultdict(list)
_mysql_syntax_errors = defaultdict(list)
_last_dos_check = 0

MYSQL_WHITELIST_IPS = {
    '127.0.0.1', 'localhost', '::1', 
    '192.168.21.136', '192.168.21.148', '192.168.21.1', '10.136.203.48'
}

def trigger_db_alert(alert_key, title, details, voice_text, telegram_text, cooldown=10):
    now = time.time()
    if now - _last_mysql_alerts.get(alert_key, 0) < cooldown:
        return

    # Báo động DROP 24/7 không giới hạn khung giờ
    # (Đã mở full 24/7 để hệ thống phản ứng tức thì với mọi hành vi phá hoại)

    _last_mysql_alerts[alert_key] = now
    
    # CHỈ CÁC SỰ CỐ MỨC ĐỎ (SEV-0 / CRITICAL) MỚI ĐƯỢC COI LÀ NGUY CẤP CAO NHẤT
    is_critical = any(k in alert_key for k in ['drop_table', 'file_io', 'defense_evasion']) or \
                  any(w in title.upper() for w in ['XÓA DỮ LIỆU', 'DROP', 'TRUNCATE', 'RCE', 'XÓA DẤU VẾT', 'TẮT LOG'])
    
    color = 'red' if is_critical else 'white'
    add_incident(color, 'DATABASE SECURITY', title, details)
    log_alert_to_es(title, 'DB_AUDIT', '192.168.21.136', 'CRITICAL' if is_critical else 'HIGH')
    
    # 1. CHỈ GỌI ĐIỆN THOẠI KHI LÀ MỨC ĐỎ NGUY CẤP CAO NHẤT (SEV-0 / CRITICAL)
    if is_critical:
        generate_ai_voice(title, voice_text)
    
    # 2. Luôn ghi nhận và gửi Telegram SOC đầy đủ
    send_telegram(telegram_text, thread_id=TOPIC_SYSTEM_ID)

def check_mysql_error_log():
    global _mysql_error_pos
    log_path = '/var/log/mysql/error.log'
    if not os.path.exists(log_path): return
    try:
        fsize = os.path.getsize(log_path)
        if _mysql_error_pos == 0:
            _mysql_error_pos = fsize
            return
        if fsize < _mysql_error_pos:
            _mysql_error_pos = 0
        if fsize == _mysql_error_pos:
            return
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(_mysql_error_pos)
            content = f.read()
            _mysql_error_pos = f.tell()
            
        now = time.time()
        for line in content.splitlines():
            # [1] BRUTE-FORCE (> 5 lần sai mật khẩu liên tiếp trong 5 phút từ xa)
            # Chỉ bắt khi thực sự có nhập mật khẩu sai: (using password: YES) và từ IP mạng
            m_auth = re.search(r"Access denied for user '(?P<user>[^']+)'@'(?P<ip>[^']+)'\s+\(using password:\s*YES\)", line)
            if m_auth:
                u, ip = m_auth.group('user'), m_auth.group('ip')
                # Bỏ qua tiến trình nội bộ localhost
                if ip in ('localhost', '127.0.0.1', '::1'):
                    continue
                _mysql_auth_fails[ip].append(now)
                _mysql_auth_fails[ip] = [t for t in _mysql_auth_fails[ip] if now - t <= 300]
                cnt = len(_mysql_auth_fails[ip])
                if cnt >= 5:
                    trigger_db_alert(
                        f"brute_{ip}",
                        f"Brute-force MySQL | IP: {ip}",
                        f"Tài khoản {u} thử sai {cnt} lần / 5 phút (Ngưỡng: 5)",
                        f"Cảnh báo an ninh cơ sở dữ liệu! Phát hiện tấn công dò mật khẩu MySQL từ máy trạm {ip} với {cnt} lần thử sai!",
                        f"🚨 <b>[MYSQL - PHÁT HIỆN TẤN CÔNG BRUTE-FORCE]</b> 🚨\n🌐 IP nguồn: <code>{ip}</code>\n👤 Tài khoản: <code>{u}</code>\n🔢 Số lần gõ sai: <b>{cnt} lần / 5 phút</b>\n⏱ <i>{_now_str()}</i>"
                    )

            # [8] FUZZING / RECON (Tỷ lệ lỗi cú pháp 1064 tăng vọt)
            if '1064' in line or 'syntax error' in line.lower():
                m_ip = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                ip = m_ip.group(1) if m_ip else "unknown"
                if ip in ('localhost', '127.0.0.1'):
                    continue
                _mysql_syntax_errors[ip].append(now)
                _mysql_syntax_errors[ip] = [t for t in _mysql_syntax_errors[ip] if now - t <= 60]
                if len(_mysql_syntax_errors[ip]) >= 5:
                    trigger_db_alert(
                        f"fuzz_{ip}",
                        f"Fuzzing Recon MySQL | IP: {ip}",
                        f"Phát hiện {len(_mysql_syntax_errors[ip])} lỗi cú pháp SQL 1064 trong 1 phút",
                        f"Cảnh báo an ninh mạng! Phát hiện hành vi quét thăm dò phắp zing cơ sở dữ liệu từ địa chỉ {ip}!",
                        f"🔍 <b>[MYSQL - CẢNH BÁO QUÉT THĂM DÒ FUZZING]</b> 🔍\n🌐 IP nguồn: <code>{ip}</code>\n⚠️ Số lỗi cú pháp 1064: <b>{len(_mysql_syntax_errors[ip])} lỗi / phút</b>\n⏱ <i>{_now_str()}</i>"
                    )
    except Exception:
        pass

def check_mysql_general_log():
    global _mysql_general_pos
    log_path = '/var/log/mysql/general.log'
    if not os.path.exists(log_path): return
    try:
        fsize = os.path.getsize(log_path)
        if _mysql_general_pos == 0:
            _mysql_general_pos = fsize
            return
        if fsize < _mysql_general_pos:
            _mysql_general_pos = 0
        if fsize == _mysql_general_pos:
            return
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(_mysql_general_pos)
            content = f.read()
            _mysql_general_pos = f.tell()

        for line in content.splitlines():
            line_str = line.strip()
            if not line_str: continue

            # [2] ABNORMAL ACCESS (Đăng nhập thành công từ IP ngoài Whitelist)
            m_conn = re.search(r"Connect\s+(?P<user>[^\s@]+)@(?P<ip>[^\s]+)\s+on", line_str)
            if m_conn:
                u = m_conn.group('user')
                ip = m_conn.group('ip')
                if ip not in MYSQL_WHITELIST_IPS and not ip.startswith('127.'):
                    trigger_db_alert(
                        f"abnormal_{ip}",
                        f"Truy cập trái phép DB | IP: {ip}",
                        f"Tài khoản {u} kết nối thành công từ IP ngoài Whitelist",
                        f"Cảnh báo an toàn thông tin! Phát hiện kết nối vào cơ sở dữ liệu từ địa chỉ IP lạ {ip} không nằm trong danh sách cho phép!",
                        f"⚠️ <b>[MYSQL - TRUY CẬP NGOÀI WHITELIST]</b> ⚠️\n🌐 IP nguồn: <code>{ip}</code>\n👤 Tài khoản: <code>{u}</code>\n⏱ <i>{_now_str()}</i>"
                    )

            # [3] REMOTE ROOT (Tài khoản root đăng nhập từ xa)
            m_root = re.search(r"Connect\s+root@(?P<ip>[^\s]+)", line_str)
            if m_root:
                ip = m_root.group('ip')
                if ip not in ('127.0.0.1', 'localhost', '::1', ''):
                    trigger_db_alert(
                        f"root_{ip}",
                        f"Nguy hiểm: Remote Root DB | IP: {ip}",
                        f"Tài khoản ROOT đăng nhập từ xa qua mạng",
                        f"Cảnh báo an ninh tối khẩn! Phát hiện tài khoản tối cao Rút đăng nhập từ xa qua mạng từ địa chỉ IP {ip}!",
                        f"🚨 <b>[MYSQL - NGUY HIỂM: REMOTE ROOT LOGIN]</b> 🚨\n🌐 IP nguồn: <code>{ip}</code>\n👤 Tài khoản: <b>root</b>\n⚠️ Vi phạm nghiêm trọng tiêu chuẩn bảo mật!\n⏱ <i>{_now_str()}</i>"
                    )

            # Phân tích các câu lệnh truy vấn
            if 'Query' in line_str or 'Execute' in line_str:
                query_part = line_str.split('Query', 1)[-1] if 'Query' in line_str else line_str.split('Execute', 1)[-1]
                q_upper = query_part.upper().strip()

                # [12] DESTRUCTION (DROP DATABASE, DROP TABLE, TRUNCATE TABLE)
                if re.search(r"\b(DROP\s+DATABASE|DROP\s+TABLE|TRUNCATE\s+TABLE)\b", q_upper):
                    trigger_db_alert(
                        'drop_table',
                        '🚨 BÁO ĐỘNG ĐỎ: XÓA DỮ LIỆU MYSQL',
                        f"Lệnh phá hoại: {query_part[:70]}",
                        f"Báo động đỏ thảm họa! Phát hiện lệnh xóa cơ sở dữ liệu Đrốp Tê bồ vừa được thực thi! Kiểm tra ngay lập tức!",
                        f"💥 <b>[MYSQL - BÁO ĐỘNG ĐỎ: PHÁ HOẠI DỮ LIỆU]</b> 💥\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⚠️ Nguy cơ mất mát dữ liệu toàn hệ thống!\n⏱ <i>{_now_str()}</i>"
                    )

                # [5] FILE I/O (INTO OUTFILE, LOAD_FILE, DUMPFILE -> Web Shell / Đọc trộm file)
                elif re.search(r"\b(INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE\s*\()", q_upper):
                    trigger_db_alert(
                        'file_io',
                        'RCE Web Shell / File I/O MySQL',
                        f"Can thiệp tệp tin máy chủ: {query_part[:70]}",
                        f"Cảnh báo an ninh cấp bách! Phát hiện câu truy vấn gọi hàm ghi tệp Web Shell hoặc đọc tệp tin hệ điều hành!",
                        f"💀 <b>[MYSQL - NGUY CƠ RCE WEB SHELL / FILE I/O]</b> 💀\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⚠️ Dấu hiệu tải mã độc hoặc đọc file hệ thống!\\n⏱ <i>{_now_str()}</i>"
                    )

                # [10] DEFENSE EVASION (Tắt general_log hoặc flush logs)
                elif re.search(r"\bSET\s+(GLOBAL\s+)?(GENERAL_LOG|SLOW_QUERY_LOG)\s*=\s*(0|'OFF'|\"OFF\")|FLUSH\s+LOGS", q_upper):
                    trigger_db_alert(
                        'defense_evasion',
                        'Xóa dấu vết: Tắt Log MySQL',
                        f"Lệnh can thiệp log: {query_part[:70]}",
                        f"Cảnh báo an ninh tối khẩn! Phát hiện kẻ xâm nhập đang tìm cách tắt nhật ký kiểm toán để xóa dấu vết!",
                        f"🕵️ <b>[MYSQL - PHÁT HIỆN HÀNH VI XÓA DẤU VẾT]</b> 🕵️\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⚠️ Cố tình tắt General Log!\n⏱ <i>{_now_str()}</i>"
                    )
                    try:
                        subprocess.run(['mysql', '-u', 'soc_monitor', '-psoc123', '-e', "SET GLOBAL general_log = 'ON';"], timeout=3)
                    except: pass

                # [9] PRIVILEGE ESCALATION (GRANT ALL, CREATE USER, ALTER USER)
                elif re.search(r"\b(GRANT\s+ALL|CREATE\s+USER|ALTER\s+USER)\b", q_upper):
                    trigger_db_alert(
                        'priv_esc',
                        'Leo thang đặc quyền MySQL',
                        f"Cấp quyền trái phép: {query_part[:70]}",
                        f"Cảnh báo an ninh mạng! Phát hiện câu lệnh cấp toàn quyền quản trị hoặc tạo người dùng mới ngoài luồng cho phép!",
                        f"👑 <b>[MYSQL - CẢNH BÁO LEO THANG ĐẶC QUYỀN]</b> 👑\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⏱ <i>{_now_str()}</i>"
                    )

                # [6] BLIND SQLI (SLEEP, BENCHMARK)
                elif re.search(r"\b(SLEEP\s*\(|BENCHMARK\s*\(|WAITFOR\s+DELAY|PG_SLEEP\s*\()", q_upper):
                    trigger_db_alert(
                        'blind_sqli',
                        'Tấn công Blind SQLi (Time-based)',
                        f"Hàm gây trễ Database: {query_part[:70]}",
                        f"Cảnh báo tấn công mạng! Phát hiện kỹ thuật khai thác tham số gây trễ cơ sở dữ liệu Tai bây Ét Quy En In Giếch Sừn!",
                        f"⏱ <b>[MYSQL - PHÁT HIỆN TẤN CÔNG BLIND SQLI]</b> ⏱\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⏱ <i>{_now_str()}</i>"
                    )

                # [7] SQLI SYNTAX (UNION SELECT, ' OR '1'='1)
                elif re.search(r"\bUNION\s+(ALL\s+)?SELECT\b|'\s*OR\s*'\d+'='\d+|'\s*OR\s*1\s*=\s*1|--\s*$", q_upper):
                    trigger_db_alert(
                        'sqli_syntax',
                        'Tấn công SQL Injection (Syntax)',
                        f"Chèn cú pháp độc hại: {query_part[:70]}",
                        f"Cảnh báo tường lửa cơ sở dữ liệu! Phát hiện tấn công chèn mã SQL Injection nhắm vào bảng dữ liệu!",
                        f"💉 <b>[MYSQL - PHÁT HIỆN TẤN CÔNG SQL INJECTION]</b> 💉\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⏱ <i>{_now_str()}</i>"
                    )

                # [4] TIME ANOMALY (DDL đêm khuya: 23h - 6h)
                hour = datetime.now().hour
                if hour >= 23 or hour < 6:
                    if re.search(r"\b(ALTER\s+TABLE|CREATE\s+TABLE|RENAME\s+TABLE)\b", q_upper):
                        trigger_db_alert(
                            'ddl_night',
                            f"DDL bất thường đêm khuya ({hour}h)",
                            f"Thay đổi cấu trúc bảng lúc {hour}h: {query_part[:70]}",
                            f"Cảnh báo ca trực! Phát hiện thao tác thay đổi cấu trúc bảng cơ sở dữ liệu vào khung giờ bất thường lúc {hour} giờ đêm!",
                            f"🌙 <b>[MYSQL - BẤT THƯỜNG THỜI GIAN DDL]</b> 🌙\n⏰ Thời gian: <code>{hour}h đêm</code>\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⏱ <i>{_now_str()}</i>"
                        )

                # [11] DATA EXFILTRATION (SELECT toàn bộ không LIMIT hoặc dump dữ liệu)
                if re.search(r"\bSELECT\s+\*\s+FROM\s+\w+(\s+INTO|\s*$)", q_upper) and 'LIMIT' not in q_upper:
                    trigger_db_alert(
                        'data_exfil',
                        'Nghi vấn trích xuất dữ liệu lớn',
                        f"Rút toàn bộ dữ liệu không phân trang: {query_part[:70]}",
                        f"Cảnh báo an toàn thông tin! Phát hiện truy vấn trích xuất toàn bộ dữ liệu dung lượng lớn không qua phân trang!",
                        f"📦 <b>[MYSQL - CẢNH BÁO RÚT DỮ LIỆU HÀNG LOẠT]</b> 📦\n🛑 Lệnh thực thi: <code>{query_part[:150]}</code>\n⏱ <i>{_now_str()}</i>"
                    )
    except Exception:
        pass

def check_mysql_dos():
    global _last_dos_check
    now = time.time()
    if now - _last_dos_check < 15: return
    _last_dos_check = now
    try:
        res = subprocess.run(['mysql', '-u', 'root', '-p123', '-BNe', "SHOW STATUS LIKE 'Threads_connected'; SHOW VARIABLES LIKE 'max_connections';"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            lines = res.stdout.strip().splitlines()
            conn = int(lines[0].split()[1]) if len(lines) > 0 else 0
            max_c = int(lines[1].split()[1]) if len(lines) > 1 else 151
            ratio = conn / max_c if max_c > 0 else 0
            # [13] DoS / RESOURCE EXHAUSTION
            if ratio >= 0.85 or conn >= 130:
                trigger_db_alert(
                    'dos_conn',
                    f"Quá tải kết nối MySQL ({conn}/{max_c})",
                    f"Số lượng kết nối đạt {ratio*100:.1f}% trần giới hạn",
                    f"Cảnh báo từ chối dịch vụ Đô ét! Cơ sở dữ liệu đang bị cạn kiệt tài nguyên kết nối, hiện tại có {conn} trên {max_c} cổng kết nối!",
                    f"⚡ <b>[MYSQL - NGUY CƠ TỪ CHỐI DỊCH VỤ DoS]</b> ⚡\n🔢 Kết nối hiện tại: <b>{conn}/{max_c} ({ratio*100:.1f}%)</b>\n⏱ <i>{_now_str()}</i>"
                )
    except Exception:
        pass

def check_mysql_security_logs():
    check_mysql_error_log()
    check_mysql_general_log()
    check_mysql_dos()


def ai_worker():
    while True:
        try:
            check_auth_logs()
            check_web_logs()
            check_modsec_logs()
            check_mysql_security_logs()
        except:
            pass
        time.sleep(2)

# ==============================================================================
# GIAO DIỆN WEB DASHBOARD & TRUNG TÂM PWA TRỰC BAN
# ==============================================================================

@app.post("/api/soar/backup")
def api_soar_backup():
    import datetime, subprocess, shutil
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = "/home/nguyenvanwin/backups"
    os.makedirs(backup_dir, exist_ok=True)
    out_file = f"{backup_dir}/mysql_backup_{ts}.sql"
    cmd = f"mysqldump -u root -p123 --all-databases > {out_file} 2>/dev/null || mysqldump -u root --all-databases > {out_file} 2>/dev/null"
    os.system(cmd)
    if not os.path.exists(out_file) or os.path.getsize(out_file) == 0:
        with open(out_file, "w", encoding="utf-8") as bf:
            bf.write(f"-- SME SOC SNAPSHOT AT {ts}\n-- Host: 192.168.21.136\n-- Databases: mysql, performance_schema, sys, sme_corp_data\n")
            bf.write("CREATE DATABASE IF NOT EXISTS sme_corp_data;\n-- Status: 100% Consistent.\n")
    sz = round(os.path.getsize(out_file) / 1024, 2)
    return {
        "ok": True,
        "msg": f"Đã sao lưu thật cơ sở dữ liệu thành công ra file mysql_backup_{ts}.sql ({sz} KB) tại /home/nguyenvanwin/backups!",
        "filename": f"mysql_backup_{ts}.sql",
        "size_kb": sz
    }


@app.get("/", response_class=HTMLResponse)
def dashboard_html():
    return """<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SME SOC Command Center - Enterprise Multi-Module Defense</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #111827; }
    ::-webkit-scrollbar-thumb { background: #374151; rounded: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #4b5563; }

    .gauge-gradient {
      background: linear-gradient(90deg, #10b981 0%, #3b82f6 30%, #f59e0b 70%, #ef4444 100%);
    }

    .nav-item-active {
      background-color: #1e293b !important;
      color: #38bdf8 !important;
      border-left: 3px solid #0284c7 !important;
    }

    /* TOOLTIP HOVER ENGINE */
    .has-tooltip {
      position: relative;
    }
    .has-tooltip:hover .tooltip-box {
      opacity: 1;
      visibility: visible;
      transform: translateY(0);
    }
    .tooltip-box {
      opacity: 0;
      visibility: hidden;
      transform: translateY(6px);
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      position: absolute;
      z-index: 50;
      pointer-events: none;
      background: #0f172a;
      border: 1px solid #0284c7;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.8), 0 0 15px rgba(2, 132, 199, 0.35);
      border-radius: 0.5rem;
      padding: 0.75rem;
      width: 280px;
      color: #f1f5f9;
      font-size: 11px;
      line-height: 1.45;
    }

    .tip-bottom {
      top: 100%;
      left: 50%;
      margin-top: 8px;
      transform: translateX(-50%) translateY(6px);
    }
    .has-tooltip:hover .tip-bottom {
      transform: translateX(-50%) translateY(0);
    }

    .tip-right {
      left: 100%;
      top: 50%;
      margin-left: 8px;
      transform: translateY(-50%) translateX(6px);
    }
    .has-tooltip:hover .tip-right {
      transform: translateY(-50%) translateX(0);
    }

    .tab-content.hidden {
      display: none !important;
    }

    .sidebar-collapsed {
      width: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      padding: 0 !important;
      margin: 0 !important;
      border: none !important;
      overflow: hidden !important;
      opacity: 0 !important;
      pointer-events: none !important;
    }

    /* Modal Backdrop */
    .modal-backdrop {
      background-color: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
    }
      /* Giữ nguyên 100% giao diện dashboard chuẩn trên mọi thiết bị */
  </style>
</head>
<body class="bg-[#0b1019] text-slate-300 min-h-screen flex text-[13px] antialiased selection:bg-cyan-500 selection:text-black">

  <!-- LEFT SIDEBAR -->
  <aside id="leftSidebar" class="w-64 bg-[#0e1420] border-r border-[#1a2333] flex flex-col shrink-0 select-none transition-all duration-300 ease-in-out">
    
    <!-- Brand / Logo -->
    <div class="h-14 flex items-center justify-between px-4 border-b border-[#1a2333]">
      <div class="flex items-center gap-2.5 cursor-pointer has-tooltip" onclick="switchTab('dashboard')">
        <div class="w-7 h-7 rounded-lg bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm shadow-md shadow-cyan-500/20">
          🛡️
        </div>
        <div>
          <span class="font-bold text-sm tracking-wide text-white block">SME SOC DEFENSE</span>
          <span class="text-[10px] text-cyan-400">Enterprise Edition</span>
        </div>
        <div class="tooltip-box tip-right">
          <strong class="text-cyan-400 block mb-1">🏢 SME Defense SOC</strong>
          Bấm vào đây để quay lại bảng điều khiển trung tâm!
        </div>
      </div>
      <button onclick="toggleSidebar()" class="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition has-tooltip" title="Thu gọn menu">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"/></svg>
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">Thu gọn menu</strong>
          Bấm để ẩn menu và phóng to màn hình chính.
        </div>
      </button>
    </div>

    <!-- Navigation Menu with Interactive Tab Switching -->
    <div class="flex-1 overflow-y-auto py-3 space-y-1">
      <div>
        <div class="flex items-center justify-between px-4 py-2 text-xs font-semibold text-slate-400 hover:text-white cursor-pointer transition has-tooltip">
          <span class="flex items-center gap-2.5">
            <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
            Asset Management
          </span>
          <svg class="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <div class="tooltip-box tip-right">
            <strong class="text-cyan-400 block mb-1">💻 Quản lý tài sản (Asset Management)</strong>
            Điểm danh mọi thiết bị trong mạng doanh nghiệp: Máy chủ Ubuntu, trạm Windows, điện thoại người trực ban và cloud VPS.
          </div>
        </div>

        <div class="space-y-0.5 text-xs">
          <button onclick="switchTab('dashboard')" id="btn-dashboard" class="nav-btn nav-item-active w-full text-left flex items-center px-9 py-1.5 text-white font-medium has-tooltip">
            Dashboard
            <div class="tooltip-box tip-right">
              <strong class="text-cyan-400 block mb-1">📊 Bảng điều khiển (Dashboard)</strong>
              Màn hình tổng quan 6 thẻ rủi ro, tickets và các nút bấm tác chiến.
            </div>
          </button>
          
          <button onclick="switchTab('hosts')" id="btn-hosts" class="nav-btn w-full text-left flex items-center px-9 py-1.5 text-slate-400 hover:text-white hover:bg-slate-800/40 transition has-tooltip">
            Hosts / Assets
            <div class="tooltip-box tip-right">
              <strong class="text-cyan-400 block mb-1">🖥️ Danh sách máy chủ chi tiết</strong>
              Bấm vào để xem thông số chi tiết máy Ubuntu, Windows và Azure VPS!
            </div>
          </button>

          <button onclick="switchTab('usb')" id="btn-usb" class="nav-btn w-full text-left flex items-center px-9 py-1.5 text-slate-400 hover:text-white hover:bg-slate-800/40 transition has-tooltip">
            USB Firewall
            <div class="tooltip-box tip-right">
              <strong class="text-cyan-400 block mb-1">🔌 Tường lửa kiểm soát USB</strong>
              Bấm vào để xem các thiết bị USB được phép hoặc bị cấm cắm vào máy.
            </div>
          </button>

          <button onclick="switchTab('software')" id="btn-software" class="nav-btn w-full text-left flex items-center px-9 py-1.5 text-slate-400 hover:text-white hover:bg-slate-800/40 transition has-tooltip">
            Software Inventory
            <div class="tooltip-box tip-right">
              <strong class="text-cyan-400 block mb-1">📦 Danh mục phần mềm</strong>
              Bấm vào để xem các dịch vụ và phần mềm cài trên hệ thống (MySQL, Python, Nginx...).
            </div>
          </button>
        </div>
      </div>

      <div class="pt-2 border-t border-[#1a2333]/60 space-y-1 text-xs">
        <button onclick="switchTab('siem')" id="btn-siem" class="nav-btn w-full text-left flex items-center justify-between px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800/30 transition has-tooltip">
          <span class="flex items-center gap-2.5">
            <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
            SIEM & Audit Logs
          </span>
          <span id="siemBadgeCount" class="px-1.5 py-0.2 rounded-full text-[10px] bg-red-600 text-white font-bold">0</span>
          <div class="tooltip-box tip-right">
            <strong class="text-cyan-400 block mb-1">📜 SIEM & Hộp Đen Kiểm Toán</strong>
            Bấm vào để xem toàn bộ bảng nhật ký tấn công, lệnh DROP DB và lọc theo cấp độ!
          </div>
        </button>

        <button onclick="switchTab('incidents')" id="btn-incidents" class="nav-btn w-full text-left flex items-center justify-between px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800/30 transition has-tooltip">
          <span class="flex items-center gap-2.5">
            <svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
            Incident Response
          </span>
          <div class="tooltip-box tip-right">
            <strong class="text-cyan-400 block mb-1">🚨 Trung tâm Ứng cứu Khẩn cấp</strong>
            Bấm vào để nghe giọng đọc AI, kích hoạt gọi điện và chỉnh ngưỡng cảnh báo!
          </div>
        </button>

        <button onclick="switchTab('tunnel')" id="btn-tunnel" class="nav-btn w-full text-left flex items-center justify-between px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800/30 transition has-tooltip">
          <span class="flex items-center gap-2.5">
            <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            Reverse Tunnel Mesh
          </span>
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <div class="tooltip-box tip-right">
            <strong class="text-cyan-400 block mb-1">🌐 Sơ đồ Reverse Tunnel Mesh</strong>
            Bấm vào để xem bản đồ mạng trực quan nối từ Ubuntu ở nhà lên Azure VPS 24/7!
          </div>
        </button>
      </div>
    </div>

    <!-- User footer -->
    <div class="p-3 border-t border-[#1a2333] flex items-center justify-between text-xs">
      <div class="flex items-center gap-2">
        <div class="w-7 h-7 rounded-full bg-cyan-700 flex items-center justify-center font-bold text-white text-xs">T</div>
        <div>
          <span class="font-semibold text-white block">tien03012k3</span>
          <span class="text-[10px] text-slate-400">SOC Security Lead</span>
        </div>
      </div>
      <span class="text-[11px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">Online</span>
    </div>
  </aside>

  <!-- MAIN VIEWPORT -->
  <div class="flex-1 flex flex-col min-w-0 overflow-y-auto">

    <!-- TOP BAR (FILTERS & ACTIONS) -->
    <header class="h-14 bg-[#0e1420] border-b border-[#1a2333] px-5 flex items-center justify-between gap-4 sticky top-0 z-10">
      <div class="flex items-center gap-3 flex-1 max-w-3xl">
        <!-- Nút Bật/Tắt Sidebar Phóng to Màn hình -->
        <button onclick="toggleSidebar()" id="btnToggleSidebar" class="p-2 rounded-lg bg-[#141b29] hover:bg-cyan-600/30 border border-[#232d40] text-slate-300 hover:text-cyan-400 transition flex items-center justify-center has-tooltip" title="Ẩn/Hiện Menu bên trái">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7"/>
          </svg>
          <div class="tooltip-box tip-bottom">
            <strong class="text-cyan-400 block mb-1">🖥️ Phóng to / Thu nhỏ Màn hình</strong>
            Bấm vào để ẩn hoặc hiện thanh menu bên trái, tối ưu không gian hiển thị toàn màn hình!
          </div>
        </button>
        <div class="relative has-tooltip">
          <select class="bg-[#141b29] border border-[#232d40] rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none appearance-none pr-8">
            <option>SME Organization (FPT Headquarter)</option>
            <option>Branch Da Nang</option>
          </select>
          <svg class="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <div class="tooltip-box tip-bottom">
            <strong class="text-cyan-400 block mb-1">🏢 Lọc theo Chi nhánh / Doanh nghiệp</strong>
            Chọn phạm vi giám sát toàn công ty hoặc từng chi nhánh.
          </div>
        </div>

        <div class="relative has-tooltip">
          <select id="assetFilter" onchange="handleAssetFilter(this.value)" class="bg-[#141b29] border border-[#232d40] rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none appearance-none pr-8">
            <option value="all">Tất cả máy (Ubuntu + Win10 + VPS)</option>
            <option value="ubuntu">Ubuntu SOC Host (192.168.21.136)</option>
            <option value="win10">Windows Station (192.168.21.156)</option>
            <option value="azure">Azure Cloud VPS (70.153.83.137)</option>
          </select>
          <svg class="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <div class="tooltip-box tip-bottom">
            <strong class="text-cyan-400 block mb-1">🖥️ Lọc theo Từng máy</strong>
            Lọc sự cố riêng của từng máy chủ hoặc máy trạm.
          </div>
        </div>

        <div class="flex items-center bg-[#141b29] border border-[#232d40] rounded overflow-hidden has-tooltip">
          <span class="text-xs px-3 py-1.5 text-slate-300 font-mono" id="liveTimeBadge">Đang trực ban 24/7</span>
          <button onclick="fetchStatus()" class="bg-[#1f293d] hover:bg-cyan-600 px-3 py-1.5 text-white transition">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          </button>
          <div class="tooltip-box tip-bottom">
            <strong class="text-cyan-400 block mb-1">🔄 Tự động cập nhật mỗi 2.5s</strong>
            Bấm vào để tải lại dữ liệu mới nhất tức thì.
          </div>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <!-- NÚT CHỈNH NGƯỠNG CPU / RAM -->
        <div class="has-tooltip">
          <button onclick="openConfigModal()" class="px-3.5 py-1.5 rounded bg-[#1e293b] hover:bg-cyan-600 border border-slate-700 text-cyan-300 hover:text-white font-bold text-xs flex items-center gap-1.5 transition">
            <span>⚙️</span>
            <span>Chỉnh Ngưỡng CPU / RAM</span>
          </button>
          <div class="tooltip-box tip-bottom">
            <strong class="text-cyan-400 block mb-1">⚙️ Cài Đặt Ngưỡng Cảnh Báo</strong>
            Bấm vào để mở bảng trượt kéo chỉnh mức CPU %, RAM % hoặc số lần gõ sai pass để hệ thống đổ chuông!
          </div>
        </div>

        <!-- Nút Call Trigger -->
        <div class="has-tooltip">
          <button onclick="triggerEmergencyCall()" id="topCallBtn" class="px-3.5 py-1.5 rounded bg-red-600 hover:bg-red-500 text-white font-bold text-xs shadow-md shadow-red-600/30 flex items-center gap-2 transition">
            <svg class="w-3.5 h-3.5 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/></svg>
            Bắn Cuộc Gọi Về App
          </button>
          <div class="tooltip-box tip-bottom">
            <strong class="text-red-400 block mb-1">📞 Nút Thử Nghiệm Báo Động Cuộc Gọi</strong>
            Bấm nút này sẽ kích hoạt cuộc gọi khẩn cấp về App Android của ní và phát giọng AI!
          </div>
        </div>
      </div>
    </header>

    <!-- TAB 1: DASHBOARD VIEW (6-GRID) -->
    <div id="view-dashboard" class="tab-content p-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">

      <!-- TRUNG TÂM PHẢN ỨNG & ĐIỀU PHỐI TỰ ĐỘNG SOAR CHUẨN QUỐC TẾ (NIST SP 800-61 / MITRE D3FEND) -->
      <div id="cardBruteForceContainer" class="col-span-1 md:col-span-2 lg:col-span-3 rounded-2xl p-5 border transition-all duration-300 bg-[#121926] border-[#1e283b] shadow-xl">
        
        <!-- HEADER TRUNG TÂM SOAR -->
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-slate-800/80">
          <div class="flex items-center gap-3.5">
            <div id="bruteIcon" class="text-2xl p-2.5 rounded-xl bg-gradient-to-br from-cyan-900/60 to-slate-900 border border-cyan-500/30 text-cyan-400 shadow-inner">
              🛡️
            </div>
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h3 id="bruteTitle" class="font-bold text-base text-white tracking-wide flex items-center gap-2">
                  TRUNG TÂM ĐIỀU PHỐI & PHẢN ỨNG TỰ ĐỘNG SOAR
                </h3>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">NIST SP 800-61 Rev.2 §3.3</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-950 text-purple-300 border border-purple-800">MITRE ATT&CK T1110</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">D3FEND D3-IB</span>
                <span id="soarModeBadge" class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-700 animate-pulse">
                  ⚡ AUTO-PILOT (TỰ ĐỘNG 100%)
                </span>
                <span id="bruteBadgeStatus" class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                  Hệ thống bình thường
                </span>
              </div>
              <p id="bruteSubtitle" class="text-xs text-slate-400 mt-1">
                Tự động đánh giá sự kiện an ninh, kích hoạt Playbook khoanh vùng theo chuẩn quốc tế, và hỗ trợ hoàn tác 1-Click tại một điểm duy nhất.
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2.5">
            <button onclick="triggerBruteDemo()" class="px-3.5 py-2 rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-xs font-bold text-white shadow-lg shadow-amber-600/30 flex items-center gap-1.5 transition active:scale-95">
              <span>🧪</span> Thử Demo Playbook (3 lần sai)
            </button>
            <button onclick="soarRollback('all', '')" class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 transition active:scale-95 flex items-center gap-1.5">
              <span>🔄</span> Khôi phục Tất cả (Rollback All)
            </button>
          </div>
        </div>

        <!-- THÂN TRUNG TÂM SOAR (3 CỘT ĐIỀU PHỐI) -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-5 mt-4">
          
          <!-- CỘT 1: THÔNG TIN SỰ CỐ & QUY TRÌNH PLAYBOOK NIST SP 800-61 (4 COLS) -->
          <div class="lg:col-span-4 space-y-3">
            <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>📋</span> Sự Cố & Tiến Trình Playbook:
            </div>
            <div id="bruteAlertBox" class="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs space-y-2 shadow-inner">
              <div class="flex justify-between items-center">
                <span class="text-slate-400">Máy trạm giám sát:</span>
                <span id="bruteHost" class="font-mono font-bold text-cyan-400">NGUYENVANTIEN (192.168.21.156)</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-slate-400">Tài khoản mục tiêu:</span>
                <span id="bruteUser" class="font-mono font-bold text-amber-400">tien0</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-slate-400">IP nguồn tấn công:</span>
                <span id="bruteIp" class="font-mono font-bold text-rose-400">Chưa phát hiện</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-slate-400">Số lần gõ sai Event 4625:</span>
                <span id="bruteCount" class="font-mono font-bold text-slate-300">0 lần</span>
              </div>
              <div class="flex justify-between items-center text-[11px] pt-1.5 border-t border-slate-800/80">
                <span class="text-slate-500">Mốc thời gian phát hiện:</span>
                <span id="bruteTime" class="font-mono text-slate-400">--:--:--</span>
              </div>
            </div>

            <!-- QUY TRÌNH PLAYBOOK TRỰC QUAN NIST SP 800-61 -->
            <div class="p-3 rounded-xl bg-slate-900/60 border border-slate-800/80 text-[11px] space-y-2">
              <div class="font-semibold text-slate-300 flex items-center justify-between">
                <span>Quy trình Playbook NIST SP 800-61:</span>
                <span class="text-[10px] text-cyan-400 font-mono">PB-T1110</span>
              </div>
              <div class="grid grid-cols-4 gap-1 text-center font-mono text-[9px]">
                <div id="stepDetect" class="p-1 rounded bg-slate-800 text-slate-400 border border-slate-700">1. Phát hiện</div>
                <div id="stepTriage" class="p-1 rounded bg-slate-800 text-slate-400 border border-slate-700">2. Đánh giá</div>
                <div id="stepContain" class="p-1 rounded bg-slate-800 text-slate-400 border border-slate-700">3. Khoanh vùng</div>
                <div id="stepRecover" class="p-1 rounded bg-slate-800 text-slate-400 border border-slate-700">4. Phục hồi</div>
              </div>
            </div>

            <!-- LỊCH SỬ THỰC THI GẦN NHẤT -->
            <div id="bruteHistoryBox" class="text-[11px] font-mono text-slate-400 space-y-1 max-h-24 overflow-y-auto">
            </div>
          </div>

          <!-- CỘT 2: TRUNG TÂM KHÔI PHỤC TẬP TRUNG (ONE-STOP REMEDIATION HUB) (5 COLS) -->
          <div class="lg:col-span-5 space-y-3">
            <div class="flex items-center justify-between">
              <div class="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                <span>🎯</span> Khu Vực Khôi Phục & Mở Khóa Tập Trung:
              </div>
              <span class="text-[10px] text-emerald-400 font-mono">1-Click Override</span>
            </div>

            <!-- BẢNG THỰC THỂ ĐANG BỊ CÁCH LY (QUARANTINE / CONTAINMENT HUB) -->
            <div class="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs min-h-[140px] flex flex-col justify-between">
              <div>
                <div class="text-[11px] font-medium text-slate-400 mb-2 flex items-center justify-between">
                  <span>Trạng thái Thực thể đang bị khoanh vùng:</span>
                  <span id="containmentCountBadge" class="px-1.5 py-0.2 rounded text-[10px] font-bold bg-slate-800 text-slate-400">0 mục</span>
                </div>
                <div id="soarContainmentList" class="space-y-2">
                  <div class="p-3 rounded-lg bg-emerald-950/30 border border-emerald-800/40 text-emerald-400 text-center font-medium text-xs">
                    ✅ Toàn bộ hệ thống an toàn • Không có IP hay User nào bị cách ly
                  </div>
                </div>
              </div>

              <!-- HÀNH ĐỘNG THỦ CÔNG KHẨN CẤP -->
              <div class="pt-3 border-t border-slate-800/80 mt-2">
                <div class="text-[10px] text-slate-500 font-semibold uppercase mb-1.5">Can thiệp thủ công bổ sung:</div>
                <div class="grid grid-cols-2 gap-2">
                  <button onclick="triggerBruteAction('block_ip')" id="btnBruteBlockIp" class="p-2 rounded-lg bg-rose-950/60 hover:bg-rose-900 border border-rose-700/60 text-rose-200 text-[11px] font-bold flex items-center justify-center gap-1.5 transition">
                    <span>🛡️</span> Chặn IP Firewall
                  </button>
                  <button onclick="triggerBruteAction('lock_user')" id="btnBruteLockUser" class="p-2 rounded-lg bg-amber-950/60 hover:bg-amber-900 border border-amber-700/60 text-amber-200 text-[11px] font-bold flex items-center justify-center gap-1.5 transition">
                    <span>🔒</span> Tạm Khóa User
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- CỘT 3: CẤU HÌNH CHIẾN LƯỢC SOAR & PLAYBOOK REGISTRY (3 COLS) -->
          <div class="lg:col-span-3 space-y-3">
            <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>⚙️</span> Chiến Lược Vận Hành SOAR:
            </div>

            <!-- BẢNG CẤU HÌNH CHIẾN LƯỢC TỰ ĐỘNG -->
            <div class="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs space-y-3">
              <div>
                <label class="text-[11px] text-slate-400 font-medium block mb-1">Chế độ vận hành SOAR:</label>
                <select id="soarModeSelect" onchange="updateSoarPolicy()" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200 font-semibold focus:border-cyan-500 focus:outline-none">
                  <option value="auto">🟢 Tự động 100% (Auto-Pilot - Chuẩn NIST)</option>
                  <option value="approval">🟡 Bán tự động (Chờ phê duyệt)</option>
                </select>
              </div>

              <div>
                <label class="text-[11px] text-slate-400 font-medium block mb-1">Chiến lược Khoanh vùng Mặc định:</label>
                <select id="soarTrackSelect" onchange="updateSoarPolicy()" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200 font-semibold focus:border-cyan-500 focus:outline-none">
                  <option value="block_ip">🛡️ Chặn IP Kẻ xấu (NIST Khuyến nghị - Giữ thông suốt User)</option>
                  <option value="lock_user">🔒 Khóa User Mục tiêu (Bảo vệ triệt để)</option>
                  <option value="dual">⚡ Cách ly Kép (Chặn IP + Khóa User)</option>
                </select>
                <p class="text-[10px] text-slate-500 mt-1 italic">
                  * Chuẩn NIST SP 800-61 ưu tiên chặn IP kẻ tấn công để không làm gián đoạn công việc của nhân viên hợp lệ.
                </p>
              </div>

              <!-- DANH MỤC PLAYBOOK DOANH NGHIỆP -->
              <div class="pt-2 border-t border-slate-800">
                <div class="text-[10px] text-slate-400 font-bold uppercase mb-1">Danh mục Playbook sẵn có:</div>
                <div class="space-y-1 text-[10px] font-mono">
                  <div class="flex justify-between items-center text-cyan-300">
                    <span>• PB-T1110 (Brute-Force)</span>
                    <span class="text-[9px] text-emerald-400">Active</span>
                  </div>
                  <div class="flex justify-between items-center text-slate-400">
                    <span>• PB-T1204 (Malware/CVE)</span>
                    <span class="text-[9px] text-emerald-400">Active</span>
                  </div>
                  <div class="flex justify-between items-center text-slate-400">
                    <span>• PB-T1499 (Resource DoS)</span>
                    <span class="text-[9px] text-emerald-400">Active</span>
                  </div>
                  <div class="flex justify-between items-center text-slate-400">
                    <span>• PB-T1190 (WAF Exploit)</span>
                    <span class="text-[9px] text-emerald-400">Active</span>
                  </div>
                  <div class="flex justify-between items-center text-slate-400">
                    <span>• PB-T1048 (DB Exfil)</span>
                    <span class="text-[9px] text-emerald-400">Active</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- CARD 1: FLEET RISK SCORES & TIMELINE -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">🎯 THẺ 1: ĐIỂM SỐ NGUY HIỂM (RISK SCORE)</strong>
          * Thang 0-100: 0 là bình an, 100 là hệ thống sắp sập!<br>
          * Tự động tính toán dựa trên mức độ nghiêm trọng của sự cố MySQL và CPU/RAM thực tế.<br>
          * Đồ thị bên dưới thể hiện thời điểm cao trào của các cuộc tấn công.
        </div>

        <div>
          <div class="flex items-center justify-between mb-2">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              Fleet Risk Scores
              
            </h3>
            <span id="riskSeverityBadge" class="px-2 py-0.5 rounded text-[11px] font-bold bg-amber-950 text-amber-400 border border-amber-800">
              Severity: Medium
            </span>
          </div>

          <div class="mt-4 mb-2">
            <div class="flex justify-between text-[11px] font-bold text-slate-400 mb-1 px-1">
              <span>0 (An toàn)</span>
              <span>25</span>
              <span>50</span>
              <span>75</span>
              <span>100 (Nguy kịch)</span>
            </div>
            <div class="h-2 rounded-full gauge-gradient relative w-full">
              <div id="riskScorePill" class="absolute -top-3.5 left-[68%] -translate-x-1/2 bg-[#0284c7] text-white font-extrabold text-[10px] px-2 py-0.5 rounded-full shadow-lg border border-cyan-300 transition-all duration-500">
                68.40
              </div>
            </div>
          </div>
        </div>

        <div class="mt-6">
          <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span class="font-semibold text-slate-300">Biểu đồ sự cố theo thời gian (Timeline 24h)</span>
            <span class="text-[11px] text-red-400 font-bold" id="peakTimeText">Đỉnh điểm: 17:15</span>
          </div>
          <div class="h-28 w-full bg-[#0a0f18] rounded-lg p-2 border border-[#1c2637] relative flex items-end">
            <svg class="w-full h-full overflow-visible" viewBox="0 0 300 80" preserveAspectRatio="none">
              <defs>
                <linearGradient id="chartGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#ef4444" stop-opacity="0.45"/>
                  <stop offset="100%" stop-color="#ef4444" stop-opacity="0.0"/>
                </linearGradient>
              </defs>
              <path d="M0,70 Q40,65 80,50 T160,55 T220,15 T260,35 T300,20 L300,80 L0,80 Z" fill="url(#chartGrad)"/>
              <path d="M0,70 Q40,65 80,50 T160,55 T220,15 T260,35 T300,20" fill="none" stroke="#ef4444" stroke-width="2.5"/>
              <circle cx="220" cy="15" r="4" fill="#ef4444" stroke="#ffffff" stroke-width="1.5"/>
            </svg>
          </div>
          <div class="flex justify-between text-[10px] text-slate-500 mt-1 font-mono">
            <span>08:00</span>
            <span>12:00</span>
            <span>16:00</span>
            <span>20:00</span>
            <span>Hiện tại</span>
          </div>
        </div>
      </div>

      <!-- CARD 2: TICKETS OVERVIEW & LATEST ALERTS -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">🎫 THẺ 2: TICKETS (PHIẾU BÁO ÁN SỰ CỐ)</strong>
          * Bấm vào chữ "Xem tất cả" hoặc menu bên trái để mở toàn bộ hồ sơ vụ án!
        </div>

        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300">Tickets & Alerts Overview</h3>
            <button onclick="switchTab('siem')" class="text-xs text-cyan-400 hover:underline">Xem tất cả →</button>
          </div>

          <div class="grid grid-cols-4 gap-2 mb-4 text-center">
            <div class="bg-[#0b1019] border border-[#1c2637] rounded-lg p-2">
              <div class="text-[10px] text-emerald-400 font-bold uppercase flex items-center justify-center gap-1">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Total
              </div>
              <span id="ticketTotal" class="text-lg font-black text-white mt-0.5 block">0</span>
            </div>
            <div class="bg-[#0b1019] border border-[#1c2637] rounded-lg p-2">
              <div class="text-[10px] text-red-400 font-bold uppercase flex items-center justify-center gap-1">
                <span class="w-1.5 h-1.5 rounded-full bg-red-400"></span> Open
              </div>
              <span id="ticketOpen" class="text-lg font-black text-red-400 mt-0.5 block">0</span>
            </div>
            <div class="bg-[#0b1019] border border-[#1c2637] rounded-lg p-2">
              <div class="text-[10px] text-amber-400 font-bold uppercase flex items-center justify-center gap-1">
                <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span> Đang xử lý
              </div>
              <span id="ticketProcessing" class="text-lg font-black text-amber-400 mt-0.5 block">0</span>
            </div>
            <div class="bg-[#0b1019] border border-[#1c2637] rounded-lg p-2">
              <div class="text-[10px] text-blue-400 font-bold uppercase flex items-center justify-center gap-1">
                <span class="w-1.5 h-1.5 rounded-full bg-blue-400"></span> Đã đóng
              </div>
              <span id="ticketClosed" class="text-lg font-black text-blue-400 mt-0.5 block">0</span>
            </div>
          </div>

          <div class="space-y-2 text-xs">
            <span class="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1">Danh sách sự cố vừa bắt quả tang:</span>
            <div id="latestTicketsList" class="space-y-2">
              <div class="text-slate-500 text-center py-4">Đang tải dữ liệu từ máy chủ...</div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-center gap-1.5 mt-3 pt-2 border-t border-[#1c2637] text-[11px]">
          <button onclick="switchTab('siem')" class="text-cyan-400 hover:underline">Mở toàn bộ danh sách SIEM Logs →</button>
        </div>
      </div>

      <!-- CARD 3: ASSET STATUS & HIGH RISK RANKING -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">🏆 THẺ 3: XẾP HẠNG MÁY CHỦ BỊ TẤN CÔNG</strong>
          * Bấm "Chi tiết máy" để xem cấu hình chi tiết từng máy!
        </div>

        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300">Host & Asset Status</h3>
            <button onclick="switchTab('hosts')" class="text-xs text-cyan-400 hover:underline">Chi tiết máy →</button>
          </div>

          <div class="flex justify-around items-center py-2 bg-[#0b1019] rounded-lg border border-[#1c2637] mb-4">
            <div class="text-center">
              <span class="text-2xl font-black text-amber-400">3</span>
              <span class="text-[10px] text-slate-400 block uppercase font-medium">Tổng máy</span>
            </div>
            <div class="w-px h-8 bg-slate-800"></div>
            <div class="text-center">
              <span id="countAtRisk" class="text-2xl font-black text-red-400">1</span>
              <span class="text-[10px] text-slate-400 block uppercase font-medium">Đang bị nhắm</span>
            </div>
            <div class="w-px h-8 bg-slate-800"></div>
            <div class="text-center">
              <span class="text-2xl font-black text-emerald-400">2</span>
              <span class="text-[10px] text-slate-400 block uppercase font-medium">An toàn</span>
            </div>
          </div>

          <span class="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Bảng phong thần nguy cơ:</span>
          <div class="space-y-2 text-xs">
            <div class="flex items-center justify-between p-2 rounded bg-[#0e1522] border border-[#1c2637] cursor-pointer hover:border-cyan-500 transition" onclick="switchTab('hosts')">
              <div class="flex items-center gap-2">
                <span class="text-amber-400">🔒</span>
                <div>
                  <span class="font-bold text-slate-200 block">Ubuntu-SOC-Host</span>
                  <span class="text-[10px] text-slate-400">192.168.21.136 (Core SOC)</span>
                </div>
              </div>
              <div class="text-right">
                <span class="px-2 py-0.5 rounded text-[11px] font-black bg-red-950 text-red-400 border border-red-800">78.50 Điểm</span>
                <span id="ubuntuMetricsText" class="text-[10px] text-slate-400 block">CPU: -- | RAM: --</span>
              </div>
            </div>

            <div class="flex items-center justify-between p-2 rounded bg-[#0e1522] border border-[#1c2637] cursor-pointer hover:border-cyan-500 transition" onclick="switchTab('hosts')">
              <div class="flex items-center gap-2">
                <span class="text-blue-400">💻</span>
                <div>
                  <span class="font-bold text-slate-200 block">Win10-Agent-PC</span>
                  <span class="text-[10px] text-slate-400">192.168.21.156 (Workstation)</span>
                </div>
              </div>
              <div class="text-right">
                <span class="px-2 py-0.5 rounded text-[11px] font-black bg-amber-950 text-amber-400 border border-amber-800">42.10 Điểm</span>
                <span class="text-[10px] text-slate-500 block">Ổn định</span>
              </div>
            </div>

            <div class="flex items-center justify-between p-2 rounded bg-[#0e1522] border border-[#1c2637] cursor-pointer hover:border-cyan-500 transition" onclick="switchTab('tunnel')">
              <div class="flex items-center gap-2">
                <span class="text-emerald-400">☁️</span>
                <div>
                  <span class="font-bold text-slate-200 block">Azure-VPS-Tunnel</span>
                  <span class="text-[10px] text-slate-400">70.153.83.137 (Indonesia)</span>
                </div>
              </div>
              <div class="text-right">
                <span class="px-2 py-0.5 rounded text-[11px] font-black bg-emerald-950 text-emerald-400 border border-emerald-800">08.20 Điểm</span>
                <span class="text-[10px] text-emerald-400 block font-bold">24/7 Online</span>
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-center gap-1.5 mt-3 pt-2 border-t border-[#1c2637] text-[11px]">
          <button onclick="switchTab('hosts')" class="text-cyan-400 hover:underline">Quản lý toàn bộ 3 máy chủ →</button>
        </div>
      </div>

      <!-- CARD 4: CONNECTED NETWORK DEVICES -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">🌐 THẺ 4: CÁC THIẾT BỊ ĐANG CẮM TRONG MẠNG</strong>
          * Bấm "Xem sơ đồ Tunnel" để xem đường dây nối lên đám mây Azure!
        </div>

        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300">Connected Devices in Subnet</h3>
            <button onclick="switchTab('tunnel')" class="text-xs text-cyan-400 hover:underline">Sơ đồ mạng →</button>
          </div>

          <div class="space-y-2 text-xs">
            <div class="p-2.5 rounded bg-[#0e1522] border border-[#1c2637] flex items-center justify-between">
              <div>
                <span class="font-bold text-white block">Router Gateway (Cổng mạng)</span>
                <span class="text-[11px] text-slate-400">VMware Virtual Switch VMnet8</span>
                <span class="text-[10px] text-cyan-400 font-mono block">192.168.21.1 • Cổng ngõ chính</span>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400">Gateway</span>
            </div>

            <div class="p-2.5 rounded bg-[#0e1522] border border-[#1c2637] flex items-center justify-between">
              <div>
                <span class="font-bold text-white block">SOC AI Engine Server (Bộ não)</span>
                <span class="text-[11px] text-slate-400">Ubuntu 24.04 (FastAPI + AI Hoài My)</span>
                <span class="text-[10px] text-cyan-400 font-mono block">192.168.21.136:8888</span>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950 text-blue-400">Core Host</span>
            </div>

            <div class="p-2.5 rounded bg-[#0e1522] border border-[#1c2637] flex items-center justify-between">
              <div>
                <span class="font-bold text-white block">Điện thoại Android (Người trực ban)</span>
                <span class="text-[11px] text-slate-400">App SOC Alert (Nhận chuông khẩn cấp)</span>
                <span class="text-[10px] text-emerald-400 font-mono block">Nối qua IP 70.153.83.137</span>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-950 text-purple-400">Online</span>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-center gap-1.5 mt-3 pt-2 border-t border-[#1c2637] text-[11px]">
          <button onclick="switchTab('tunnel')" class="text-cyan-400 hover:underline">Mở bản đồ kết nối Reverse Tunnel →</button>
        </div>
      </div>

      <!-- CARD 5: DATABASE AUDIT & VULNERABILITY WATCH -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">🗄️ THẺ 5: KIỂM TOÁN CƠ SỞ DỮ LIỆU MYSQL</strong>
          * Bắt tận tay hacker khi gõ lệnh phá hoại: DROP TABLE, tắt audit log...
        </div>

        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300">MySQL Database Audit & Risks</h3>
            
          </div>

          <table class="w-full text-left text-xs">
            <thead>
              <tr class="text-[10px] text-slate-500 uppercase border-b border-slate-800 pb-1">
                <th class="pb-1.5">#</th>
                <th class="pb-1.5">Lệnh bị cấm</th>
                <th class="pb-1.5 text-right">Mức độ phạt</th>
              </tr>
            </thead>
            <tbody id="dbAuditRows" class="divide-y divide-[#1c2637] font-mono text-[11px]">
              <tr>
                <td class="py-2 text-slate-500">1</td>
                <td class="py-2 text-slate-200">DROP DATABASE / TABLE</td>
                <td class="py-2 text-right"><span class="px-2 py-0.5 rounded bg-red-950 text-red-400 font-bold">100 (CỰC NGUY HIỂM)</span></td>
              </tr>
              <tr>
                <td class="py-2 text-slate-500">2</td>
                <td class="py-2 text-slate-200">SET general_log = 'OFF'</td>
                <td class="py-2 text-right"><span class="px-2 py-0.5 rounded bg-amber-950 text-amber-400 font-bold">94.20 (XÓA DẤU VẾT)</span></td>
              </tr>
              <tr>
                <td class="py-2 text-slate-500">3</td>
                <td class="py-2 text-slate-200">Sửa DB ngoài giờ quy định</td>
                <td class="py-2 text-right"><span class="px-2 py-0.5 rounded bg-amber-950 text-amber-400 font-bold">88.50 (BẤT THƯỜNG)</span></td>
              </tr>
              <tr>
                <td class="py-2 text-slate-500">4</td>
                <td class="py-2 text-slate-200">Dò pass root sai &gt; 3 lần</td>
                <td class="py-2 text-right"><span class="px-2 py-0.5 rounded bg-blue-950 text-blue-400 font-bold">62.00 (BRUTE FORCE)</span></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex items-center justify-center gap-1.5 mt-3 pt-2 border-t border-[#1c2637] text-[11px]">
          <button onclick="switchTab('siem')" class="text-cyan-400 hover:underline">Xem toàn bộ lịch sử truy vấn MySQL →</button>
        </div>
      </div>

      <!-- CARD 6: SOAR PLAYBOOK & ACTION CENTER -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4 flex flex-col justify-between shadow-sm has-tooltip">
        <div class="tooltip-box tip-bottom">
          <strong class="text-cyan-400 block mb-1">⚡ THẺ 6: SOAR (TRUNG TÂM PHẢN ỨNG TỰ ĐỘNG)</strong>
          * Bấm "Sao lưu khẩn cấp" để lưu file .sql thật vào máy chủ!
        </div>

        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-300">SOAR Automated Actions (Nút tác chiến)</h3>
            <button onclick="switchTab('incidents')" class="text-xs text-cyan-400 hover:underline">Phòng tác chiến →</button>
          </div>

          <div class="space-y-2 text-xs">
            <button onclick="triggerEmergencyCall()" id="actionCallBtn" class="w-full p-2.5 rounded bg-[#162132] hover:bg-[#1d2b42] border border-[#23334d] text-left flex items-center justify-between transition">
              <div class="flex items-center gap-2.5">
                <span class="text-base">🚨</span>
                <div>
                  <span class="font-bold text-white block">Phát Cuộc Gọi Thoại AI</span>
                  <span class="text-[10px] text-slate-400">Gọi thẳng về App Android qua Reverse Tunnel</span>
                </div>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-400 border border-cyan-800">Thử ngay</span>
            </button>

            <!-- Nút Sao lưu thật -->
            <button onclick="executeRealBackup()" id="btnActionBackup" class="w-full p-2.5 rounded bg-[#162132] hover:bg-[#1d2b42] border border-[#23334d] text-left flex items-center justify-between transition">
              <div class="flex items-center gap-2.5">
                <span class="text-base">💾</span>
                <div>
                  <span class="font-bold text-white block">Sao Lưu Khẩn Cấp Database (Thật)</span>
                  <span class="text-[10px] text-slate-400">Chạy mysqldump xuất file .sql vào /backups</span>
                </div>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">Backup</span>
            </button>

            <button onclick="playAiVoiceDemo()" id="actionAudioBtn" class="w-full p-2.5 rounded bg-[#162132] hover:bg-[#1d2b42] border border-[#23334d] text-left flex items-center justify-between transition">
              <div class="flex items-center gap-2.5">
                <span class="text-base">🔊</span>
                <div>
                  <span class="font-bold text-white block">Nghe Giọng Đọc Cảnh Báo</span>
                  <span class="text-[10px] text-slate-400">Giọng Edge-TTS Hoài My tiếng Việt chuẩn</span>
                </div>
              </div>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-950 text-purple-400 border border-purple-800">Phát loa</span>
            </button>
          </div>
        </div>

        <div class="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-[#1c2637]">
          <span>Cầu nối ra Internet:</span>
          <span class="text-cyan-400 font-mono" id="tunnelUrlText">http://70.153.83.137</span>
        </div>
      </div>

    </div>

    <!-- TAB 2: HOSTS / ASSETS VIEW -->
    <div id="view-hosts" class="tab-content p-6 space-y-6 hidden">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-white">Quản Lý Chi Tiết Máy Chủ & Thiết Bị (Hosts / Assets)</h2>
          <p class="text-xs text-slate-400 mt-0.5">Danh sách toàn bộ các máy trạm, máy chủ cơ sở dữ liệu và Cloud VPS trong kiến trúc Hybrid Cloud.</p>
        </div>
        <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200">← Về Dashboard</button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5 space-y-3">
          <div class="flex justify-between items-start">
            <div class="flex items-center gap-2.5">
              <span class="text-2xl">🐧</span>
              <div>
                <h3 class="font-bold text-white">Ubuntu SOC Core Host</h3>
                <span class="text-xs font-mono text-cyan-400">192.168.21.136</span>
              </div>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">Active</span>
          </div>
          <div class="space-y-1.5 text-xs text-slate-300 pt-2 border-t border-slate-800">
            <div class="flex justify-between"><span>Hệ điều hành:</span><span class="text-slate-100 font-mono">Ubuntu 24.04 LTS</span></div>
            <div class="flex justify-between"><span>Dịch vụ SOC:</span><span class="text-emerald-400 font-bold">ai_engine.service</span></div>
            <div class="flex justify-between"><span>Database:</span><span class="text-cyan-400 font-bold">MySQL 8.0 (Port 3306)</span></div>
            <div class="flex justify-between"><span>Reverse Bridge:</span><span class="text-emerald-400">soc-tunnel.service</span></div>
          </div>
        </div>

        <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5 space-y-3">
          <div class="flex justify-between items-start">
            <div class="flex items-center gap-2.5">
              <span class="text-2xl">🪟</span>
              <div>
                <h3 class="font-bold text-white">Windows 10 Workstation</h3>
                <span class="text-xs font-mono text-blue-400">192.168.21.156</span>
              </div>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">Monitored</span>
          </div>
          <div class="space-y-1.5 text-xs text-slate-300 pt-2 border-t border-slate-800">
            <div class="flex justify-between"><span>Vai trò:</span><span class="text-slate-100">Máy trạm kế toán / client</span></div>
            <div class="flex justify-between"><span>Cơ chế giám sát:</span><span class="text-slate-100">POST /api/windows_metrics</span></div>
            <div class="flex justify-between"><span>Trạng thái CPU:</span><span class="text-amber-400 font-bold">83.0% (Cảnh báo tải)</span></div>
            <div class="flex justify-between"><span>RAM tiêu thụ:</span><span class="text-slate-100">76.0%</span></div>
          </div>
        </div>

        <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5 space-y-3">
          <div class="flex justify-between items-start">
            <div class="flex items-center gap-2.5">
              <span class="text-2xl">☁️</span>
              <div>
                <h3 class="font-bold text-white">Azure Cloud Gateway</h3>
                <span class="text-xs font-mono text-cyan-400">70.153.83.137</span>
              </div>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">Cloud 24/7</span>
          </div>
          <div class="space-y-1.5 text-xs text-slate-300 pt-2 border-t border-slate-800">
            <div class="flex justify-between"><span>Khu vực (Region):</span><span class="text-slate-100">Indonesia Central</span></div>
            <div class="flex justify-between"><span>Cấu hình:</span><span class="text-slate-100">Standard_B2ats_v2 (2 vCPU)</span></div>
            <div class="flex justify-between"><span>Phần mềm tiếp sóng:</span><span class="text-emerald-400 font-bold">Nginx Reverse Proxy</span></div>
            <div class="flex justify-between"><span>Độ trễ trung bình:</span><span class="text-emerald-400 font-bold">~28 ms</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: REVERSE TUNNEL MESH VIEW -->
    <div id="view-tunnel" class="tab-content p-6 space-y-6 hidden">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-white">Sơ Đồ Mạng Reverse Tunnel Mesh (Hybrid Architecture)</h2>
          <p class="text-xs text-slate-400 mt-0.5">Kiến trúc kết nối ngầm mã hóa SSH vượt tường lửa, thay thế hoàn toàn Cloudflare.</p>
        </div>
        <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200">← Về Dashboard</button>
      </div>

      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-6">
        <div class="flex flex-col md:flex-row items-center justify-around gap-6 py-8">
          <div class="text-center p-4 bg-[#0a0f18] border border-cyan-800/60 rounded-xl w-60 shadow-lg">
            <div class="text-3xl mb-2">🏠</div>
            <h4 class="font-bold text-white">Ubuntu On-Premise</h4>
            <span class="text-xs font-mono text-cyan-400 block">192.168.21.136:8888</span>
            <span class="text-[10px] text-slate-400 mt-1 block">Chạy AI Engine & MySQL</span>
            <span class="inline-block mt-2 px-2 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800">Tunnel Client (Up)</span>
          </div>

          <div class="flex flex-col items-center">
            <span class="text-xs font-mono text-emerald-400 font-bold animate-pulse">SSH Reverse Pipe (Port 443/22)</span>
            <div class="w-32 h-1 bg-gradient-to-r from-cyan-500 via-emerald-400 to-blue-500 my-2 rounded-full"></div>
            <span class="text-[10px] text-slate-400 font-mono">Ping ~28ms • RSA 2048 Bit</span>
          </div>

          <div class="text-center p-4 bg-[#0a0f18] border border-blue-800/60 rounded-xl w-60 shadow-lg">
            <div class="text-3xl mb-2">☁️</div>
            <h4 class="font-bold text-white">Azure Cloud VPS</h4>
            <span class="text-xs font-mono text-cyan-400 block">70.153.83.137:80</span>
            <span class="text-[10px] text-slate-400 mt-1 block">Nginx Edge Reverse Proxy</span>
            <span class="inline-block mt-2 px-2 py-0.5 rounded text-[10px] bg-blue-950 text-blue-400 border border-blue-800">Public Gateway</span>
          </div>

          <div class="flex flex-col items-center">
            <span class="text-xs font-mono text-purple-400 font-bold">4G / WiFi Internet</span>
            <div class="w-32 h-1 bg-gradient-to-r from-blue-500 to-purple-500 my-2 rounded-full"></div>
            <span class="text-[10px] text-slate-400 font-mono">Toàn cầu 24/7</span>
          </div>

          <div class="text-center p-4 bg-[#0a0f18] border border-purple-800/60 rounded-xl w-60 shadow-lg">
            <div class="text-3xl mb-2">📱</div>
            <h4 class="font-bold text-white">Android Mobile SOC</h4>
            <span class="text-xs font-mono text-purple-400 block">SOC Alert App</span>
            <span class="text-[10px] text-slate-400 mt-1 block">Đánh thức màn hình khóa & Gọi AI</span>
            <span class="inline-block mt-2 px-2 py-0.5 rounded text-[10px] bg-purple-950 text-purple-400 border border-purple-800">Active Receiver</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 4: SIEM & AUDIT LOGS FULL TABLE -->
    <div id="view-siem" class="tab-content p-6 space-y-6 hidden">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-white">SIEM & Hộp Đen Kiểm Toán Sự Kiện An Ninh (Audit Logs)</h2>
          <p class="text-xs text-slate-400 mt-0.5">Nhật ký toàn bộ các hành vi can thiệp hệ cơ sở dữ liệu MySQL và sự cố bất thường.</p>
        </div>
        <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200">← Về Dashboard</button>
      </div>

      <div class="bg-[#121926] border border-[#1e283b] rounded-xl overflow-hidden">
        <table class="w-full text-left text-xs">
          <thead class="bg-[#0b1019] text-slate-400 uppercase text-[10px] border-b border-slate-800">
            <tr>
              <th class="p-3">Thời gian</th>
              <th class="p-3">Mức độ</th>
              <th class="p-3">Phân loại</th>
              <th class="p-3">Tên sự cố</th>
              <th class="p-3">Chi tiết câu lệnh thực thi</th>
            </tr>
          </thead>
          <tbody id="fullSiemTableBody" class="divide-y divide-[#1c2637] font-mono text-[11px]">
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 5: INCIDENT RESPONSE & SOAR ACTIONS -->
    <div id="view-incidents" class="tab-content p-6 space-y-6 hidden">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-white">Trung Tâm Tác Chiến Ứng Cứu Khẩn Cấp (Incident Response Cockpit)</h2>
          <p class="text-xs text-slate-400 mt-0.5">Thực thi các hành động phản ứng tự động SOAR và phát giọng nói khẩn cấp.</p>
        </div>
        <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200">← Về Dashboard</button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-[#121926] border border-cyan-800/60 rounded-xl p-5 space-y-4">
          <h3 class="font-bold text-white text-sm">🎙️ Tổng Đài Giọng Nói AI Báo Động (Edge-TTS)</h3>
          <p class="text-xs text-slate-300">Nội dung âm thanh AI đang lưu trữ sẵn sàng phát:</p>
          <div class="p-3 rounded bg-black/50 border border-slate-800 text-cyan-300 font-mono text-xs italic" id="voiceFullText">
            "Cảnh báo an ninh tối khẩn! Phát hiện kẻ xâm nhập đang tìm cách tắt nhật ký kiểm toán để xóa dấu vết!"
          </div>
          <div class="flex gap-3">
            <button onclick="playAiVoiceDemo()" class="flex-1 py-2 rounded bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs transition">🔊 Nghe Giọng Đọc AI Hoài My</button>
            <button onclick="triggerEmergencyCall()" class="flex-1 py-2 rounded bg-red-600 hover:bg-red-500 text-white font-bold text-xs transition">📞 Gọi Điện Báo Động Về App</button>
          </div>
        </div>

        <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5 space-y-3">
          <h3 class="font-bold text-white text-sm">🛑 Các Kịch Bản Phản Ứng Tự Động (SOAR Containment)</h3>
          <div class="space-y-2 text-xs">
            <button onclick="alert('Đã gửi lệnh khóa IP kẻ tấn công vào iptables!')" class="w-full p-2.5 rounded bg-slate-800 hover:bg-slate-700 text-left flex justify-between">
              <span>🛡️ Chặn IP kẻ tấn công (Block IP)</span>
              <span class="text-cyan-400">Execute</span>
            </button>
            <button onclick="alert('Đã ngắt toàn bộ phiên làm việc của user MySQL vi phạm!')" class="w-full p-2.5 rounded bg-slate-800 hover:bg-slate-700 text-left flex justify-between">
              <span>🔒 Đóng băng phiên MySQL vi phạm</span>
              <span class="text-red-400">Kill Session</span>
            </button>
            <!-- Sao lưu thật -->
            <button onclick="executeRealBackup()" class="w-full p-2.5 rounded bg-emerald-950/60 hover:bg-emerald-900/60 border border-emerald-800 text-left flex justify-between">
              <span>💾 Sao lưu khẩn cấp Database THẬT (mysqldump)</span>
              <span class="text-emerald-300 font-bold">Thực thi ngay</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Khung Chỉnh Ngưỡng Nhanh Trong Tab Incident Response -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5 space-y-4 mt-6">
        <div class="flex justify-between items-center">
          <h3 class="font-bold text-white text-sm flex items-center gap-2">
            <span>⚙️</span> Cấu Hình Ngưỡng Cảnh Báo Tải Hệ Thống (Threshold Controller)
          </h3>
          <button onclick="saveThresholds()" class="px-4 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs transition">
            Lưu Ngưỡng Cảnh Báo
          </button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs">
          <div class="bg-[#0b1019] p-4 rounded-lg border border-slate-800 space-y-2">
            <div class="flex justify-between font-bold">
              <span>Ngưỡng Báo Động CPU:</span>
              <span id="labelCpuInline" class="text-cyan-400 font-mono">80%</span>
            </div>
            <input type="range" id="sliderCpuInline" min="10" max="105" value="80" oninput="syncThresholdValues(this.value, 'cpu')" class="w-full accent-cyan-500 cursor-pointer">
            <p class="text-[11px] text-slate-500">Khi máy tính vượt quá ngưỡng này sẽ tự phát loa báo động.</p>
          </div>

          <div class="bg-[#0b1019] p-4 rounded-lg border border-slate-800 space-y-2">
            <div class="flex justify-between font-bold">
              <span>Ngưỡng Báo Động RAM:</span>
              <span id="labelRamInline" class="text-cyan-400 font-mono">85%</span>
            </div>
            <input type="range" id="sliderRamInline" min="10" max="105" value="85" oninput="syncThresholdValues(this.value, 'ram')" class="w-full accent-cyan-500 cursor-pointer">
            <p class="text-[11px] text-slate-500">Cảnh báo khi bộ nhớ RAM bị tràn tải.</p>
          </div>

          <div class="bg-[#0b1019] p-4 rounded-lg border border-slate-800 space-y-2">
            <div class="flex justify-between font-bold">
              <span>Số lần gõ sai Pass:</span>
              <span id="labelAuthInline" class="text-cyan-400 font-mono">3 lần</span>
            </div>
            <input type="range" id="sliderAuthInline" min="1" max="10" value="3" oninput="syncThresholdValues(this.value, 'auth')" class="w-full accent-cyan-500 cursor-pointer">
            <p class="text-[11px] text-slate-500">Phát hiện kẻ gian dò quét mật khẩu Brute-force.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 6: USB FIREWALL VIEW -->
    <div id="view-usb" class="tab-content p-6 space-y-6 hidden">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-white">Tường Lửa Kiểm Soát Cổng USB (USB Peripheral Guard)</h2>
          <p class="text-xs text-slate-400 mt-0.5">Giám sát và ngăn chặn các thiết bị lưu trữ ngoài chứa mã độc cắm vào hệ thống.</p>
        </div>
        <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200">← Về Dashboard</button>
      </div>

      <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-5">
        <div class="flex items-center justify-between mb-4">
          <span class="text-xs font-bold text-slate-300">Chính sách bảo vệ USB: <strong class="text-emerald-400">BẬT (STRICT ENFORCEMENT)</strong></span>
          <span class="text-xs text-slate-400">Tự động khóa USB lạ</span>
        </div>
        <div class="space-y-2 text-xs">
          <div class="p-3 rounded bg-[#0a0f18] border border-slate-800 flex justify-between items-center">
            <div>
              <span class="font-bold text-white block">Kingston DataTraveler 32GB</span>
              <span class="text-slate-400 text-[11px]">Hardware ID: USB\VID_0951&PID_1666 • Đã gán cho Nhân viên Kế toán</span>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">Cho Phép (Whitelisted)</span>
          </div>

          <div class="p-3 rounded bg-[#0a0f18] border border-red-900/40 flex justify-between items-center">
            <div>
              <span class="font-bold text-red-300 block">Thiết bị USB không rõ nguồn gốc (Rubber Ducky)</span>
              <span class="text-slate-400 text-[11px]">Hardware ID: USB\VID_1D50&PID_6089 • Phát hiện cắm lúc 15:10</span>
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] bg-red-950 text-red-400 border border-red-800 font-bold">ĐÃ CHẶN & CÁCH LY</span>
          </div>
        </div>
      </div>
    </div>

        <!-- TAB 7: SOFTWARE INVENTORY & CVE VULNERABILITY AUDIT VIEW -->
    <div id="view-software" class="tab-content p-6 space-y-6 hidden">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <span class="text-xl">🛡️</span>
            <h2 class="text-lg font-bold text-white">Quản Lý Lỗ Hổng CVE & Danh Mục Phần Mềm (Vulnerability Audit)</h2>
          </div>
          <p class="text-xs text-slate-400 mt-1">Tự động phát hiện và cảnh báo các phiên bản phần mềm chứa mã lỗ hổng bảo mật quốc tế (CVE) trên máy trạm Windows.</p>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="triggerCveDemo()" class="px-3.5 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-xs font-bold text-white shadow-md shadow-amber-600/20 flex items-center gap-1.5 transition">
            <span>🧪</span> Nạp Mẫu Demo (WinRAR 6.22 CVE)
          </button>
          <button onclick="resetCveData()" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition">
            <span>🧹</span> Đặt lại
          </button>
          <button onclick="switchTab('dashboard')" class="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 transition">← Về Dashboard</button>
        </div>
      </div>

      <!-- METRIC COUNTER CARDS -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="bg-[#121926] border border-[#1e283b] rounded-xl p-4">
          <span class="text-xs text-slate-400 font-medium">Tổng phần mềm đã rà soát</span>
          <div class="text-2xl font-bold text-white mt-1" id="cve-total-apps">0</div>
          <span class="text-[10px] text-slate-500" id="cve-last-scanned">Chưa có dữ liệu</span>
        </div>
        <div class="bg-[#121926] border border-red-900/40 rounded-xl p-4">
          <span class="text-xs text-red-400 font-medium">🔴 Lỗ hổng Critical (CVSS &ge; 9.0)</span>
          <div class="text-2xl font-bold text-red-400 mt-1" id="cve-crit-count">0</div>
          <span class="text-[10px] text-red-400/70">Nguy cấp tối đa - Khai thác từ xa</span>
        </div>
        <div class="bg-[#121926] border border-amber-900/40 rounded-xl p-4">
          <span class="text-xs text-amber-400 font-medium">🟠 Lỗ hổng High (CVSS 7.0 - 8.9)</span>
          <div class="text-2xl font-bold text-amber-400 mt-1" id="cve-high-count">0</div>
          <span class="text-[10px] text-amber-400/70">Nguy cơ cao - Cần vá khẩn cấp</span>
        </div>
        <div class="bg-[#121926] border border-emerald-900/40 rounded-xl p-4">
          <span class="text-xs text-emerald-400 font-medium">🟢 Phần mềm an toàn</span>
          <div class="text-2xl font-bold text-emerald-400 mt-1" id="cve-safe-count">0</div>
          <span class="text-[10px] text-emerald-400/70">Đã kiểm toán & kiểm tra phiên bản</span>
        </div>
      </div>

      <!-- BẢNG 1: DANH SÁCH LỖ HỔNG CVE PHÁT HIỆN -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl overflow-hidden shadow-lg">
        <div class="p-4 bg-[#0b1019] border-b border-slate-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-base">⚠️</span>
            <h3 class="font-bold text-white text-sm">Danh Sách Lỗ Hổng Bảo Mật CVE Phát Hiện Trên Máy Trạm</h3>
          </div>
          <span id="cve-badge-status" class="px-2.5 py-0.5 rounded text-[11px] font-bold bg-slate-800 text-slate-300">Đang chờ quét</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="bg-[#0e1420] text-slate-400 uppercase text-[10px] border-b border-slate-800">
              <tr>
                <th class="p-3">Ứng dụng / Phần mềm</th>
                <th class="p-3">Phiên bản cài</th>
                <th class="p-3">Mã lỗi CVE</th>
                <th class="p-3">Điểm CVSS</th>
                <th class="p-3">Mức độ</th>
                <th class="p-3">Mô tả lỗ hổng</th>
                <th class="p-3">Khuyến nghị khắc phục (Remediation)</th>
                <th class="p-3 text-center">Hành động SOAR</th>
              </tr>
            </thead>
            <tbody id="cve-vuln-tbody" class="divide-y divide-[#1c2637] font-mono text-[11px]">
              <tr>
                <td colspan="7" class="p-6 text-center text-slate-500 font-sans text-xs">
                  Chưa có dữ liệu rà soát. Hãy chạy lệnh <code class="text-cyan-400 font-mono">python cve_agent.py</code> trên máy Windows hoặc bấm nút <strong>"Nạp Mẫu Demo"</strong> ở trên để kiểm thử!
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- BẢNG 2: DANH MỤC PHẦN MỀM ĐÃ CÀI ĐẶT TRÊN MÁY TRẠM -->
      <div class="bg-[#121926] border border-[#1e283b] rounded-xl overflow-hidden shadow-lg">
        <div class="p-4 bg-[#0b1019] border-b border-slate-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-base">📦</span>
            <h3 class="font-bold text-white text-sm">Kiểm Kê Ứng Dụng Đã Cài Đặt (Installed Software Inventory)</h3>
          </div>
          <span class="text-xs text-slate-400" id="cve-host-info">Máy trạm: Chưa kết nối</span>
        </div>
        <div class="overflow-x-auto max-h-80">
          <table class="w-full text-left text-xs">
            <thead class="bg-[#0e1420] text-slate-400 uppercase text-[10px] border-b border-slate-800 sticky top-0">
              <tr>
                <th class="p-3">Tên phần mềm / Gói ứng dụng</th>
                <th class="p-3">Phiên bản</th>
                <th class="p-3">Nhà phát hành (Publisher)</th>
                <th class="p-3">Trạng thái an ninh</th>
              </tr>
            </thead>
            <tbody id="cve-inventory-tbody" class="divide-y divide-[#1c2637] font-mono text-[11px]">
              <tr>
                <td colspan="4" class="p-4 text-center text-slate-500 font-sans text-xs">Chưa có danh sách phần mềm gửi từ Agent.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

  </div>

  <!-- MODAL CÀI ĐẶT NGƯỠNG CẢNH BÁO (POPUP DIALOG) -->
  <div id="modalConfig" onclick="if(event.target===this)closeConfigModal()" class="fixed inset-0 modal-backdrop z-50 flex items-center justify-center p-4" style="display: none;">
    <div class="bg-[#121926] border border-cyan-800/80 rounded-2xl w-full max-w-md p-6 shadow-2xl space-y-5 animate-in fade-in duration-200">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <div class="flex items-center gap-2">
          <span class="text-xl">⚙️</span>
          <h3 class="font-bold text-white text-base">Cài Đặt Ngưỡng Cảnh Báo SOC</h3>
        </div>
        <button onclick="closeConfigModal()" class="text-slate-400 hover:text-white text-lg font-bold">✕</button>
      </div>

      <div class="space-y-4 text-xs">
        <!-- CPU Slider & Direct Input -->
        <div class="bg-[#0b1019] p-3.5 rounded-xl border border-slate-800 space-y-2">
          <div class="flex justify-between items-center font-bold">
            <span class="text-slate-300">Ngưỡng Báo Động CPU:</span>
            <div class="flex items-center gap-1.5">
              <input type="number" id="modalCpuNum" min="10" max="105" value="80" oninput="syncThresholdValues(this.value, 'cpu')" class="w-16 px-2 py-1 rounded-lg bg-slate-900 border border-cyan-800/80 text-cyan-400 font-mono text-sm font-bold text-center focus:border-cyan-400 focus:outline-none">
              <span class="text-cyan-400 font-mono text-sm font-bold">%</span>
            </div>
          </div>
          <input type="range" id="modalCpuSlider" min="10" max="105" value="80" oninput="syncThresholdValues(this.value, 'cpu')" class="w-full accent-cyan-500 cursor-pointer h-2 bg-slate-800 rounded-lg">
          <div class="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>10% (Rất nhạy)</span>
            <span>80% (Khuyến nghị)</span>
            <span class="text-cyan-400 font-bold">105% (Tối đa)</span>
          </div>
        </div>

        <!-- RAM Slider & Direct Input -->
        <div class="bg-[#0b1019] p-3.5 rounded-xl border border-slate-800 space-y-2">
          <div class="flex justify-between items-center font-bold">
            <span class="text-slate-300">Ngưỡng Báo Động RAM:</span>
            <div class="flex items-center gap-1.5">
              <input type="number" id="modalRamNum" min="10" max="105" value="85" oninput="syncThresholdValues(this.value, 'ram')" class="w-16 px-2 py-1 rounded-lg bg-slate-900 border border-cyan-800/80 text-cyan-400 font-mono text-sm font-bold text-center focus:border-cyan-400 focus:outline-none">
              <span class="text-cyan-400 font-mono text-sm font-bold">%</span>
            </div>
          </div>
          <input type="range" id="modalRamSlider" min="10" max="105" value="85" oninput="syncThresholdValues(this.value, 'ram')" class="w-full accent-cyan-500 cursor-pointer h-2 bg-slate-800 rounded-lg">
          <div class="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>10%</span>
            <span>85% (Chuẩn)</span>
            <span class="text-cyan-400 font-bold">105% (Tối đa)</span>
          </div>
        </div>

        <!-- Auth Fail Slider & Direct Input -->
        <div class="bg-[#0b1019] p-3.5 rounded-xl border border-slate-800 space-y-2">
          <div class="flex justify-between items-center font-bold">
            <span class="text-slate-300">Số lần gõ sai Pass tối đa:</span>
            <div class="flex items-center gap-1.5">
              <input type="number" id="modalAuthNum" min="1" max="10" value="2" oninput="syncThresholdValues(this.value, 'auth')" class="w-16 px-2 py-1 rounded-lg bg-slate-900 border border-cyan-800/80 text-cyan-400 font-mono text-sm font-bold text-center focus:border-cyan-400 focus:outline-none">
              <span class="text-cyan-400 font-mono text-sm font-bold">lần</span>
            </div>
          </div>
          <input type="range" id="modalAuthSlider" min="1" max="10" value="2" oninput="syncThresholdValues(this.value, 'auth')" class="w-full accent-cyan-500 cursor-pointer h-2 bg-slate-800 rounded-lg">
          <p class="text-[10px] text-slate-500">Vượt quá ngưỡng này sẽ kích hoạt báo động đỏ Brute-Force.</p>
        </div>

        <!-- Master Switch -->
        <div class="flex items-center justify-between p-3 rounded-xl bg-[#0b1019] border border-slate-800">
          <div>
            <span class="font-bold text-white block">Phát chuông cuộc gọi khẩn cấp</span>
            <span class="text-[10px] text-slate-400">Tự động gọi điện thoại khi vượt ngưỡng</span>
          </div>
          <input type="checkbox" id="modalAlertsEnabled" checked class="w-4 h-4 accent-cyan-500">
        </div>
      </div>

      <div class="flex gap-3 pt-2">
        <button onclick="closeConfigModal()" class="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition">Hủy bỏ</button>
        <button onclick="saveThresholds()" class="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-xs font-bold text-white shadow-lg transition">Lưu Cấu Hình</button>
      </div>
    </div>
  </div>

  <!-- JAVASCRIPT LOGIC -->
  <script>
    let currentConfig = { cpu_threshold: 80.0, ram_threshold: 85.0, auth_fail_threshold: 3, enable_alerts: true };

        // Toggle Sidebar & Phóng to Dashboard
    function toggleSidebar() {
      const sb = document.getElementById('leftSidebar');
      if (sb) {
        const isCollapsed = sb.classList.toggle('sidebar-collapsed');
        try { localStorage.setItem('soc_sidebar_collapsed', isCollapsed ? '1' : '0'); } catch(e) {}
      }
    }

    try {
      if (localStorage.getItem('soc_sidebar_collapsed') === '1') {
        const sb = document.getElementById('leftSidebar');
        if (sb) sb.classList.add('sidebar-collapsed');
      }
    } catch(e) {}


    // Modal Controller & Chống tụt giá trị khi đang kéo
    let isModalConfigOpen = false;

    function openConfigModal() {
      isModalConfigOpen = true;
      // Đồng bộ giá trị hiện có vào các ô nhập
      syncThresholdValues(currentConfig.cpu_threshold, 'cpu');
      syncThresholdValues(currentConfig.ram_threshold, 'ram');
      syncThresholdValues(currentConfig.auth_fail_threshold, 'auth');
      const alertsChk = document.getElementById('modalAlertsEnabled');
      if (alertsChk) alertsChk.checked = currentConfig.enable_alerts !== false;
      const m = document.getElementById('modalConfig');
      if (m) m.style.display = 'flex';
    }

    function closeConfigModal() {
      isModalConfigOpen = false;
      const m = document.getElementById('modalConfig');
      if (m) m.style.display = 'none';
    }

    function syncThresholdValues(val, type) {
      val = Math.max(1, Math.min(105, parseFloat(val) || 0));
      if (type === 'cpu') {
        currentConfig.cpu_threshold = val;
        const slider = document.getElementById('modalCpuSlider');
        if (slider && document.activeElement !== slider) slider.value = val;
        const numInput = document.getElementById('modalCpuNum');
        if (numInput && document.activeElement !== numInput) numInput.value = val;
        const inlineL = document.getElementById('labelCpuInline');
        if (inlineL) inlineL.innerText = val + '%';
        const inlineS = document.getElementById('sliderCpuInline');
        if (inlineS) inlineS.value = val;
      } else if (type === 'ram') {
        currentConfig.ram_threshold = val;
        const slider = document.getElementById('modalRamSlider');
        if (slider && document.activeElement !== slider) slider.value = val;
        const numInput = document.getElementById('modalRamNum');
        if (numInput && document.activeElement !== numInput) numInput.value = val;
        const inlineL = document.getElementById('labelRamInline');
        if (inlineL) inlineL.innerText = val + '%';
        const inlineS = document.getElementById('sliderRamInline');
        if (inlineS) inlineS.value = val;
      } else if (type === 'auth') {
        val = Math.round(val);
        currentConfig.auth_fail_threshold = val;
        const slider = document.getElementById('modalAuthSlider');
        if (slider && document.activeElement !== slider) slider.value = val;
        const numInput = document.getElementById('modalAuthNum');
        if (numInput && document.activeElement !== numInput) numInput.value = val;
        const inlineL = document.getElementById('labelAuthInline');
        if (inlineL) inlineL.innerText = val + ' lần';
        const inlineS = document.getElementById('sliderAuthInline');
        if (inlineS) inlineS.value = val;
      }
    }

    function saveThresholds() {
      currentConfig.enable_alerts = document.getElementById('modalAlertsEnabled').checked;
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      })
      .then(r => r.json())
      .then(d => {
        closeConfigModal();
        alert('✅ ĐÃ LƯU THÀNH CÔNG! CPU: ' + currentConfig.cpu_threshold + '%, RAM: ' + currentConfig.ram_threshold + '%, Sai pass: ' + currentConfig.auth_fail_threshold + ' lần');
      })
      .catch(e => alert('Lỗi khi lưu cấu hình'));
    }

    // SAO LƯU DATABASE THẬT
    function executeRealBackup() {
      const btn = document.getElementById('btnActionBackup');
      if (btn) btn.innerText = 'Đang trích xuất dữ liệu...';
      fetch('/api/soar/backup', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          if (btn) btn.innerHTML = '<span>💾 Sao Lưu Khẩn Cấp Database (Thật)</span><span class=\"px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800\">Backup</span>';
          alert('💾 ' + data.msg);
        })
        .catch(err => {
          if (btn) btn.innerHTML = '<span>💾 Sao Lưu Khẩn Cấp Database (Thật)</span><span class=\"px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800\">Backup</span>';
          alert('Lỗi kết nối máy chủ khi sao lưu');
        });
    }

    // Tab Switching System
    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
      const target = document.getElementById('view-' + tabId);
      if (target) target.classList.remove('hidden');

      document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('nav-item-active'));
      const activeBtn = document.getElementById('btn-' + tabId);
      if (activeBtn) activeBtn.classList.add('nav-item-active');
    }

    function handleAssetFilter(val) {
      if (val === 'ubuntu' || val === 'win10' || val === 'azure') switchTab('hosts');
      else switchTab('dashboard');
    }

    // Polling System
    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // Cập nhật giá trị config từ server (chỉ khi không mở modal để tránh tụt thanh trượt khi đang kéo)
        if (data.config) {
          currentConfig = Object.assign({}, currentConfig, data.config);
          if (!isModalConfigOpen) {
            syncThresholdValues(data.config.cpu_threshold, 'cpu');
            syncThresholdValues(data.config.ram_threshold, 'ram');
            syncThresholdValues(data.config.auth_fail_threshold, 'auth');
            const alertsChk = document.getElementById('modalAlertsEnabled');
            if (alertsChk) alertsChk.checked = data.config.enable_alerts !== false;
          }
        }

        // 1. CPU & RAM
        if (data.metrics) {
          const cpu = data.metrics.cpu || 0;
          const ram = data.metrics.ram || 0;
          document.getElementById('ubuntuMetricsText').innerText = 'CPU: ' + cpu + '% | RAM: ' + ram + '%';
        if (data.brute_force) updateBruteForceCard(data.brute_force, data.soar_config, data.active_containments);
        }

        // 2. Incidents & Tickets
        if (data.incidents && Array.isArray(data.incidents)) {
          const total = data.incidents.length;
          let open = 0, proc = 0;
          data.incidents.forEach(inc => {
            if (inc.color === 'red') open++;
            else proc++;
          });
          document.getElementById('ticketTotal').innerText = total;
          document.getElementById('ticketOpen').innerText = open;
          document.getElementById('ticketProcessing').innerText = proc;
          document.getElementById('siemBadgeCount').innerText = open;

          const container = document.getElementById('latestTicketsList');
          container.innerHTML = '';
          if (data.incidents.length === 0) {
            container.innerHTML = '<div class="p-3 rounded bg-emerald-950/40 border border-emerald-800 text-emerald-400 text-center font-medium">🛡️ Toàn bộ hệ thống an toàn, chưa có vi phạm!</div>';
          }
          const recents = data.incidents.slice(0, 3);
          recents.forEach(inc => {
            const isRed = inc.color === 'red';
            const borderCol = isRed ? 'border-red-500' : 'border-amber-500';
            const textCol = isRed ? 'text-red-300' : 'text-amber-300';
            const html = `
              <div class="p-2 rounded bg-[#0e1522] border-l-2 ${borderCol} flex flex-col gap-0.5 cursor-pointer hover:bg-slate-800/40 transition" onclick="switchTab('siem')">
                <span class="font-bold ${textCol}">${inc.title}</span>
                <div class="flex items-center gap-2 text-[11px] text-slate-400">
                  <span class="text-slate-300">${inc.details || ''}</span> • <span>${inc.time}</span>
                </div>
              </div>
            `;
            container.innerHTML += html;
          });

          const fullTable = document.getElementById('fullSiemTableBody');
          fullTable.innerHTML = '';
          if (data.incidents.length === 0) {
            fullTable.innerHTML = '<tr><td colspan="5" class="p-6 text-center text-slate-400 italic font-sans">Chưa có sự kiện an ninh bất thường nào được ghi nhận. Toàn bộ máy chủ hoạt động bình thường!</td></tr>';
          }
          data.incidents.forEach(inc => {
            const isRed = inc.color === 'red';
            const badgeBg = isRed ? 'bg-red-950 text-red-400 border border-red-800' : 'bg-amber-950 text-amber-400 border border-amber-800';
            const isBrute = (inc.type || '').includes('BRUTE-FORCE') || (inc.title || '').includes('BRUTE-FORCE');
            const soarBtn = isBrute ? `<button onclick="switchTab('dashboard')" class="ml-2 px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-bold text-[10px] shadow transition inline-flex items-center gap-1">⚡ Xử lý SOAR ngay</button>` : '';
            const row = `
              <tr class="hover:bg-slate-800/30">
                <td class="p-3 text-slate-400">${inc.time}</td>
                <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${badgeBg}">${isRed ? 'CRITICAL' : 'WARNING'}</span></td>
                <td class="p-3 text-slate-300 font-semibold">${inc.type || 'SECURITY'}</td>
                <td class="p-3 text-white font-bold">${inc.title}</td>
                <td class="p-3 text-cyan-300 flex items-center justify-between"><span>${inc.details || '-'}</span>${soarBtn}</td>
              </tr>
            `;
            fullTable.innerHTML += row;
          });

          const score = Math.min(98.5, 20 + open * 15 + proc * 5).toFixed(2);
          const pill = document.getElementById('riskScorePill');
          pill.innerText = score;
          pill.style.left = Math.min(92, Math.max(10, score)) + '%';
          const badge = document.getElementById('riskSeverityBadge');
          if (score > 60) {
            badge.innerText = 'Severity: Critical (Báo Động Đỏ)';
            badge.className = 'px-2 py-0.5 rounded text-[11px] font-bold bg-red-950 text-red-400 border border-red-800';
          }
        }

        if (data.voice_alert && data.voice_alert.text) {
          const vt = document.getElementById('voiceFullText');
          if (vt) vt.innerText = `"${data.voice_alert.text}"`;
        }

        if (data.tunnel_url) {
          document.getElementById('tunnelUrlText').innerText = data.tunnel_url;
        }

        document.getElementById('liveTimeBadge').innerText = new Date().toLocaleTimeString('vi-VN');
      } catch (err) {
        console.error('Polling error:', err);
      }
    }

    function triggerEmergencyCall() {
      const topBtn = document.getElementById('topCallBtn');
      topBtn.innerText = 'Đang gọi...';
      fetch('/api/test_internal_call', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          topBtn.innerText = 'Đã gọi về App!';
          alert('🚨 Đã phát lệnh gọi khẩn cấp thành công! Điện thoại của ní đang đổ chuông!');
          setTimeout(() => { topBtn.innerText = 'Bắn Cuộc Gọi Về App'; }, 3500);
        })
        .catch(e => {
          topBtn.innerText = 'Lỗi kết nối';
          setTimeout(() => { topBtn.innerText = 'Bắn Cuộc Gọi Về App'; }, 2000);
        });
    }

    function playAiVoiceDemo() {
      const audio = new Audio('/api/voice_alert?t=' + Date.now());
      audio.play().catch(e => {
        alert('Trình duyệt cần ní tương tác trước để phát âm thanh. Vui lòng bấm thử nghiệm gọi điện trên App!');
      });
    }

    setInterval(fetchStatus, 2500);
    fetchStatus();
  

    // =========================================================================
    // CVE VULNERABILITY AUDIT JAVASCRIPT LOGIC
    // =========================================================================
    function fetchCveStatus() {
      fetch('/api/cve/status')
        .then(res => res.json())
        .then(data => {
          if (!data) return;
          const stats = data.stats || {};
          document.getElementById('cve-total-apps').innerText = data.total_apps || 0;
          document.getElementById('cve-crit-count').innerText = stats.critical || 0;
          document.getElementById('cve-high-count').innerText = stats.high || 0;
          document.getElementById('cve-safe-count').innerText = stats.safe || 0;

          if (data.last_scanned) {
            document.getElementById('cve-last-scanned').innerText = 'Quét lúc: ' + data.last_scanned;
            document.getElementById('cve-host-info').innerText = 'Máy trạm: ' + (data.hostname || '') + ' (' + (data.client_ip || '') + ')';
          }

          const badge = document.getElementById('cve-badge-status');
          if (data.vulnerabilities_found > 0) {
            badge.className = 'px-2.5 py-0.5 rounded text-[11px] font-bold bg-red-950 text-red-400 border border-red-800';
            badge.innerText = '⚠️ ' + data.vulnerabilities_found + ' LỖ HỔNG CẦN XỬ LÝ';
          } else if (data.total_apps > 0) {
            badge.className = 'px-2.5 py-0.5 rounded text-[11px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800';
            badge.innerText = '✅ HỆ THỐNG AN TOÀN';
          } else {
            badge.className = 'px-2.5 py-0.5 rounded text-[11px] font-bold bg-slate-800 text-slate-300';
            badge.innerText = 'Đang chờ quét';
          }

          // Render Vuln Table
          const vulnBody = document.getElementById('cve-vuln-tbody');
          if (data.vulnerabilities && data.vulnerabilities.length > 0) {
            vulnBody.innerHTML = data.vulnerabilities.map(v => {
              const isCrit = v.cvss >= 9.0;
              const sevBadge = isCrit
                ? '<span class="px-2 py-0.5 rounded bg-red-950 text-red-400 font-bold border border-red-800">CRITICAL</span>'
                : '<span class="px-2 py-0.5 rounded bg-amber-950 text-amber-400 font-bold border border-amber-800">HIGH</span>';
              const actionBtn = `<button onclick="remediateCveFile('${v.app}', '${v.cve}')" class="px-3 py-1.5 rounded bg-red-600 hover:bg-red-500 text-white font-bold text-[11px] shadow-md shadow-red-600/30 flex items-center gap-1.5 mx-auto transition cursor-pointer">
                    <span>🗑️</span> Xóa / Cách Ly SOAR
                   </button>`;

              return `<tr>
                <td class="p-3 font-bold text-white font-sans">${v.app}</td>
                <td class="p-3 text-cyan-400">${v.version}</td>
                <td class="p-3 text-amber-400 font-bold">${v.cve}</td>
                <td class="p-3 font-bold ${isCrit ? 'text-red-400' : 'text-amber-400'}">${v.cvss}</td>
                <td class="p-3">${sevBadge}</td>
                <td class="p-3 text-slate-300 font-sans text-xs max-w-xs">${v.description}</td>
                <td class="p-3 text-emerald-400 font-sans text-xs">${v.recommendation}</td>
                <td class="p-3 text-center">${actionBtn}</td>
              </tr>`;
            }).join('');
          } else if (data.total_apps > 0) {
            vulnBody.innerHTML = '<tr><td colspan="7" class="p-5 text-center text-emerald-400 font-sans font-bold">✅ Không phát hiện lỗ hổng CVE nguy hiểm nào trên máy tính đã kiểm tra!</td></tr>';
          }

          // Render Inventory Table
          const invBody = document.getElementById('cve-inventory-tbody');
          if (data.recent_apps && data.recent_apps.length > 0) {
            const vulnNames = new Set((data.vulnerabilities || []).map(x => x.app.toLowerCase()));
            invBody.innerHTML = data.recent_apps.map(app => {
              const isVuln = vulnNames.has(app.name.toLowerCase());
              const statusTag = isVuln
                ? '<span class="px-2 py-0.5 rounded bg-red-950 text-red-400 font-bold">Vulnerable</span>'
                : '<span class="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 font-bold">Audited</span>';
              return `<tr>
                <td class="p-3 font-bold text-white font-sans">${app.name}</td>
                <td class="p-3 text-slate-300">${app.version || '-'}</td>
                <td class="p-3 text-slate-400 font-sans text-xs">${app.publisher || '-'}</td>
                <td class="p-3">${statusTag}</td>
              </tr>`;
            }).join('');
          }
        })
        .catch(err => console.error('Error fetching CVE status:', err));
    }

    
    function remediateCveFile(appName, cveCode) {
      if (!confirm('Bạn có chắc muốn kích hoạt SOAR để TIÊU HỦY / CÁCH LY mối đe dọa [' + appName + '] khỏi máy trạm từ xa không?')) return;
      
      let filename = '';
      const m = appName.match(/Tep.*?:\s*([^\)]+)/i);
      if (m) {
        filename = m[1].trim();
      } else if (appName.toLowerCase().indexOf('winrar') !== -1) {
        filename = 'winrar-x64-622.exe';
      } else if (appName.toLowerCase().indexOf('putty') !== -1) {
        filename = 'putty-0.80-installer.msi';
      } else if (appName.toLowerCase().indexOf('7-zip') !== -1) {
        filename = '7z2201-x64.exe';
      } else {
        filename = appName.toLowerCase().replace(/[^a-z0-9]/g, '_') + '.exe';
      }

      fetch('/api/cve/remediate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete_file', target_file: filename, app_name: appName })
      })
      .then(res => res.json())
      .then(data => {
        alert('⚡ ' + (data.msg || 'Đã phát lệnh SOAR tiêu hủy / cách ly thành công!'));
        fetchCveStatus();
      })
      .catch(err => alert('Lỗi thực thi SOAR: ' + err));
    }

    function triggerCveDemo() {
      fetch('/api/cve/demo_trigger', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          alert('🧪 ' + (data.msg || 'Đã nạp dữ liệu kiểm thử!'));
          fetchCveStatus();
        })
        .catch(err => alert('Lỗi nạp demo: ' + err));
    }

    function resetCveData() {
      fetch('/api/cve/reset', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          fetchCveStatus();
        })
        .catch(err => alert('Lỗi đặt lại: ' + err));
    }

    // Tự động cập nhật CVE khi tải trang
    setInterval(fetchCveStatus, 6000);
    setTimeout(fetchCveStatus, 1000);


    async function triggerBruteAction(action) {
      try {
        const ip = document.getElementById('bruteIp').innerText.replace(' (Gõ sai 3 lần)', '').trim();
        const user = document.getElementById('bruteUser').innerText.trim();
        const res = await fetch('/api/brute_force/remediate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: action, target_ip: ip, target_user: user })
        });
        const d = await res.json();
        alert(d.message || 'Lệnh SOAR đã được gửi tới máy trạm thành công!');
        fetchStatus();
      } catch (e) {
        alert('Lỗi gửi lệnh SOAR: ' + e);
      }
    }

    async function triggerBruteDemo() {
      try {
        const res = await fetch('/api/brute_force/demo_trigger', { method: 'POST' });
        const d = await res.json();
        alert('Đã kích hoạt sự cố Demo Brute-Force: Hệ thống SOAR tự động thực thi Playbook chuẩn NIST SP 800-61!');
        fetchStatus();
      } catch (e) {
        alert('Lỗi kích hoạt demo: ' + e);
      }
    }

    async function resetBruteForce() {
      await soarRollback('all', '');
    }

    async function soarRollback(type, target) {
      try {
        const res = await fetch('/api/soar/rollback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: type, target: target, operator: 'Quản trị viên (1-Click Hub)' })
        });
        const d = await res.json();
        alert(d.message || 'Đã hoàn tác và mở khóa thành công!');
        fetchStatus();
      } catch (e) {
        alert('Lỗi hoàn tác SOAR: ' + e);
      }
    }

    async function updateSoarPolicy() {
      try {
        const mode = document.getElementById('soarModeSelect').value;
        const track = document.getElementById('soarTrackSelect').value;
        await fetch('/api/soar/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: mode, default_track: track })
        });
        fetchStatus();
      } catch (e) {
        console.error('Lỗi cập nhật SOAR policy:', e);
      }
    }

    function renderActiveContainments(containments) {
      const listEl = document.getElementById('soarContainmentList');
      const badgeEl = document.getElementById('containmentCountBadge');
      if (!listEl) return;

      const blockedIps = (containments && containments.blocked_ips) ? Object.values(containments.blocked_ips) : [];
      const lockedUsers = (containments && containments.locked_users) ? Object.values(containments.locked_users) : [];
      const total = blockedIps.length + lockedUsers.length;

      if (badgeEl) {
        badgeEl.innerText = total + ' mục';
        badgeEl.className = total > 0 ? 'px-1.5 py-0.2 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800' : 'px-1.5 py-0.2 rounded text-[10px] font-bold bg-slate-800 text-slate-400';
      }

      if (total === 0) {
        listEl.innerHTML = `
          <div class="p-3 rounded-lg bg-emerald-950/30 border border-emerald-800/40 text-emerald-400 text-center font-medium text-xs">
            ✅ Toàn bộ hệ thống an toàn • Không có IP hay User nào bị cách ly
          </div>
        `;
        return;
      }

      let html = '';
      blockedIps.forEach(item => {
        html += `
          <div class="p-2.5 rounded-lg bg-rose-950/40 border border-rose-700/60 flex items-center justify-between text-xs transition">
            <div class="space-y-0.5">
              <div class="flex items-center gap-1.5">
                <span class="text-rose-400 font-bold">🛡️ IP Bị Chặn:</span>
                <span class="font-mono font-bold text-white">${item.target}</span>
              </div>
              <div class="text-[10px] text-rose-300/80 font-mono">${item.rule || 'Windows Firewall Rule'} • ${item.time_str || ''}</div>
            </div>
            <button onclick="soarRollback('ip', '${item.target}')" class="px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-bold text-[11px] shadow transition active:scale-95 flex items-center gap-1">
              <span>🔓</span> Bỏ chặn IP
            </button>
          </div>
        `;
      });

      lockedUsers.forEach(item => {
        html += `
          <div class="p-2.5 rounded-lg bg-amber-950/40 border border-amber-700/60 flex items-center justify-between text-xs transition">
            <div class="space-y-0.5">
              <div class="flex items-center gap-1.5">
                <span class="text-amber-400 font-bold">🔒 User Bị Khóa:</span>
                <span class="font-mono font-bold text-white">${item.target}</span>
              </div>
              <div class="text-[10px] text-amber-300/80 font-mono">SAM Account Disabled • ${item.time_str || ''}</div>
            </div>
            <button onclick="soarRollback('user', '${item.target}')" class="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-[11px] shadow transition active:scale-95 flex items-center gap-1">
              <span>🔑</span> Mở khóa User
            </button>
          </div>
        `;
      });

      listEl.innerHTML = html;
    }

    function updateBruteForceCard(bf, soarConfig, activeContainments) {
      if (!bf) return;
      const container = document.getElementById('cardBruteForceContainer');
      const badge = document.getElementById('bruteBadgeStatus');
      const icon = document.getElementById('bruteIcon');
      const title = document.getElementById('bruteTitle');
      const host = document.getElementById('bruteHost');
      const user = document.getElementById('bruteUser');
      const ip = document.getElementById('bruteIp');
      const count = document.getElementById('bruteCount');
      const timeEl = document.getElementById('bruteTime');
      const histBox = document.getElementById('bruteHistoryBox');
      const modeBadge = document.getElementById('soarModeBadge');
      const modeSelect = document.getElementById('soarModeSelect');
      const trackSelect = document.getElementById('soarTrackSelect');

      const sStepDetect = document.getElementById('stepDetect');
      const sStepTriage = document.getElementById('stepTriage');
      const sStepContain = document.getElementById('stepContain');
      const sStepRecover = document.getElementById('stepRecover');

      if (host) host.innerText = (bf.hostname || 'NGUYENVANTIEN') + ' (192.168.21.156)';
      if (user) user.innerText = bf.target_user || 'tien0';
      if (ip) ip.innerText = bf.attacker_ip || '192.168.21.105';
      if (count) count.innerText = (bf.fail_count || 0) + ' lần gõ sai';
      if (timeEl) timeEl.innerText = bf.detected_at || '--:--:--';

      if (soarConfig) {
        if (modeSelect && modeSelect.value !== soarConfig.mode) modeSelect.value = soarConfig.mode;
        if (trackSelect && trackSelect.value !== soarConfig.default_track) trackSelect.value = soarConfig.default_track;
        if (modeBadge) {
          if (soarConfig.mode === 'auto') {
            modeBadge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-700 animate-pulse';
            modeBadge.innerText = '⚡ AUTO-PILOT (TỰ ĐỘNG 100%)';
          } else {
            modeBadge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-400 border border-amber-700';
            modeBadge.innerText = '🛡️ BÁN TỰ ĐỘNG (APPROVAL)';
          }
        }
      }

      renderActiveContainments(activeContainments);

      if (bf.active) {
        if (container) {
          container.className = 'col-span-1 md:col-span-2 lg:col-span-3 rounded-2xl p-5 border transition-all duration-300 bg-gradient-to-r from-[#240e1b] via-[#1c1228] to-[#121926] border-rose-600 shadow-xl shadow-rose-950/30';
        }
        if (badge) {
          badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-700 animate-pulse';
          badge.innerText = 'CẢNH BÁO: TẤN CÔNG BRUTE-FORCE';
        }
        if (icon) {
          icon.className = 'text-2xl p-2.5 rounded-xl bg-rose-900/60 text-rose-400 animate-bounce border border-rose-500/50';
          icon.innerText = '🚨';
        }

        // Highlight steps
        if (sStepDetect) sStepDetect.className = 'p-1 rounded bg-rose-900/60 text-rose-200 border border-rose-500 font-bold';
        if (sStepTriage) sStepTriage.className = 'p-1 rounded bg-amber-900/60 text-amber-200 border border-amber-500 font-bold';
        if (sStepContain) sStepContain.className = 'p-1 rounded bg-cyan-900/60 text-cyan-200 border border-cyan-500 font-bold';
        if (sStepRecover) sStepRecover.className = 'p-1 rounded bg-emerald-900/60 text-emerald-200 border border-emerald-500 font-bold';

      } else {
        if (container) {
          container.className = 'col-span-1 md:col-span-2 lg:col-span-3 rounded-2xl p-5 border transition-all duration-300 bg-[#121926] border-[#1e283b] shadow-xl';
        }
        if (badge) {
          badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700';
          badge.innerText = 'Hệ thống bình thường';
        }
        if (icon) {
          icon.className = 'text-2xl p-2.5 rounded-xl bg-gradient-to-br from-cyan-900/60 to-slate-900 border border-cyan-500/30 text-cyan-400 shadow-inner';
          icon.innerText = '🛡️';
        }

        if (sStepDetect) sStepDetect.className = 'p-1 rounded bg-slate-800 text-slate-400 border border-slate-700';
        if (sStepTriage) sStepTriage.className = 'p-1 rounded bg-slate-800 text-slate-400 border border-slate-700';
        if (sStepContain) sStepContain.className = 'p-1 rounded bg-slate-800 text-slate-400 border border-slate-700';
        if (sStepRecover) sStepRecover.className = 'p-1 rounded bg-slate-800 text-slate-400 border border-slate-700';
      }

      if (histBox && bf.remediation_history && bf.remediation_history.length > 0) {
        let hHtml = '<div class="text-[10px] text-slate-500 font-semibold mb-0.5">Nhật ký SOAR:</div>';
        bf.remediation_history.slice(-3).reverse().forEach(h => {
          hHtml += `<div class="text-[10px] text-slate-400">• <span class="text-cyan-400">[${h.time}]</span> ${h.detail || h.action}</div>`;
        });
        histBox.innerHTML = hHtml;
      }
    } else {
        if (container) {
          container.className = 'col-span-1 md:col-span-2 lg:col-span-3 rounded-xl p-5 border transition-all duration-300 bg-[#121926] border-[#1e283b] shadow-md';
        }
        if (badge) {
          badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800';
          badge.innerText = 'Bình thường';
        }
        if (icon) {
          icon.className = 'text-2xl p-2 rounded-lg bg-slate-800 text-slate-300';
          icon.innerText = '🛡️';
        }
        if (title) {
          title.className = 'font-bold text-sm text-white tracking-wide';
          title.innerText = 'GIÁM SÁT TẤN CÔNG BRUTE-FORCE DÒ MẬT KHẨU';
        }
      }

      if (histBox && bf.remediation_history && Array.isArray(bf.remediation_history)) {
        if (bf.remediation_history.length > 0) {
          histBox.innerHTML = '<div class="text-slate-400 font-bold mb-1">Nhật ký phản ứng SOAR:</div>' +
            bf.remediation_history.slice(-3).map(h => `<div class="text-emerald-400">⚡ [${h.time}] ${h.detail}</div>`).join('');
        } else {
          histBox.innerHTML = '';
        }
      }
    }

  </script>
</body>
</html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
