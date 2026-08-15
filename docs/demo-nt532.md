# Demo NT532: độ tin cậy xử lý bản tin MQTT

> **Trạng thái tài liệu:** kịch bản demo kèm biên bản validation kỹ thuật ngày
> 14/08/2026. Báo cáo mang trạng thái
> `READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS`; bìa và thông tin hành chính
> Nhóm 3 đã được điền theo mẫu tham chiếu do người dùng cung cấp. Node vật lý,
> screen reader thủ công và zoom 400% vẫn `NOT_VERIFIED`.

Tên đề tài:

> **Đánh giá độ tin cậy xử lý bản tin MQTT trong hệ thống IoT edge phi lâm sàng
> dưới lỗi cảm biến và lỗi ở tầng ứng dụng**

Hướng môn học: **IoT Protocol - user-provided brief** cho môn Công nghệ IoT hiện
đại NT532. Chưa có rubric/learning outcome chính thức để tuyên bố đối sánh đầy
đủ. Demo không đo 5G và không đánh giá độ chính xác y tế.

## 1. Mục tiêu và thời lượng

Trong 12-15 phút, demo phải cho thấy được bốn lớp bằng chứng:

1. MQTT topic/schema hiện hữu vẫn tương thích và chạy end-to-end.
2. Dữ liệu sensor invalid bị fail-closed thay vì trở thành số đo hoặc alert giả.
3. Xử lý atomic/session-aware chống duplicate, out-of-order, crash/retry và old
   Last Will ghi đè boot hiện tại.
4. Experiment runner tạo schedule tái lập và evidence redacted; KPI chính dùng
   coverage của toàn lịch và schedule-to-API upper-bound, đồng thời luôn phân
   biệt app impairment với packet/network/5G measurement.

Node vật lý chỉ là bước tùy chọn để chứng minh pipeline. Simulator là nguồn
ground truth chính của demo tái lập.

## 2. Ranh giới an toàn và claim

- Không dùng số đo hoặc alert để chẩn đoán, điều trị hay quyết định cấp cứu.
- `low_spo2` và `fall_suspected_demo` chỉ là tình huống tổng hợp của prototype.
- Không gọi DS18B20 là nhiệt độ cơ thể và không gọi MAX30102 là thiết bị y tế.
- Không gọi `remote-app-emulated` là mạng 5G, packet loss hoặc network emulator.
- Không gọi delivery ngoài là exactly-once. Chỉ đánh giá logical commit và quan
  sát API theo identity `(device_id, boot_id, stream, seq)`.
- Không chụp hoặc xuất username, password, token, raw exception hay endpoint
  nhạy cảm.

## 3. Chuẩn bị trước buổi demo

Chạy từ thư mục gốc `iot-health-edge` trong PowerShell. Chuẩn bị môi trường theo
[README](../README.md), rồi đặt credential cục bộ bằng biến môi trường hoặc nhập
ẩn. Không đưa giá trị thật vào lệnh, slide hoặc evidence:

```powershell
.\.venv\Scripts\Activate.ps1
$env:SIMULATOR_MQTT_USERNAME = 'health_node'
$env:SIMULATOR_MQTT_PASSWORD = '<mat-khau-node-cuc-bo>'
```

Broker/edge phải chạy và dashboard phải mở tại `http://127.0.0.1:8000`. Trước
khi trình bày, chạy gate read-only/build-only sau; không dùng launcher có thể
upload firmware:

```powershell
.\scripts\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware
```

Khối artifact dưới đây là evidence lịch sử trước telemetry v4. Source regression
suite của artifact đó đạt `258 passed`; nó không xác nhận worktree `0.4.0`.
Final verification artifact `1.3`,
browser artifact `1.1` và evidence bundle v5 đã được khóa bằng SHA-256 trong biên
bản ở Mục 5; không tái dùng hash hoặc run v1-v4.

Nếu regression P0 hoặc full pytest fail, dừng và ghi `FAILED`; không chuyển lỗi
source thành `NOT_VERIFIED`. Docker live, firmware build-only hoặc phần cứng chỉ
được ghi `NOT_VERIFIED` khi thiếu đúng dependency/môi trường tương ứng.

## 4. Luồng demo chính

Các quan sát dưới đây là tiêu chí cho lần trình bày lại. Với cấu hình broker
mặc định, credential `health_node` chỉ được ACL cho phép publish vào namespace
của `health-node-01`. Vì vậy cả ba lượt dùng cùng device ID và được phân biệt
bằng `boot_id` mới do từng lần chạy simulator sinh ra. Chỉ dùng device ID khác
khi đã provision credential/ACL tương ứng; không nới ACL thành wildcard để chạy
demo.

### Bước 1 - Normal: chứng minh pipeline MQTT

```powershell
python -m simulator --device-id health-node-01 --scenario normal --count 20 --seed 101
```

Quan sát bắt buộc:

- node online, schema `health.telemetry.v4` và sequence tăng;
- ba topic vẫn thuộc namespace `iot-health/v1/devices/{device_id}/...`;
- dữ liệu hợp lệ được lưu/hiển thị và không có alert demo mới;
- trạng thái Edge và trạng thái node không bị gộp thành một nhãn.

Evidence cần chụp: command exit code, API/dashboard với device ID, schema, boot,
seq và timestamp. Không dùng ảnh dashboard DHT11 cũ làm bằng chứng cho source v4.

### Bước 2 - Motion artifact: chứng minh fail-closed

```powershell
python -m simulator --device-id health-node-01 --scenario motion_artifact --count 20 --seed 102
```

Quan sát bắt buộc:

- `motion_artifact=true`;
- HR/SpO2 là `null` với validity flag tương ứng bằng `false`;
- UI phân biệt trạng thái `noisy` với `fault` và giải thích lý do dữ liệu bị loại;
- không mở alert sinh hiệu từ các candidate invalid.

### Bước 2b - PPG chưa ổn định: raw không được giả làm confirmed

```powershell
python -m simulator --device-id health-node-01 --scenario unstable_ppg --count 6 --seed 106
```

Raw HR phải luân phiên 180/66 trong API audit; `heart_rate_bpm` và `spo2_pct`
confirmed phải là `null`, reason là `unstable`, dashboard hiện “Đang xác nhận”
và không mở alert sinh hiệu.

### Bước 3 - Low SpO2 demo: alert hợp lệ và ACK

```powershell
python -m simulator --device-id health-node-01 --scenario low_spo2 --count 20 --seed 103
```

Quan sát bắt buộc:

- candidate có quality hợp lệ và chỉ mở alert sau hold time cấu hình;
- một episode chỉ tạo một logical alert, telemetry tiếp tục vi phạm không tạo
  alert trùng;
- ACK trên dashboard lưu actor/note/thời điểm; “đã xem” không đồng nghĩa “đã xử
  lý y tế”.

Nếu cấu hình hold time khác mặc định khiến 20 mẫu chưa đủ, tăng `--count` và ghi
giá trị cấu hình trong manifest/biên bản; không rút ngắn hold chỉ để demo đẹp.

### Bước 4 - Fault schedule correctness/session

Chạy tập regression đúng blast radius:

```powershell
python -m pytest tests/test_db.py tests/test_ingestion.py tests/test_rules.py tests/test_mqtt_client.py -q
```

Fault matrix phải có evidence cho từng fixture sau:

| Fixture | Lịch sự kiện tối thiểu | Ground truth |
|---|---|---|
| Crash/retry | exception sau telemetry insert; restart service; retry cùng identity | đúng một telemetry, một logical alert và một history |
| Alert-write rollback | exception giữa alert write và outer commit; restart; retry | DB và rule state rollback cùng nhau; retry hoàn tất đúng một lần |
| Duplicate | phát lại cùng `(device, boot, stream, seq)` | disposition `duplicate`; không chạy rule lần hai |
| Out-of-order | current boot nhận sequence lùi | disposition `out_of_order`; không rewind device/rule |
| Old LWT | `boot-A online -> boot-B telemetry -> boot-A offline` | boot B vẫn là session hiện tại; LWT cũ có disposition `stale` |

Baseline phải được pin tại commit
`7030e4b30300dec65646e3091356ca00d9eaa8f5` cùng config hash và chạy trong
worktree đọc riêng. Không checkout baseline đè workspace đã harden. Mỗi fixture
deterministic lặp 30 lần với database mới chỉ để kiểm tra repeatability; báo
`pass/30`, không gán Wilson CI cho các lần lặp không độc lập.

### Bước 5 - Xem schedule trước khi đo

Hai lệnh dry-run sau phải dùng cùng scenario/count/seed:

```powershell
python -m simulator.experiment --profile lan-baseline --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
python -m simulator.experiment --profile remote-app-emulated --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
```

Dry-run phải ghi `planned`, không xuất số measured. Profile thứ hai phải hiện rõ:

```text
profile_kind=app_impairment
injection_point=before_mqtt_publish
network_claim=none
```

`intentionally_dropped` là logical message runner không attempt; đó không phải
packet loss quan sát được.

### Bước 6 - Chạy cặp experiment và xuất evidence

Chỉ chạy sau khi broker/edge thật sẵn sàng và `--help` đã xác nhận runner. V5
dùng 30 cặp seed; ví dụ cặp seed 1:

```powershell
python -m simulator.experiment --profile lan-baseline --scenario normal --count 30 --seed 1 --interval 0.25 --polling-resolution-ms 100 --observe-timeout 5 --device-id health-node-01 --run-id nt532-rq2-v5-lan-001 --output-dir evidence/runs
python -m simulator.experiment --profile remote-app-emulated --scenario normal --count 30 --seed 1 --interval 0.25 --polling-resolution-ms 100 --observe-timeout 5 --device-id health-node-01 --run-id nt532-rq2-v5-remote-001 --output-dir evidence/runs
python -m simulator.aggregate --input-dir evidence/runs --output evidence/analysis/rq2-v5-experiments.json --run-prefix nt532-rq2-v5- --min-seeds 30
```

Lặp hai lệnh runner với seed `1..30` và run ID ba chữ số. Aggregate chỉ nhận
artifact version `5.0` có prefix `nt532-rq2-v5-`; evidence v1-v4 không dùng.

Mỗi run phải tạo đúng cấu trúc:

```text
evidence/runs/<run_id>/
|-- manifest.json
|-- samples.jsonl
`-- summary.json
```

Kiểm tra run mới nhất mà không in credential:

```powershell
$latestRun = Get-ChildItem -LiteralPath .\evidence\runs -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
Get-Content -LiteralPath (Join-Path $latestRun.FullName 'manifest.json')
Get-Content -LiteralPath (Join-Path $latestRun.FullName 'summary.json')
```

Reconciliation bắt buộc tách `scheduled`, `intentionally_dropped`,
`unique_logical_publish_attempted`, `attempt_count`, `published`, `ingested` và
`api_observed`. KPI chính:

```text
scheduled_observation_ratio = unique_api_observed / scheduled
schedule_to_api_upper_bound_ms = api_observed_monotonic - scheduled_slot_monotonic
```

Coverage chính giữ intentional drop trong mẫu số. KPI phụ
`attempted_delivery_ratio = unique_api_observed / unique_logical_publish_attempted`
chỉ đánh giá message đã attempt; alias `delivery_ratio` không được trình bày như
KPI chính. Retry chỉ tăng `attempt_count`, không tăng mẫu số logical.

Chỉ báo percentile khi run `completed` có ít nhất 20 observed message. P50/p95
schedule-to-API chỉ tính trên message quan sát được nên phải đọc cùng coverage;
đây là same-host polling upper-bound, không phải network latency. Campaign chính
dùng 30 cặp seed và báo paired delta `remote-app-emulated - lan-baseline`.

### Bước 7 - Kiểm tra redaction và đóng demo

```powershell
Get-ChildItem -LiteralPath .\evidence\runs -Recurse -File |
    Select-String -Pattern 'password|passwd|token|secret|authorization|raw_exception'
```

Kỳ vọng không có credential hoặc raw exception. Nếu có hit, không trình chiếu
hay đóng gói evidence; chuyển run thành failed/invalid và xử lý redaction trước.

Kết thúc bằng ba câu rõ ràng:

1. Kết quả RQ1 chỉ nói về atomic/session-aware processing ở cấp ứng dụng trên
   MQTT 3.1.1, không phải đề xuất giao thức mới.
2. Kết quả RQ2 chỉ mô tả pipeline simulator dưới app impairment, không suy ra
   packet loss, TCP behavior hoặc 5G.
3. Prototype là phi lâm sàng và không chứng minh độ chính xác cảm biến y tế.

## 5. Biên bản validation kỹ thuật

| Hạng mục | Trạng thái | Evidence/giá trị |
|---|---|---|
| Provenance RQ1 | `VERIFIED_WITH_LIMITATION` | baseline commit `7030e4b30300dec65646e3091356ca00d9eaa8f5`, clean hash `760429f9dceed614279cb6c937d111a66fb1cb63ca813ed615c7de1bbd24c280`; artifact hardened sinh pre-commit với scoped hash `4bce098e63c53ab20bc7d9ab37162848504160b620c4a1a7ebba6ccfe7de5419`; source hiện ở `935c393e03a68465e538f624ff3405cd4560eb49` |
| Provenance RQ2 v5 | `VERIFIED_WITH_LIMITATION` | artifact sinh với `worktree_uncommitted`; allowlisted source hash `f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280` khớp commit `935c393e03a68465e538f624ff3405cd4560eb49` |
| Source regression lịch sử | `VERIFIED_WITH_LIMITATION` | `258 passed` thuộc artifact/commit trước v4; worktree v4 được kiểm thử riêng, không thay đổi artifact đã ký |
| Normal campaign | `VERIFIED` | artifact `5.0`, 30 matched seed/profile, 30 message/run; `evidence/analysis/rq2-v5-experiments.json`, SHA-256 `b2bb2e80edee83bd8a89531d079e4148ddb1442e7a9734cb2de353e4cddd4ffb` |
| Historical normal simulator E2E v3 | `VERIFIED_WITH_LIMITATION` | acceptance 14/08/2026: simulator 1.2.0/schema v3, seq 20; không phải bằng chứng v4 |
| Historical motion artifact v3 | `VERIFIED_WITH_LIMITATION` | HR/SpO2 null + invalid, không alert; snapshot cũ không xác nhận gate firmware v4 |
| Historical low SpO2 + ACK v3 | `VERIFIED_WITH_LIMITATION` | SpO2 88,5%, một alert + ACK; chỉ là contract/rule lịch sử |
| Current simulator/API/dashboard v4 | `NOT_VERIFIED` | cần tạo artifact E2E mới từ simulator 1.3.0, gồm `unstable_ppg`; unit/integration tests không thay thế artifact đo |
| Fault probe A/B | `VERIFIED_WITH_LIMITATION` | atomic alert: baseline 0/30, hardened 30/30; old LWT: baseline 0/30, hardened 30/30; deterministic repeatability, không có inferential CI |
| `lan-baseline` | `VERIFIED` | scheduled observation 1,0 [1,0; 1,0]; schedule→API p50 235,0 ms [234,0; 254,087]; p95 305,525 ms [289,8; 348,4]; attempted delivery phụ 1,0 |
| `remote-app-emulated` | `VERIFIED_WITH_BOUNDARY` | scheduled observation 0,833333 [0,8; 0,866667]; p50 632,75 ms [539,0; 710,75]; p95 969,925 ms [885,575; 1.101,75]; intentional drop 0,166667 [0,133333; 0,2]; attempted delivery phụ 1,0 |
| Paired remote − LAN | `VERIFIED_WITH_BOUNDARY` | coverage -0,166667 [-0,2; -0,133333]; p50 +363,0 ms [+316,5; +472,25]; p95 +634,275 ms [+564,875; +760,025]; attempted delta 0 |
| Measurement boundary | `VERIFIED` | same-process host monotonic, polling 100 ms, primary schedule-to-API, app impairment before publish, `network_claim=none`, `measured_5g=false` |
| Final verification lịch sử | `VERIFIED_WITH_LIMITATION` | artifact `1.3` tại commit lịch sử; không bao phủ worktree telemetry v4/firmware 0.4.0 |
| Browser smoke | `VERIFIED_WITH_LIMITATION` | artifact `1.1`, 320/360/768/1440 px; SHA-256 `e03c63d8849751fd57742839c0da802499f5eb757abaf55140b174012c210a02`; không phải WCAG conformance |
| Manual screen reader/zoom 400% | `NOT_VERIFIED` | cần kiểm tra thủ công riêng |
| Research bundle secret scan | `VERIFIED` | 189 file allowlist; aggregate reconcile + 185 text file redaction pass; ZIP SHA-256 `52aa1960e98209560a61fe9c835a98d47e46f95a5e8780bc365a6a993e083daa` |
| Software acceptance bundle | `VERIFIED` | 14 payload allowlist; 10 text file redaction/reconciliation pass; ZIP SHA-256 `b6dc2e9016d97fecdb8394b653fc0dbee0eba2cd1073b099f3cf8dceff984542` |
| Docker live | `VERIFIED` | health/capability boundary pass trong exact final invocation |
| Firmware build-only | `VERIFIED_WITH_LIMITATION` | build pass; không upload, không suy ra runtime phần cứng |
| Node vật lý | `NOT_VERIFIED` | tùy chọn; build thành công không chứng minh runtime phần cứng |

RQ2 v5 dùng 30 cặp seed, bootstrap percentile 95% CI với 5.000 resample; paired
effect dùng đơn vị matched seed pair. `remote-app-emulated` có logical drop cố ý
trước MQTT publish, được giữ trong denominator scheduled. Attempted delivery
`1,0` là KPI phụ, không phủ nhận coverage `0,833333` và không phải kết quả
mạng/5G.

## 6. Xử lý sự cố khi trình bày

- Runner chỉ tạo dry-run: giữ trạng thái `planned`; không đọc KPI như measured.
- Broker/edge không chạy: trình bày contract/fault regression và đánh dấu live
  experiment `NOT_VERIFIED`, không giả dữ liệu dashboard.
- Ít hơn 20 observed message: hiện “chưa đủ mẫu”, không tính p50/p95.
- Hai run khác seed/count/config: không so trực tiếp; chạy lại cặp matched.
- Node cùng hotspot với broker laptop: gọi đúng là demo LAN qua hotspot.
- Evidence thiếu manifest/sample/summary hoặc hash/config: run không đủ điều kiện
  đưa vào báo cáo.

## 7. Tài liệu đối chiếu

- [Hợp đồng dữ liệu MQTT](data-contract.md)
- [Kiến trúc và phạm vi](architecture-and-scope.md)
- [Chế độ mạng và bảo mật](network-and-security.md)
- [Checklist kiểm thử](test-checklist.md)
- [Nguồn báo cáo NT532](../deliverables/BAO-CAO-NT532-MQTT-MVP.md)
- [OASIS MQTT Version 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)
