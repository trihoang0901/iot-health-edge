# IoT Health Edge MVP

Prototype học tập **phi lâm sàng** dùng NodeMCU ESP8266, MAX30102, cảm biến
chuyển động MPU-6050 hoặc MPU-6500-compatible và DHT11. Node gửi dữ liệu có
cờ chất lượng qua MQTT; laptop nhận, lưu SQLite, áp dụng luật cảnh báo demo và
hiển thị dashboard tiếng Việt.

Không dùng kết quả để chẩn đoán, điều trị, quyết định cấp cứu hoặc thay thế thiết bị y tế. DHT11 chỉ đo nhiệt độ/độ ẩm **môi trường**, không đo nhiệt độ da, nhiệt độ cơ thể hay nhiệt độ lõi và không kích hoạt cảnh báo sức khỏe.

## Chạy nhanh nhất: simulator trước, chưa cần cắm mạch

Yêu cầu: Docker Desktop đang chạy. Python 3.11+ chỉ cần cho simulator hoặc khi
chọn chạy edge trực tiếp. Trước tiên tạo tài khoản broker:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Initialize-Mosquitto.ps1
```

Script hỏi hai mật khẩu khác nhau: một cho `health_edge`, một cho `health_node`.
Không đưa chúng vào Git, ảnh chụp màn hình hoặc cuộc trò chuyện.

### Phương án A — Docker đầy đủ

Sao chép cấu hình mẫu một lần, rồi thay `MQTT_PASSWORD` bằng mật khẩu
`health_edge` vừa tạo. `.env` đã bị Git bỏ qua nhưng vẫn chứa bí mật cục bộ:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env
}
notepad .\.env
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full up -d --build
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full ps
```

Profile `full` chạy cả Mosquitto và edge/dashboard. API chỉ được publish ra
`127.0.0.1:8000`; SQLite nằm trong Docker volume `edge-data`.

### Phương án B — broker Docker, edge chạy trực tiếp

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
docker compose -f .\deploy\docker-compose.yml up -d
$env:MQTT_USERNAME = 'health_edge'
$env:MQTT_PASSWORD = '<mat-khau-edge-vua-tao>'
$env:EDGE_DATABASE_PATH = '.\data\health-edge.db'
python -m uvicorn edge.app:app --host 127.0.0.1 --port 8000
```

Không chạy đồng thời edge Docker và edge trực tiếp trên cùng cổng 8000.

Để phát dữ liệu tổng hợp, mở PowerShell khác và chuẩn bị Python nếu chưa làm:

```powershell
if (-not (Test-Path .\.venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:SIMULATOR_MQTT_USERNAME = 'health_node'
$env:SIMULATOR_MQTT_PASSWORD = '<mat-khau-node-vua-tao>'
python -m simulator --scenario normal --count 20
```

Mở `http://127.0.0.1:8000`. Các kịch bản có sẵn:

```powershell
python -m simulator --scenario motion_artifact --count 20
python -m simulator --scenario dht_fault --count 20
python -m simulator --scenario low_spo2 --count 20
python -m simulator --scenario high_hr --count 20
python -m simulator --scenario fall --count 8
python -m simulator --scenario offline --count 5
```

Muốn xem payload mà chưa chạy broker:

```powershell
python -m simulator --scenario fall --count 4 --dry-run
```

## Thông báo Telegram tùy chọn

Edge có thể gửi một tin tiếng Việt khi alert ngưỡng mới mở và cho mỗi sự kiện
ngã demo mới đã chống trùng. Tính năng bị tắt mặc định; lỗi Telegram không làm
dừng MQTT, SQLite hoặc dashboard.

Bot token và Chat ID chỉ được điền vào `.env` cục bộ, không đưa vào mã nguồn,
ảnh chụp hoặc cuộc trò chuyện. Xem [hướng dẫn Telegram](docs/telegram-notifications.md)
để tạo bot, lấy Chat ID, bật Docker và chạy bài thử. Đây là kênh best-effort
phi lâm sàng, không phải hệ thống cấp cứu.

## Chuyển sang phần cứng

1. Đấu dây theo [BOM và wiring](docs/bom-and-wiring.md).
2. Bật hotspot/router ở Wi-Fi 2,4 GHz (ESP8266 không hỗ trợ Wi-Fi 5 GHz),
   khởi tạo broker như trên và tìm IPv4 của laptop bằng `ipconfig`.
3. Cho phép TCP 1883 trên Windows Firewall **chỉ với mạng Private**.
4. Điền Wi-Fi, IPv4 broker hiện tại và tài khoản node vào
   `firmware/health-node/include/secrets.h`. Nếu dùng broker trên laptop, có thể
   chạy `START-IOT-HEALTH-EDGE.bat`; launcher sẽ dừng trước khi nạp nếu
   `MQTT_HOST` không khớp một IPv4 cục bộ đang hoạt động.
5. Xem Serial Monitor trước, sau đó kiểm tra dashboard và [checklist](docs/test-checklist.md).

Linh kiện cốt lõi người dùng đã có đủ. Breadboard, dây Dupont, cáp USB data và nguồn ổn định chỉ là vật tư hỗ trợ lắp thử. DHT11 dùng DATA tại D5/GPIO14; cảm biến rời bốn chân cần pull-up 4,7–10 kΩ lên 3V3, còn nhiều module ba chân đã có sẵn điện trở này. Buzzer/nút nhấn là tùy chọn; thao tác ACK chính nằm trên dashboard.

Firmware `0.2.1` phát `health.telemetry.v2` với `ambient_temp_c` và
`humidity_pct`. Edge vẫn xác thực telemetry v1 và giữ nguyên dữ liệu
`skin_temp_*` lịch sử trong SQLite; dữ liệu cũ không bị đổi nghĩa thành số đo
DHT11. Firmware nhận MPU-6050 có `WHO_AM_I=0x68` hoặc module
MPU-6500-compatible có `WHO_AM_I=0x70`, cùng ở địa chỉ I2C `0x68`. Mã lỗi công
khai cũ `mpu6050_unavailable` được giữ lại cho cả hai biến thể để không phá vỡ
edge/dashboard. Xem chi tiết trong [hợp đồng dữ liệu](docs/data-contract.md).

## Lưu ý về 5G

Nếu NodeMCU và laptop cùng là hai máy ngang hàng trên hotspot điện thoại, MQTT tới broker trên laptop thường chỉ đi trong WLAN cục bộ. Đây là **demo LAN**, không đủ bằng chứng để tuyên bố dữ liệu đã qua 5G.

“5G” ở đây là mạng di động thế hệ 5, không phải băng tần Wi-Fi 5 GHz.

Chỉ gọi là thử nghiệm backhaul 5G khi broker/edge nằm ở đầu xa và tuyến dữ liệu thực sự đi qua Internet 5G, kèm bằng chứng cấu hình/tuyến/độ trễ. Xem [chế độ mạng và bảo mật](docs/network-and-security.md).

Firmware dùng PubSubClient nên một lần kết nối lại MQTT có thể tạm ngắt lấy mẫu
chuyển động khoảng hai giây. Cửa sổ PPG/candidate ngã sẽ bị hủy an toàn sau
khoảng trống, nhưng sự kiện nằm trọn trong khoảng đó có thể bị bỏ lỡ. Đây là
giới hạn đã chấp nhận của MVP phi lâm sàng, không phải cơ chế an toàn cá nhân.

## Tài liệu

- [Kiến trúc và ranh giới](docs/architecture-and-scope.md)
- [BOM và wiring](docs/bom-and-wiring.md)
- [Quickstart Windows](docs/windows-quickstart.md)
- [Hợp đồng dữ liệu MQTT](docs/data-contract.md)
- [Chế độ mạng và bảo mật](docs/network-and-security.md)
- [Khắc phục sự cố](docs/troubleshooting.md)
- [Checklist kiểm thử](docs/test-checklist.md)
- [Thông báo Telegram](docs/telegram-notifications.md)

## Cấu trúc

```text
firmware/   firmware PlatformIO cho NodeMCU
edge/       MQTT ingestion, SQLite, FastAPI và dashboard
simulator/  bộ phát dữ liệu MQTT tổng hợp
deploy/     Mosquitto, profile edge Docker, ACL và generator mật khẩu
docs/       hướng dẫn vận hành và kiểm thử
tests/      kiểm thử tự động
```
