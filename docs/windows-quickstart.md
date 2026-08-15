# Quickstart trên Windows

## 1. Chuẩn bị

- Docker Desktop ở trạng thái Running.
- Python 3.11 trở lên.
- PowerShell mở tại thư mục `iot-health-edge`.

Kiểm tra:

```powershell
docker version
docker compose version
py --version
```

## 2. Tạo môi trường Python

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Nếu PowerShell chặn activate script, chỉ thay chính sách cho cửa sổ hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. Tạo tài khoản broker

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Initialize-Mosquitto.ps1
```

Nhập hai mật khẩu mạnh và khác nhau:

- `health_edge`: edge chỉ đọc ba loại topic.
- `health_node`: firmware/simulator chỉ ghi ba topic của `health-node-01`.

Script không nhận plaintext qua tham số; nó gọi `mosquitto_passwd` tương tác. Hash và ACL nằm trong thư mục đã bị `.gitignore` loại trừ. Không quên mật khẩu: chúng không thể khôi phục từ hash. Muốn chủ động tạo lại toàn bộ tệp tài khoản, chạy script với `-Force`.

Khởi động broker:

```powershell
docker compose -f .\deploy\docker-compose.yml up -d
docker compose -f .\deploy\docker-compose.yml ps
docker compose -f .\deploy\docker-compose.yml logs mosquitto
```

## 4. Chạy edge

### Cách A — profile Docker `full`

Sao chép `.env.example` một lần, mở tệp và thay `MQTT_PASSWORD` bằng mật khẩu
`health_edge` vừa tạo. `.env` bị Git bỏ qua nhưng vẫn là tệp bí mật cục bộ:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env
}
notepad .\.env
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full up -d --build
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full ps
```

Dashboard ở `http://127.0.0.1:8000`. Edge container chạy non-root và chỉ bind
HTTP vào loopback của laptop. SQLite nằm trong volume `edge-data`.

Telegram là tùy chọn và tắt mặc định. Nếu cần nhận cảnh báo trên điện thoại,
làm theo [hướng dẫn Telegram](telegram-notifications.md), điền token/Chat ID
trong `.env`, rồi chạy lại lệnh `up -d --build edge`. File chạy một chạm vẫn
dùng cùng `.env`; không cần sửa firmware.

### Cách B — chạy edge trực tiếp bằng Python

`.env.example` chỉ là danh sách tham khảo cho cách chạy trực tiếp; ứng dụng
không tự đọc `.env`. Đặt biến cho đúng cửa sổ PowerShell:

```powershell
$env:MQTT_HOST = '127.0.0.1'
$env:MQTT_PORT = '1883'
$env:MQTT_USERNAME = 'health_edge'
$env:MQTT_PASSWORD = '<mat-khau-edge>'
$env:EDGE_DATABASE_PATH = '.\data\health-edge.db'
python -m uvicorn edge.app:app --host 127.0.0.1 --port 8000
```

Khi bật Telegram ở cách B, phải đặt thêm `TELEGRAM_ENABLED`,
`TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` trong đúng cửa sổ PowerShell; xem
[hướng dẫn riêng](telegram-notifications.md). Không ghi token trực tiếp vào
script dùng chung.

Truy cập `http://127.0.0.1:8000`. Không cần chạy Uvicorn với quyền Administrator.
Không chạy đồng thời cách A và B vì cả hai dùng cổng 8000.

## 5. Chạy simulator

Trong PowerShell thứ hai:

```powershell
.\.venv\Scripts\Activate.ps1
$env:SIMULATOR_MQTT_USERNAME = 'health_node'
$env:SIMULATOR_MQTT_PASSWORD = '<mat-khau-node>'
$env:DEVICE_ID = 'health-node-01'
python -m simulator --scenario normal --count 20
```

Thử các nhánh:

```powershell
python -m simulator --scenario motion_artifact --count 20
python -m simulator --scenario ds18b20_fault --count 20
python -m simulator --scenario low_spo2 --count 20
python -m simulator --scenario high_hr --count 20
python -m simulator --scenario fall --count 8
python -m simulator --scenario offline --count 5
```

Ngưỡng demo có khoảng giữ mặc định nên `low_spo2`/`high_hr` cần chạy đủ lâu. Dùng `--count 0` để chạy liên tục và `Ctrl+C` để dừng. Dashboard là nơi ACK cảnh báo chính.

## 6. Chuyển từ simulator sang NodeMCU

1. Đấu dây theo [BOM và wiring](bom-and-wiring.md).
2. Kết nối laptop và NodeMCU vào cùng mạng dùng để bring-up; hotspot phải bật
   Wi-Fi 2,4 GHz cho ESP8266. Biểu tượng di động 5G không có nghĩa hotspot đang
   dùng Wi-Fi 5 GHz.
3. Chạy `ipconfig`, tìm IPv4 của adapter Wi-Fi/Mobile Hotspot; không cấu hình
   firmware bằng `127.0.0.1`. Thực hiện lại bước này sau mỗi lần bật lại hotspot.
4. Cho phép inbound TCP 1883 trong Windows Firewall cho profile **Private**, giới hạn subnet cục bộ nếu có thể.
5. Sao chép `firmware\health-node\include\secrets.example.h` thành
   `secrets.h` nếu chưa có, rồi cấu hình bằng IPv4 laptop, `health_node`, mật
   khẩu node và `device_id=health-node-01`. Không đưa `secrets.h` vào Git/log.
6. Với broker local trên laptop, chạy launcher một chạm:

   ```powershell
   .\START-IOT-HEALTH-EDGE.bat
   ```

   Mode mặc định `Start` chỉ kiểm tra cấu hình runtime, khởi động Docker và xác
   nhận dữ liệu mới; nó không đọc bootstrap `secrets.h`, không tìm COM và không
   nạp firmware. Chỉ chạy mode `Flash` khi chủ động nâng firmware lần đầu hoặc
   rollback có kiểm soát.
7. Nếu nạp thủ công, chạy trong `firmware\health-node`:

   ```powershell
   pio run
   pio run --target upload
   pio device monitor --baud 115200
   ```

8. Bằng chứng phần cứng lịch sử là firmware `0.3.1` đã được upload trong phiên
   bring-up 2026-08-14; source hiện tại `0.4.0` chưa được nghiệm thu lại trên
   node vật lý. Sau hard reset lịch sử, Serial boot `a164b119f1fd90b3` báo firmware
   `0.3.1`, `wifi_connected ip=192.168.137.37` và `mqtt_connected`. API nhận
   `health.telemetry.v3` tại `seq=23/25/28`, nhiệt độ `27.3125 °C`, motion
   hợp lệ/`idle` và `sensor_faults=[]`. Máy Windows của phiên thử đã rollback driver CH340 từ
   `3.9.2024.9` xuống `3.7.2022.1`; không tự áp dụng rollback này trên máy khác
   nếu COM/upload vẫn hoạt động. Mỗi lần nạp sau vẫn phải xác nhận telemetry mới
   có `system.fw="0.3.1"`, `seq` tăng và thiết bị `online=true`.
9. Với cảm biến chuyển động, I2C scanner phải thấy địa chỉ `0x68`, nhưng ACK
   này chưa phải kết quả đạt. Đọc tiếp `WHO_AM_I` (`0x75`): `0x68` là
   MPU-6050, `0x70` là MPU-6500-compatible. Sau đó xác nhận đọc đủ 14 byte từ
   `0x3B` và ít nhất hai telemetry mới trong cùng boot có `seq` tăng,
   `quality.motion_valid=true`, accel/gyro hữu hạn và không có fault cũ
   `mpu6050_unavailable`. Chưa có đủ bằng chứng này thì để checklist phần cứng
   ở trạng thái chưa hoàn thành.
10. Với MAX30102, xác nhận raw red/IR thay đổi rõ khi đặt ngón tay đúng và ổn
    định. Firmware `0.2.2` đã được kiểm tra không chặn đọc theo pre-read
    `OVF_COUNTER`, nhưng vẫn
    fail-closed nếu khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch
    từ bốn mẫu. Chỉ đánh dấu HR/SpO₂ đạt sau khi telemetry cuối có giá trị và cờ
    hợp lệ đúng; raw quang học riêng lẻ chưa đủ.
11. DS18B20 phải ở powered three-wire: VDD=3V3, GND chung, DATA=D5/GPIO14 và
    pull-up ngoài 4,7 kΩ từ DATA lên 3V3. Source `0.3.1` bật thêm pull-up nội yếu
    như fallback prototype và yêu cầu chuyển đổi 12-bit bất đồng bộ rồi đọc sau
    ít nhất `750 ms`; không chờ bằng `delay(750)`. Scanner A/B của phiên thử
    không tìm thấy ROM ở `external_only`, nhưng nhánh có fallback pull-up nội
    tìm được family `0x28`, CRC hợp lệ, powered và `27.3125 °C`. Kết quả này
    không cho phép bỏ điện trở ngoài trên wearable. Khi cảm biến lỗi, v3 vẫn
    phải phát `wearable.wrist_surface_temp_c=null`,
    `quality.wrist_surface_temp_valid=false`, fault `ds18b20_unavailable` và
    duy trì MAX30102, dual-MPU cùng MQTT. Sau hard reset, MAX30102 không còn
    unavailable hoặc `ppg_sample_loss`; chưa đặt ngón tay nên HR/SpO₂ là `null`
    đúng fail-closed và vẫn cần retest ngón tay riêng. Dashboard đã hiển thị
    online, nhiệt độ `27.3 °C` hợp lệ, firmware `0.3.1` và không có lỗi trình
    duyệt.

Launcher trên cố ý dành cho broker local. Nếu kiến trúc dùng broker đầu xa,
không bỏ qua gate bằng cách giả địa chỉ local; dùng quy trình thủ công và các
yêu cầu mạng/TLS trong [tài liệu bảo mật](network-and-security.md).

Không cần buzzer hoặc nút để hoàn thành MVP. Nếu thêm về sau, chúng chỉ là giao diện phụ; ACK có thẩm quyền vẫn qua dashboard.

## 7. Dừng dịch vụ

```powershell
docker compose -f .\deploy\docker-compose.yml --profile full down
```

Lệnh trên giữ các Docker volume `mosquitto-data` và `edge-data`. Chỉ thêm
`--volumes` khi chủ động muốn mất toàn bộ dữ liệu Mosquitto và SQLite; không
cần làm trong vận hành bình thường.

## 8. Launcher phục hồi mạng

File BAT chỉ chuyển tiếp sang Windows PowerShell 5.1. Mode mặc định là `Start`:

```powershell
.\START-IOT-HEALTH-EDGE.bat Start -NoPause
.\START-IOT-HEALTH-EDGE.bat Doctor -NoPause
.\START-IOT-HEALTH-EDGE.bat Verify -NoPause
```

- `Start` khởi động stack, chờ API healthy và kiểm tra telemetry mới. Mode này
  không đọc `secrets.h`, không cần COM/USB và không nạp firmware; vì vậy Wi-Fi
  hoặc IP bootstrap đã cũ không ngăn stack khởi động.
- `Doctor` kiểm tra cú pháp endpoint, DNS trên Windows, TCP 1883, MQTT
  authentication và ACL. Kết quả DNS Windows không chứng minh ESP8266 cũng
  phân giải được hostname trên mạng đang dùng. Riêng probe ACL dùng MQTT v5 để
  đọc PUBACK reason `Not authorized`; firmware vận hành vẫn dùng MQTT 3.1.1.
- `Verify` chạy bộ kiểm chứng và build firmware, không cần COM/USB.
- `Flash` là mode duy nhất được phép upload. Mode này kiểm tra bootstrap,
  tự tìm CH340 (hoặc nhận `-Port COMx`), sinh secret AP nếu chưa có và chỉ nạp
  application image; không erase hoặc upload LittleFS.

Lần nâng cấp đầu tiên có chủ đích:

```powershell
.\START-IOT-HEALTH-EDGE.bat Flash -Port COM5 -NoPause
```

Sau đó cấu hình Wi-Fi/broker bằng captive portal. Khi node vẫn online, yêu cầu
mở portal từ xa bằng lệnh sau. Launcher chỉ báo thành công sau khi edge xác
nhận status trực tiếp, gửi command QoS 1 `retain=false`, và nhận receipt
`provisioning_started` đúng correlation ID:

```powershell
.\START-IOT-HEALTH-EDGE.bat OpenPortal -NoPause
```

Nếu node đã mất Wi-Fi/MQTT thì lệnh từ xa không thể tới node. Chờ portal tự mở
sau khoảng 45 giây, hoặc reset/power-cycle để tạo cửa sổ portal mới sau khi cửa
sổ cũ hết hạn. Xem mật khẩu AP trong cửa sổ cục bộ:

```powershell
.\START-IOT-HEALTH-EDGE.bat ShowPortalAccess -NoPause
```

Secret được mã hóa DPAPI theo user Windows. Nó không được in ra terminal/log
hay đưa vào tham số tiến trình; clipboard chỉ thay đổi khi người dùng bấm nút
**Sao chép** trong cửa sổ.
