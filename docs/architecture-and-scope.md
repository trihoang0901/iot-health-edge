# Kiến trúc và ranh giới hệ thống

## Mục tiêu MVP

Hệ thống chứng minh một chuỗi IoT hoàn chỉnh: lấy mẫu cảm biến, gắn cờ chất lượng, truyền MQTT, lưu tại edge, áp dụng luật demo, hiển thị và xác nhận cảnh báo. Thiết kế ưu tiên khả năng giải thích và tái lập hơn là tuyên bố độ chính xác y tế.

```text
MAX30102 -----\
MPU 6-axis -----> NodeMCU ESP8266 -> Wi-Fi/MQTT -> Mosquitto
DHT11 ---------/                              -> FastAPI -> SQLite
                                                     \-> dashboard/ACK
                                                     \-> queue/worker -> Telegram (tùy chọn)
```

Ba topic duy nhất của mỗi thiết bị:

```text
iot-health/v1/devices/{device_id}/telemetry
iot-health/v1/devices/{device_id}/event
iot-health/v1/devices/{device_id}/status
```

## Vai trò thành phần

- NodeMCU duy trì Wi-Fi/MQTT, đọc cảm biến không chặn quá lâu và xuất dữ liệu theo schema versioned.
- MAX30102 cung cấp tín hiệu quang thử nghiệm. Giá trị chỉ được dùng khi có ngón
  tay, tín hiệu đủ tốt, không có nhiễu chuyển động và dữ liệu cảm biến MPU hợp
  lệ trong toàn bộ cửa sổ tính. Firmware không dùng `OVF_COUNTER` đọc trước mẫu
  làm gate; tính liên tục vẫn fail-closed theo khoảng lấy mẫu và số mẫu thư viện
  SparkFun thực sự fetch vào buffer cục bộ.
- MPU-6050 (`WHO_AM_I=0x68`) hoặc module MPU-6500-compatible
  (`WHO_AM_I=0x70`) cung cấp độ lớn gia tốc/con quay cho trạng thái chuyển động
  và sự kiện ngã demo. Firmware phân loại bằng thanh ghi nhận dạng, không chỉ
  dựa vào ACK tại địa chỉ I2C `0x68`.
- DHT11 cung cấp nhiệt độ và độ ẩm môi trường. Cảm biến này không đo nhiệt độ
  da, nhiệt độ cơ thể hay nhiệt độ lõi và dữ liệu của nó không tham gia luật
  cảnh báo sức khỏe.
- Mosquitto xác thực username/password và giới hạn topic bằng ACL.
- Edge gán thời điểm nhận có thẩm quyền, xác thực payload, lưu SQLite và tạo cảnh báo demo.
- Dashboard là giao diện chính để theo dõi và ACK; buzzer/nút vật lý không bắt buộc.
- Khi được bật rõ ràng, edge chỉ đưa alert mới vào hàng đợi RAM giới hạn để
  worker gửi tóm tắt qua Telegram; lỗi hoặc queue đầy không chặn MQTT, SQLite
  hay dashboard. Xem [hướng dẫn Telegram](telegram-notifications.md).

## Ranh giới bắt buộc

- Không chẩn đoán, điều trị, gọi cấp cứu hoặc đưa ra quyết định y khoa.
- Không tuyên bố MAX30102/DHT11 đạt độ chính xác của thiết bị y tế; DHT11 chỉ
  dùng để quan sát điều kiện môi trường của prototype.
- Không dùng camera, RFID, PIR, relay, servo, quạt hoặc điện lưới trong lõi MVP.
- Không công khai broker TCP 1883 ra Internet.
- Telegram bị tắt mặc định, là kênh bên thứ ba best-effort và không được dùng
  làm cơ chế báo động/cấp cứu bảo đảm.
- Ngưỡng cảnh báo chỉ là giá trị demo có thể cấu hình, không phải ngưỡng lâm sàng.
- Thời gian trên node là `uptime_ms`; edge mới gán thời gian nhận theo đồng hồ hệ thống.

## Nguyên tắc chất lượng dữ liệu

Một số đo không hợp lệ phải là `null` và cờ `*_valid` tương ứng phải là
`false`. Quy tắc này áp dụng độc lập cho nhiệt độ môi trường và độ ẩm DHT11.
Edge không được tạo cảnh báo sinh hiệu từ dữ liệu bị đánh dấu nhiễu/chưa hợp
lệ và không có luật cảnh báo sức khỏe nào cho DHT11. Chỉ event
`fall_suspected_demo` mở alert ngã; `fall_state` trong telemetry dùng để quan
sát máy trạng thái. Event vẫn chỉ là tín hiệu demo cần người kiểm tra, không
phải kết luận có người đã ngã.

Firmware `0.2.2` phát `health.telemetry.v2`. Edge phân luồng nghiêm ngặt theo
trường `schema`, đồng thời tiếp tục nhận `health.telemetry.v1`. Migration
SQLite chỉ thêm các cột môi trường và phiên bản schema; các cột/bản ghi
`skin_temp_*` cũ được giữ nguyên, không bị xóa và không bị diễn giải lại thành
nhiệt độ DHT11.

Hai biến thể IMU dùng cùng contract motion và cùng mã fault tương thích ngược
`mpu6050_unavailable`. Việc hỗ trợ `WHO_AM_I=0x70` không thay đổi schema và
không phải chứng nhận độ chính xác hay an toàn phát hiện ngã.

Với MAX30102, firmware `0.2.2` bỏ pre-read `OVF_COUNTER` khỏi gate vì counter
có thể bão hòa sau startup overflow và tự khóa vòng clear-and-return trước khi
một mẫu hoàn chỉnh được tiêu thụ. Cửa sổ PPG vẫn bị xóa và đánh dấu không hợp lệ
khi khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu. Tín
hiệu red/IR thô chứng minh đường quang hoạt động nhưng không tự chứng minh HR hay
SpO₂ hợp lệ.

Edge giới hạn hàng đợi RAM và kích thước MQTT payload. SQLite chỉ giữ số hàng
telemetry mới nhất theo từng thiết bị (`EDGE_TELEMETRY_RETENTION_ROWS`, mặc định
50.000); các trang đã cấp phát được SQLite tái sử dụng và có thể không làm kích
thước tệp giảm ngay sau khi xóa hàng cũ.
