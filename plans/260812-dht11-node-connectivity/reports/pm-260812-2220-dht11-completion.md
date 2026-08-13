---
type: project-management
date: 2026-08-12
status: completed
---

# DHT11 và health node - Báo cáo hoàn tất

## Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Firmware | DHT11 D5/GPIO14, telemetry v2, firmware 0.2.0 |
| Edge | Nhận strict v1/v2, migration SQLite không phá hủy |
| Dashboard | 4 thẻ; dữ liệu offline/API lỗi không còn trông như live |
| Kết nối node | Serial, broker và API đều xác nhận online |
| Kiểm thử | 139 passed; PlatformIO/Compose/JS/docs đều đạt |
| Review | Không còn finding mở |

## Bằng chứng runtime

- Upload COM10 thành công; Serial có `wifi_connected` và `mqtt_connected`.
- Broker thấy client health node; API nhận bản tin mới
  `health.telemetry.v2`, firmware `0.2.0`, `online=true`.
- Dashboard live hiển thị đúng nhiệt độ/độ ẩm môi trường và trạng thái DHT11.

## Giới hạn còn lại

DHT11 thật vẫn trả `null`/invalid cùng `dht11_unavailable`; MAX30102 và
MPU-6050 cũng chưa sẵn sàng trong lần chạy cuối. Node vẫn publish đều, nên đây
là phần đấu dây/nguồn/pinout cảm biến cần kiểm tra tại breadboard, không phải
lỗi Wi-Fi, MQTT, schema hay edge. Không dùng các số đo này cho chẩn đoán hoặc
xử trí y tế.

## Bước tiếp theo

1. Kiểm tra VCC 3V3, GND chung, DATA D5/GPIO14 và pull-up 4,7-10 kOhm.
2. Xác nhận đúng thứ tự chân theo datasheet của module DHT11 đang dùng.
3. Sau khi có số đọc hợp lệ, đối chiếu cả hai validity flag và xóa fault
   `dht11_unavailable`; không cần đổi lại schema hay backend.
