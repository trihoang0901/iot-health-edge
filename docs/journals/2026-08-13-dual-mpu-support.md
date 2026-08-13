---
date: 2026-08-13
session: dual-mpu-support
status: completed
---

# Journal: 2026-08-13 — Hỗ trợ MPU-6050 và MPU-6500 tương thích

## Bối cảnh

Module được bán dưới SKU 02532 phản hồi tại địa chỉ I2C `0x68`, nhưng sáu lần
đọc trực tiếp ở 100 kHz và 400 kHz đều cho `WHO_AM_I=0x70`, không phải `0x68`
của MPU-6050. Bus I2C và khung chuyển động `0x3B` vẫn đọc được, nên hướng xử lý
là hỗ trợ đúng biến thể phần cứng thay vì bỏ qua kiểm tra định danh.

## Những gì đã xảy ra

- Thêm driver sáu trục do dự án sở hữu,
  [`Mpu6Axis`](../../firmware/health-node/include/Mpu6Axis.h), nhận MPU-6050
  (`0x68`) và MPU-6500 tương thích (`0x70`), nhưng từ chối ID khác.
- Driver đọc đủ khung 14 byte, giải mã big-endian có dấu, scale theo cấu hình
  ±8 g/±500 °/s và fail-closed khi đọc thiếu hoặc lỗi I2C. Cấu hình riêng cho
  MPU-6500 gồm thanh ghi DLPF gia tốc `0x1D`; MPU-6050 không bị ghi vào thanh
  ghi dành riêng này. Chi tiết nằm trong
  [`Mpu6Axis.cpp`](../../firmware/health-node/src/Mpu6Axis.cpp).
- Review phát hiện phép đọc-lại `GYRO_CONFIG` của MPU-6500 chưa kiểm tra hai bit
  `FCHOICE_B`. Mask xác minh đã được sửa thành `0x1B`; nhánh MPU-6050 tiếp tục
  dùng `0x18` vì hai bit thấp là reserved.
- Driver mới được nối vào
  [`SensorHub`](../../firmware/health-node/src/SensorHub.cpp), firmware nâng lên
  `0.2.1` và upload thành công lên node qua COM10.

## Bằng chứng xác minh

- `142` test Python đạt.
- `11` test native đạt: 7 kịch bản `FallDetector` và 4 nhóm kiểm tra
  [`Mpu6Axis`](../../firmware/health-node/test/native/mpu6axis_test.cpp).
- PlatformIO build môi trường `nodemcuv2` đạt; upload firmware `0.2.1` đạt.
- Mười mẫu telemetry mới đều có `motion_valid=true`, độ lớn gia tốc
  `0.934–0.945 g` và tốc độ góc `1.47–3.37 °/s`.
- Các trường gia tốc/con quay là số hữu hạn và lỗi `mpu6050_unavailable` đã
  biến mất khỏi telemetry runtime.

## Phản ánh

Tên hàng hoặc SKU không đủ để chọn driver; địa chỉ I2C cũng không phân biệt
được hai dòng chip. Gate đúng phải gồm ACK, `WHO_AM_I`, cấu hình đọc-lại và
khung số đo mới. Việc giữ driver nhỏ trong dự án làm rõ khác biệt thanh ghi,
mask và scale giữa hai biến thể, đồng thời vẫn từ chối phần cứng không xác định.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Hỗ trợ cả ID `0x68` và `0x70` | Module thực tế trả `0x70` ổn định | Giữ được module hiện có mà không giả mạo nó là MPU-6050 |
| Dùng driver `Mpu6Axis` của dự án | Cần cấu hình và xác minh theo từng biến thể | SensorHub có cùng giao diện chuyển động cho hai chip |
| Không bỏ qua `WHO_AM_I` | ACK hoặc tên SKU không chứng minh đúng IC | ID lạ và lỗi bus vẫn fail-closed |
| Giữ phát hiện té ngã ở mức prototype | Chưa có thử nghiệm chuyển động/té ngã vật lý | Không đưa ra tuyên bố y tế hoặc độ chính xác lâm sàng |

## Bằng chứng còn chờ

- MAX30102 và DHT11 đang tháo rời nên vẫn chưa được xác minh lại sau thay đổi.
- Chưa thực hiện bài thử chuyển động có kiểm soát hoặc mô phỏng chuỗi té ngã
  vật lý trên node thật.

## Bước tiếp theo

1. Gắn lại từng cảm biến MAX30102 và DHT11, kiểm tra độc lập trước khi ghép bus.
2. Thu telemetry khi xoay/nghiêng MPU để xác nhận cả gia tốc và con quay thay
   đổi đúng chiều, không chỉ số đo khi đặt yên.
3. Mô phỏng chuỗi low-g → impact → stillness có kiểm soát và đối chiếu sự kiện;
   không dùng prototype để chẩn đoán, xử trí y tế hoặc cảnh báo cấp cứu.
