---
date: 2026-08-12
session: dht11-node-connectivity
status: completed
---

# Journal: 2026-08-12 — Chuyển DHT11 và kết nối health node

## Bối cảnh

Hệ thống được chuyển từ đường đo nhiệt độ bề mặt DS18B20 sang DHT11 đo nhiệt
độ và độ ẩm môi trường. Đồng thời, `health-node-01` hiển thị ngoại tuyến dù
dashboard còn giữ dữ liệu cũ; log kết nối MQTT và cấu hình broker được kiểm tra
để phân biệt dữ liệu cache với kết nối hiện tại.

## Những gì đã xảy ra

- Firmware được nâng lên `0.2.0`, dùng DHT11 tại D5/GPIO14 và phát
  `health.telemetry.v2` với environment riêng.
- Edge tiếp tục nhận telemetry v1. Migration SQLite thêm cột môi trường nhưng
  giữ nguyên dữ liệu/cột nhiệt độ bề mặt lịch sử, không đổi nghĩa dữ liệu cũ.
- Cấu hình `MQTT_HOST` cũ không còn khớp IPv4 broker hiện tại. Launcher local
  được bổ sung gate từ chối host không thuộc IPv4 non-loopback đang hoạt động
  trước khi Docker hoặc bước upload chạy.
- Firmware `0.2.0` đã được upload thành công qua COM10. Broker đã thấy client
  health node; API nhận telemetry `health.telemetry.v2` mới và báo
  `online=true`.
- Sau khi reset COM10, Serial của firmware `0.2.0` đã ghi nhận
  `wifi_connected ip=192.168.137.123` và `mqtt_connected`. Chuỗi bằng chứng
  transport hiện đủ từ Wi-Fi/MQTT trên node tới broker và API.
- Thời gian host, container và `received_at` hiện cùng UTC; không còn dấu hiệu
  lệch đồng hồ trong bằng chứng API mới.
- DHT11 trong phiên kiểm tra vẫn trả `null` với cờ invalid. Vì chưa có số đọc
  hợp lệ từ cảm biến thật, phần bring-up điện DHT11 chưa đạt.
- Vòng xác minh cuối đạt 139 test Python, clean PlatformIO build, kiểm tra
  Compose/cú pháp, tài liệu-link/JSON và review độc lập không còn finding mở.

## Phản ánh

RSSI hoặc số đo cuối còn trên dashboard không chứng minh node đang online.
Bằng chứng broker và API mới chứng minh đường MQTT đã phục hồi, nhưng cần giữ
riêng gate cảm biến: kết nối node thành công không đồng nghĩa DHT11 đã đấu dây,
có pull-up hoặc đọc đúng.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Dùng DHT11 cho môi trường | Phù hợp linh kiện hiện có | Có nhiệt độ môi trường và độ ẩm, không có nhiệt độ cơ thể |
| Tách telemetry v2 khỏi field nhiệt độ cũ | Tránh đổi nghĩa dữ liệu | Edge nhận v1/v2; SQLite migration không phá hủy lịch sử |
| Không có cảnh báo sức khỏe DHT11 | DHT11 không phải cảm biến y tế/cơ thể | Chỉ hiển thị và kiểm tra chất lượng dữ liệu môi trường |
| Chặn `MQTT_HOST` stale trong launcher local | IP hotspot/laptop có thể đổi | Lỗi cấu hình được phát hiện trước khi nạp firmware |

## Bằng chứng còn chờ

- Số đọc DHT11 vật lý hợp lệ cho cả `ambient_temp_c` và `humidity_pct`, đúng cờ
  quality và không còn `dht11_unavailable`.
- Kiểm tra pull-up/pinout thực tế nếu DHT11 tiếp tục trả `null`.

Không được dùng số đo DHT11 để suy ra nhiệt độ da, nhiệt độ cơ thể, nhiệt độ
lõi, chẩn đoán, xử trí y tế hoặc cảnh báo cấp cứu.

## Bước tiếp theo

1. Kiểm tra pinout DHT11, DATA D5/GPIO14, GND chung và pull-up 4,7–10 kΩ lên 3V3.
2. Xác nhận telemetry mới có hai số đo môi trường hợp lệ; chỉ khi đó mới đóng
   gate bring-up DHT11.
