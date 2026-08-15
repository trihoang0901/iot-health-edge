# Kiến trúc và ranh giới hệ thống

## Mục tiêu MVP

Hệ thống chứng minh một chuỗi IoT hoàn chỉnh: lấy mẫu cảm biến, gắn cờ chất lượng, truyền MQTT, lưu tại edge, áp dụng luật demo, hiển thị và xác nhận cảnh báo. Thiết kế ưu tiên khả năng giải thích và tái lập hơn là tuyên bố độ chính xác y tế.

```text
MAX30102 -----\
MPU 6-axis -----> NodeMCU ESP8266 <-> Wi-Fi/MQTT <-> Mosquitto
DS18B20 -------/                              -> FastAPI -> SQLite
                                                     \-> dashboard/ACK
                                                     \-> queue/worker -> Telegram (tùy chọn)
```

Ba stream dữ liệu và một command subtree của mỗi thiết bị:

```text
iot-health/v1/devices/{device_id}/telemetry
iot-health/v1/devices/{device_id}/event
iot-health/v1/devices/{device_id}/status
iot-health/v1/devices/{device_id}/command/{boot_id}
```

## Vai trò thành phần

- NodeMCU duy trì Wi-Fi/MQTT bằng state machine không chặn, đọc cảm biến không
  chặn quá lâu, xuất dữ liệu theo schema versioned và chỉ nhận command nhắm đúng
  boot/session hiện tại.
- MAX30102 cung cấp tín hiệu quang thử nghiệm. Giá trị chỉ được dùng khi có ngón
  tay, tín hiệu đủ tốt, không có nhiễu chuyển động và dữ liệu cảm biến MPU hợp
  lệ trong toàn bộ cửa sổ tính. Firmware không dùng `OVF_COUNTER` đọc trước mẫu
  làm gate; tính liên tục vẫn fail-closed theo khoảng lấy mẫu và số mẫu thư viện
  SparkFun thực sự fetch vào buffer cục bộ.
- MPU-6050 (`WHO_AM_I=0x68`) hoặc module MPU-6500-compatible
  (`WHO_AM_I=0x70`) cung cấp độ lớn gia tốc/con quay cho trạng thái chuyển động
  và sự kiện ngã demo. Firmware phân loại bằng thanh ghi nhận dạng, không chỉ
  dựa vào ACK tại địa chỉ I2C `0x68`.
- DS18B20 dùng chế độ cấp nguồn ba dây trên D5/GPIO14 để lấy nhiệt độ bề mặt tại
  điểm tiếp xúc cổ tay. Firmware khởi phát chuyển đổi 12-bit bất đồng bộ và đọc
  sau ít nhất `750 ms`; vòng lặp MAX30102, motion và MQTT không chờ chuyển đổi.
  Source `0.4.0` giữ pull-up nội yếu như fallback cho dây prototype ngắn;
  hành vi này mới có bằng chứng phần cứng lịch sử trên `0.3.1`. Bản wearable
  ổn định vẫn bắt buộc có điện trở ngoài 4,7 kΩ từ DATA lên 3V3.
  Giá trị không phải nhiệt độ cơ thể/lõi, không dùng kết luận sốt và không tham
  gia luật cảnh báo sức khỏe.
- Mosquitto xác thực username/password và giới hạn topic bằng ACL.
- Edge gán thời điểm nhận có thẩm quyền, xác thực payload, lưu SQLite và tạo cảnh báo demo.
- Dashboard là giao diện chính để theo dõi và ACK; buzzer/nút vật lý không bắt buộc.
- Khi được bật rõ ràng, edge chỉ đưa alert mới vào hàng đợi RAM giới hạn để
  worker gửi tóm tắt qua Telegram; lỗi hoặc queue đầy không chặn MQTT, SQLite
  hay dashboard. Xem [hướng dẫn Telegram](telegram-notifications.md).

## Ranh giới bắt buộc

- Không chẩn đoán, điều trị, gọi cấp cứu hoặc đưa ra quyết định y khoa.
- Không tuyên bố MAX30102/DS18B20 đạt độ chính xác của thiết bị y tế; DS18B20
  chỉ mô tả bề mặt tại điểm tiếp xúc trong prototype.
- Không dùng camera, RFID, PIR, relay, servo, quạt hoặc điện lưới trong lõi MVP.
- Không công khai broker TCP 1883 ra Internet.
- Telegram bị tắt mặc định, là kênh bên thứ ba best-effort và không được dùng
  làm cơ chế báo động/cấp cứu bảo đảm.
- Ngưỡng cảnh báo chỉ là giá trị demo có thể cấu hình, không phải ngưỡng lâm sàng.
- Thời gian trên node là `uptime_ms`; edge mới gán thời gian nhận theo đồng hồ hệ thống.

## Nguyên tắc chất lượng dữ liệu

Một số đo không hợp lệ phải là `null` và cờ `*_valid` tương ứng phải là
`false`. Với v3, `wearable.wrist_surface_temp_c` luôn đi cùng
`quality.wrist_surface_temp_valid`; lỗi cảm biến tạo fault kỹ thuật
`ds18b20_unavailable`. Edge không được tạo cảnh báo sinh hiệu từ dữ liệu bị
đánh dấu nhiễu/chưa hợp lệ và không có luật cảnh báo nhiệt độ/sốt. Chỉ event
`fall_suspected_demo` mở alert ngã; `fall_state` trong telemetry dùng để quan
sát máy trạng thái. Event vẫn chỉ là tín hiệu demo cần người kiểm tra, không
phải kết luận có người đã ngã.

Source firmware `0.4.0` phát `health.telemetry.v3`. Edge phân luồng nghiêm ngặt
theo trường `schema`, đồng thời tiếp tục nhận `health.telemetry.v1` và v2.
Migration SQLite chỉ thêm cột nhiệt độ cổ tay/cờ hợp lệ dạng nullable/defaulted;
các cột, bản ghi và raw payload `skin_temp_*` v1 cùng environment DHT11 v2 được
giữ nguyên, không bị xóa hoặc diễn giải lại thành nhiệt độ cổ tay.

Hai biến thể IMU dùng cùng contract motion và cùng mã fault tương thích ngược
`mpu6050_unavailable`. Việc hỗ trợ `WHO_AM_I=0x70` không thay đổi schema và
không phải chứng nhận độ chính xác hay an toàn phát hiện ngã.

### Bằng chứng phần cứng lịch sử

Với MAX30102, firmware `0.2.2` đã bỏ pre-read `OVF_COUNTER` khỏi gate vì counter
có thể bão hòa sau startup overflow và tự khóa vòng clear-and-return trước khi
một mẫu hoàn chỉnh được tiêu thụ. Cửa sổ PPG vẫn bị xóa và đánh dấu không hợp lệ
khi khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu. Tín
hiệu red/IR thô và telemetry HR/SpO₂ hợp lệ đã được ghi nhận trên `0.2.2`, nhưng
không tự chứng minh độ chính xác y tế. Source `0.3.1` giữ đường MAX/dual-MPU này
và đã có telemetry phần cứng mới sau hard reset trong boot
`a164b119f1fd90b3`, `seq=23/25/28`: nhiệt độ cổ tay `27.3125 °C`, motion
hợp lệ/`idle` và `sensor_faults=[]`. MAX30102 không còn unavailable hoặc
`ppg_sample_loss`; không có ngón tay nên HR/SpO₂ là `null` đúng fail-closed và
chưa tạo bằng chứng HR/SpO₂ mới trên `0.3.1`.

Các mốc `0.2.2`/`0.3.1` trong đoạn trên là bằng chứng vật lý lịch sử, không
phải nghiệm thu phần cứng cho source `0.4.0`. Các tiêu chí đổi Wi-Fi, đổi IP
broker, rollback candidate, portal deadline, auth denied và soak heap của
`0.4.0` vẫn **CHƯA XÁC NHẬN**.

## State machine phục hồi mạng `0.4.0`

```text
STA mất link (phát hiện <=1 s)
  -> thử last-good, rồi các profile theo priority
     -> association + DHCP (tối đa 8 s/profile)
     -> resolve DNS (tối đa 1,5 s)
     -> MQTT primary/fallback (tối đa 2 s/đường)
        -> thành công: publish recovery status + trở lại RUNNING
        -> hết profile: backoff 1..30 s rồi full sweep mới
  -> không có đường hợp lệ sau ~45 s: mở portal một lần/boot
     -> hard deadline 300 s -> đóng AP
```

Mỗi DHCP/network change làm mất cache endpoint ở tầng ứng dụng và buộc resolve
lại hostname. Fallback IPv4 chỉ được dùng khi thuộc subnet DHCP của đúng
profile; nó không che lỗi xác thực. CONNACK `3` chỉ retry MQTT. CONNACK
`1/2/4/5` không roam và không mở portal vì broker đã reachable nhưng protocol,
client ID hoặc credential sai.

Recovery status được chọn theo ưu tiên
`recovered_provisioning` → `recovered_wifi_profile` →
`recovered_broker_ip_change` → `recovered_dns_fallback` →
`recovered_mqtt_transport`. Edge coi chúng là connection start, giữ riêng
`last_recovery_reason/at`; heartbeat chỉ cập nhật freshness, không xóa dấu vết
transition/recovery.

## Kho cấu hình hai slot và portal

Mỗi slot LittleFS chứa `schema_version`, `generation`, CRC32, broker
`{host,port}` và tối đa ba profile `{ssid,password,enabled,priority,fallback_ipv4}`.
Boot chọn slot committed hợp lệ có generation cao nhất. Portal ghi candidate
vào slot còn lại qua temp-file + rename, trả HTTP thành công rồi đóng AP trước
khi trial STA để tránh xung đột kênh AP/STA. Candidate chỉ được promote sau
chuỗi Wi-Fi → DHCP → DNS/fallback → MQTT authentication; trial lỗi hoặc mất
điện quay về committed và không tự format filesystem.

Portal dùng `WIFI_AP_STA`, WPA2 và hard deadline 300 giây. Giao diện chỉ quản
lý Wi-Fi/broker, có CSRF nonce một lần, body tối đa 4096 byte, HTML escaping,
`Cache-Control: no-store`, không prefill password và không nhận MQTT credential.
Sau timeout, reset/power-cycle là trigger cục bộ cho cửa sổ mới; command MQTT
không thể cứu node đã mất Wi-Fi/MQTT.

## Command mở portal

Edge chỉ phát `health.command.v1` QoS 1, `retain=false` vào topic gắn boot sau
khi thấy heartbeat trực tiếp không-retained còn mới và command session của boot
hiện tại. Node kiểm tra device, boot, session, expiry wrap-safe và dedupe trước
khi thực thi. PUBACK chỉ chứng minh broker nhận publish; hoàn thành chỉ được xác
nhận khi status `provisioning_started` mang `correlation_id=command_id` quay về
edge. Vì vậy launcher không báo thành công giả khi node offline hoặc command bị
từ chối.

Edge giới hạn hàng đợi RAM và kích thước MQTT payload. SQLite chỉ giữ số hàng
telemetry mới nhất theo từng thiết bị (`EDGE_TELEMETRY_RETENTION_ROWS`, mặc định
50.000); các trang đã cấp phát được SQLite tái sử dụng và có thể không làm kích
thước tệp giảm ngay sau khi xóa hàng cũ.
