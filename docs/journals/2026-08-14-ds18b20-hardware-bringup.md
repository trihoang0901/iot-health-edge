---
date: 2026-08-14
session: ds18b20-hardware-bringup
status: completed
---

# Journal: 2026-08-14 — Bring-up phần cứng DS18B20

## Bối cảnh

Firmware `0.3.1` thêm pull-up nội yếu của ESP8266 như một fallback cho bus
1-Wire prototype trên D5/GPIO14. Mục tiêu phiên này là tách lỗi host/USB khỏi
lỗi wiring, kiểm tra trực tiếp ROM và scratchpad DS18B20, rồi xác nhận contract
`health.telemetry.v3` trên production. Đây vẫn là prototype phi lâm sàng.

## Những gì đã xảy ra

- Driver CH340 trên máy bring-up được rollback từ `oem252.inf`
  `3.9.2024.9` xuống `oem121.inf` `3.7.2022.1`. Sau rollback, thiết bị CH340
  hiện ở COM10 với trạng thái `OK`. Thay đổi driver chỉ là biến môi trường của
  máy thử, không phải khuyến nghị chung cho mọi NodeMCU.
- Scanner A/B ở nhánh `external_only` không enumerate được ROM 1-Wire. Khi bật
  fallback pull-up nội, scanner tìm được ROM family `0x28`, CRC hợp lệ,
  addressed power báo externally powered và nhiệt độ `27.3125 °C`.
- Firmware production `0.3.1` được upload. Trước hard reset, edge nhận telemetry
  v3 cùng boot ID prefix `366fa…` tại `seq=7`, `seq=10` và `seq=12`.
- Các bản tin trước reset có nhiệt độ bề mặt cổ tay hợp lệ,
  `quality.wrist_surface_temp_valid=true`, motion hợp lệ và không có
  `ds18b20_unavailable`.
- MAX30102 khởi tạo được, nhưng capture trước reset không có ngón tay và còn
  fault `ppg_sample_loss`.
- Sau hard reset, Serial boot `a164b119f1fd90b3` báo firmware `0.3.1`,
  `wifi_connected ip=192.168.137.37` và `mqtt_connected`.
- Edge nhận telemetry mới cùng boot tại `seq=23`, `seq=25` và `seq=28`. Cả ba
  mẫu có nhiệt độ `27.3125 °C`, `wrist_surface_temp_valid=true`, motion
  valid/`idle` và `sensor_faults=[]`.
- MAX30102 sau reset không còn unavailable hoặc `ppg_sample_loss`. Không có
  ngón tay nên `finger_present=false`, HR/SpO₂ là `null` đúng fail-closed; phiên
  này vẫn chưa tạo bằng chứng HR/SpO₂ mới.
- Dashboard hiển thị node online, nhiệt độ cổ tay `27.3 °C` ở trạng thái hợp lệ,
  firmware `0.3.1` và không có lỗi trình duyệt.

## Bằng chứng quan sát được

| Tầng | Kết quả | Diễn giải giới hạn |
|---|---|---|
| USB/driver | CH340 `3.9.2024.9` → `3.7.2022.1`, COM10 `OK` | Tương quan theo máy thử, không chứng minh nguyên nhân duy nhất |
| Scanner `external_only` | Không tìm thấy ROM | Chưa đạt đường external-only; cần kiểm tra điện trở, mối hàn và dây |
| Scanner có pull-up nội | Family `0x28`, CRC hợp lệ, powered, `27.3125 °C` | Chứng minh giao tiếp prototype, không thay thế pull-up ngoài |
| Telemetry trước reset | Boot prefix `366fa…`, `seq=7/10/12`, temperature valid, motion valid, không DS fault | Có `ppg_sample_loss`, cần phân biệt fault khởi động với trạng thái ổn định |
| Serial sau hard reset | Boot `a164b119f1fd90b3`, fw `0.3.1`, Wi-Fi `192.168.137.37`, MQTT connected | Xác nhận đúng firmware và đường truyền mới |
| Telemetry chốt | Cùng boot, `seq=23/25/28`, `27.3125 °C`, temperature valid, motion valid/idle, `sensor_faults=[]` | Chứng minh pipeline v3 ổn định ở ba checkpoint |
| MAX30102 chốt | Khởi tạo, không còn fault; không có ngón tay nên HR/SpO₂ `null` | Fail-closed đúng nhưng chưa xác nhận phép đo có ngón tay |
| Dashboard | Online, wrist `27.3 °C` hợp lệ, fw `0.3.1`, không browser error | Xác nhận đường hiển thị end-to-end tại thời điểm thử |

## Đánh giá

Fallback pull-up nội giúp bus prototype ngắn enumerate và đọc DS18B20 trong
phiên này. Tuy nhiên pull-up nội ESP8266 yếu, biến thiên và không phải linh kiện
được kiểm soát cho dây wearable. Việc nhánh `external_only` không thấy ROM cho
thấy đường pull-up ngoài hoặc chất lượng kết nối vẫn cần được xử lý; không được
diễn giải kết quả fallback thành quyền bỏ điện trở 4,7 kΩ.

Telemetry mới xác nhận đúng contract nhiệt độ và motion, nhưng không xác nhận
độ chính xác nhiệt độ bề mặt, nhiệt độ cơ thể/lõi, phát hiện ngã hay MAX30102.
`ppg_sample_loss` ở capture trước đã biến mất sau hard reset; trạng thái chốt
không có sensor fault. HR/SpO₂ vẫn `null` vì không có ngón tay, là fail-closed
đúng chứ không phải số đo HR/SpO₂.

## Quyết định

| Quyết định | Lý do | Tác động |
|---|---|---|
| Giữ pull-up nội trong `0.3.1` như fallback prototype | Hỗ trợ bring-up dây ngắn khi bus yếu | Tăng khả năng chẩn đoán, không đổi wiring wearable |
| Vẫn bắt buộc pull-up ngoài 4,7 kΩ DATA→3V3 | Cần mức kéo lên ổn định và có kiểm soát | Không đóng wearable chỉ dựa vào pull-up nội |
| Ghi driver CH340 như biến môi trường | Trạng thái host thay đổi cùng phiên thử | Không tổng quát hóa rollback thành cách sửa mặc định |
| Chỉ đánh dấu DS contract/motion đạt mức bring-up | Có telemetry mới, seq tăng và fault đúng | Không tuyên bố hiệu chuẩn hoặc an toàn y tế |
| Để phép đo MAX30102 hiện tại ở trạng thái chưa đạt | Sensor không còn fault nhưng chưa có ngón tay | Cần một lần retest PPG riêng |

## Chưa được xác minh

- External-only chưa enumerate lại thành công với điện trở 4,7 kΩ đã được xác
  minh và mối nối ổn định.
- Chưa có soak test wearable dài hạn cho bus 1-Wire, nguồn, nhiệt và reconnect.
- Chưa có capture `0.3.1` với ngón tay ổn định để xác nhận PPG/HR/SpO₂.
- Số đọc `27.3125 °C` không phải hiệu chuẩn và không đại diện nhiệt độ cơ thể.

## Bước tiếp theo

1. Kiểm tra đúng điện trở 4,7 kΩ từ DATA lên 3V3, mối hàn và pinout; chạy lại
   scanner external-only cho tới khi ROM/CRC ổn định mà không phụ thuộc fallback.
2. Lặp telemetry trong thời gian dài hơn và xác nhận boot/seq, nhiệt độ, motion,
   Wi-Fi/MQTT không mất nhịp.
3. Đặt ngón tay đúng, che sáng và chờ cửa sổ PPG sạch; chỉ đánh dấu phép đo MAX
   đạt khi `finger_present`, PPG, HR/SpO₂ và các cờ valid phù hợp.
