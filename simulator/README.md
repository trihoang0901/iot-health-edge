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

Các kịch bản: `normal`, `ds18b20_fault`, `motion_artifact`, `low_spo2`,
`high_hr`, `fall`, `offline`. Simulator mặc định phát strict
`health.telemetry.v3`. Kịch bản `ds18b20_fault` đặt
`wearable.wrist_surface_temp_c` thành `null`, cờ
`quality.wrist_surface_temp_valid=false` và thêm fault kỹ thuật
`ds18b20_unavailable`. Dùng `--count 0` để chạy liên tục. Có thể dùng
`--prompt-password` thay biến mật khẩu để nhập ẩn. CLI cố ý không nhận mật khẩu
dạng tham số để tránh shell lưu plaintext trong lịch sử.

Simulator phát đúng ba topic:

```text
iot-health/v1/devices/{device_id}/telemetry
iot-health/v1/devices/{device_id}/event
iot-health/v1/devices/{device_id}/status
```

Status được retain; telemetry dùng QoS 0 giống giới hạn của PubSubClient trên
firmware; event/status dùng QoS 1 trong simulator. Nhiệt độ v3 là số đo tiếp xúc
bề mặt cổ tay thử nghiệm từ DS18B20, không phải nhiệt độ cơ thể/lõi, không dùng
để chẩn đoán sốt và không kích hoạt alert nhiệt độ.
