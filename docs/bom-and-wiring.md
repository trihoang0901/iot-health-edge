# BOM và đấu dây

## Linh kiện cốt lõi

| Linh kiện | Vai trò trong MVP |
|---|---|
| NodeMCU ESP8266MOD | Bộ điều khiển và Wi-Fi |
| MAX30102 | Tín hiệu quang để ước lượng HR/SpO₂ demo |
| MPU-6050 hoặc MPU-6500-compatible | Gia tốc/con quay và phát hiện ngã demo |
| DS18B20 chống nước, ba dây | Nhiệt độ bề mặt tại điểm tiếp xúc cổ tay |
| Điện trở 4,7 kΩ | Pull-up bắt buộc từ DATA DS18B20 lên 3V3 |

DS18B20 chỉ mô tả nhiệt độ bề mặt tại điểm tiếp xúc. Không diễn giải thành
nhiệt độ cơ thể/lõi, không kết luận sốt và không dùng làm cảnh báo sức khỏe.
ESP32-CAM, PIR, RC522, servo, quạt và relay không cần cho lõi hệ thống; không
đóng cắt 220 V gần người dùng.

## Vật tư hỗ trợ

- Cáp USB **có đường data** và nguồn USB ổn định.
- Breadboard và dây Dupont để lắp nhanh.
- Kẹp/vỏ che sáng cho MAX30102 giúp giảm ánh sáng ngoài và thay đổi lực ngón tay.
- Buzzer/nút nhấn chỉ là tùy chọn; ACK chính thực hiện trên dashboard.

DS18B20 chống nước thường có ba dây nhưng màu dây không phải chuẩn nhận dạng
đáng tin cậy. Xác minh VDD/DATA/GND từ datasheet hoặc nhãn của đúng đầu dò trước
khi cấp nguồn. Thiết kế này dùng powered three-wire, không dùng parasite-power.

## Sơ đồ chân đề xuất

| NodeMCU | GPIO | Nối tới | Ghi chú |
|---|---:|---|---|
| 3V3 | — | VCC MAX30102, VCC MPU motion, VDD DS18B20 | Chỉ áp dụng khi breakout hỗ trợ logic/nguồn 3,3 V |
| GND | — | GND của cả ba cảm biến | Bắt buộc chung mass |
| D1 | GPIO5 | SCL MAX30102 + SCL MPU motion | Bus I²C dùng chung |
| D2 | GPIO4 | SDA MAX30102 + SDA MPU motion | Bus I²C dùng chung |
| D5 | GPIO14 | DATA DS18B20 | Điện trở 4,7 kΩ từ DATA lên 3V3 |

MAX30102 thường ở địa chỉ `0x57`. Source `0.3.0` giữ cấu hình đã được kiểm tra
trên `0.2.2`: địa chỉ `0x68` cho cả MPU-6050 và module MPU-6500-compatible, vì
vậy AD0 phải ở mức thấp. Giá trị
`WHO_AM_I` đọc từ thanh ghi `0x75` là `0x68` cho MPU-6050 hoặc `0x70` cho biến
thể compatible; đây không phải địa chỉ I2C. DS18B20 dùng bus 1-Wire riêng trên
D5, không nằm trên bus I2C.

```text
NodeMCU 3V3 ----+---- MAX30102 VCC
                +---- MPU motion VCC
                +---- DS18B20 VDD
                +--[4,7 kΩ]-- DS18B20 DATA

NodeMCU D1/GPIO5 ----- MAX30102 SCL + MPU motion SCL
NodeMCU D2/GPIO4 ----- MAX30102 SDA + MPU motion SDA
NodeMCU D5/GPIO14 ---- DS18B20 DATA
NodeMCU GND ----------- GND chung
```

Không nối tắt VDD xuống GND để dùng parasite-power. Powered three-wire là cấu
hình duy nhất của kế hoạch này: VDD=3V3, DATA=D5/GPIO14, GND=GND chung.

## Kiểm tra trước khi cấp nguồn

1. Xác nhận pinout in trên từng breakout/module; module clone có thể khác nhau.
2. Xác nhận DS18B20 DATA nối D5/GPIO14 qua pull-up 4,7 kΩ lên 3V3; VDD cũng nối
   3V3 và GND nối mass chung. Không kéo DATA lên 5 V.
3. IC MAX30102 nguyên bản dùng nhiều rail nguồn; chỉ đấu trực tiếp theo bảng khi
   đó là breakout hoàn chỉnh hỗ trợ 3,3 V. Không đưa 5 V vào SDA/SCL ESP8266.
4. Nhiều breakout I²C đã có điện trở pull-up. Nếu bus chập chờn, kiểm tra tổng
   pull-up thay vì tự động lắp thêm.
5. Tránh D3/GPIO0, D4/GPIO2 và D8/GPIO15 cho ngoại vi có thể kéo sai mức lúc boot.
6. Chỉ cấp nguồn sau khi nối GND chung và kiểm tra không chập 3V3–GND.

Sau khi cấp nguồn, chưa đánh dấu phần cứng MPU đạt chỉ vì scanner thấy `0x68`.
Phải đọc `WHO_AM_I` và chỉ chấp nhận `0x68` hoặc `0x70`, đọc đủ 14 byte từ
`0x3B`, rồi xác nhận firmware đang chạy phát số gia tốc/con quay hữu hạn mới.
Lần kiểm tra phần cứng trước đã đạt trên `0.2.2`; source `0.3.0` chưa upload.
Phát hiện ngã vẫn chỉ là tính năng demo phi lâm sàng; không thử ngã trên người.

Với MAX30102, ACK tại `0x57` chưa đủ. Firmware `0.2.2` đã được nạp và kiểm
tra red/IR thô thay đổi rõ giữa không-ngón-tay và ngón tay đặt ổn định. Firmware
không dùng pre-read `OVF_COUNTER` làm gate, nhưng vẫn hủy cửa sổ PPG nếu khoảng
lấy mẫu vượt `250 ms` hoặc SparkFun `check()` fetch từ bốn mẫu. Số quang thô
không phải bằng chứng HR/SpO₂ cuối hay độ chính xác y tế.

Source firmware `0.3.0` đặt DS18B20 ở 12-bit, gọi yêu cầu chuyển đổi bất đồng bộ
rồi chỉ đọc sau ít nhất `750 ms`; không `delay(750)` hoặc chờ bận trong vòng
lặp. Lỗi/thiếu đầu dò phải phát `wearable.wrist_surface_temp_c=null`,
`quality.wrist_surface_temp_valid=false` và fault `ds18b20_unavailable` mà
không dừng MAX30102, dual-MPU, Wi-Fi hay MQTT. Source này chưa được upload và
chưa có số đọc DS18B20 vật lý được xác nhận.
