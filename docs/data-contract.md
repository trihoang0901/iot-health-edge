# Hợp đồng dữ liệu MQTT

## Topic ổn định

`device_id` dùng chữ thường, chữ số và dấu gạch ngang, tối đa 32 ký tự.

| Loại | Topic |
|---|---|
| Telemetry | `iot-health/v1/devices/{device_id}/telemetry` |
| Sự kiện | `iot-health/v1/devices/{device_id}/event` |
| Trạng thái | `iot-health/v1/devices/{device_id}/status` |

`v1` trong đường dẫn là phiên bản namespace topic và vẫn được giữ khi
telemetry nâng lên v2/v3/v4. `device_id` trong payload phải khớp segment thiết bị
trong topic. JSON không được chứa `NaN`/`Infinity` hoặc field ngoài schema.

## Telemetry hiện hành `health.telemetry.v4`

Firmware `0.4.0` và simulator `1.3.0` tách ứng viên PPG thô khỏi giá trị đã
được xác nhận:

```json
{
  "schema": "health.telemetry.v4",
  "device_id": "health-node-01",
  "boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "seq": 42,
  "uptime_ms": 42100,
  "vitals": {
    "heart_rate_raw_bpm": 180.0,
    "heart_rate_bpm": null,
    "spo2_raw_pct": 97.0,
    "spo2_pct": null
  },
  "wearable": { "wrist_surface_temp_c": 33.2 },
  "motion": { "accel_g": 1.012, "gyro_dps": 2.1, "fall_state": "idle" },
  "quality": {
    "ppg": 0.58,
    "ppg_state": "unstable",
    "finger_present": true,
    "motion_artifact": false,
    "heart_rate_valid": false,
    "spo2_valid": false,
    "wrist_surface_temp_valid": true,
    "motion_valid": true
  },
  "system": { "rssi_dbm": -55, "free_heap": 36120, "fw": "0.4.0", "faults": [] }
}
```

- `*_raw_*` là ứng viên của thuật toán MAXIM, chỉ để audit/tinh chỉnh; nó chưa
  phải kết quả được chấp nhận và không được dùng cho alert hoặc thẻ số chính.
- `heart_rate_bpm` và `spo2_pct` là giá trị confirmed. Khi chưa đủ tin cậy,
  chúng bắt buộc là `null` và cờ `*_valid=false`; edge không giữ lại giá trị cũ.
- `quality.ppg_state` nhận một trong: `valid`, `no_finger`, `warming_up`,
  `motion`, `clipping`, `low_perfusion`, `unstable`, `sample_loss`.
- Chỉ trạng thái `valid` mới được đi kèm giá trị HR/SpO2 confirmed. Với
  `no_finger` hoặc `sample_loss`, cả raw lẫn confirmed phải là `null`.
- API chuẩn hóa tiếp tục trả `vitals.*` để tương thích, đồng thời thêm
  `measurements.heart_rate` và `measurements.spo2` gồm `raw_value`,
  `confirmed_value`, `valid`, `state`, `reason` và `unit`.
- Rule engine chỉ đọc confirmed + validity. Mẫu invalid không được mở hoặc đóng
  alert; việc đóng alert sinh hiệu cần một khoảng recovery liên tục.

## Telemetry lịch sử `health.telemetry.v3`

Firmware `0.3.1` và simulator `1.2.0` đã phát cấu trúc sau; edge vẫn nhận để
tương thích dữ liệu/node cũ:

```json
{
  "schema": "health.telemetry.v3",
  "device_id": "health-node-01",
  "boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "seq": 42,
  "uptime_ms": 42100,
  "vitals": {
    "heart_rate_bpm": 72.4,
    "spo2_pct": 98.1
  },
  "wearable": {
    "wrist_surface_temp_c": 33.2
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
    "wrist_surface_temp_valid": true,
    "motion_valid": true
  },
  "system": {
    "rssi_dbm": -55,
    "free_heap": 36120,
    "fw": "0.3.1",
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
- `wearable.wrist_surface_temp_c` hợp lệ nằm trong `0..50 °C`. Đây là ràng
  buộc dữ liệu của prototype, không phải dải chẩn đoán hay chứng nhận hiệu chuẩn.
- Mỗi giá trị có cờ `*_valid` riêng. Nếu cờ là `false`, giá trị tương ứng bắt
  buộc là `null`; nếu cờ là `true`, giá trị không được `null`.
- Khi DS18B20 đọc lỗi hoặc vắng mặt, telemetry vẫn được gửi với
  `wearable.wrist_surface_temp_c=null`,
  `quality.wrist_surface_temp_valid=false` và `system.faults` chứa
  `ds18b20_unavailable`.
- DS18B20 chỉ đo bề mặt tại điểm tiếp xúc cổ tay. Edge không diễn giải nó thành
  nhiệt độ cơ thể/lõi, không kết luận sốt và không tạo alert nhiệt độ.
- Khi `motion_artifact=true`, HR và SpO₂ phải không hợp lệ. Nếu
  `motion_valid=false`, `accel_g`/`gyro_dps` là `null` và
  `fall_state="unknown"`.
- Source firmware `0.3.1` tiếp tục hỗ trợ MPU-6050 (`WHO_AM_I=0x68`) và module
  MPU-6500-compatible (`WHO_AM_I=0x70`) tại cùng địa chỉ I2C `0x68`. Danh tính
  IMU không được thêm vào payload; cả hai biến thể dùng cùng field motion và
  tiếp tục báo mã tương thích ngược `mpu6050_unavailable` khi lỗi.
- HR hoặc SpO₂ hợp lệ còn yêu cầu `quality.ppg` khác `null`, có ngón tay và
  `motion_valid=true`.
- Source firmware `0.3.1` giữ sửa lỗi đã được kiểm tra ở `0.2.2`: không dùng
  pre-read `OVF_COUNTER` của MAX30102 làm gate.
  Cửa sổ PPG vẫn bị xóa, HR/SpO₂ thành `null` và cờ hợp lệ thành `false` nếu
  khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu vào
  buffer cục bộ. Thay đổi này không đổi schema hay quy tắc null/valid.
- `faults` là danh sách mã kỹ thuật, không phải chẩn đoán. Ngoài
  `ds18b20_unavailable`, firmware có thể báo `mpu6050_unavailable`,
  `ppg_sample_loss` hoặc `event_queue_overflow`.

Firmware `0.3.1` yêu cầu chuyển đổi DS18B20 12-bit bất đồng bộ và đọc kết quả
sau ít nhất `750 ms`; payload không nói rằng vòng lặp đã chờ. Pull-up nội yếu
chỉ là fallback prototype, không thay đổi contract và không thay thế pull-up
ngoài 4,7 kΩ của wearable.

Bring-up phần cứng 2026-08-14 đã nhận v3 sau hard reset từ boot
`a164b119f1fd90b3` tại `seq=23/25/28`: nhiệt độ `27.3125 °C`,
`wrist_surface_temp_valid=true`, `motion_valid=true`, `fall_state="idle"` và
`sensor_faults=[]` ở cả ba mẫu. MAX30102 không còn unavailable hoặc
`ppg_sample_loss`, nhưng `finger_present=false` nên HR/SpO₂ là `null` đúng
contract. Đây là bằng chứng contract/pipeline, không phải hiệu chuẩn cảm biến
hoặc xác nhận độ chính xác y tế.

## Tương thích telemetry v1/v2/v3 và dữ liệu lịch sử

Edge xác thực nghiêm ngặt cả bốn discriminator:

- `health.telemetry.v1` giữ `vitals.skin_temp_c` và
  `quality.skin_temp_valid` cho node/lịch sử cũ.
- `health.telemetry.v2` giữ `environment.ambient_temp_c`, `humidity_pct` và hai
  cờ hợp lệ DHT11 cho node/lịch sử v2.
- `health.telemetry.v3` chỉ dùng object `wearable` và cờ nhiệt độ cổ tay mới;
  v3 không chấp nhận field nhiệt độ v1/v2.
- `health.telemetry.v4` giữ `wearable` của v3 và thêm cặp raw/confirmed cùng
  `quality.ppg_state`; v1-v3 không bị suy diễn là đã đi qua gate firmware mới.

Migration SQLite là không phá hủy: hệ thống thêm `schema_version`,
`ambient_temp_c`, `humidity_pct`, các cờ v2, rồi thêm nullable
`wrist_surface_temp_c` và cờ `wrist_surface_temp_valid` mặc định false. Không
xóa cột/bản ghi/raw payload cũ; migration v4 chỉ thêm nullable
`heart_rate_raw_bpm`, `spo2_raw_pct` và `ppg_state`. API trả cấu trúc
chuẩn hóa dạng superset: field không thuộc schema gốc là `null` với cờ `false`;
v1/v2 không bao giờ được suy diễn thành nhiệt độ cổ tay. Alert
`surface_temp_demo` lịch sử đã được retired/resolved và không được thay bằng
luật sốt hay luật nhiệt độ mới.

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
    "fw": "0.4.0",
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
