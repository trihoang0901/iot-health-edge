# Checklist kiểm thử MVP

Ghi ngày giờ, phiên bản firmware/edge, `device_id`, chế độ mạng và kết quả cho từng mục. Không dùng người có bệnh lý hoặc dùng kết quả làm quyết định sức khỏe.

## A. Simulator-first

| Bài thử | Lệnh | Kỳ vọng |
|---|---|---|
| Contract không cần broker | `python -m simulator --scenario fall --count 8 --dry-run` | JSON hợp lệ; ba topic namespace v1, telemetry strict `health.telemetry.v3`; có đúng một event fall |
| Bình thường | `python -m simulator --scenario normal --count 20` | Dashboard online, không có alert demo mới |
| Lỗi DS18B20 | `python -m simulator --scenario ds18b20_fault --count 20` | Telemetry v3 vẫn tới edge; `wearable.wrist_surface_temp_c=null`, cờ false, có `ds18b20_unavailable`; không tạo alert |
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
- [ ] `wrist_surface_temp_c` có giá trị khi
      `wrist_surface_temp_valid=false` bị từ chối; giá trị hợp lệ phải hữu hạn
      và nằm trong `0..50 °C`.
- [ ] Motion invalid nhưng còn accel/gyro bị từ chối.
- [ ] Telemetry v1/v2 hợp lệ vẫn được nhận; mỗi phiên bản từ chối field ngoài
      schema và v3 không chấp nhận `skin_temp_*` hay `environment`.
- [ ] Migration database cũ giữ nguyên bản ghi/cột `skin_temp_*`, đồng thời
      giữ cột environment v2, raw payload và thêm nullable/defaulted wrist
      columns mà không yêu cầu xóa SQLite.
- [ ] Dữ liệu DS18B20, kể cả `49.9 °C` hợp lệ theo contract, không mở alert sức
      khỏe/sốt hoặc gửi Telegram; `surface_temp_demo` cũ không được khôi phục.
- [ ] API normalization trả field không thuộc schema gốc là `null`/false; dữ
      liệu nhiệt độ v1/v2 không bao giờ xuất hiện như nhiệt độ cổ tay.
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
- [ ] DS18B20 ở powered three-wire: VDD=3V3, GND chung, DATA=D5/GPIO14 và
      pull-up **4,7 kΩ** từ DATA lên 3V3; không dùng parasite-power.
- [x] Source `0.3.1` yêu cầu chuyển đổi 12-bit bất đồng bộ và chỉ đọc sau ít
      nhất `750 ms`; không có `delay(750)`/busy wait trong vòng sampling.
- [x] Khi hợp lệ, v3 phát đúng `wearable.wrist_surface_temp_c` và
      `quality.wrist_surface_temp_valid=true`; khi lỗi phát null/false cùng
      `ds18b20_unavailable` mà node vẫn online. Boot `a164b119f1fd90b3` tại
      `seq=23/25/28` đã có `27.3125 °C` hợp lệ và `sensor_faults=[]`.
- [x] Scanner A/B ghi nhận `external_only` không tìm thấy ROM; với fallback
      pull-up nội tìm được family `0x28`, CRC hợp lệ, addressed power ở chế độ
      powered và `27.3125 °C`. Mục wiring 4,7 kΩ phía trên vẫn để chưa hoàn
      thành vì pull-up nội không thay thế phần cứng wearable ổn định.
- [ ] Đọc từng cảm biến riêng ổn định trước khi ghép.
- [ ] Khi ghép, MQTT, MAX30102 và dual-MPU không mất nhịp trong lúc DS18B20
      đang chuyển đổi.
- [ ] Che sáng/cố định ngón tay giúp điểm `ppg` ổn định hơn; nhiễu chuyển động làm cờ valid tắt.
- [x] Diagnostic bỏ pre-read `OVF_COUNTER` nhận khoảng 25 mẫu/s, gap tối đa
      10–37 ms và `storage_hits=0`; no-finger IR khoảng 812–853, probe ngón tay
      trước đó khoảng 219.000–225.000. Đây chỉ là bằng chứng raw/optics.
- [x] Clean build và upload firmware `0.2.2`; broker/API nhận boot mới, node
      online và telemetry mới có `seq` tăng. Diagnostic xác nhận không còn vòng
      clear-and-return do `OVF_COUNTER`.
- [x] Clean build và full automated tests đã qua ở baseline migration;
      firmware `0.3.1` sau đó đã build/upload và có telemetry phần cứng mới.
      Không suy ra độ chính xác y tế từ build hoặc số đọc đơn lẻ.
- [x] Host bring-up rollback driver CH340 từ `3.9.2024.9` xuống `3.7.2022.1`
      trước upload; ghi đây là biến môi trường của phiên thử, không phải yêu cầu
      chung cho mọi NodeMCU.
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
- [x] Telemetry `0.3.1` cùng boot `a164b119f1fd90b3`, `seq=23/25/28` có
      `quality.motion_valid=true`, `fall_state="idle"` và `sensor_faults=[]`. Đây là kiểm tra pipeline,
      không phải hiệu chuẩn ngã.
- [x] Sau hard reset, MAX30102 đã khởi tạo và không còn unavailable hoặc
      `ppg_sample_loss`; `finger_present=false` làm HR/SpO₂ `null` đúng
      fail-closed.
- [ ] Cần retest MAX30102 với ngón tay ổn định trước khi coi HR/SpO₂ hiện tại là
      đạt.
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
- [x] Dashboard hiển thị ba số đo live: HR, SpO₂ và nhiệt độ bề mặt cổ tay;
      không hiện DHT11/độ ẩm cho node mới, không relabel v1/v2, và dữ liệu cuối
      được đánh dấu stale khi node offline.
- [x] Tất cả scenario chạy lại được từ hướng dẫn Windows.
- [x] Automated tests của edge qua 100%.
- [x] Firmware build thành công khi có PlatformIO.
- [ ] Không có credential thật trong artefact bàn giao.
- [x] Báo cáo không tuyên bố chẩn đoán, độ chính xác y tế hoặc 5G khi chưa có bằng chứng.
- [x] Báo cáo ghi rõ DS18B20 chỉ đo bề mặt tại điểm tiếp xúc, không phải nhiệt
      độ cơ thể/lõi, không kết luận sốt và không dùng làm alert sức khỏe.
- [x] Báo cáo ghi rõ `0.3.1` đã có bring-up DS18B20/motion vật lý, nhưng
      external-only scanner chưa tìm thấy ROM và MAX hiện chưa có capture ngón
      tay; bằng chứng MAX/dual-MPU `0.2.2` được giữ riêng như lịch sử, không bị
      nâng thành độ chính xác y tế.
- [x] Dashboard sau hard reset hiển thị node online, nhiệt độ `27.3 °C` hợp lệ,
      firmware `0.3.1` và không có lỗi trình duyệt.

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
