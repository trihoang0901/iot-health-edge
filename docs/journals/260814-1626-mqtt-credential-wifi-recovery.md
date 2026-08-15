---
date: 2026-08-14
session: mqtt-credential-wifi-recovery
status: completed
---

# Journal: 2026-08-14 — Khôi phục MQTT/Wi-Fi cho health node

## Bối cảnh

Dashboard và Edge vẫn hoạt động nhưng NodeMCU vật lý không xuất hiện online.
Phiên này lần theo từng ranh giới firmware → Wi-Fi → Mosquitto → Edge/API →
dashboard, đồng thời giữ toàn bộ kiểm tra credential ở chế độ không hiển thị
giá trị nhạy cảm. Hệ thống vẫn là prototype phi lâm sàng.

## Những gì đã xảy ra

- Root cause là credential drift: cấu hình node trong firmware không còn khớp
  credential đang được Mosquitto chấp nhận. Node đã tới broker nhưng MQTT
  CONNECT bị từ chối, vì vậy dashboard không thể nhận telemetry mới.
- Launcher được harden để phát hiện placeholder, kiểm tra chính xác
  `MQTT_USERNAME + DEVICE_ID` cùng ba quyền ghi `telemetry|event|status`, đợi
  Edge/MQTT sẵn sàng và chạy CONNECT-only probe trước khi upload.
- Luồng probe truyền payload mã hóa Base64 qua stdin, không đặt credential vào
  argv/log và xử lý khác biệt stdin của Windows PowerShell. Probe không
  publish hoặc subscribe.
- Bổ sung hai đường phục hồi cục bộ: đồng bộ firmware từ cấu hình node hiện có,
  hoặc xoay credential bằng RNG rồi cập nhật đồng bộ cấu hình, broker và
  firmware. Rotation dùng staging, mutex, restart/probe và rollback khi lỗi.
- Firmware production `0.3.1` được build/upload thành công qua COM10. Sau khi
  mạng Wi-Fi bị đổi, một lần mở serial/reset đã khởi động lại node; log xác
  nhận `wifi_connected` rồi `mqtt_connected` mà không cần sửa dashboard.

## Bằng chứng cuối

| Tầng | Kết quả |
|---|---|
| Firmware/USB | Upload COM10 thành công; firmware `0.3.1` |
| Node/API | `online=true`, schema `health.telemetry.v3` |
| Dòng telemetry | `seq=58 → 71` trong 12 giây |
| Ingestion | `accepted=216 → 229`; `rejected=0`, processing errors `0` |
| Dashboard/API | Dashboard HTTP `200`; API trả dữ liệu node mới |
| Regression | Toàn bộ suite đạt `286 passed` |

## Phản ánh

Node được cấp nguồn hoặc xuất hiện ở COM không chứng minh kết nối ứng dụng.
Trong sự cố này, broker handshake mới là ranh giới hỏng; Wi-Fi reconnect sau
upload chỉ là trạng thái chuyển tiếp riêng. Gate trước upload và telemetry có
sequence tăng giúp phân biệt rõ cấu hình hợp lệ, kết nối tạm thời và bằng chứng
end-to-end thực sự.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Fail-closed khi auth/ACL preflight không đạt | Tránh upload firmware chắc chắn không vào được broker | Lỗi được chặn trước khi thay đổi NodeMCU |
| Đồng bộ hoặc xoay credential như một thao tác có rollback | Tránh drift giữa các nguồn cấu hình | Khôi phục nhất quán mà không lộ bí mật |
| Chỉ đóng sự cố bằng telemetry mới và dashboard HTTP 200 | Trạng thái service đơn lẻ chưa chứng minh E2E | Có audit trail từ node tới web |

## Bước tiếp theo

1. Giữ auth/ACL probe trong mọi lần launcher chạy và sau mọi lần rotation.
2. Theo dõi reconnect dài hơn để tách lỗi Wi-Fi thoáng qua khỏi lỗi credential.
3. Tiếp tục giữ kết luận ở mức prototype phi lâm sàng; các metric trên chỉ xác
   nhận transport và hiển thị, không xác nhận độ chính xác y tế.
