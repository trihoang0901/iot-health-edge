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
python -m simulator --scenario dht_fault --count 20
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

   Launcher kiểm tra bí mật theo trạng thái (không in giá trị), yêu cầu
   `MQTT_HOST` là một IPv4 non-loopback đang hoạt động trên laptop, khởi động
   Docker, tự tìm CH340 và nạp firmware nếu có NodeMCU. Nếu báo
   `MQTT_HOST ... khong khop`, cập nhật IP trong `secrets.h` rồi chạy lại;
   launcher dừng trước khi nạp firmware cũ.
7. Nếu nạp thủ công, chạy trong `firmware\health-node`:

   ```powershell
   pio run
   pio run --target upload
   pio device monitor --baud 115200
   ```

8. Xác nhận Serial có `wifi_connected` và `mqtt_connected`; API có bản tin mới
   `health.telemetry.v2`, firmware `0.2.2` và thiết bị `online=true`. Broker
   phải thấy client của health node. DHT11 hợp lệ sẽ có
   `environment.ambient_temp_c`/`humidity_pct`; nếu chưa đọc được, hai giá trị
   phải là `null`, cờ hợp lệ là `false` và có `dht11_unavailable` nhưng node
   vẫn phải online.
9. Với cảm biến chuyển động, I2C scanner phải thấy địa chỉ `0x68`, nhưng ACK
   này chưa phải kết quả đạt. Đọc tiếp `WHO_AM_I` (`0x75`): `0x68` là
   MPU-6050, `0x70` là MPU-6500-compatible. Sau đó xác nhận đọc đủ 14 byte từ
   `0x3B` và ít nhất hai telemetry mới trong cùng boot có `seq` tăng,
   `quality.motion_valid=true`, accel/gyro hữu hạn và không có fault cũ
   `mpu6050_unavailable`. Chưa có đủ bằng chứng này thì để checklist phần cứng
   ở trạng thái chưa hoàn thành.
10. Với MAX30102, xác nhận raw red/IR thay đổi rõ khi đặt ngón tay đúng và ổn
    định. Firmware `0.2.2` không chặn đọc theo pre-read `OVF_COUNTER`, nhưng vẫn
    fail-closed nếu khoảng lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch
    từ bốn mẫu. Chỉ đánh dấu HR/SpO₂ đạt sau khi telemetry cuối có giá trị và cờ
    hợp lệ đúng; raw quang học riêng lẻ chưa đủ.

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
