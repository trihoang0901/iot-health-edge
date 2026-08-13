# Checklist kiểm thử MVP

Ghi ngày giờ, phiên bản firmware/edge, `device_id`, chế độ mạng và kết quả cho từng mục. Không dùng người có bệnh lý hoặc dùng kết quả làm quyết định sức khỏe.

## A. Simulator-first

| Bài thử | Lệnh | Kỳ vọng |
|---|---|---|
| Contract không cần broker | `python -m simulator --scenario fall --count 8 --dry-run` | JSON hợp lệ; ba topic namespace v1, schema `health.telemetry.v2`; có đúng một event fall |
| Bình thường | `python -m simulator --scenario normal --count 20` | Dashboard online, không có alert demo mới |
| Lỗi DHT11 | `python -m simulator --scenario dht_fault --count 20` | Telemetry v2 vẫn tới edge; hai giá trị môi trường null, hai cờ false, có `dht11_unavailable`; không tạo alert |
| Nhiễu chuyển động | `python -m simulator --scenario motion_artifact --count 20` | HR/SpO₂ là null, cờ invalid; không sinh alert sinh hiệu |
| SpO₂ thấp demo | `python -m simulator --scenario low_spo2 --count 20` | Alert demo sau hold time, không xuất hiện nếu cờ invalid |
| HR cao demo | `python -m simulator --scenario high_hr --count 20` | Alert demo sau hold time |
| Ngã demo | `python -m simulator --scenario fall --count 8` | Máy trạng thái đi qua các pha; đúng event `fall_suspected_demo` mở một alert |
| Offline | `python -m simulator --scenario offline --count 5` | Status retained chuyển offline; UI cập nhật |

Sau mỗi alert, ACK trên dashboard và xác nhận actor/note/thời điểm được lưu. Buzzer/nút không cần cho bài thử.

## B. Contract và chống lỗi

- [ ] Topic có device ID khác payload bị từ chối.
- [ ] `NaN`, field lạ và enum sai bị từ chối.
- [ ] HR/SpO₂ có giá trị khi cờ invalid bị từ chối.
- [ ] Nhiệt độ môi trường/độ ẩm có giá trị khi cờ tương ứng false bị từ chối;
      giá trị hợp lệ phải nằm trong giới hạn contract.
- [ ] Motion invalid nhưng còn accel/gyro bị từ chối.
- [ ] Telemetry v1 hợp lệ vẫn được nhận; telemetry v2 không chấp nhận
      `skin_temp_*` hoặc field ngoài schema.
- [ ] Migration database cũ giữ nguyên bản ghi/cột `skin_temp_*`, đồng thời
      thêm các cột schema/environment mà không yêu cầu xóa SQLite.
- [ ] Dữ liệu DHT11, kể cả giá trị cực biên hợp lệ, không mở alert sức khỏe;
      `surface_temp_demo` cũ không còn được đánh giá/quảng bá.
- [ ] Hai bản tin cùng `(device_id, boot_id, seq)` không tạo bản ghi/alert trùng.
- [ ] Hai event cùng `(device_id, event_id)` chỉ mở một alert; hai thiết bị khác nhau được phép dùng cùng chuỗi `event_id`.
- [ ] Payload vượt `EDGE_MAX_PAYLOAD_BYTES` bị từ chối và lịch sử mỗi thiết bị không vượt giới hạn retention đã đặt.
- [ ] Telemetry chỉ có `fall_state=alarm` nhưng không có event không tự mở alert ngã.
- [ ] Node im lặng quá timeout chuyển offline ngay cả khi Last Will chưa tới.

## C. Broker và bí mật

- [ ] Kết nối anonymous thất bại.
- [ ] `health_node` không đọc được telemetry và không ghi được device ID khác.
- [ ] `health_edge` đọc được ba loại topic.
- [ ] Không có `.env`, password file, khóa hoặc credential trong source/package bàn giao.
- [ ] TCP 1883 chỉ mở trên profile/subnet LAN cần thiết.
- [ ] Không forward TCP 1883 ra Internet.
- [ ] Trong workflow broker local, launcher từ chối `MQTT_HOST` không thuộc
      IPv4 non-loopback đang hoạt động và không in credential.

## D. Phần cứng theo từng tầng

- [ ] I2C scanner thấy MAX30102 `0x57` và cảm biến MPU tại `0x68`; AD0 ở mức
      thấp. ACK địa chỉ chưa đủ để đánh dấu cảm biến đạt.
- [x] Đọc `WHO_AM_I` (`0x75`) được `0x68` cho MPU-6050 hoặc `0x70` cho
      MPU-6500-compatible; ID khác phải fail closed.
- [x] Đọc đủ frame 14 byte từ `0x3B`; NACK/frame thiếu làm motion invalid và
      tạo fault tương thích ngược `mpu6050_unavailable`, không phát số cũ/giả.
- [ ] DHT11 DATA nối D5/GPIO14; cảm biến rời có pull-up 4,7–10 kΩ lên 3V3 hoặc
      module được xác nhận đã có pull-up.
- [ ] DHT11 không được đọc nhanh hơn hai giây; khi hợp lệ phát đồng thời nhiệt
      độ/độ ẩm môi trường với cờ đúng.
- [ ] Đọc từng cảm biến riêng ổn định trước khi ghép.
- [ ] Khi ghép, MQTT không rớt trong lúc đọc DHT11 hoặc thu FIFO MAX30102.
- [ ] Che sáng/cố định ngón tay giúp điểm `ppg` ổn định hơn; nhiễu chuyển động làm cờ valid tắt.
- [x] Diagnostic bỏ pre-read `OVF_COUNTER` nhận khoảng 25 mẫu/s, gap tối đa
      10–37 ms và `storage_hits=0`; no-finger IR khoảng 812–853, probe ngón tay
      trước đó khoảng 219.000–225.000. Đây chỉ là bằng chứng raw/optics.
- [x] Clean build và upload firmware `0.2.2`; broker/API nhận boot mới, node
      online và telemetry mới có `seq` tăng. Diagnostic xác nhận không còn vòng
      clear-and-return do `OVF_COUNTER`.
- [ ] Thử cưỡng bức gap `>250 ms` và SparkFun fetch `>=4`; xác nhận cửa sổ bị
      xóa, phát `ppg_sample_loss` và không phát số cũ.
- [x] Đặt ngón tay đúng, ổn định và che sáng: 20 mẫu production liên tiếp có
      `finger_present=true`, PPG 0,66–0,81, HR/SpO₂ có giá trị và cờ valid;
      mẫu chốt không còn fault. Đây là bring-up pipeline, không phải xác nhận
      độ chính xác y tế.
- [ ] Rút từng cảm biến tạo fault kỹ thuật đúng, không biến thành số đo giả.
- [ ] Mất Wi-Fi/broker rồi khôi phục: node reconnect, boot/seq/status hợp lý.
- [x] Ở firmware trước bugfix PPG, Serial có `wifi_connected` và
      `mqtt_connected`; broker thấy client health node; API nhận telemetry v2
      mới, báo `online=true`, `seq` tăng trong cùng boot, motion hợp lệ với số
      hữu hạn và không còn `mpu6050_unavailable`.
- [ ] Khi module đứng yên, gia tốc mới hợp lý quanh 1 g; xoay module làm
      accel/gyro thay đổi. Chỉ đánh dấu sau bằng chứng telemetry phần cứng mới.
- [ ] Để offline đủ lâu làm tràn bốn event RAM: `event_queue_overflow` xuất hiện sau reconnect.
- [ ] Nguồn/cáp không gây reset; `free_heap` còn biên an toàn trong 15 phút.

## E. Chế độ mạng và tuyên bố

- [ ] Ghi rõ `LAN peer`, `USB tether + local broker` hay `remote broker`.
- [ ] Với peer cùng hotspot, báo cáo không gọi dữ liệu đã đi qua 5G.
- [ ] Hotspot phát Wi-Fi 2,4 GHz cho ESP8266; báo cáo phân biệt rõ 5G di động và Wi-Fi 5 GHz.
- [ ] Chỉ đo backhaul 5G khi broker ở đầu xa và có bằng chứng route/endpoint.
- [ ] Nếu dùng đầu xa, đường truyền nằm trong VPN/private overlay hoặc đã xác minh TLS/CA end-to-end; không dùng TCP 1883 công khai.
- [ ] Ghi p50/p95/p99, mất gói và baseline trên cùng tải nếu mục tiêu là so sánh mạng.

## F. Tiêu chí bàn giao

- [ ] Dashboard hiển thị cảnh báo phi lâm sàng rõ ràng.
- [ ] Dashboard hiển thị bốn số đo: HR, SpO₂, nhiệt độ môi trường và độ ẩm;
      dữ liệu cuối được đánh dấu stale khi node offline.
- [ ] Tất cả scenario chạy lại được từ hướng dẫn Windows.
- [ ] Automated tests của edge qua 100%.
- [ ] Firmware build thành công khi có PlatformIO.
- [ ] Không có credential thật trong artefact bàn giao.
- [ ] Báo cáo không tuyên bố chẩn đoán, độ chính xác y tế hoặc 5G khi chưa có bằng chứng.
- [ ] Báo cáo ghi rõ DHT11 không đo nhiệt độ da/cơ thể/lõi và không dùng DHT11
      làm cảnh báo sức khỏe.

## G. Telegram tùy chọn

- [ ] Khi `TELEGRAM_ENABLED=false`, edge chạy không cần token/Chat ID và không
  tạo worker Telegram.
- [ ] Khi bật nhưng thiếu token hoặc Chat ID, edge fail-fast mà không in giá trị
  bí mật.
- [ ] Alert ngưỡng mới mở gửi đúng một tin; telemetry tiếp tục vi phạm không
  gửi thêm; resolved rồi mở lại gửi tin mới.
- [ ] Hai event cùng `(device_id, event_id)` gửi một tin; `event_id` mới gửi tin
  mới dù alert ngã cũ còn hoạt động.
- [ ] Tin chỉ có tóm tắt tối thiểu và nhãn phi lâm sàng/không cấp cứu.
- [ ] Mô phỏng timeout, HTTP 429/5xx, 4xx vĩnh viễn và queue đầy không làm MQTT,
  SQLite, dashboard hoặc ingestion worker lỗi.
- [ ] Log/metrics không chứa token, Chat ID, URL chứa token hoặc body phản hồi.
