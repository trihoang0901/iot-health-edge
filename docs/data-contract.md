# Hợp đồng dữ liệu MQTT

## Topic ổn định

`device_id` dùng chữ thường, chữ số và dấu gạch ngang, tối đa 32 ký tự.

| Loại | Topic |
|---|---|
| Telemetry | `iot-health/v1/devices/{device_id}/telemetry` |
| Sự kiện | `iot-health/v1/devices/{device_id}/event` |
| Trạng thái | `iot-health/v1/devices/{device_id}/status` |

`v1` trong đường dẫn là phiên bản namespace topic và vẫn được giữ khi
telemetry nâng lên v2. `device_id` trong payload phải khớp segment thiết bị
trong topic. JSON không được chứa `NaN`/`Infinity` hoặc field ngoài schema.

## Telemetry hiện hành `health.telemetry.v2`

Firmware `0.2.2` và simulator hiện hành phát cấu trúc sau:

```json
{
  "schema": "health.telemetry.v2",
  "device_id": "health-node-01",
  "boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "seq": 42,
  "uptime_ms": 42100,
  "vitals": {
    "heart_rate_bpm": 72.4,
    "spo2_pct": 98.1
  },
  "environment": {
    "ambient_temp_c": 28.5,
    "humidity_pct": 63.0
  },
  "motion": {
    "accel_g": 1.012,
    "gyro_dps": 2.1,
    "fall_state": "idle"
  },
  "quality": {
    "ppg": 0.94,
    "finger_present": true,
    "motion_artifact": false,
    "heart_rate_valid": true,
    "spo2_valid": true,
    "motion_valid": true,
    "ambient_temp_valid": true,
    "humidity_valid": true
  },
  "system": {
    "rssi_dbm": -55,
    "free_heap": 36120,
    "fw": "0.2.2",
    "faults": []
  }
}
```

Quy tắc chung:

- `seq` tăng trong một lần boot; cặp `(device_id, boot_id, seq)` nhận diện bản
  tin lặp.
- `uptime_ms` là bộ đếm millisecond 32-bit từ lúc node boot, không phải Unix
  time. Trên ESP8266 nó quay vòng theo modulo `2^32` sau khoảng 49,7 ngày.
- `accel_g` và `gyro_dps` là độ lớn vô hướng, không phải vector ba trục.
- `fall_state` chỉ nhận `idle`, `low_g`, `impact`, `verify_stillness`, `alarm`,
  `acked`, `refractory` hoặc `unknown`.
- `quality.ppg` là điểm chất lượng chuẩn hóa `0..1`, có thể `null`; đây không
  phải độ tin cậy lâm sàng.
- Nhiệt độ môi trường hợp lệ nằm trong `0..50 °C`; độ ẩm tương đối hợp lệ nằm
  trong `0..100%`. Đây là ràng buộc dữ liệu của prototype, không phải chứng
  nhận hiệu chuẩn.
- Mỗi giá trị có cờ `*_valid` riêng. Nếu cờ là `false`, giá trị tương ứng bắt
  buộc là `null`; nếu cờ là `true`, giá trị không được `null`.
- Khi DHT11 đọc lỗi, telemetry vẫn được gửi với hai giá trị môi trường `null`,
  cờ tương ứng `false` và `system.faults` chứa `dht11_unavailable`.
- DHT11 đo điều kiện môi trường, không phải nhiệt độ da/cơ thể/lõi. Edge không
  tạo cảnh báo sức khỏe từ nhiệt độ hoặc độ ẩm DHT11.
- Khi `motion_artifact=true`, HR và SpO₂ phải không hợp lệ. Nếu
  `motion_valid=false`, `accel_g`/`gyro_dps` là `null` và
  `fall_state="unknown"`.
- Firmware `0.2.2` hỗ trợ MPU-6050 (`WHO_AM_I=0x68`) và module
  MPU-6500-compatible (`WHO_AM_I=0x70`) tại cùng địa chỉ I2C `0x68`. Danh tính
  IMU không được thêm vào payload; cả hai biến thể dùng cùng field motion và
  tiếp tục báo mã tương thích ngược `mpu6050_unavailable` khi lỗi.
- HR hoặc SpO₂ hợp lệ còn yêu cầu `quality.ppg` khác `null`, có ngón tay và
  `motion_valid=true`.
- Firmware `0.2.2` không dùng pre-read `OVF_COUNTER` của MAX30102 làm gate.
  Cửa sổ PPG vẫn bị xóa, HR/SpO₂ thành `null` và cờ hợp lệ thành `false` nếu
  khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu vào
  buffer cục bộ. Thay đổi này không đổi schema hay quy tắc null/valid.
- `faults` là danh sách mã kỹ thuật, không phải chẩn đoán. Ngoài
  `dht11_unavailable`, firmware có thể báo `mpu6050_unavailable`,
  `ppg_sample_loss` hoặc `event_queue_overflow`.

## Tương thích telemetry v1 và dữ liệu lịch sử

Edge tiếp tục xác thực nghiêm ngặt `health.telemetry.v1`, gồm các field cũ
`vitals.skin_temp_c` và `quality.skin_temp_valid`. Hỗ trợ này chỉ để đọc node
cũ và lịch sử; firmware `0.2.2` không phát hai field đó và DHT11 không được ánh
xạ vào chúng.

Migration SQLite là không phá hủy: hệ thống thêm `schema_version`,
`ambient_temp_c`, `humidity_pct`, `ambient_temp_valid` và `humidity_valid` mà
không xóa cột/bản ghi `skin_temp_*`. Khi đọc qua API, bản ghi v1 giữ nhiệt độ
bề mặt lịch sử và có environment rỗng; bản ghi v2 có environment riêng và
không giả lập nhiệt độ bề mặt. Alert `surface_temp_demo` cũ đang mở được chuyển
sang `resolved` khi migration chạy; luật này không còn được quảng bá hoặc đánh
giá cho dữ liệu mới. Mapping hiển thị cũ chỉ được giữ để đọc lịch sử.

## Event `health.event.v1`

```json
{
  "schema": "health.event.v1",
  "device_id": "health-node-01",
  "boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "event_id": "evt-9b1dc6854b1e4d6bb1bbb1ef82bc6b36",
  "seq": 43,
  "uptime_ms": 43100,
  "type": "fall_suspected_demo"
}
```

Mỗi lần phát hiện mới phải có `event_id` mới. Retransmit cùng sự kiện giữ
nguyên `event_id` để edge chống trùng. Event `fall_suspected_demo` là nguồn duy
nhất mở alert ngã; trạng thái trung gian trong telemetry chỉ để quan sát máy
trạng thái. Đây chỉ là nghi ngờ ngã trong demo, luôn cần người xác minh.

## Status `health.status.v1`

```json
{
  "schema": "health.status.v1",
  "device_id": "health-node-01",
  "boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "seq": 43,
  "uptime_ms": 43500,
  "online": false,
  "reason": "connection_lost",
  "system": {
    "rssi_dbm": -55,
    "free_heap": 35980,
    "fw": "0.2.2",
    "faults": []
  }
}
```

Status được retain. Node/simulator đặt Last Will `online=false`; sau khi kết
nối thành công phải ghi đè bằng status `online=true`. Edge vẫn áp dụng timeout
nhận dữ liệu vì mất mạng bất thường có thể làm Last Will đến trễ.

## QoS và dữ liệu cá nhân

- Firmware dùng QoS 0 cho telemetry do giới hạn PubSubClient; consumer phải
  chịu được bản tin trùng và khoảng trống dữ liệu.
- Không retain telemetry hoặc event; chỉ retain status.
- Không đưa tên, số điện thoại, bệnh án hoặc định danh cá nhân vào topic/payload.
- Edge lưu thêm thời điểm nhận từ đồng hồ laptop; đó là timestamp dùng cho lịch sử.
