---
date: 2026-08-13
session: max30102-fifo-recovery
status: complete
---

# Journal: 2026-08-13 — Khôi phục FIFO MAX30102

## Bối cảnh

MAX30102 phản hồi trên I2C và probe riêng cho thấy tín hiệu quang thay đổi khi
có ngón tay, nhưng firmware production liên tục bỏ cửa sổ PPG. Cần phân biệt lỗi
dây/cảm biến với lỗi gate bảo vệ FIFO trước khi đánh giá HR/SpO₂.

## Những gì đã xảy ra

- Root cause nằm ở việc đọc `OVF_COUNTER` trước khi lấy mẫu và dùng counter này
  làm gate lỗi. Sau startup overflow, counter có thể bão hòa trong khi một số
  module compatible cần tiêu thụ một mẫu hoàn chỉnh mới xóa trạng thái đó.
- Nhánh cũ clear FIFO rồi return trước khi đọc mẫu, vì vậy có thể tự khóa trong
  vòng clear-and-return dù cảm biến và đường quang vẫn hoạt động.
- Bản sửa cho firmware `0.2.2` bỏ pre-read `OVF_COUNTER` khỏi gate trong
  [`SensorHub.cpp`](../../firmware/health-node/src/SensorHub.cpp).
- Tính fail-closed vẫn được giữ: khoảng lấy mẫu lớn hơn `250 ms` hoặc SparkFun
  `check()` fetch từ bốn mẫu vào buffer cục bộ sẽ xóa cửa sổ, vô hiệu HR/SpO₂ và
  báo mất mẫu thay vì phát dữ liệu gián đoạn hay số cũ.

## Bằng chứng hiện có

- Firmware diagnostic bỏ gate overflow nhận khoảng 25 mẫu/s.
- Gap lớn nhất quan sát được nằm trong 10–37 ms, thấp hơn gate 250 ms.
- `storage_hits=0`, tức không thấy lần fetch nào chạm giới hạn buffer cục bộ
  trong phiên diagnostic.
- IR khi không có ngón tay khoảng 812–853; probe trước với ngón tay đạt khoảng
  219.000–225.000. Chênh lệch này chứng minh đường quang/raw response, không phải
  bằng chứng HR hoặc SpO₂ hợp lệ.
- Clean build firmware `0.2.2` đạt: RAM 35.200/81.920 byte (43,0%), flash
  305.527/1.044.464 byte (29,3%). Pytest đạt 145 test; hai bộ test native cho
  IMU và fall detector, compileall và Docker Compose config đều đạt.
- Upload production lên COM10 hoàn tất lúc `2026-08-13T14:49:31Z`. Broker nhận
  client boot mới `168db49aabe19b2f`; API báo `online=true`, firmware `0.2.2`,
  schema `health.telemetry.v2`, `seq` tăng và telemetry mới sau upload.
- MAX30102 không còn fault `max30102_unavailable`; `ppg_sample_loss` vẫn được
  giữ fail-closed cho tới khi thu đủ 100 mẫu sạch có ngón tay.
- Phiên production cuối thu 20 mẫu API liên tiếp với `finger_present=true`, PPG
  khoảng 0,66–0,81, `motion_artifact=false`, HR/SpO₂ có giá trị cùng cờ valid.
  Mẫu chốt ở `seq=972` có HR 125 bpm, SpO₂ 100%, PPG 0,674 và không còn fault.
  Các giá trị dao động đáng kể nên chỉ xác nhận pipeline prototype hoạt động,
  không phải bằng chứng độ chính xác hay ổn định y tế.

## Phản ánh

Một counter phần cứng hữu ích cho chẩn đoán không nhất thiết phù hợp làm gate
trước đọc. Khi chính thao tác tiêu thụ mẫu là điều kiện phục hồi, return sớm sẽ
biến cơ chế bảo vệ thành trạng thái tự khóa. Gate theo thời gian và số mẫu thực
sự fetch gần với rủi ro cần ngăn: cửa sổ PPG bị gián đoạn.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Bỏ pre-read `OVF_COUNTER` khỏi gate | Có thể bão hòa sau startup và cần đọc mẫu để phục hồi | FIFO có thể tiếp tục được drain |
| Giữ gate gap `>250 ms` | Khoảng trống làm cửa sổ không liên tục | HR/SpO₂ fail-closed thay vì dùng dữ liệu gián đoạn |
| Giữ gate SparkFun fetch `>=4` | Buffer cục bộ chỉ có bốn slot | Không âm thầm dùng mẫu đã bị ghi đè |
| Xác nhận pipeline HR/SpO₂ production | 20 mẫu liên tiếp có finger/valid và fault rỗng | Hoàn tất bring-up phi lâm sàng, chưa xác nhận độ chính xác |

## Bước tiếp theo

1. Nếu cần đánh giá độ ổn định, thu nhiều cửa sổ dài hơn với module cố định và
   so sánh với thiết bị tham chiếu phù hợp; không dùng một cửa sổ để hiệu chuẩn.
2. Giữ toàn bộ kết luận ở mức prototype phi lâm sàng; không suy ra độ chính xác
   y tế từ raw IR hoặc một lần đo demo.
