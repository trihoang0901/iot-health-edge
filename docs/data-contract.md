# Hợp đồng dữ liệu MQTT

## Topic ổn định

`device_id` dùng chữ thường, chữ số và dấu gạch ngang, tối đa 32 ký tự.

| Loại | Topic |
|---|---|
| Telemetry | `iot-health/v1/devices/{device_id}/telemetry` |
| Sự kiện | `iot-health/v1/devices/{device_id}/event` |
| Trạng thái | `iot-health/v1/devices/{device_id}/status` |
| Lệnh theo boot | `iot-health/v1/devices/{device_id}/command/{boot_id}` |

`v1` trong đường dẫn là phiên bản namespace topic và vẫn được giữ khi
telemetry nâng lên v2/v3. `device_id` trong payload phải khớp segment thiết bị
trong topic. JSON không được chứa `NaN`/`Infinity` hoặc field ngoài schema.

## Telemetry hiện hành `health.telemetry.v3`

Source firmware `0.4.0` và simulator hiện hành phát cấu trúc sau:

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
    "fw": "0.4.0",
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
- Source firmware `0.4.0` tiếp tục hỗ trợ MPU-6050 (`WHO_AM_I=0x68`) và module
  MPU-6500-compatible (`WHO_AM_I=0x70`) tại cùng địa chỉ I2C `0x68`. Danh tính
  IMU không được thêm vào payload; cả hai biến thể dùng cùng field motion và
  tiếp tục báo mã tương thích ngược `mpu6050_unavailable` khi lỗi.
- HR hoặc SpO₂ hợp lệ còn yêu cầu `quality.ppg` khác `null`, có ngón tay và
  `motion_valid=true`.
- Source firmware `0.4.0` giữ sửa lỗi đã được kiểm tra ở `0.2.2`: không dùng
  pre-read `OVF_COUNTER` của MAX30102 làm gate.
  Cửa sổ PPG vẫn bị xóa, HR/SpO₂ thành `null` và cờ hợp lệ thành `false` nếu
  khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu vào
  buffer cục bộ. Thay đổi này không đổi schema hay quy tắc null/valid.
- `faults` là danh sách mã kỹ thuật, không phải chẩn đoán. Ngoài
  `ds18b20_unavailable`, firmware có thể báo `mpu6050_unavailable`,
  `ppg_sample_loss` hoặc `event_queue_overflow`.

Firmware `0.4.0` yêu cầu chuyển đổi DS18B20 12-bit bất đồng bộ và đọc kết quả
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

## Tương thích telemetry v1/v2 và dữ liệu lịch sử

Edge xác thực nghiêm ngặt cả ba discriminator:

- `health.telemetry.v1` giữ `vitals.skin_temp_c` và
  `quality.skin_temp_valid` cho node/lịch sử cũ.
- `health.telemetry.v2` giữ `environment.ambient_temp_c`, `humidity_pct` và hai
  cờ hợp lệ DHT11 cho node/lịch sử v2.
- `health.telemetry.v3` chỉ dùng object `wearable` và cờ nhiệt độ cổ tay mới;
  v3 không chấp nhận field nhiệt độ v1/v2.

Migration SQLite là không phá hủy: hệ thống thêm `schema_version`,
`ambient_temp_c`, `humidity_pct`, các cờ v2, rồi thêm nullable
`wrist_surface_temp_c` và cờ `wrist_surface_temp_valid` mặc định false. Không
xóa cột/bản ghi/raw payload `skin_temp_*` hoặc environment. API trả cấu trúc
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
  "command_session_id": "70f3a908-cb7d-4512-a286-52f79d48d311",
  "correlation_id": null,
  "system": {
    "rssi_dbm": -55,
    "free_heap": 35980,
    "fw": "0.4.0",
    "faults": []
  }
}
```

`command_session_id` và `correlation_id` là field tùy chọn. Session nonce được
node sinh mới cho boot hiện tại và không do launcher tự chọn. Receipt thực thi
portal dùng `reason="provisioning_started"` cùng
`correlation_id=<command_id>`. Heartbeat trực tiếp được publish non-retained để
edge chứng minh node đang live trước khi phát command; trạng thái connection và
Last Will vẫn dùng retained state. Sau kết nối thành công, node phải ghi đè Last
Will `online=false` bằng status online. Edge vẫn áp dụng timeout nhận dữ liệu vì
mất mạng bất thường có thể làm Last Will đến trễ.

Các reason phục hồi hợp lệ gồm:

- `recovered_provisioning`
- `recovered_wifi_profile`
- `recovered_broker_ip_change`
- `recovered_dns_fallback`
- `recovered_mqtt_transport`

Chúng mở connection epoch mới và được lưu riêng thành
`last_recovery_reason/last_recovery_at`. Heartbeat sau đó chỉ cập nhật
`last_status_at`, không xóa transition/recovery gần nhất.

## Command `health.command.v1`

```json
{
  "schema": "health.command.v1",
  "device_id": "health-node-01",
  "target_boot_id": "73f77b235fc24b29a6f8268b396ca69e",
  "command_id": "4ec4058a-6fe6-4496-a79a-802d8805bb35",
  "command_session_id": "70f3a908-cb7d-4512-a286-52f79d48d311",
  "action": "open_provisioning",
  "expires_uptime_ms": 73400
}
```

Command chỉ được edge publish QoS 1, `retain=false` vào topic có đúng boot hiện
tại. `command_id` và `command_session_id` là UUID; expiry không quá 30 giây
phía trước theo miền `uptime_ms` modulo `2^32`. Node từ chối sai device, boot,
session, action, expiry hoặc command trùng trong bốn ID gần nhất. Vì
PubSubClient không đưa cờ retain cho subscriber, boot-specific topic, nonce và
expiry là lớp chống replay bắt buộc.

MQTT PUBACK/broker ACK không phải execution receipt. Chỉ status
`provisioning_started` có đúng `correlation_id=command_id` chứng minh node đã
thực thi yêu cầu. API tạo command là
`POST /api/v1/devices/{device_id}/commands/open-provisioning`; body có thể rỗng
hoặc mang `expected_command_session_id` để fail closed khi session vừa đổi.

## QoS và dữ liệu cá nhân

- Firmware dùng QoS 0 cho telemetry do giới hạn PubSubClient; consumer phải
  chịu được bản tin trùng và khoảng trống dữ liệu.
- Command dùng QoS 1 và luôn `retain=false`. Không retain telemetry/event hoặc
  heartbeat; retained status chỉ biểu diễn connection state/Last Will.
- Không đưa tên, số điện thoại, bệnh án hoặc định danh cá nhân vào topic/payload.
- Edge lưu thêm thời điểm nhận từ đồng hồ laptop; đó là timestamp dùng cho lịch sử.
