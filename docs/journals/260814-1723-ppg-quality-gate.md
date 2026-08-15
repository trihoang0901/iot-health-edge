---
date: 2026-08-14
session: ppg-quality-gate
status: source-validated
---

# Journal: 2026-08-14 — PPG Quality Gate

## Context

MAX30102 từng phát các chuỗi HR thay đổi phi lý như `180 → 66 bpm`. Mục tiêu là
chặn số chưa đủ tin cậy ngay tại firmware, giữ dữ liệu thô để phân tích và chỉ
cho backend/alert sử dụng giá trị đã xác nhận. Đây vẫn là prototype phi lâm sàng.

## What happened

- Firmware lên `0.4.0`, telemetry lên `health.telemetry.v4`; thêm HR/SpO₂
  `raw` và giữ trường cũ làm `confirmed`.
- Thêm `PpgQualityGate` C++ thuần: cửa sổ quang 100 mẫu ở 25 Hz, median/MAD cho
  khoảng RR, Hampel/median trên tối đa 5 kết quả và cần ít nhất 3 kết quả nhất
  quán.
- Gate phát hiện `no_finger`, `warming_up`, `motion`, `clipping`,
  `low_perfusion`, `unstable`, `sample_loss`. Mức nhảy lớn hơn 25 bpm phải qua
  3 cửa sổ mới; trong lúc chờ, confirmed là `null`, không giữ số cũ.
- Review độc lập bổ sung Hampel/độ trải riêng cho SpO₂ (tối đa 4 điểm phần
  trăm), xóa raw-valid khi `sample_loss` và làm launcher fail-closed nếu sau
  upload không thấy đúng v4/firmware `0.4.0`.
- Ngưỡng khởi đầu: RR MAD tương đối tối đa 0,15; raw HR lệch HR suy ra từ RR tối
  đa 12 bpm; biên độ quang tương đối tối thiểu 0,003; clipping khi có ít nhất 3
  mẫu sát biên ADC 18-bit.
- Backend lưu và trả riêng `raw_value`/`confirmed_value`; rule chỉ đọc confirmed.
  Alert cần chuỗi mẫu phục hồi hợp lệ liên tục trong 10 giây mới đóng.
- Dashboard ánh xạ `warming_up` và `unstable` thành “Đang xác nhận”, thay vì hiện
  BPM bất thường.

## Reflection

Tách raw khỏi confirmed làm trạng thái không chắc chắn trở nên trung thực và
kiểm tra được. Gate nhiều lớp giảm nguy cơ một cửa sổ nhiễu đi thẳng tới alert,
nhưng các ngưỡng hiện chỉ là giá trị khởi đầu từ kiểm thử tổng hợp; chưa thể xem
chúng là độ chính xác y tế hoặc bằng chứng phần cứng.

## Decisions

| Quyết định | Lý do | Tác động |
|---|---|---|
| Fail closed bằng `null` | Không làm mượt hoặc giữ một số sai | Dashboard/alert không dùng số chưa xác nhận |
| Giữ raw tách biệt | Cần dữ liệu để tune và audit | API/SQLite vẫn quan sát được ứng viên thuật toán |
| Xác nhận 3/5 và ngưỡng nhảy 25 bpm | Cân bằng độ trễ với khả năng loại spike | Đổi mức lớn có trạng thái chờ rõ ràng |
| Đóng alert sau phục hồi 10 giây | Một mẫu bình thường chưa đủ | Giảm đóng/mở alert liên tục |

## Validation

- Full pytest sau review fixes: `304 passed`.
- Native `PpgQualityGate`: compile với `-Wall -Wextra -Werror` và chạy đạt.
- PlatformIO NodeMCU ESP8266: build thành công; RAM 43,3%, flash 29,8%.
- `node --check edge/static/app.js`: đạt.
- `docker compose config --quiet`: đạt.
- Simulator `unstable_ppg` v4 giữ raw `180 → 66 → 180`, confirmed `null` và
  `ppg_state=unstable` đúng schema.

## Limitations

- Không upload firmware lên NodeMCU trong phiên này.
- Chưa có lần kiểm chứng phần cứng mới với `finger_present=true` và HR/SpO₂ được
  xác nhận qua đủ cửa sổ.
- Chưa thu trace Red/IR thật để hiệu chỉnh LED, ADC, clipping, low-perfusion và
  ngưỡng RR; kết quả test tổng hợp không thay thế kiểm tra trên người/thiết bị.

## Next

- Làm kẹp ngón tay cố định, che sáng và giữ lực ép ổn định.
- Ghi trace Red/IR thật ở nhiều mức LED/ADC, sau đó tune ngưỡng bằng dữ liệu thay
  vì phỏng đoán.
- Upload `0.4.0`, kiểm tra firmware → MQTT → Edge API → dashboard với ngón tay
  hiện diện và lưu bằng chứng raw/confirmed/state mới.
- Chỉ cân nhắc cảm biến khác hoặc sensor-hub bù chuyển động nếu mục tiêu chuyển
  sang đo liên tục ở cổ tay khi vận động.
