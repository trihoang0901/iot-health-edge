# MQTT simulator

Chạy từ thư mục gốc dự án. `--dry-run` không cần broker hoặc thông tin đăng nhập:

```powershell
python -m simulator --scenario fall --count 6 --dry-run
```

Chạy thật với broker cục bộ:

```powershell
$env:SIMULATOR_MQTT_USERNAME = 'health_node'
$env:SIMULATOR_MQTT_PASSWORD = '<mat-khau-node-da-tao>'
python -m simulator --scenario normal --count 20
```

Các kịch bản: `normal`, `dht_fault`, `motion_artifact`, `low_spo2`, `high_hr`, `fall`, `offline`. Kịch bản `dht_fault` vẫn phát `health.telemetry.v2`, nhưng đặt nhiệt độ môi trường và độ ẩm thành `null`, hai cờ hợp lệ thành `false`, đồng thời thêm lỗi kỹ thuật `dht11_unavailable`. Dùng `--count 0` để chạy liên tục. Có thể dùng `--prompt-password` thay biến mật khẩu để nhập ẩn. CLI cố ý không nhận mật khẩu dạng tham số để tránh shell lưu plaintext trong lịch sử.

Simulator phát đúng ba topic:

```text
iot-health/v1/devices/{device_id}/telemetry
iot-health/v1/devices/{device_id}/event
iot-health/v1/devices/{device_id}/status
```

Status được retain; telemetry dùng QoS 0 giống giới hạn của PubSubClient trên firmware; event/status dùng QoS 1 trong simulator. Telemetry v2 mô phỏng DHT11 bằng `environment.ambient_temp_c` và `environment.humidity_pct`; đây là số đo môi trường tổng hợp, không phải nhiệt độ cơ thể hay dữ liệu bệnh nhân.
