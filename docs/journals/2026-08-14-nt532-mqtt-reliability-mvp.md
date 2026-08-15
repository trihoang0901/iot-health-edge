# Nhật ký kỹ thuật: NT532 MQTT reliability MVP

## Quyết định chính

Đổi câu chuyện đồ án từ theo dõi bệnh nhân/5G chưa có bằng chứng sang testbed IoT
edge phi lâm sàng đánh giá độ tin cậy xử lý logical message trên MQTT 3.1.1.
5G được giữ ở roadmap validation backhaul khi có broker đầu xa và route evidence;
không mua thêm board, sensor hay modem.

## Điều đã thay đổi

- Gom commit telemetry, rule và alert vào cùng transaction; RAM rule state được
  snapshot/restore và notification chỉ chạy sau commit.
- Thêm session admission bền theo device/boot/stream, epoch cho retained LWT và
  migration cho mọi telemetry boot lịch sử.
- Xây runner/aggregate v5 với provenance, schedule monotonic tuyệt đối,
  `slot_to_publish_ms`, raw reconciliation, paired bootstrap và registry cache
  chỉ cho run strict-valid.
- Làm lại dashboard thành experiment cockpit, thêm URL state/race guard,
  history metadata, measurement boundary và trạng thái degraded trung thực.
- Xây pipeline verification, browser evidence, report Word và packager
  allowlist/redaction fail-closed.

## Bài học

Các phiên bản evidence v1-v4 bị loại vì những sai lệch như denominator không
bao gồm drop, clock/timeline chưa đo trực tiếp, artifact finalize không atomic
hoặc invariant dùng requested sleep thay cho thời gian thực. Không nới tolerance
để hợp thức hóa dữ liệu cũ; v5 đo trực tiếp và chạy lại đủ 60 run.

Kết quả RQ2 phải đọc coverage cùng latency: dropped message không có latency.
Attempted delivery 1,0 không có nghĩa toàn bộ lịch được quan sát. App impairment
trước publish không thể đại diện cho packet loss, TCP retransmission hay 5G.

## Trạng thái kết thúc

Full suite 235 pass; exact final verification, Docker live, firmware build-only,
60 run v5, aggregate, browser 4 viewport, evidence bundle và DOCX 32 trang đều
đã khóa bằng artifact/SHA. Node vật lý, manual screen reader và zoom 400% vẫn
`NOT_VERIFIED`. Sau đó người dùng đã cung cấp đủ thông tin hành chính và một báo
cáo tham chiếu cho bìa; trạng thái được nâng thành
`READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS` sau render/QA lại.
