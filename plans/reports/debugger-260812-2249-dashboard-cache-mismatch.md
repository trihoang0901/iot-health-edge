---
type: debugger
date: 2026-08-12
status: resolved
---

# Dashboard báo sai Edge không phản hồi

## Tóm tắt

- **Hiện tượng:** selector còn ghi node trực tuyến nhưng pill báo Edge không
  phản hồi và bốn thẻ bị xóa.
- **Ảnh hưởng:** giao diện sai trạng thái; MQTT, API và dữ liệu không bị mất.
- **Nguyên nhân:** tab Edge dùng `app.js` DS18B20 cũ cùng HTML DHT11 mới.
- **Trạng thái:** đã sửa và deploy.

## Phân tích kỹ thuật

Tại thời điểm ảnh 22:38:08, `/api/v1/devices` và `/api/v1/overview` đều trả
200. SQLite đồng thời nhận telemetry DHT11 hợp lệ. Script cache cũ vẫn tìm
`#skin-temp`; HTML mới không còn phần tử này nên JavaScript ném `TypeError`.
Khối catch cũ gom lỗi render thành nhãn `Edge không phản hồi`.

Tab lỗi dùng CSS ba cột cũ, trong khi source/server hiện dùng bốn cột. Một
profile trình duyệt sạch tải cùng URL và hiển thị đúng ngay lập tức.

## Khắc phục

- Tạo version tài nguyên từ SHA-256 của favicon, CSS và JavaScript.
- Gắn version chung vào ba URL static trong HTML được phục vụ.
- Đặt `Cache-Control: no-store` cho `/` và `/static/*`.
- Phân biệt lỗi render với lỗi Edge; ghi lỗi thật vào console.
- Cô lập lỗi tải lịch sử alert để không xóa số đo chính.

## Bằng chứng sau sửa

- Fresh suite sau review/fix cleanup: 142 passed.
- Compile Python, `node --check` và Docker Compose config đạt.
- Edge healthy; MQTT connected/subscribed; node online.
- Hai tab Edge được mở lại với asset version cuối `2dce6a98d67f`.
- Dashboard hiển thị bốn cột, DHT11 28,9 °C và 48,0%, cả hai hợp lệ; asset
  hiện tại không có warning/error.
- Khi refresh lỗi, dropdown, timestamp, số đo, biểu đồ và cảnh báo cũ đều được
  xóa; nhãn phân biệt mất kết nối, HTTP/JSON lỗi và lỗi render.

## Giới hạn

Nhịp tim và SpO2 vẫn trống khi chưa đặt ngón tay hoặc MAX30102 chưa có mẫu hợp
lệ. Dữ liệu chỉ phục vụ prototype phi lâm sàng.
