---
date: 2026-08-15
session: windows-launcher-suite
status: source-validated
---

# Journal: 2026-08-15 — Windows Launcher Suite

## Context

Nâng launcher Windows đơn lẻ thành bộ công cụ cài đặt, khởi chạy, dừng, kiểm
tra trạng thái và xem log; đồng thời giữ đường chạy phần mềm tách biệt khỏi thao
tác phần cứng có thể nạp firmware.

## What Happened

- Tạo lõi dùng chung `IOT-HEALTH-EDGE.ps1` và 7 wrapper BAT cho install,
  software, hardware, legacy start, stop, status và logs.
- Chế độ software không upload firmware; hardware và launcher legacy giữ đúng
  semantics kiểm tra cấu hình, upload rồi chờ telemetry mới.
- Logs dùng file môi trường `NUL` để không nạp `.env`; mốc telemetry được lấy
  sau khi upload hoàn tất để không nhận nhầm dữ liệu firmware cũ.
- Thêm helper tương thích PowerShell 5.1 để thu stderr của native process mà
  không phụ thuộc cú pháp mới.
- Kiểm thử đạt `315 passed`; focused launcher đạt `29 passed`; PowerShell parser
  có `0` lỗi; Compose validation với cả `NUL` và `.env` đều đạt. Reviewer chấp
  thuận ở mức `9.5/10`.

## Reflection

Việc gom logic vào một PowerShell core làm các BAT mỏng và nhất quán hơn. Hai
điểm sửa cuối — cô lập logs khỏi `.env` và đặt timestamp sau upload — loại bỏ
rủi ro lộ cấu hình và false-positive quan trọng. Tuy vậy, bằng chứng hiện mới ở
mức source/contract validation, chưa phải xác nhận vận hành trên máy và phần
cứng thật.

## Decisions

| Decision | Rationale | Impact |
|---|---|---|
| Một PS1 dùng chung, BAT chỉ làm entrypoint | Tránh lặp logic và lệch hành vi | Bảo trì và kiểm thử tập trung |
| Tách software khỏi hardware | Khởi chạy dịch vụ không được vô tình upload | Giảm rủi ro tác động NodeMCU |
| Logs chạy với môi trường `NUL` | Không cần đọc bí mật để xem log | `.env` không bị nạp trong action logs |
| Chỉ chốt telemetry sau upload | Loại dữ liệu còn sót của firmware cũ | Hardware verification fail-closed chính xác hơn |

## Next

- Chưa chạy installer, launcher hardware hoặc upload firmware trong phiên này;
  cần smoke test có kiểm soát trên máy đích khi sẵn sàng.
- Không đọc, ghi hoặc hiển thị secret; không tạo commit.
- Thư mục `new-clone/` nằm ngoài phạm vi thay đổi này.
