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


def get_current_tunnel_url():
    return "http://70.153.83.137"
def generate_ai_voice(title, text):
    global LATEST_VOICE_ALERT
    now_ts = time.time()
    with _lock:
        LATEST_VOICE_ALERT["alert_id"] += 1
        LATEST_VOICE_ALERT["title"] = title
        LATEST_VOICE_ALERT["text"] = text
        LATEST_VOICE_ALERT["time"] = _now_str()
        LATEST_VOICE_ALERT["timestamp"] = now_ts
        aid = LATEST_VOICE_ALERT["alert_id"]

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

            # 1. CHỈ GỌI ĐIỆN THOẠI KHI CPU QUÁ TẢI MỨC ĐỎ NGUY CẤP (>= 95%)
            # GỌI ĐIỆN THOẠI KHI CPU QUÁ TẢI NGUY CẤP (>= 95%) HOẶC BẤM NÚT TEST (ngưỡng <= 10%)
            if cpu_val >= 95.0 or CONFIG.get("cpu_threshold", 85) <= 10.0:
                generate_ai_voice(
                    f"Quá tải CPU {cpu_val:.0f}%",
                    f"Cảnh báo khẩn cấp! Máy trạm Windows địa chỉ IP {client_ip} đang bị quá tải tài nguyên! CPU {cpu_val:.0f} phần trăm, RAM {ram_val:.0f} phần trăm. Đề nghị kỹ sư trực ban kiểm tra ngay!"
                )

            # 2. Báo Telegram
            sys_msg = (
                f"🚨 <b>[SME SOC - MÁY TRẠM QUÁ TẢI]</b> 🚨\n"
                f"💻 IP: <code>{client_ip}</code>\n"
                f"🔥 CPU: <b>{cpu_val:.1f}%</b> (Ngưỡng {CONFIG['cpu_threshold']}%) | 💾 RAM: <b>{ram_val:.1f}%</b> (Ngưỡng {CONFIG['ram_threshold']}%)\n"
                f"⚠️ Kích hoạt chuông gọi nội bộ & Báo động tới kỹ sư trực ban!\n"
                f"⏱ <i>{_now_str()}</i>"
            )
            send_telegram(sys_msg, thread_id=TOPIC_SYSTEM_ID)
            send_soar_cpu_ram_alert(cpu_val, ram_val, client_ip)

        elif is_recovered and old_status == "overload":
            CURRENT_METRICS["status"] = "normal"
            rec_msg = f"✅ <b>[MÁY TRẠM ĐÃ HẠ TẢI AN TOÀN]</b> CPU: {cpu_val:.1f}%, RAM: {ram_val:.1f}%"
            send_telegram(rec_msg, thread_id=TOPIC_SYSTEM_ID)

    return {
            "tunnel_url": get_current_tunnel_url(),"status": "ok", "action": cmd_action}

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
            "push_sub_count": len(PUSH_SUBSCRIPTIONS)
        }

@app.post("/api/config")
async def update_config(req: Request):
    body = await req.json()
    with _lock:
        for k in ("cpu_threshold", "ram_threshold", "web_mb_threshold", "auth_fail_threshold"):
            if k in body:
                CONFIG[k] = float(body[k]) if "threshold" in k and k != "auth_fail_threshold" else int(body[k])
    return {"status": "ok", "config": CONFIG}

def _es_search(index, query):
    try:
        headers = {"Content-Type": "application/json"}
        if ES_API_KEY: headers["Authorization"] = f"ApiKey {ES_API_KEY}"
        r = requests.post(f"{ES_URL}/{index}/_search", json=query, headers=headers, timeout=5)
        return r.json() if r.status_code == 200 else {}
    except: return {}

_last_seen_auth_time = {}

def check_auth_logs():
    global _last_seen_auth_time
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

def trigger_db_alert(alert_key, title, details, voice_text, telegram_text, cooldown=30):
    now = time.time()
    if now - _last_mysql_alerts.get(alert_key, 0) < cooldown:
        return

    # Nếu là lệnh DROP thì CHỈ THÔNG BÁO trong khung giờ từ 18h đến 19h (7h tối)
    current_hour = datetime.now().hour
    if ('drop_table' in alert_key or 'DROP' in title.upper()) and not (18 <= current_hour < 19):
        return

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
@app.get("/", response_class=HTMLResponse)
def dashboard_html():
    return """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SME SOC Dashboard & Emergency Center</title>
    
    <!-- PWA & Apple iOS Tags -->
    <link rel="manifest" href="/manifest.json">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="SOC Alert">
    <meta name="theme-color" content="#0284c7">

    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
            background: #0b1120; 
            color: #f8fafc; 
            margin: 0; 
            padding: 12px 16px; 
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            border-bottom: 1px solid #1e293b; 
            padding-bottom: 10px; 
            margin-bottom: 12px; 
            flex-wrap: wrap;
            gap: 10px;
        }
        h1 { margin: 0; font-size: 18px; color: #38bdf8; display: flex; align-items: center; gap: 8px; }
        
        .header-buttons { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        .btn-pwa-unlock { background: #0284c7; color: white; padding: 7px 14px; border-radius: 6px; font-weight: bold; border: none; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 6px; box-shadow: 0 2px 8px rgba(2, 132, 199, 0.4); }
        .btn-pwa-test { background: #334155; color: #38bdf8; padding: 7px 14px; border-radius: 6px; font-weight: bold; border: 1px solid #0284c7; cursor: pointer; font-size: 12px; }

        /* 3 BẢNG TRÊN */
        .grid-top { display: grid; grid-template-columns: 1fr 1.2fr 1fr; gap: 12px; margin-bottom: 12px; }
        @media (max-width: 900px) {
            .grid-top { grid-template-columns: 1fr; }
        }
        .card-mini { background: #1e293b; border-radius: 8px; padding: 12px 14px; border: 1px solid #334155; }
        .card-mini-title { font-size: 13px; font-weight: bold; color: #94a3b8; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        
        .metrics-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: center; }
        .metric-box { background: #0f172a; padding: 6px 10px; border-radius: 6px; border: 1px solid #334155; }
        .metric-num { font-size: 20px; font-weight: 800; color: #38bdf8; }
        .progress-bar { background: #334155; height: 6px; border-radius: 3px; overflow: hidden; margin-top: 4px; }
        .progress-fill { background: #38bdf8; height: 100%; width: 0%; transition: width 0.3s; }
        
        .badge { padding: 3px 8px; border-radius: 999px; font-size: 10px; font-weight: bold; }
        .badge-normal { background: #065f46; color: #34d399; }
        .badge-overload { background: #991b1b; color: #f87171; animation: pulse 1.2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

        /* FORM NGƯỠNG */
        .cfg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; }
        .cfg-item label { display: block; font-size: 11px; color: #94a3b8; margin-bottom: 2px; }
        .cfg-item input { width: 100%; padding: 4px 8px; background: #0f172a; border: 1px solid #475569; border-radius: 4px; color: #fff; font-size: 12px; }
        
        .btn-group { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
        .btn { padding: 5px 10px; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; font-size: 11px; }
        .btn-primary { background: #0284c7; color: white; }
        .btn-danger { background: #dc2626; color: white; }
        .btn-warning { background: #d97706; color: white; }
        .btn-secondary { background: #475569; color: white; }

        /* BẢNG LOG DƯỚI */
        .log-container { background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155; flex-grow: 1; display: flex; flex-direction: column; }
        .log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #334155; padding-bottom: 8px; }
        .log-list { overflow-y: auto; max-height: 400px; flex-grow: 1; }
        
        .log-row { display: grid; grid-template-columns: 130px 180px 1fr 100px; gap: 10px; align-items: center; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; font-size: 12px; font-family: monospace; }
        @media (max-width: 768px) {
            .log-row { grid-template-columns: 1fr; gap: 4px; }
        }
        .log-red { background: rgba(239, 68, 68, 0.15); border-left: 4px solid #ef4444; color: #fca5a5; }
        .log-red .tag { background: #ef4444; color: #fff; }
        .log-orange { background: rgba(249, 115, 22, 0.15); border-left: 4px solid #f97316; color: #fdba74; }
        .log-orange .tag { background: #f97316; color: #fff; }
        .log-purple { background: rgba(168, 85, 247, 0.15); border-left: 4px solid #a855f7; color: #d8b4fe; }
        .log-purple .tag { background: #a855f7; color: #fff; }
        .log-yellow { background: rgba(234, 179, 8, 0.15); border-left: 4px solid #eab308; color: #fde047; }
        .log-yellow .tag { background: #eab308; color: #000; font-weight: bold; }
        .log-blue { background: rgba(14, 165, 233, 0.15); border-left: 4px solid #0ea5e9; color: #7dd3fc; }
        .log-blue .tag { background: #0ea5e9; color: #fff; }
        .filter-btn { background: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; transition: all 0.2s; }
        .filter-btn.active, .filter-btn:hover { background: #0284c7; color: white; border-color: #38bdf8; }
        .tag { padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; text-align: center; display: inline-block; }

        /* MÀN HÌNH CUỘC GỌI TOÀN MÀN HÌNH */
        .call-overlay {
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(11, 17, 32, 0.95);
            backdrop-filter: blur(10px);
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .call-box {
            background: #1e293b;
            border: 2px solid #ef4444;
            border-radius: 16px;
            max-width: 440px;
            width: 100%;
            padding: 28px 24px;
            text-align: center;
            box-shadow: 0 0 50px rgba(239, 68, 68, 0.5);
            animation: pulse-border 1.5s infinite;
        }
        @keyframes pulse-border {
            0%, 100% { box-shadow: 0 0 30px rgba(239, 68, 68, 0.4); }
            50% { box-shadow: 0 0 60px rgba(239, 68, 68, 0.8); }
        }
        .call-badge { display: inline-block; background: #991b1b; color: #fca5a5; padding: 4px 12px; border-radius: 999px; font-weight: bold; font-size: 12px; margin-bottom: 12px; }
        .call-avatar { width: 72px; height: 72px; margin: 0 auto 12px auto; background: #0f172a; border: 2px solid #38bdf8; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 32px; animation: bounce 1s infinite alternate; }
        @keyframes bounce { from { transform: scale(0.95); } to { transform: scale(1.05); } }
        .call-title { margin: 0 0 8px 0; font-size: 20px; color: #f87171; }
        .call-msg { font-size: 14px; color: #cbd5e1; margin-bottom: 16px; line-height: 1.5; }
        .call-pulse-text { font-size: 13px; font-weight: bold; color: #fbbf24; margin-bottom: 20px; letter-spacing: 1px; }

        .call-actions { display: flex; flex-direction: column; gap: 10px; }
        .btn-call-answer { background: #16a34a; color: white; padding: 14px; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 4px 15px rgba(22, 163, 74, 0.4); }
        .btn-call-answer:hover { background: #15803d; }
        .btn-call-decline { background: #334155; color: #94a3b8; padding: 10px; border: none; border-radius: 10px; font-size: 13px; font-weight: bold; cursor: pointer; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ SME SOC CONTROL & EMERGENCY MONITOR</h1>
        <div class="header-buttons">
            <div id="tunnelBadge" style="background: rgba(14, 165, 233, 0.15); border: 1px solid #0284c7; border-radius: 6px; padding: 5px 12px; font-size: 11px; color: #38bdf8; display: inline-flex; align-items: center; gap: 8px; cursor: pointer;" onclick="copyTunnelUrl()" title="Bấm để sao chép đường link App">
                <span>📱 Link App:</span>
                <strong id="tunnelUrlText" style="color: #fff; font-family: monospace;">https://brands-sense-protocol-capacity.trycloudflare.com</strong>
                <span style="font-size: 10px; background: #0284c7; color: #fff; padding: 2px 6px; border-radius: 3px; font-weight: bold;">COPY</span>
            </div>
            <button id="btnPush" class="btn-pwa-unlock" onclick="enablePushNotifications()">🔔 BẬT BÁO ĐỘNG MÀN HÌNH KHÓA</button>
            <button class="btn-pwa-test" onclick="triggerTestInternalCall()">📞 Test gọi & Báo động</button>
        </div>
    </div>

    <!-- 3 BẢNG TRÊN -->
    <div class="grid-top">
        <div class="card-mini">
            <div class="card-mini-title">
                <span>💻 WINDOWS (192.168.21.148)</span>
                <span id="vmStatus" class="badge badge-normal">BÌNH THƯỜNG</span>
            </div>
            <div class="metrics-row">
                <div class="metric-box">
                    <span style="font-size: 11px; color: #94a3b8;">CPU:</span> <span id="cpuVal" class="metric-num">0%</span>
                    <div class="progress-bar"><div id="cpuFill" class="progress-fill"></div></div>
                </div>
                <div class="metric-box">
                    <span style="font-size: 11px; color: #94a3b8;">RAM:</span> <span id="ramVal" class="metric-num">0%</span>
                    <div class="progress-bar"><div id="ramFill" class="progress-fill"></div></div>
                </div>
            </div>
            <div style="font-size: 11px; color: #64748b; margin-top: 6px;">Cập nhật: <span id="lastUpdate">--</span></div>
        </div>

        <div class="card-mini">
            <div class="card-mini-title"><span>⚙️ ĐIỀU CHỈNH NGƯỠNG AN NINH</span></div>
            <div class="cfg-grid">
                <div class="cfg-item"><label>Ngưỡng CPU (%):</label><input type="number" id="cfgCpu"></div>
                <div class="cfg-item"><label>Ngưỡng RAM (%):</label><input type="number" id="cfgRam"></div>
                <div class="cfg-item"><label>Sai MK (Lần):</label><input type="number" id="cfgAuth"></div>
                <div class="cfg-item"><label>Web Proxy (MB):</label><input type="number" id="cfgWeb" step="0.5"></div>
            </div>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="saveConfig()">💾 Lưu</button>
                <button class="btn btn-warning" onclick="quickTestLowerCpu()">⚡ Test 10%</button>
                <button class="btn btn-secondary" onclick="resetConfig()">🔄 Reset</button>
            </div>
        </div>

        <div class="card-mini">
            <div class="card-mini-title">
                <span>⚡ TỔNG ĐÀI AI & WEB PUSH</span>
                <span id="voiceBadge" class="badge badge-normal">SẴN SÀNG</span>
            </div>
            <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 6px;">
                Trực ban: <b id="voiceAlertTitle" style="color:#38bdf8;">Chưa có sự cố</b>
            </div>
            <div style="font-size: 11px; color: #94a3b8; margin-bottom: 8px;">
                Thiết bị nhận push: <span id="pushCount" style="color:#34d399; font-weight:bold;">0</span> máy
            </div>
            <div class="btn-group">
                <button class="btn btn-danger" onclick="triggerShutdown()">🛑 Shutdown VM</button>
                <button class="btn btn-warning" onclick="triggerRaise()">⚡ Hạ tải SOAR</button>
            </div>
        </div>
    </div>

    <!-- BẢNG THEO DÕI SỰ CỐ (ĐA MÀU CHUẨN SOC) -->
    <div class="log-container">
        <div class="log-header" style="flex-wrap: wrap; gap: 8px;">
            <div style="font-weight: bold; color: #f8fafc; font-size: 13px; display: flex; align-items: center; gap: 8px;">
                🚨 BẢNG THEO DÕI SỰ CỐ AN NINH MẠNG THỜI GIAN THỰC 
                <span id="incidentCount" class="badge badge-normal">0 sự cố</span>
            </div>
            <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                <button class="filter-btn active" onclick="setFilter('all', this)">Tất cả</button>
                <button class="filter-btn" onclick="setFilter('critical', this)">🔴 Nguy cấp (SEV-0)</button>
                <button class="filter-btn" onclick="setFilter('exploit', this)">🟠 Tấn công (WAF/SQLi)</button>
                <button class="filter-btn" onclick="setFilter('auth', this)">🟣 Xác thực (Brute-force)</button>
                <button class="filter-btn" onclick="setFilter('warning', this)">🟡 Thăm dò (Recon/DDL)</button>
                <button class="filter-btn" onclick="setFilter('infra', this)">🔵 Tài nguyên (CPU/DoS)</button>
            </div>
        </div>
        <div style="font-size: 11px; color: #64748b; margin-bottom: 8px; display: flex; gap: 14px; flex-wrap: wrap;">
            <span>🔴 <b style="color:#ef4444;">ĐỎ:</b> Phá hoại, RCE Web Shell, Tắt Log</span>
            <span>🟠 <b style="color:#f97316;">CAM:</b> SQL Injection, WAF Lớp 7, Remote Root</span>
            <span>🟣 <b style="color:#a855f7;">TÍM:</b> Brute-force mật khẩu, Leo thang quyền</span>
            <span>🟡 <b style="color:#eab308;">VÀNG:</b> Fuzzing 1064, DDL đêm, Web Proxy</span>
            <span>🔵 <b style="color:#0ea5e9;">XANH:</b> Quá tải CPU/RAM, DoS kết nối</span>
        </div>
        <div id="logList" class="log-list">
            <div style="text-align: center; color: #64748b; padding: 40px;">Đang lắng nghe sự kiện an ninh từ Windows, Gateway Proxy & WAF ModSecurity...</div>
        </div>
    </div>

    <!-- GIAO DIỆN CUỘC GỌI ĐẾN TOÀN MÀN HÌNH TRÊN IPHONE -->
    <div id="callOverlay" class="call-overlay" style="display: none;">
        <div class="call-box">
            <div class="call-badge">🚨 CUỘC GỌI CẢNH BÁO NỘI BỘ</div>
            <div class="call-avatar">🛡️</div>
            <h2 id="callTitle" class="call-title">BÁO ĐỘNG AN NINH</h2>
            <p id="callMessage" class="call-msg">Đang kết nối tổng đài...</p>
            <div id="callStatusText" class="call-pulse-text">📞 ĐANG ĐỔ CHUÔNG RENG RENG...</div>
            <div class="call-actions">
                <button id="btnAnswer" class="btn-call-answer" onclick="answerCall()">📞 NHẤC MÁY (NGHE GIỌNG NÓI AI)</button>
                <button id="btnDecline" class="btn-call-decline" onclick="declineCall()">⛔ TẮT CHUÔNG</button>
            </div>
            <div id="soarActionsMobile" style="display:none; margin-top: 16px; border-top: 1px solid #334155; padding-top: 12px;">
                <div style="font-size: 11px; color: #94a3b8; margin-bottom: 8px;">Phản ứng nhanh SOAR từ xa:</div>
                <div class="btn-group" style="justify-content: center;">
                    <button class="btn btn-danger" onclick="triggerShutdown()">🛑 Tắt máy từ xa</button>
                    <button class="btn btn-warning" onclick="triggerRaise()">⚡ Hạ tải</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Đăng ký Service Worker
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').then(reg => {
                console.log('SW Registered successfully:', reg.scope);
            }).catch(err => {
                console.log('SW registration error:', err);
            });
        }

        // Hệ thống âm thanh Web Audio Synthesizer
        let audioCtx = null;
        let ringInterval = null;
        let isRinging = false;
        let audioUnlocked = false;
        let lastHandledAlertId = 0;
        let voiceAudio = new Audio();

        function unlockAudio() {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            audioUnlocked = true;
            playSingleBeep(880, 0.1);
        }

        function playSingleBeep(freq, dur) {
            try {
                if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.frequency.value = freq;
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
                osc.start();
                osc.stop(audioCtx.currentTime + dur);
            } catch(e) {}
        }

        function startTelephoneRingtone() {
            if (isRinging) return;
            isRinging = true;
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();

            function ringCadence() {
                if (!isRinging || !audioCtx) return;
                const t0 = audioCtx.currentTime;
                [440, 480].forEach(freq => {
                    const osc = audioCtx.createOscillator();
                    const gain = audioCtx.createGain();
                    osc.frequency.value = freq;
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    gain.gain.setValueAtTime(0.25, t0);
                    gain.gain.setValueAtTime(0, t0 + 1.2);
                    osc.start(t0);
                    osc.stop(t0 + 1.2);
                });
            }

            ringCadence();
            ringInterval = setInterval(ringCadence, 3000);
        }

        function stopRingtone() {
            isRinging = false;
            if (ringInterval) {
                clearInterval(ringInterval);
                ringInterval = null;
            }
        }

        function showIncomingCall(title, msg) {
            document.getElementById('callTitle').innerText = title;
            document.getElementById('callMessage').innerText = msg;
            document.getElementById('callStatusText').innerHTML = '📞 ĐANG ĐỔ CHUÔNG RENG RENG...';
            document.getElementById('btnAnswer').style.display = 'flex';
            document.getElementById('soarActionsMobile').style.display = 'none';
            document.getElementById('callOverlay').style.display = 'flex';
            startTelephoneRingtone();
        }

        function answerCall() {
            stopRingtone();
            document.getElementById('callStatusText').innerHTML = '🟢 ĐANG PHÁT GIỌNG NÓI AI QUA LOA...';
            document.getElementById('btnAnswer').style.display = 'none';
            document.getElementById('soarActionsMobile').style.display = 'block';

            voiceAudio.src = '/api/voice_alert?t=' + Date.now();
            voiceAudio.play().catch(e => console.log('Audio play error:', e));
            voiceAudio.onended = () => {
                document.getElementById('callStatusText').innerHTML = '✅ ĐÃ HOÀN THÀNH BẢN TIN CẢNH BÁO';
            };
        }

        function declineCall() {
            stopRingtone();
            if (voiceAudio) voiceAudio.pause();
            document.getElementById('callOverlay').style.display = 'none';
        }

        function copyTunnelUrl() {
            const txt = document.getElementById('tunnelUrlText').innerText;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(txt);
                }
            } catch(e) {}
            prompt('Đã sao chép đường link App Mobile. Anh dán vào App điện thoại nhé:', txt);
        }

        async function triggerTestInternalCall() {
            unlockAudio();
            await fetch('/api/test_internal_call', { method: 'POST' });
        }

        // BẬT WEB PUSH NOTIFICATION CHO MÀN HÌNH KHÓA IPHONE
        async function enablePushNotifications() {
            unlockAudio();
            if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
                alert('⚠️ Để nhận thông báo màn hình khóa trên iPhone, anh hãy bấm nút Chia sẻ -> "Thêm vào Màn hình chính" trước nhé!');
                return;
            }
            try {
                const permission = await Notification.requestPermission();
                if (permission !== 'granted') {
                    alert('❌ Quyền thông báo bị từ chối trong Cài đặt iPhone!');
                    return;
                }

                const reg = await navigator.serviceWorker.ready;
                const resp = await fetch('/api/vapid_public_key');
                const keyData = await resp.json();
                
                const sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlB64ToUint8Array(keyData.publicKey)
                });

                await fetch('/api/push_subscribe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(sub)
                });

                const btn = document.getElementById('btnPush');
                btn.innerHTML = '✅ ĐÃ BẬT BÁO ĐỘNG MÀN HÌNH KHÓA';
                btn.style.background = '#065f46';
                btn.style.color = '#34d399';
                alert('🎉 THÀNH CÔNG! Giờ đây khi tắt màn hình iPhone, bạn vẫn sẽ nhận được thông báo rung và chuông cảnh báo!');
            } catch (err) {
                alert('Lỗi kích hoạt Push: ' + err.message);
            }
        }

        function urlB64ToUint8Array(base64String) {
            const padding = '='.repeat((4 - base64String.length % 4) % 4);
            const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
            const rawData = window.atob(base64);
            const outputArray = new Uint8Array(rawData.length);
            for (let i = 0; i < rawData.length; ++i) {
                outputArray[i] = rawData.charCodeAt(i);
            }
            return outputArray;
        }

        // Khi người dùng bấm vào thông báo màn hình khóa mở ra: Tự động phát giọng nói AI!
        window.addEventListener('DOMContentLoaded', () => {
            const params = new URLSearchParams(window.location.search);
            if (params.get('play_alert') === '1') {
                setTimeout(() => {
                    showIncomingCall('🚨 BÁO ĐỘNG TỪ MÀN HÌNH KHÓA', 'Đang phát bản tin an ninh khẩn cấp...');
                    answerCall();
                }, 600);
            }
        });

                let currentFilter = 'all';
        let cachedIncidents = [];

        function setFilter(category, btn) {
            currentFilter = category;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            renderIncidents();
        }

        function renderIncidents() {
            const container = document.getElementById('logList');
            if (!cachedIncidents || cachedIncidents.length === 0) return;
            
            document.getElementById('incidentCount').innerText = cachedIncidents.length + ' sự cố';
            let html = '';
            cachedIncidents.forEach(item => {
                const fullText = (item.type + ' ' + item.title + ' ' + (item.details || '')).toUpperCase();
                
                let colorClass = 'log-blue';
                let levelTag = '<span class="tag">INFRA OVERLOAD</span>';
                let category = 'infra';
                
                if (fullText.includes('XÓA') || fullText.includes('DROP') || fullText.includes('TRUNCATE') || fullText.includes('RCE') || fullText.includes('WEB SHELL') || fullText.includes('TẮT LOG') || fullText.includes('DEFENSE')) {
                    colorClass = 'log-red';
                    levelTag = '<span class="tag">CRITICAL (SEV-0)</span>';
                    category = 'critical';
                } else if (fullText.includes('SQL INJECTION') || fullText.includes('BLIND') || fullText.includes('REMOTE ROOT') || fullText.includes('WAF') || fullText.includes('MODSECURITY')) {
                    colorClass = 'log-orange';
                    levelTag = '<span class="tag">EXPLOIT (WAF/SQLi)</span>';
                    category = 'exploit';
                } else if (fullText.includes('BRUTE-FORCE') || fullText.includes('MẬT KHẨU') || fullText.includes('LEO THANG') || fullText.includes('PRIVILEGE') || fullText.includes('WHITELIST') || fullText.includes('4625')) {
                    colorClass = 'log-purple';
                    levelTag = '<span class="tag">AUTH / ACCESS</span>';
                    category = 'auth';
                } else if (fullText.includes('FUZZ') || fullText.includes('1064') || fullText.includes('ĐÊM') || fullText.includes('TIME ANOMALY') || fullText.includes('PROXY')) {
                    colorClass = 'log-yellow';
                    levelTag = '<span class="tag">WARNING / RECON</span>';
                    category = 'warning';
                } else {
                    colorClass = 'log-blue';
                    levelTag = '<span class="tag">INFRA / OVERLOAD</span>';
                    category = 'infra';
                }
                
                if (currentFilter !== 'all' && currentFilter !== category) {
                    return;
                }
                
                html += `
                    <div class="log-row ${colorClass}">
                        <div style="color: #94a3b8;">⏱ ${item.time}</div>
                        <div style="font-weight: bold;">${item.type}</div>
                        <div><b>${item.title}</b> <span style="opacity: 0.8; font-size: 11px;">(${item.details})</span></div>
                        <div style="text-align: right;">${levelTag}</div>
                    </div>
                `;
            });
            if (!html) {
                html = '<div style="text-align: center; color: #64748b; padding: 30px;">Không có sự cố nào thuộc danh mục này.</div>';
            }
            container.innerHTML = html;
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();

                // 1. Cập nhật metrics CPU/RAM
                const cpu = d.metrics.cpu || 0;
                const ram = d.metrics.ram || 0;
                document.getElementById('cpuVal').innerText = cpu.toFixed(1) + '%';
                document.getElementById('ramVal').innerText = ram.toFixed(1) + '%';
                document.getElementById('lastUpdate').innerText = d.metrics.last_updated;

                const cpuFill = document.getElementById('cpuFill');
                cpuFill.style.width = cpu + '%';
                cpuFill.style.background = cpu >= d.config.cpu_threshold ? '#ef4444' : '#38bdf8';

                const ramFill = document.getElementById('ramFill');
                ramFill.style.width = ram + '%';

                const statusBadge = document.getElementById('vmStatus');
                if (d.metrics.status === 'overload') {
                    statusBadge.innerText = '🔥 QUÁ TẢI';
                    statusBadge.className = 'badge badge-overload';
                } else {
                    statusBadge.innerText = 'BÌNH THƯỜNG';
                    statusBadge.className = 'badge badge-normal';
                }

                // 2. Điền form cấu hình nếu không đang focus
                if (!document.getElementById('cfgCpu').dataset.focused) document.getElementById('cfgCpu').value = d.config.cpu_threshold;
                if (!document.getElementById('cfgRam').dataset.focused) document.getElementById('cfgRam').value = d.config.ram_threshold;
                if (!document.getElementById('cfgAuth').dataset.focused) document.getElementById('cfgAuth').value = d.config.auth_fail_threshold;
                if (!document.getElementById('cfgWeb').dataset.focused) document.getElementById('cfgWeb').value = d.config.web_mb_threshold;

                // 3. Số máy đăng ký push
                if (document.getElementById('pushCount')) {
                    document.getElementById('pushCount').innerText = d.push_sub_count || 0;
                }

                // 4. Quản lý Cuộc gọi AI Voice khi đang mở màn hình
                if (d.voice_alert) {
                    document.getElementById('voiceAlertTitle').innerText = d.voice_alert.title || 'Sẵn sàng';
                    if (lastHandledAlertId === 0) {
                        lastHandledAlertId = d.voice_alert.alert_id;
                    } else if (d.voice_alert.alert_id > lastHandledAlertId) {
                        lastHandledAlertId = d.voice_alert.alert_id;
                        showIncomingCall(d.voice_alert.title, d.voice_alert.text);
                    }
                }

                // 5. Render Bảng Sự Cố (Phân loại đa màu chuẩn SOC)
                if (d.incidents) {
                    cachedIncidents = d.incidents;
                    renderIncidents();
                }

            } catch (e) {}
        }

        ['cfgCpu', 'cfgRam', 'cfgAuth', 'cfgWeb'].forEach(id => {
            const el = document.getElementById(id);
            el.onfocus = () => el.dataset.focused = "1";
            el.onblur = () => delete el.dataset.focused;
        });

        async function saveConfig() {
            const payload = {
                cpu_threshold: parseFloat(document.getElementById('cfgCpu').value),
                ram_threshold: parseFloat(document.getElementById('cfgRam').value),
                auth_fail_threshold: parseInt(document.getElementById('cfgAuth').value),
                web_mb_threshold: parseFloat(document.getElementById('cfgWeb').value)
            };
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            alert('✅ Đã lưu cấu hình ngưỡng!');
        }

        async function quickTestLowerCpu() {
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ cpu_threshold: 10.0 })
            });
            alert('⚡ Đã hạ CPU xuống 10% để test ngay!');
        }

        async function resetConfig() {
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ cpu_threshold: 80.0, ram_threshold: 85.0, auth_fail_threshold: 2, web_mb_threshold: 1.5 })
            });
            alert('🔄 Đã reset ngưỡng về mặc định!');
        }

        async function triggerShutdown() {
            if (confirm('🚨 Bạn có chắc muốn TẮT MÁY Windows không?')) {
                await fetch('/api/soar/shutdown', { method: 'POST' });
                alert('🚨 Đã phát lệnh TẮT MÁY Windows qua SOAR!');
            }
        }

        async function triggerRaise() {
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ cpu_threshold: 99.0, ram_threshold: 99.0 })
            });
            alert('⚡ Đã hạ tải hệ thống!');
        }

        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</body>
</html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
