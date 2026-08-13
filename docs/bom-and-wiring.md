# BOM và đấu dây

## Linh kiện cốt lõi

| Linh kiện | Vai trò trong MVP |
|---|---|
| NodeMCU ESP8266MOD | Bộ điều khiển và Wi-Fi |
| MAX30102 | Tín hiệu quang để ước lượng HR/SpO₂ demo |
| MPU-6050 hoặc MPU-6500-compatible | Gia tốc/con quay và phát hiện ngã demo |
| DHT11 hoặc module DHT11 | Nhiệt độ và độ ẩm môi trường |
| Điện trở 4,7–10 kΩ | Pull-up DATA lên 3V3 nếu DHT11/module chưa có sẵn |

DHT11 không đo nhiệt độ da, nhiệt độ cơ thể hay nhiệt độ lõi. Không đặt cảm
biến lên người để suy ra tình trạng sức khỏe và không dùng số đo DHT11 làm cảnh
báo sức khỏe. ESP32-CAM, PIR, RC522, servo, quạt và relay không cần cho lõi hệ
thống; không đóng cắt 220 V gần người dùng.

## Vật tư hỗ trợ

- Cáp USB **có đường data** và nguồn USB ổn định.
- Breadboard và dây Dupont để lắp nhanh.
- Kẹp/vỏ che sáng cho MAX30102 giúp giảm ánh sáng ngoài và thay đổi lực ngón tay.
- Buzzer/nút nhấn chỉ là tùy chọn; ACK chính thực hiện trên dashboard.

DHT11 rời thường có bốn chân và cần điện trở pull-up ngoài. Nhiều module ba
chân đã tích hợp điện trở; kiểm tra bo mạch/sơ đồ của đúng module trước khi lắp
thêm. Không suy đoán thứ tự chân chỉ từ hình hoặc màu dây.

## Sơ đồ chân đề xuất

| NodeMCU | GPIO | Nối tới | Ghi chú |
|---|---:|---|---|
| 3V3 | — | VCC MAX30102, VCC MPU motion, VCC DHT11 | Chỉ áp dụng khi breakout hỗ trợ logic/nguồn 3,3 V |
| GND | — | GND của cả ba cảm biến | Bắt buộc chung mass |
| D1 | GPIO5 | SCL MAX30102 + SCL MPU motion | Bus I²C dùng chung |
| D2 | GPIO4 | SDA MAX30102 + SDA MPU motion | Bus I²C dùng chung |
| D5 | GPIO14 | DATA DHT11 | Pull-up DATA lên 3V3 nếu module chưa có sẵn |

MAX30102 thường ở địa chỉ `0x57`. Firmware `0.2.1` dùng địa chỉ `0x68` cho cả
MPU-6050 và module MPU-6500-compatible, vì vậy AD0 phải ở mức thấp. Giá trị
`WHO_AM_I` đọc từ thanh ghi `0x75` là `0x68` cho MPU-6050 hoặc `0x70` cho biến
thể compatible; đây không phải địa chỉ I2C. DHT11 dùng giao thức một dây riêng
trên D5, không nằm trên bus I2C.

```text
NodeMCU 3V3 ----+---- MAX30102 VCC
                +---- MPU motion VCC
                +---- DHT11 VCC
                +--[4,7–10 kΩ nếu cần]-- DHT11 DATA

NodeMCU D1/GPIO5 ----- MAX30102 SCL + MPU motion SCL
NodeMCU D2/GPIO4 ----- MAX30102 SDA + MPU motion SDA
NodeMCU D5/GPIO14 ---- DHT11 DATA
NodeMCU GND ----------- GND chung
```

Với DHT11 rời bốn chân, chân `NC` để hở. Thứ tự VCC/DATA/NC/GND phải lấy từ
datasheet hoặc ký hiệu trên đúng linh kiện; module ba chân có thể sắp xếp khác.

## Kiểm tra trước khi cấp nguồn

1. Xác nhận pinout in trên từng breakout/module; module clone có thể khác nhau.
2. Xác nhận DATA DHT11 nối D5/GPIO14 và chỉ được kéo lên 3V3, không kéo lên 5 V.
3. IC MAX30102 nguyên bản dùng nhiều rail nguồn; chỉ đấu trực tiếp theo bảng khi
   đó là breakout hoàn chỉnh hỗ trợ 3,3 V. Không đưa 5 V vào SDA/SCL ESP8266.
4. Nhiều breakout I²C đã có điện trở pull-up. Nếu bus chập chờn, kiểm tra tổng
   pull-up thay vì tự động lắp thêm.
5. Tránh D3/GPIO0, D4/GPIO2 và D8/GPIO15 cho ngoại vi có thể kéo sai mức lúc boot.
6. Chỉ cấp nguồn sau khi nối GND chung và kiểm tra không chập 3V3–GND.

Sau khi cấp nguồn, chưa đánh dấu phần cứng MPU đạt chỉ vì scanner thấy `0x68`.
Phải đọc `WHO_AM_I` và chỉ chấp nhận `0x68` hoặc `0x70`, đọc đủ 14 byte từ
`0x3B`, rồi xác nhận firmware `0.2.1` phát số gia tốc/con quay hữu hạn mới.
Phát hiện ngã vẫn chỉ là tính năng demo phi lâm sàng; không thử ngã trên người.

Firmware đọc DHT11 không nhanh hơn một lần mỗi hai giây. Lỗi đọc phải tạo giá
trị `null`, cờ hợp lệ `false` và fault `dht11_unavailable` nhưng không được làm
dừng Wi-Fi/MQTT.
