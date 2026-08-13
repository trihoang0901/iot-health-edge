# Khắc phục sự cố

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
- Chạy `START-IOT-HEALTH-EDGE.bat`. Trong workflow broker local, launcher dừng
  trước Docker/upload nếu `MQTT_HOST` không khớp bất kỳ IPv4 non-loopback đang
  hoạt động nào trên laptop. Gate này không in SSID hoặc mật khẩu.
- Sau khi sửa `secrets.h`, phải build và nạp lại firmware; chỉ sửa file không
  thay đổi chương trình đang chạy trên NodeMCU.
- Xác nhận Mosquitto đang map cổng 1883, Windows Firewall cho phép subnet
  Private, client hotspot không bị cô lập và tài khoản `health_node` đúng ACL.
- Kết nối chỉ được xem là phục hồi khi broker thấy client node, API nhận bản
  tin `health.telemetry.v2` mới với firmware `0.2.2` và báo `online=true`.
  Serial `mqtt_connected` là checkpoint phần cứng bổ sung cần ghi lại.

### Payload bị từ chối

- `device_id` trong topic và payload phải khớp.
- Số đo có cờ invalid phải là `null`, không phải `0`, `NaN` hoặc chuỗi.
- Telemetry mới phải dùng `health.telemetry.v2`, đặt giá trị DHT11 trong
  `environment` và dùng `ambient_temp_valid`/`humidity_valid`; không đặt chúng
  vào field `skin_temp_*` cũ.
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
- Dùng firmware `0.2.2`: pre-read `OVF_COUNTER` không còn là gate. Firmware vẫn
  fail-closed khi khoảng gọi MAX30102 vượt `250 ms` hoặc SparkFun `check()` fetch
  từ bốn mẫu vào buffer cục bộ; khi đó cửa sổ PPG cũ bị hủy có chủ đích.
- Diagnostic đã thấy khoảng 25 mẫu/s, gap tối đa 10–37 ms và không có local
  storage hit. IR không-ngón-tay khoảng 812–853; probe với ngón tay trước đó đạt
  khoảng 219.000–225.000. Điều này xác nhận đường quang thô, chưa xác nhận HR
  hoặc SpO₂ cuối.
- Đặt ngón tay phủ đúng LED/photodiode, giữ lực ổn định và che ánh sáng ngoài.
  Chỉ kết luận đạt khi telemetry mới có HR/SpO₂ cùng cờ hợp lệ phù hợp; không
  diễn giải raw IR thành số đo sức khỏe.

### MPU-6050/MPU-6500-compatible không hoạt động

- Firmware `0.2.2` thăm dò địa chỉ I2C `0x68`; giữ AD0 ở mức thấp. Nếu scanner
  chỉ thấy `0x69`, sửa mức AD0/dây nối thay vì đổi kết luận từ tên sản phẩm.
- Sau khi ACK tại `0x68`, đọc thanh ghi `WHO_AM_I` ở `0x75`. Chỉ `0x68`
  (MPU-6050) hoặc `0x70` (MPU-6500-compatible) được hỗ trợ. Địa chỉ `0x68` và
  giá trị nhận dạng `0x68` là hai phép kiểm tra khác nhau.
- Tiếp tục đọc đủ 14 byte từ `0x3B` đến `0x48`. NACK, ID khác hoặc frame thiếu
  nghĩa là chưa đạt, dù I2C scanner đã thấy địa chỉ.
- Nạp firmware `0.2.2` rồi yêu cầu telemetry mới cùng boot có `seq` tăng,
  `quality.motion_valid=true`, `motion.accel_g`/`motion.gyro_dps` hữu hạn và
  không có `mpu6050_unavailable`. Gia tốc đứng yên nên hợp lý quanh 1 g sau khi
  đặt module ổn định; đây chỉ là kiểm tra bring-up, không phải hiệu chuẩn.
- Mã `mpu6050_unavailable` được cố ý giữ cho cả hai biến thể nhằm tương thích
  edge/dashboard; nó không chứng minh module là MPU-6050.
- Kiểm tra cùng bus I2C với MAX30102 và nguồn 3,3 V logic. Nếu từng cảm biến
  chạy riêng nhưng ghép lại lỗi, kiểm tra pull-up, dây dài và nguồn.
- Không mô phỏng ngã bằng cách để người ngã. Chỉ dùng chuyển động cầm tay hoặc
  thả module lên vật liệu đệm trong bài thử phi lâm sàng có kiểm soát.

### DHT11 trả `null` hoặc `dht11_unavailable`

- Kiểm tra pinout của đúng cảm biến/module, DATA D5/GPIO14 và GND chung. Không
  suy đoán thứ tự chân theo hình bán hàng.
- DHT11 rời bốn chân cần pull-up 4,7–10 kΩ từ DATA lên **3V3**; module ba chân
  thường đã có điện trở nhưng phải xác minh trên module cụ thể.
- Không đọc nhanh hơn một lần mỗi hai giây. Firmware vẫn phải phát telemetry
  với giá trị `null`, cờ hợp lệ `false` và fault kỹ thuật khi đọc lỗi.
- Kiểm tra nguồn 3,3 V, dây ngắn và tránh để dây DATA gần tải gây nhiễu. Không
  đưa 5 V vào GPIO ESP8266.
- Số đo DHT11 chỉ mô tả môi trường, không phải nhiệt độ cơ thể. Edge cố ý không
  tạo cảnh báo sức khỏe từ nhiệt độ hoặc độ ẩm này.

### ESP8266 reset/ngắt MQTT

- Dùng cáp data và nguồn USB ổn định; không cấp servo/quạt/relay từ 3V3.
- Không đọc DHT11 nhanh hơn hai giây hoặc giữ vòng MAX30102 quá lâu mà bỏ
  `yield()`/`mqtt.loop()`.
- Giữ JSON gọn; PubSubClient cần buffer phù hợp.
- Theo dõi `free_heap` và reset reason trên Serial.
- `ppg_sample_loss` sau reconnect nghĩa là firmware đã bỏ cửa sổ PPG không còn
  liên tục; chờ thu đủ cửa sổ sạch mới xem HR/SpO₂. `event_queue_overflow` nghĩa
  là hơn bốn sự kiện đã phát sinh trong lúc chưa gửi được và cần ghi nhận mất dữ liệu.

## Tuyên bố 5G không khớp thực tế

Nếu broker là laptop cùng hotspot với NodeMCU, route có thể chỉ ở LAN. Không sửa báo cáo bằng suy đoán; đổi nhãn thành demo LAN hoặc chuyển broker/edge tới đầu xa rồi ghi bằng chứng tuyến và phép đo.
