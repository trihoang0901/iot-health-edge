# Docker cục bộ: Mosquitto và edge tùy chọn

Chế độ mặc định chỉ chạy broker Mosquitto dành cho phát triển trong mạng LAN.
Broker:

- từ chối kết nối ẩn danh;
- lưu dữ liệu bền vững trong Docker volume;
- dùng ACL để node chỉ ghi đúng ba topic của `device_id` đã cấu hình;
- không chứa mật khẩu hoặc hash mật khẩu trong mã nguồn.

Từ PowerShell tại thư mục gốc dự án:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Initialize-Mosquitto.ps1
docker compose -f .\deploy\docker-compose.yml up -d
docker compose -f .\deploy\docker-compose.yml logs -f mosquitto
```

## Profile `full`: broker + edge/dashboard

Tạo `.env` cục bộ một lần và thay `MQTT_PASSWORD` bằng mật khẩu của tài khoản
`health_edge` đã nhập ở script trên. Không commit, gửi hoặc chụp màn hình tệp
này:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env
}
notepad .\.env
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full up -d --build
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full ps
```

Edge chạy non-root, filesystem container ở chế độ read-only, không có Linux
capability và chỉ publish dashboard ra `127.0.0.1:8000`. SQLite được lưu trong
volume `edge-data`; khởi động lại container không xóa dữ liệu. Healthcheck chỉ
đạt khi `/healthz` báo cả SQLite và MQTT hoạt động.

Xem log hoặc dừng profile:

```powershell
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full logs -f edge
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full down
```

Lệnh `down` giữ cả `mosquitto-data` và `edge-data`. Không thêm `--volumes` trừ
khi chủ động muốn xóa dữ liệu đã lưu.

Script gọi `mosquitto_passwd` tương tác bên trong container. Mật khẩu không được đưa vào tham số dòng lệnh và chỉ hash được ghi vào `deploy/mosquitto/generated/passwords`. Chạy lại có `-Force` sẽ thay toàn bộ tệp tài khoản hiện có, vì vậy chỉ dùng khi chủ động xoay vòng thông tin đăng nhập.

Để thêm node khác, tạo một bộ triển khai/ACL phù hợp hoặc mở rộng generator có kiểm soát; không dùng chung tài khoản thiết bị trong bản triển khai thật.

Broker này nghe TCP `1883`, có xác thực nhưng **không mã hóa**. Chỉ dùng trong LAN tin cậy, không NAT/forward cổng ra Internet. Dashboard Docker chỉ bind loopback; không đổi thành `0.0.0.0:8000` nếu chưa bổ sung xác thực HTTP. Với broker từ xa, dùng MQTT qua TLS `8883` và xác minh CA.
