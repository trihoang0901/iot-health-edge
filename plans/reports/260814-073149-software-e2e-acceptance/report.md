---
title: Biên bản nghiệm thu phần mềm NT532 MQTT Edge MVP
date: 2026-08-14
status: MVP_SOFTWARE_ACCEPTED_WITH_DECLARED_LIMITATIONS
scope: software-only, no hardware upload
---

# Kết luận

MVP phần mềm **PASS** trong phạm vi đã cam kết: MQTT 3.1.1, edge ingestion,
session/dedup, quality-aware rules, alert/ACK, dashboard, runner và evidence.
Không gắn thêm thiết bị và không upload firmware trong lần nghiệm thu này.

Kết luận này không đồng nghĩa node vật lý, độ chính xác y tế hoặc backhaul 5G đã
được kiểm chứng. Prototype vẫn là hệ thống phi lâm sàng.

# Phạm vi đã chạy

- Docker Mosquitto + Edge API live;
- ba scenario simulator tuần tự qua broker thật;
- transaction, retry, duplicate, ordering, old LWT và session regressions;
- dashboard Chrome ở 320, 360, 768 và 1440 px;
- toàn bộ source regression, JavaScript syntax và Compose resolved config;
- hai experiment dry-run artifact v5;
- firmware `nodemcuv2` build-only, không upload;
- validator và redaction của bundle nghiên cứu v5 hiện hữu.

# Kết quả chính

| Gate | Kết quả | Bằng chứng |
|---|---:|---|
| Docker live | PASS | Edge healthy; DB healthy; MQTT connected + subscribed; worker alive; processing errors 0 |
| Normal E2E | PASS | schema v3, seq 20, quality hợp lệ, 0 alert mới |
| Motion artifact | PASS | HR/SpO2 null + invalid, fault `ppg_motion_artifact`, 0 alert mới |
| Low SpO2 | PASS | SpO2 hợp lệ 88,5%, đúng 1 alert `demo_low_spo2` |
| ACK idempotency | PASS | ACK hai lần, cùng alert giữ trạng thái `acknowledged` |
| Fault/session focused | PASS | 49/49 test |
| Full regression | PASS | 235/235 test trong 23,68 giây |
| Browser smoke | PASS | 4/4 viewport; không overflow, duplicate ID hoặc control thiếu nhãn |
| JavaScript + Compose | PASS | syntax và resolved config |
| Experiment dry-run | PASS | hai profile `planned`, artifact 5.0, `network_claim=none`, `measured_5g=false` |
| Firmware build-only | PASS | RAM 43,0%; flash 29,5%; không upload |
| Evidence bundle v5 | PASS | 189 file allowlist; 0 sensitive-key hit; 0 absolute-path hit |

Chi tiết ba scenario và provenance tái lập:
[scenario-acceptance.json](scenario-acceptance.json). Snapshot API đã rút gọn,
không chứa credential hoặc đường dẫn máy trạm:
[scenario-observations.json](scenario-observations.json).
Browser artifact: [browser-smoke.json](ui/browser-smoke.json).

Ba lệnh measured đã dùng cùng credential/node namespace được ACL cho phép:

```powershell
python -m simulator --device-id health-node-01 --scenario normal --count 20 --seed 101
python -m simulator --device-id health-node-01 --scenario motion_artifact --count 20 --seed 102
python -m simulator --device-id health-node-01 --scenario low_spo2 --count 20 --seed 103
```

Source runner được khóa bằng SHA-256
`f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280`;
verification canonical artifact `1.3` có SHA-256
`9e82fe7fa3848812eb18fc0491f01fc250ac71032beb4e94c8d61f55e8eb0c69`.
Con số `235/235` ở bảng trên là tại thời điểm chạy acceptance; canonical
verification sau commit source sạch đạt `257/257`.

# Kiểm tra giao diện

Các ảnh được sinh từ đúng static asset đang được container phục vụ:

- [mobile 320 px](ui/dashboard-mobile-320.png)
- [mobile 360 px](ui/dashboard-mobile-360.png)
- [tablet 768 px](ui/dashboard-tablet-768.png)
- [desktop 1440 px](ui/dashboard-desktop-1440.png)

Ảnh chụp sau khi simulator kết thúc nên node hiển thị ngoại tuyến là đúng contract:
simulator publish retained `online=false`, reason `simulator_complete`. Cảnh báo
SpO2 hiển thị `Đã xem`, khớp trạng thái ACK đã kiểm tra.

# Lỗi phát hiện và đã sửa

Runbook trước đây dùng ba device ID demo khác nhau, trong khi credential
`health_node` chỉ được ACL cho phép publish namespace `health-node-01`. Broker
đã từ chối đúng các publish ngoài ACL. `docs/demo-nt532.md` đã được sửa để dùng
cùng device ID, phân biệt từng lượt bằng `boot_id`; ACL không bị nới wildcard.

# Quan sát còn lại

- Broker ghi nhận 30 lần thử kết nối không được cấp quyền trong 15 phút từ một
  client chưa xác định. Broker đều từ chối; luồng acceptance hợp lệ không bị ảnh hưởng.
- Manual screen reader và zoom trình duyệt 400% chưa được kiểm tra thủ công.
- Node vật lý và dữ liệu cảm biến mới chưa được chạy trong lượt này.
- `remote-app-emulated` chỉ là app impairment trước MQTT publish, không phải
  packet loss, network emulator hoặc phép đo 5G.

# Quyết định phát hành

- **MVP phần mềm để demo/chấm môn:** GO.
- **Tuyên bố sản phẩm y tế, node vật lý đã xác minh hoặc 5G đã đo:** NO-GO.
- Khi demo trực tiếp, chạy simulator song song nếu cần quan sát trạng thái
  `online`; sau khi lệnh kết thúc, trạng thái `offline` là hành vi dự kiến.
