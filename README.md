# SME SOC Emergency Center & Reverse Tunnel

Hệ thống điều hành an ninh mạng (SOC) và trung tâm cảnh báo cuộc gọi khẩn cấp cho doanh nghiệp vừa và nhỏ (SME).

## 1. Kiến trúc hệ thống
- **SOC AI Engine (`ai_engine.py`)**: Chạy trên máy chủ Ubuntu cục bộ, giám sát thời gian thực CPU, RAM, Network, các lệnh nguy hiểm (DROP DATABASE, DROP TABLE), tự động tổng hợp giọng nói khẩn cấp qua Edge-TTS.
- **Reverse Tunnel (Azure Cloud VPS)**: Máy chủ Ubuntu 24.04 tại Indonesia Central (`70.153.83.137`), chạy Nginx Reverse Proxy tiếp nhận lưu lượng toàn cầu và chuyển tiếp an toàn qua SSH Tunnel ngầm về máy chủ SOC cục bộ.
- **Android App (`soc_android_app`)**: Ứng dụng Android chạy ngầm 24/7 (`SOCService`), tự động đánh thức màn hình khóa và phát chuông báo động cuộc gọi thoại khẩn cấp khi phát hiện sự cố an ninh nghiêm trọng.

## 2. Các thành phần chính
- `/ai_engine.py`: Mã nguồn trung tâm điều hành SOC & AI Engine.
- `/soc_android_app/`: Toàn bộ mã nguồn ứng dụng Android cảnh báo khẩn cấp.
- `BAO_CAO_KIEM_THU_HE_THONG_SME_SOC.docx`: Tài liệu báo cáo kiểm thử hệ thống.
- `BAO_CAO_TU_XAY_DUNG_REVERSE_TUNNEL.md`: Báo cáo giải pháp và kiến trúc Reverse Tunnel.
