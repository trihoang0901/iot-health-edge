---
date: 2026-08-13
session: ds18b20-wearable-migration
status: completed
---

# Journal: 2026-08-13 — Chuyển sang DS18B20 đeo cổ tay

## Bối cảnh

Node mới chuyển từ DHT11 môi trường sang DS18B20 tiếp xúc bề mặt cổ tay. Cần
một contract mới để không đổi nghĩa dữ liệu `skin_temp_*` v1 hoặc environment
DHT11 v2, đồng thời không làm gián đoạn MAX30102, dual-MPU và MQTT.

## Những gì đã thay đổi

- Source firmware được nâng định hướng lên `0.3.0` và strict
  `health.telemetry.v3`.
- Nhiệt độ mới dùng đúng `wearable.wrist_surface_temp_c`, đi cùng
  `quality.wrist_surface_temp_valid`; lỗi dùng `ds18b20_unavailable`.
- DS18B20 dùng powered three-wire trên D5/GPIO14, pull-up 4,7 kΩ từ DATA lên
  3V3. Chế độ parasite-power không thuộc cấu hình hỗ trợ.
- Thiết kế yêu cầu chuyển đổi 12-bit bất đồng bộ và đọc sau ít nhất `750 ms`;
  không chờ bằng `delay()` hoặc polling bận trong vòng sampling.
- Edge giữ strict v1/v2, thêm v3 và migration SQLite dạng additive. Các cột,
  hàng và raw payload lịch sử không bị xóa hoặc đổi nghĩa.
- Dashboard/node mới chỉ trình bày HR, SpO₂ và nhiệt độ bề mặt cổ tay. Dữ liệu
  nhiệt độ v1/v2 không được hiển thị như số đo cổ tay.

## Ranh giới phi lâm sàng

DS18B20 chỉ cung cấp nhiệt độ bề mặt tại điểm tiếp xúc. Giá trị không đại diện
nhiệt độ cơ thể/lõi, không dùng chẩn đoán sốt và không kích hoạt alert hay
Telegram. MAX30102, phát hiện ngã và mọi alert hiện có vẫn chỉ là demo cần người
kiểm tra.

## Bằng chứng giữ nguyên từ `0.2.2`

Firmware `0.2.2` đã được upload trong phiên trước. Đường MAX30102 không còn bị
khóa bởi pre-read `OVF_COUNTER`; diagnostic có raw quang học và production có
20 mẫu liên tiếp với ngón tay được nhận, PPG cùng HR/SpO₂ hợp lệ. Dual-MPU cũng
đã có telemetry motion hợp lệ. Đây là bằng chứng bring-up phi lâm sàng, không
phải hiệu chuẩn hoặc chứng nhận độ chính xác.

## Chưa được xác minh

- Source `0.3.0` **chưa được upload** trong migration này.
- Chưa có số đọc DS18B20 vật lý, chưa xác nhận thời gian chuyển đổi trên phần
  cứng và chưa đánh giá tiếp xúc/vỏ đeo thực tế.
- Build/test tự động chỉ là gate source; không thay thế bằng chứng phần cứng.

## Bằng chứng source và regression

- Ba native executable `Ds18b20Schedule`, `Mpu6Axis` và `FallDetector` qua với
  C++17, `-Wall -Wextra -Werror`. Scheduler bao phủ deadline 750 ms, cadence
  start-to-start 2 giây, retry 10 giây, rollover `millis()` và invalidation.
- Full Python suite cuối: **164 passed**, không fail/skip. `compileall`, syntax
  JavaScript và Docker Compose config đều exit 0.
- Simulator normal và `ds18b20_fault` phát sáu telemetry mẫu, cả sáu parse đúng
  strict v3. V3 từ chối kiểu coercible và buộc fault DS18B20 khớp cờ valid.
- Clean PlatformIO build thành công: RAM 35.224/81.920 byte (43,0%), flash
  308.255/1.044.464 byte (29,5%); không có warning thuộc source dự án.
- Audit tài liệu có ba JSON hợp lệ, không có link nội bộ hỏng. Review độc lập
  và adversarial không còn finding sau hai vòng sửa.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Tạo telemetry v3 | Tránh đổi nghĩa v1/v2 | Legacy tiếp tục đọc đúng nghĩa |
| Dùng object `wearable` | Tách bề mặt cổ tay khỏi môi trường/body | UI và API không relabel dữ liệu cũ |
| Chuyển đổi DS18B20 bất đồng bộ | Bảo vệ vòng MAX/MPU/MQTT | Không có blocking 750 ms |
| Không có alert nhiệt độ | Không có cơ sở lâm sàng | Không kết luận sốt hoặc gửi Telegram |
| Migration DB additive | Bảo toàn lịch sử | Không xóa DB/cột/raw payload |

## Bước tiếp theo

1. Không upload trong plan hiện tại. Nếu có phiên phần cứng được cho phép sau
   này, thu telemetry mới `fw=0.3.0`, v3, `seq` tăng và kiểm tra DS18B20 độc lập.
2. Chỉ sau bằng chứng vật lý mới đánh dấu các mục DS18B20/ghép cảm biến trong
   checklist; không suy ra chất lượng đo từ build hoặc simulator.
