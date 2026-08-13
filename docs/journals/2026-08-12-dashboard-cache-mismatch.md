---
date: 2026-08-12
session: dashboard-cache-mismatch
status: completed
---

# Journal: Dashboard báo sai Edge không phản hồi

## Bối cảnh

Sau khi đổi dashboard từ DS18B20 sang DHT11 và rebuild edge, hai tab Edge giữ
JavaScript/CSS cũ nhưng tải HTML mới. Giao diện vì vậy báo sai rằng Edge không
phản hồi trong khi node, broker, API và SQLite vẫn hoạt động.

## Những gì đã xảy ra

- Script DS18B20 cũ tìm `#skin-temp`; HTML DHT11 mới không có phần tử này nên
  render ném `TypeError` sau khi overview đã trả 200.
- Static URL không có version và không có Cache-Control, cho phép trộn asset
  giữa hai lần deploy.
- Dashboard nay dùng hash SHA-256 chung cho favicon/CSS/JavaScript và
  `Cache-Control: no-store` cho trang/static.
- Nhánh lỗi xóa đồng bộ dữ liệu không còn đáng tin cậy và phân biệt lỗi mạng,
  HTTP/JSON và lỗi render.

## Bằng chứng

- 142 test Python đạt; compile, JavaScript syntax và Compose config đạt.
- Hai tab Edge dùng asset version `2dce6a98d67f`, node trực tuyến.
- DHT11 hiển thị 28,9 °C và 48,0%, hai cờ hợp lệ.
- Review độc lập không còn finding mở.

## Quyết định

Không coi mọi ngoại lệ frontend là mất kết nối Edge. HTML và static asset phải
được phát theo cùng content version; trạng thái cache cũ không được hiển thị như
dữ liệu đang sống.

## Bước tiếp theo

MAX30102 và MPU-6050 vẫn báo unavailable trong lần runtime cuối. Kiểm tra riêng
nguồn, GND chung và I2C D1/D2; không liên hệ lỗi phần cứng này với cache của
dashboard.
