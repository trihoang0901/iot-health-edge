# Khắc phục sự cố

## Chọn đúng launcher

- Chỉ cần MQTT/API/dashboard: `START-SOFTWARE.bat`.
- Chủ động nạp NodeMCU và xác minh telemetry mới: `START-HARDWARE.bat`.
- Kiểm tra nhanh: `STATUS-IOT-HEALTH-EDGE.bat`.
- Log giới hạn 10 phút/200 dòng: `LOGS-IOT-HEALTH-EDGE.bat`.
- Dừng nhưng giữ dữ liệu: `STOP-IOT-HEALTH-EDGE.bat`.
- Tên cũ `START-IOT-HEALTH-EDGE.bat` giữ hành vi cũ: thiếu CH340 thì vẫn mở
  software và bỏ qua upload. Không dùng tên này khi muốn bắt buộc có board;
  hãy dùng `START-HARDWARE.bat`.

## Broker/Docker

### Container thoát ngay, báo thiếu password/ACL

Chạy generator trước rồi xem log:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Initialize-Mosquitto.ps1
docker compose -f .\deploy\docker-compose.yml up -d
docker compose -f .\deploy\docker-compose.yml logs mosquitto
```

Không tạo tệp password rỗng thủ công. Nếu chủ động tạo lại tài khoản, dùng `-Force` và cập nhật cả hai tiến trình.

### `Not authorized`

- Kiểm tra edge dùng `health_edge`, simulator/firmware dùng `health_node`.
- Kiểm tra mật khẩu đúng tài khoản.
- ACL mẫu chỉ cho node ghi `health-node-01`. `--device-id` khác sẽ bị broker từ chối.
- Topic phải đúng chính tả và đúng ba hậu tố `telemetry|event|status`.
- Launcher restart Mosquitto để nạp đúng password/ACL trên đĩa, kiểm tra ba
  quyền `topic write` exact của `MQTT_USERNAME + DEVICE_ID`, rồi thử MQTT
  CONNECT bằng credential trong `secrets.h` **trước khi upload**. Probe chỉ
  truyền credential qua stdin, không publish/subscribe và không in giá trị
  hoặc raw exception.
- Nếu mật khẩu node vẫn là giá trị mẫu, xoay tự động bằng RNG cục bộ. Script
  cập nhật đồng bộ broker hash, `.env` và `secrets.h`, chỉ chuyển mật khẩu mới
  qua stdin của `mosquitto_passwd`, rồi restart/probe broker mà không in giá trị:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Rotate-LocalNodeMqttCredential.ps1
  ```

- Nếu launcher báo credential firmware không khớp Mosquitto, đồng bộ từ tài
  khoản node/simulator cục bộ rồi chạy lại launcher để build/upload:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Sync-FirmwareMqttCredential.ps1
  .\START-HARDWARE.bat
  ```

  Script chỉ sửa `MQTT_USERNAME`/`MQTT_PASSWORD` trong `secrets.h`, không in
  bí mật. Không dùng nó để đổi tài khoản `health_edge`.

### `Connection refused` hoặc timeout

- `docker compose ... ps` phải cho thấy Mosquitto đang chạy.
- NodeMCU phải dùng IPv4 laptop, không dùng `127.0.0.1`.
- Kiểm tra Windows Firewall và profile mạng Private.
- Hotspot có thể cô lập client; thử router khác hoặc USB tether + Windows Mobile Hotspot.
- ESP8266 chỉ thấy Wi-Fi 2,4 GHz; đổi băng tần hotspot khỏi 5 GHz và thử WPA2 nếu WPA3-only không tương thích.
- Sau khi bật lại hotspot, chạy `ipconfig` vì IP có thể đổi.

## Edge/dashboard

### Dashboard báo offline dù simulator đã chạy

- Chạy `normal` ít nhất vài bản tin và kiểm tra log edge.
- Status là retained; simulator kết thúc có chủ ý sẽ phát `online=false`.
- Nếu chỉ chạy `--dry-run`, không có bản tin nào tới broker.
- Đảm bảo edge và simulator dùng cùng broker/port.

### `health-node-01` có Wi-Fi nhưng vẫn offline

- Đừng dùng RSSI hoặc thời điểm cũ trên dashboard làm bằng chứng kết nối hiện
  tại; khi offline, UI chỉ có thể đang hiển thị giá trị cuối đã lưu.
- Nếu Serial có `wifi_connected` nhưng lặp `mqtt_connect_failed state=-2`, hãy
  kiểm tra endpoint trước: chạy `ipconfig`, so IPv4 của adapter đang phục vụ
  NodeMCU với `MQTT_HOST` trong
  `firmware\health-node\include\secrets.h`. IP hotspot/router có thể đổi sau
  khi kết nối lại.
- Chạy `START-HARDWARE.bat`. Trong workflow broker local, launcher dừng
  trước Docker/upload nếu `MQTT_HOST` không khớp bất kỳ IPv4 non-loopback đang
  hoạt động nào trên laptop. Gate này không in SSID hoặc mật khẩu.
- Sau khi sửa `secrets.h`, phải build và nạp lại firmware; chỉ sửa file không
  thay đổi chương trình đang chạy trên NodeMCU.
- Xác nhận Mosquitto đang map cổng 1883, Windows Firewall cho phép subnet
  Private, client hotspot không bị cô lập và tài khoản `health_node` đúng ACL.
- Firmware vật lý hiện đã lên `0.3.1`. Sau hard reset, Serial boot
  `a164b119f1fd90b3` báo `wifi_connected ip=192.168.137.37` và
  `mqtt_connected`; edge nhận v3 tại `seq=23/25/28`, nhiệt độ `27.3125 °C`,
  motion hợp lệ/`idle` và `sensor_faults=[]`. Sau mỗi lần upload,
  chỉ xem kết nối là phục hồi khi broker thấy client, API nhận bản tin mới có
  `system.fw="0.3.1"`, `seq` tăng và `online=true`; Serial `mqtt_connected` là
  checkpoint bổ sung.

### Payload bị từ chối

- `device_id` trong topic và payload phải khớp.
- Số đo có cờ invalid phải là `null`, không phải `0`, `NaN` hoặc chuỗi.
- Telemetry source mới phải dùng `health.telemetry.v3`, đặt đúng
  `wearable.wrist_surface_temp_c` và
  `quality.wrist_surface_temp_valid`; không đặt nhiệt độ cổ tay vào
  `skin_temp_*` v1 hoặc `environment` v2. Edge vẫn nhận strict v1/v2 cho node và
  lịch sử cũ, nhưng không ánh xạ chúng thành nhiệt độ cổ tay.
- `fall_state` phải thuộc enum trong [data contract](data-contract.md).
- Không thêm field tùy ý; schema edge cấm field lạ.

### SQLite báo `database is locked`

- Không chạy nhiều instance edge cùng ghi một file.
- Dừng instance Uvicorn cũ trước khi chạy lại.
- Đặt `EDGE_DATABASE_PATH` tới thư mục có quyền ghi; không mở database bằng công cụ giữ transaction lâu.

### `/healthz` báo `degraded`

- Xem `database.healthy`, `mqtt.connected`, `mqtt.subscribed` và
  `ingestion.worker_alive` trong chính phản hồi health.
- SUBACK bị ACL từ chối làm `mqtt.subscribed=false`; kiểm tra đúng tài khoản
  `health_edge` và ACL đã được broker nạp lại.
- `ingestion.processing_errors>0` là lỗi runtime/SQLite đã được worker cô lập;
  kiểm tra `last_error` và log, sửa nguyên nhân rồi khởi động lại edge để xóa trạng thái lỗi.

## Telegram

### Không nhận được tin

- Xác nhận đã nhấn **Start** hoặc gửi tin cho bot trước.
- Kiểm tra `TELEGRAM_ENABLED=true`, token và Chat ID trong `.env`, sau đó tạo
  lại edge container; ứng dụng fail-fast nếu bật mà thiếu một trong hai giá trị.
- Kiểm tra laptop/container có Internet và phân giải được `api.telegram.org`.
- Xem log đã lọc: `docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full logs --since 5m edge | Select-String Telegram`.
- `telegram_client_error` thường là token/Chat ID/quyền bot không hợp lệ và
  không được retry. `rate_limited` hoặc `telegram_server_error` được retry hữu
  hạn; đợi rồi tạo một alert demo mới.

Log chỉ chứa mã lỗi nội bộ đã che dữ liệu. Không dán token, URL bot đầy đủ,
`.env`, phản hồi `getUpdates` hoặc `docker inspect` vào báo lỗi.

### Có tin trùng hoặc mất tin

MQTT phát lại cùng `event_id` ngã đã được chống trùng. Tuy vậy, Telegram có thể
nhận tin ngay trước khi client timeout rồi lần retry gửi lại. Queue nằm trong
RAM nên queue đầy, restart hoặc crash cũng có thể làm mất tin. Đây là giới hạn
best-effort đã chấp nhận, không dùng kênh này cho tình huống cấp cứu.

## Phần cứng

### CH340 xuất hiện nhưng upload/COM không ổn định

- Máy bring-up 2026-08-14 đã rollback driver CH340 từ `3.9.2024.9` xuống bản
  Microsoft-signed `3.7.2022.1` trước khi upload thành công. Đây là bằng chứng
  của đúng máy thử, không chứng minh bản 3.9 luôn lỗi trên mọi máy.
- Trước khi đổi driver, ghi lại COM, INF và phiên bản hiện tại, đóng Serial
  Monitor/Arduino IDE và sao lưu package driver. Việc xóa package có thể ảnh
  hưởng mọi thiết bị CH34x dùng chung driver; Windows Update cũng có thể cài lại
  bản mới.
- Sau rollback phải xác nhận thiết bị ở trạng thái `OK`, đúng phiên bản mong
  muốn và upload/telemetry mới thực sự chạy. Chỉ thấy tên COM chưa đủ chứng minh
  firmware hay cảm biến hoạt động.

### MAX30102 không thấy ở `0x57`

- Kiểm tra SDA D2/GPIO4, SCL D1/GPIO5 và GND chung.
- Xác nhận breakout hỗ trợ 3,3 V; không suy đoán từ hình bán hàng.
- Chạy I²C scanner riêng trước khi ghép thuật toán.
- Kiểm tra pull-up I²C đã có trên module; quá nhiều pull-up song song cũng có thể làm bus lỗi.

### MAX30102 thấy ở `0x57` nhưng liên tục `ppg_sample_loss`

- Firmware trước `0.2.2` có thể đọc `OVF_COUNTER` trước mẫu và xem giá trị bão
  hòa sau startup overflow là lỗi. Một số module cần tiêu thụ một mẫu hoàn chỉnh
  trước khi counter trở lại bình thường, nên clear-and-return trước khi đọc có
  thể tự khóa đường FIFO.
- Sửa lỗi đã được kiểm tra trên `0.2.2` và được giữ trong source `0.3.1`:
  pre-read `OVF_COUNTER` không còn là gate. Firmware vẫn fail-closed khi khoảng
  gọi MAX30102 vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu vào buffer
  cục bộ; khi đó cửa sổ PPG cũ bị hủy có chủ đích.
- Diagnostic đã thấy khoảng 25 mẫu/s, gap tối đa 10–37 ms và không có local
  storage hit. IR không-ngón-tay khoảng 812–853; probe với ngón tay đạt khoảng
  219.000–225.000. Trên production `0.2.2`, 20 mẫu liên tiếp sau đó có
  `finger_present=true`, PPG 0,66–0,81 và HR/SpO₂ hợp lệ. Đây là bring-up
  pipeline, không xác nhận độ chính xác y tế.
- Capture trước hard reset có `ppg_sample_loss`. Sau hard reset, MAX30102 đã
  khởi tạo và không còn unavailable hoặc `ppg_sample_loss`; do chưa đặt ngón
  tay, `finger_present=false` và HR/SpO₂ là `null` đúng fail-closed. Đây vẫn
  chưa phải HR/SpO₂ pass mới; đặt ngón tay ổn định, che sáng và chờ một cửa sổ
  PPG sạch trước khi đánh giá tiếp.
- Đặt ngón tay phủ đúng LED/photodiode, giữ lực ổn định và che ánh sáng ngoài.
  Chỉ kết luận đạt khi telemetry mới có HR/SpO₂ cùng cờ hợp lệ phù hợp; không
  diễn giải raw IR thành số đo sức khỏe.

### MPU-6050/MPU-6500-compatible không hoạt động

- Logic đã được kiểm tra trên `0.2.2` và giữ trong source `0.3.1` thăm dò địa
  chỉ I2C `0x68`; giữ AD0 ở mức thấp. Nếu scanner
  chỉ thấy `0x69`, sửa mức AD0/dây nối thay vì đổi kết luận từ tên sản phẩm.
- Sau khi ACK tại `0x68`, đọc thanh ghi `WHO_AM_I` ở `0x75`. Chỉ `0x68`
  (MPU-6050) hoặc `0x70` (MPU-6500-compatible) được hỗ trợ. Địa chỉ `0x68` và
  giá trị nhận dạng `0x68` là hai phép kiểm tra khác nhau.
- Tiếp tục đọc đủ 14 byte từ `0x3B` đến `0x48`. NACK, ID khác hoặc frame thiếu
  nghĩa là chưa đạt, dù I2C scanner đã thấy địa chỉ.
- Telemetry `0.3.1` mới cùng boot `a164b119f1fd90b3`, `seq=23/25/28` đã có
  `quality.motion_valid=true`, `fall_state="idle"` và `sensor_faults=[]`. Vẫn cần kiểm
  tra accel/gyro hữu hạn, đứng yên hợp lý quanh 1 g và thay đổi khi xoay module;
  đây chỉ là bring-up, không phải hiệu chuẩn.
- Mã `mpu6050_unavailable` được cố ý giữ cho cả hai biến thể nhằm tương thích
  edge/dashboard; nó không chứng minh module là MPU-6050.
- Kiểm tra cùng bus I2C với MAX30102 và nguồn 3,3 V logic. Nếu từng cảm biến
  chạy riêng nhưng ghép lại lỗi, kiểm tra pull-up, dây dài và nguồn.
- Không mô phỏng ngã bằng cách để người ngã. Chỉ dùng chuyển động cầm tay hoặc
  thả module lên vật liệu đệm trong bài thử phi lâm sàng có kiểm soát.

### DS18B20 trả `null` hoặc `ds18b20_unavailable`

- Kiểm tra đúng pinout đầu dò, không suy đoán theo màu dây. Cấu hình được hỗ trợ
  là powered three-wire: VDD=3V3, GND chung, DATA=D5/GPIO14; không dùng
  parasite-power.
- Bắt buộc có điện trở 4,7 kΩ từ DATA lên **3V3**. Không kéo GPIO ESP8266 lên
  5 V; giữ dây gọn và tránh tải gây nhiễu.
- Source `0.3.1` bật pull-up nội yếu của ESP8266 như fallback cho dây prototype
  ngắn. Fallback này không thay thế điện trở ngoài 4,7 kΩ cho wearable ổn định.
- Source `0.3.1` đặt độ phân giải 12-bit, gọi chuyển đổi bất đồng bộ và chỉ đọc
  sau ít nhất `750 ms`. Nếu code chờ `delay(750)` hoặc polling bận, MAX30102,
  motion/MQTT có thể mất nhịp; đó là lỗi triển khai, không phải cách khắc phục.
- Lỗi phải vẫn phát v3 với `wearable.wrist_surface_temp_c=null`,
  `quality.wrist_surface_temp_valid=false` và fault `ds18b20_unavailable`.
- Giá trị hợp lệ chỉ là nhiệt độ bề mặt tại điểm tiếp xúc, không phải nhiệt độ
  cơ thể/lõi, không kết luận sốt và không tạo alert sức khỏe/Telegram.
- Scanner A/B 2026-08-14 không tìm thấy ROM trong nhánh `external_only`; nhánh
  có fallback pull-up nội tìm được family `0x28`, CRC hợp lệ, addressed power
  ở chế độ powered và `27.3125 °C`. Production `0.3.1` sau hard reset phát
  `27.3125 °C`, nhiệt độ/motion hợp lệ và `sensor_faults=[]` tại
  `seq=23/25/28`.
  External-only chưa enumerate được ROM vẫn là tín hiệu phải kiểm tra lại điện
  trở, mối hàn và dây trước khi đóng thành wearable.

### ESP8266 reset/ngắt MQTT

- Dùng cáp data và nguồn USB ổn định; không cấp servo/quạt/relay từ 3V3.
- Không chờ đồng bộ 750 ms cho DS18B20 hoặc giữ vòng MAX30102 quá lâu mà bỏ
  `yield()`/`mqtt.loop()`.
- Giữ JSON gọn; PubSubClient cần buffer phù hợp.
- Theo dõi `free_heap` và reset reason trên Serial.
- `ppg_sample_loss` sau reconnect nghĩa là firmware đã bỏ cửa sổ PPG không còn
  liên tục; chờ thu đủ cửa sổ sạch mới xem HR/SpO₂. `event_queue_overflow` nghĩa
  là hơn bốn sự kiện đã phát sinh trong lúc chưa gửi được và cần ghi nhận mất dữ liệu.

## Tuyên bố 5G không khớp thực tế

Nếu broker là laptop cùng hotspot với NodeMCU, route có thể chỉ ở LAN. Không sửa báo cáo bằng suy đoán; đổi nhãn thành demo LAN hoặc chuyển broker/edge tới đầu xa rồi ghi bằng chứng tuyến và phép đo.
