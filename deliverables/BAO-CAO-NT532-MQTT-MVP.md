---
title: "Đánh giá độ tin cậy xử lý bản tin MQTT trong hệ thống IoT edge phi lâm sàng dưới lỗi cảm biến và lỗi ở tầng ứng dụng"
document_status: READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS
results_status: TECHNICAL_VALIDATION_VERIFIED
course: "Công nghệ IoT hiện đại"
course_code: NT532
track: "IoT Protocol - user-provided brief"
institution: "Trường Đại học Công nghệ Thông tin - ĐHQG-HCM"
faculty: "Khoa Mạng máy tính và Truyền thông"
lecturer: "Nguyễn Khánh Thuật"
class_code: "NT532.Q31"
group: "3"
student_1_name: "Hoàng Xuân Minh Trí"
student_1_id: "24521829"
student_2_name: "Lê Hoàng Việt"
student_2_id: "23521778"
semester: "Hè, năm học 2025-2026"
submission_place: "TP. Hồ Chí Minh"
submission_date: "15/08/2026"
template_reference: "BaoCaoDoAn-Nhom10.docx do người dùng cung cấp"
baseline_commit: 7030e4b30300dec65646e3091356ca00d9eaa8f5
hardened_commit: 935c393e03a68465e538f624ff3405cd4560eb49
updated_at: "2026-08-14 Asia/Saigon"
---

# ĐẠI HỌC QUỐC GIA THÀNH PHỐ HỒ CHÍ MINH

## TRƯỜNG ĐẠI HỌC CÔNG NGHỆ THÔNG TIN

### KHOA MẠNG MÁY TÍNH VÀ TRUYỀN THÔNG

### BÁO CÁO ĐỒ ÁN MÔN CÔNG NGHỆ IOT HIỆN ĐẠI - NT532

# Đánh giá độ tin cậy xử lý bản tin MQTT trong hệ thống IoT edge phi lâm sàng dưới lỗi cảm biến và lỗi ở tầng ứng dụng

**Hướng đề tài:** IoT Protocol - user-provided brief, chờ rubric/learning outcome
chính thức<br>
**Giảng viên hướng dẫn:** Nguyễn Khánh Thuật<br>
**Lớp học phần:** NT532.Q31<br>
**Nhóm:** 3<br>
**Sinh viên thực hiện:** Hoàng Xuân Minh Trí - MSSV 24521829; Lê Hoàng Việt -
MSSV 23521778<br>
**Học kỳ/năm học:** Hè, năm học 2025-2026<br>
**Địa điểm, ngày nộp:** TP. Hồ Chí Minh, ngày 15 tháng 08 năm 2026<br>
**Mẫu bìa tham chiếu:** `BaoCaoDoAn-Nhom10.docx` do người dùng cung cấp; nội
dung Nhóm 10 không được sao chép.

> **READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS.** Thông tin hành chính và
> bìa đã được hoàn thiện theo mẫu tham chiếu do người dùng cung cấp. Phần kỹ
> thuật đã được validation theo ledger ở Mục 7.4. Các giới hạn `NOT_VERIFIED`
> về node vật lý, screen reader thủ công, zoom 400%, 5G và độ chính xác y tế phải
> được giữ nguyên; vai trò phân công chi tiết không được suy đoán khi người dùng
> chưa cung cấp.

## Quy ước trạng thái bằng chứng

| Trạng thái | Ý nghĩa |
|---|---|
| `SOURCE_VERIFIED` | Đã đối chiếu nội dung source/tài liệu hiện có; không đồng nghĩa runtime đã chạy trong phiên cuối |
| `VERIFIED` | Gate hoặc phép đo đã chạy đạt và có artifact/đường dẫn truy vết |
| `PENDING_VALIDATION` | Implementation hoặc phép đo đang chờ gate xác minh cuối |
| `NOT_VERIFIED` | Không có môi trường/evidence để kiểm chứng; không được chuyển thành kết quả đạt |
| `FAILED` | Gate đã chạy và không đạt; phải giữ nguyên đến khi có lần chạy lại thành công |
| `DRAFT_NOT_SUBMISSION_READY` | Thiếu thông tin hành chính, render hoặc evidence bắt buộc để nộp |
| `READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS` | Đã hoàn tất bìa, thông tin hành chính, evidence và QA tài liệu; các giới hạn kỹ thuật được công khai thay vì suy đoán |

# Tóm tắt

Đồ án xây dựng một testbed IoT edge phi lâm sàng sử dụng MQTT 3.1.1 để truyền
telemetry, sự kiện và trạng thái từ node cảm biến hoặc simulator đến Mosquitto,
dịch vụ FastAPI/SQLite và dashboard tiếng Việt. Trọng tâm của báo cáo không phải
độ chính xác y tế hay hiệu năng 5G, mà là độ tin cậy xử lý logical message ở tầng
ứng dụng: tính atomic giữa lưu telemetry và áp dụng rule, chống trùng, quản lý
boot/session, loại bỏ message stale/out-of-order và tạo evidence tái lập.

Nghiên cứu so sánh baseline được pin tại commit
`7030e4b30300dec65646e3091356ca00d9eaa8f5` với implementation hardened trên
cùng payload trace, rule và fault schedule. Implementation hardened hiện được
khóa tại commit `935c393e03a68465e538f624ff3405cd4560eb49`. Các artifact RQ1/RQ2 được
sinh trước commit với `source_state=worktree_uncommitted`; scoped SHA-256 của
chúng vẫn khớp source đã commit và được giữ nguyên như provenance lịch sử. Một
câu hỏi phụ dùng simulator để
mô tả pipeline dưới hai profile app impairment. Profile
`remote-app-emulated` chèn delay/jitter/drop/outage **trước MQTT publish**; nó
không phải network emulator, packet loss đo được hay phép đo 5G.

Probe deterministic cho RQ1 cho thấy baseline đạt `0/30` ở cả case atomic alert
sau crash/retry và old Last Will, trong khi working tree hardened đạt `30/30` ở
cả hai case. RQ2 v5 dùng 30 cặp seed độc lập, 30 message/run. Median tỷ lệ quan
sát trên toàn bộ lịch (`scheduled_observation_ratio`) là `1,0` cho
`lan-baseline` và `0,833333` cho `remote-app-emulated`; paired median delta
remote trừ LAN là `-0,166667`. Median p50/p95 schedule-to-API polling
upper-bound lần lượt là `235,0/305,525 ms` và `632,75/969,925 ms`. Tỷ lệ quan sát
trên những message thực sự attempt đều là `1,0`, nhưng đây chỉ là KPI phụ. Các
số này phản ánh app impairment trước publish trên cùng host, không phải network
latency, packet loss hay kết quả 5G.

Nghiệm thu phần mềm E2E ngày 14/08/2026 chạy ba scenario qua broker và edge
live bằng đúng namespace ACL. Normal không tạo alert; motion artifact vô hiệu
hóa HR/SpO2 và không tạo false alert; low SpO2 hợp lệ tạo đúng một logical
alert, ACK lặp giữ nguyên trạng thái `acknowledged`. Full regression đạt
`235/235` tại thời điểm acceptance; canonical verification cuối sau khi bổ
sung release regression đạt `257/257`. Focused fault/session đạt `49/49`,
browser smoke đạt 4/4 viewport và
firmware chỉ được build, không upload. Kết quả này cho phép GO đối với MVP phần
mềm demo/chấm môn, không mở rộng sang node vật lý, y tế hoặc 5G.

**Từ khóa:** MQTT 3.1.1; IoT Protocol; edge computing; session; Last Will;
idempotency; fault injection; reproducibility; non-clinical testbed.

# 1. Đặt vấn đề

## 1.1. Bối cảnh

MQTT là giao thức truyền tải publish/subscribe nhẹ, phù hợp môi trường IoT hạn
chế tài nguyên [1]. Tuy nhiên, QoS của MQTT không tự động bảo đảm một chuỗi xử
lý ứng dụng end-to-end đúng một lần. Trong testbed này, firmware phát telemetry
QoS 0; edge còn phải xác thực schema, lưu SQLite, cập nhật session, áp rule và
mở alert. Crash giữa các bước hoặc message từ boot cũ có thể tạo trạng thái DB,
rule và dashboard không nhất quán dù broker vẫn hoạt động đúng chuẩn.

Source hiện hữu đã có node ESP8266, strict schema v1/v2/v3, ba topic MQTT,
Mosquitto với ACL, FastAPI/SQLite, simulator và dashboard. Khoảng trống cần xử lý
cho đồ án IoT Protocol là biến các cơ chế này thành một pipeline có policy
session rõ, transaction boundary kiểm thử được và evidence tái lập.

## 1.2. Mục tiêu

Mục tiêu chính:

1. bảo đảm telemetry/rule/alert không bị dở dang khi crash và retry;
2. phân loại duplicate, out-of-order, stale và boot mới theo identity rõ ràng;
3. giữ tương thích topic namespace và schema production hiện có;
4. tạo runner/evidence xác định được denominator, clock domain và injection
   point;
5. cung cấp demo/report mà người chấm có thể tái lập, không cần mua thêm thiết
   bị.

## 1.3. Phù hợp môn học và giới hạn xác nhận

Hướng **IoT Protocol** là brief do người dùng cung cấp. Chưa có syllabus, rubric
hay learning outcome chính thức trong workspace; vì vậy báo cáo chỉ ghi nhận
course fit ở mức giả định hợp lý và chưa tuyên bố đáp ứng đầy đủ NT532.

| Thành phần đồ án | Liên hệ IoT Protocol dự kiến | Evidence bắt buộc |
|---|---|---|
| MQTT 3.1.1 | QoS, ClientId/session, retained status, Last Will | Contract, packet metadata và test |
| Topic/schema versioned | Interoperability và backward compatibility | Golden payload v1/v2/v3 |
| Atomic/session-aware ingestion | Reliability phía application consumer | Fault fixture, DB state và disposition |
| Experiment runner | Reproducibility, denominator và measurement boundary | Manifest, samples, summary |
| Security boundary | ACL, secret redaction, LAN/remote boundary | Config redacted và audit |

Khi nhận rubric chính thức, phải bổ sung traceability từ từng tiêu chí môn học
đến source, test, KPI và evidence. Không dùng bảng trên thay cho xác nhận của
giảng viên.

## 1.4. Đóng góp mục tiêu và tính mới

Các đóng góp đã được validation trong phạm vi **cấp đồ án môn học** gồm:

- outer transaction cho telemetry, rule transition và logical alert/history;
- policy boot/session và sequence riêng theo stream;
- fault matrix có ground truth cho crash/retry, duplicate, out-of-order và old
  Last Will;
- experiment artifact có run identity, schedule, correlation và redaction;
- UI giải thích protocol/runtime và không biến dữ liệu invalid thành alert giả.

Đồ án không đề xuất giao thức MQTT mới, không nâng claim thành scientific
novelty và không tuyên bố MQTT exactly-once cho delivery bên ngoài.

# 2. Nền tảng kỹ thuật và nguồn chuẩn

## 2.1. MQTT 3.1.1

OASIS định nghĩa MQTT là giao thức Client-Server publish/subscribe. QoS 0 là
at-most-once; mất message có thể xảy ra và sender không retry ở flow QoS này.
ClientId được dùng để nhận diện state của MQTT session. Will Message được broker
phát khi kết nối kết thúc bất thường theo các điều kiện của chuẩn; retained
message giúp subscriber mới nhận trạng thái gần nhất [1].

Dự án dùng các đặc tính trên như sau [4]:

- telemetry: QoS 0, không retain;
- event: không retain; simulator có thể dùng QoS 1;
- status: retain và có Last Will `online=false`;
- consumer vẫn dùng timeout freshness vì Last Will có thể đến trễ;
- `(device_id, boot_id, stream, seq)` là identity reconciliation của tầng ứng
  dụng, không phải thay đổi packet format MQTT.

QoS 2 trong chuẩn MQTT mô tả exactly-once delivery của Application Message ở
protocol flow tương ứng; nó không tự bao phủ transaction SQLite, rule engine,
notification hoặc thao tác ACK. Vì vậy báo cáo chỉ dùng thuật ngữ “đúng một
logical alert/history trong transaction nội bộ” khi evidence chứng minh.

## 2.2. Edge và ranh giới phi lâm sàng

Edge gán thời điểm nhận, xác thực payload, lưu lịch sử, chạy rule demo và phục
vụ API/dashboard cục bộ. Cảm biến và rule chỉ phục vụ bring-up/testbed:

- HR/SpO2 là giá trị tham khảo, không chứng minh độ chính xác y tế;
- DS18B20 đo bề mặt tại điểm tiếp xúc, không phải nhiệt độ cơ thể/lõi;
- `fall_suspected_demo` luôn cần người xác minh;
- không có quyết định chẩn đoán, điều trị hay cấp cứu.

## 2.3. 5G chỉ là roadmap sau MVP

Tổng quan 5GS của 3GPP mô tả hệ thống gồm UE, NG-RAN và 5G Core cùng các network
function/control-user plane liên quan [2]. Trong cấu hình hiện tại, NodeMCU và
laptop có thể là hai peer trên cùng WLAN của hotspot; gói MQTT đến broker laptop
có thể không đi qua mạng di động. Do đó báo cáo không đặt “5G” trong tên, RQ hoặc
kết luận thực nghiệm.

Chỉ được mở nhánh validation backhaul 5G khi có broker/edge đầu xa, bằng chứng
endpoint/route/network mode, thời gian thử, baseline cùng tải và phương pháp đo
được mô tả. Không mua modem/board mới chỉ để giữ từ khóa 5G.

## 2.4. Measurement boundary và RFC 9341

RFC 9341 mô tả Alternate-Marking cho đo packet loss/delay bằng correlation giữa
các measurement point, đồng bộ thời gian phù hợp và controlled domain [3]. Dự
án không triển khai phương pháp này. RFC được dùng để làm rõ một nguyên tắc:
việc runner chủ động bỏ logical message trước publish không phải packet-loss
measurement, và one-way delay giữa hai đồng hồ không đồng bộ không được suy ra
từ timestamp ứng dụng.

# 3. Baseline hệ thống

## 3.1. Kiến trúc

```text
Node ESP8266 hoặc simulator
        |
        | MQTT 3.1.1 / topic + strict JSON schema
        v
Mosquitto auth + ACL
        |
        v
MQTT client -> bounded ingestion -> validation/session -> SQLite + rule
                                                     |             |
                                                     v             v
                                                   API        logical alert
                                                     |
                                                     v
                                           Dashboard/ACK cục bộ
```

Telegram là transport tùy chọn, disabled-by-default và best-effort; lỗi/queue
đầy không được rollback ingestion. Dashboard/API mặc định bind loopback.

## 3.2. Topic và contract

| Loại | Topic | Schema hiện hành |
|---|---|---|
| Telemetry | `iot-health/v1/devices/{device_id}/telemetry` | `health.telemetry.v3`, vẫn nhận v1/v2 |
| Event | `iot-health/v1/devices/{device_id}/event` | `health.event.v1` |
| Status | `iot-health/v1/devices/{device_id}/status` | `health.status.v1` |

`device_id` trong payload phải khớp topic. JSON không nhận `NaN`, `Infinity`
hoặc field ngoài strict schema. Giá trị invalid phải là `null` với validity flag
`false`; fault là mã kỹ thuật, không phải chẩn đoán [4].

## 3.3. Baseline nghiên cứu

Baseline RQ1 được pin tại:

```text
7030e4b30300dec65646e3091356ca00d9eaa8f5
```

Baseline được chạy trong Git worktree đọc riêng; không checkout đè workspace
hardened. Provenance cuối được ghi như sau:

```text
baseline_commit = 7030e4b30300dec65646e3091356ca00d9eaa8f5
hardened_release_commit = 935c393e03a68465e538f624ff3405cd4560eb49
baseline_rq1_source_state = commit_clean
baseline_rq1_source_sha256 = 760429f9dceed614279cb6c937d111a66fb1cb63ca813ed615c7de1bbd24c280
hardened_rq1_measurement_source_state = worktree_uncommitted
hardened_rq1_source_sha256 = 4bce098e63c53ab20bc7d9ab37162848504160b620c4a1a7ebba6ccfe7de5419
rq2_artifact_version = 5.0
rq2_measurement_source_state = worktree_uncommitted
rq2_source_sha256 = f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280
```

Hai `rq1_source_sha256` chỉ băm nội dung theo thứ tự xác định của bốn file
`edge/db.py`, `edge/rules.py`, `edge/service.py`, `edge/mqtt_client.py`; chúng
không phải hash toàn repository hay config runtime. Báo cáo không công bố
`hardened_config_hash` hoặc full-tree source hash. Từng artifact kết quả được
khóa thêm bằng SHA-256 tại Mục 7.4. RQ2 v5 băm allowlist 13 file được ghi ngay
trong `controls.source_provenance.source_files`; đó cũng không phải hash toàn
repository. Trường `commit` trong artifact RQ1 hardened và `controls.commit`
trong aggregate RQ2 vẫn chứa HEAD/baseline anchor, **không** được hiểu là commit
của implementation hardened.

# 4. Câu hỏi nghiên cứu

## 4.1. RQ1 - atomic/session-aware processing

> So với baseline được pin, xử lý atomic + session-aware thay đổi tỷ lệ logical
> alert đúng và tỷ lệ state rewind thế nào dưới crash/retry, duplicate,
> out-of-order và old Last Will deterministic?

**H1:** implementation hardened tạo đúng một logical telemetry/alert/history và
không rewind current session trong toàn bộ fault matrix; baseline có ít nhất hai
counterexample tái hiện được bằng regression fixture.

H1 được đặt trước phép đo; kết quả kiểm chứng và giới hạn nằm tại Mục 7.2.

## 4.2. RQ2 - app impairment phía simulator

> App impairment trước MQTT publish ảnh hưởng thế nào đến tỷ lệ message trong
> toàn bộ lịch được API quan sát và schedule-to-API polling upper-bound của
> pipeline simulator?

RQ2 chỉ mô tả pipeline ứng dụng. Kết quả không được suy ra thành TCP packet loss,
MQTT reconnect behavior, network QoS, carrier benchmark hoặc 5G.

# 5. Thiết kế nghiên cứu

## 5.1. Factor, control và sampling unit

RQ1 dùng factor `implementation = baseline | hardened`. Hai nhánh giữ nguyên
payload trace, threshold, hold time, hysteresis, fault schedule và ground truth.
Mỗi fixture xác định trước current boot, unique telemetry/alert/history và
disposition mong đợi.

Mỗi deterministic case chạy 30 lần với database mới chỉ để chứng minh
repeatability. Báo `pass/30`; không dùng Wilson CI vì các lần lặp cùng fixture và
schedule không phải sample độc lập. Nếu nghiên cứu suy diễn được bổ sung, phải
định nghĩa quần thể seed/schedule độc lập và sampling unit trước khi tính CI.

RQ2 dùng 30 cặp seed độc lập, ghép `remote-app-emulated` với `lan-baseline` theo
cùng seed. Báo median run-level `scheduled_observation_ratio`, p50/p95
schedule-to-API upper-bound và bootstrap percentile 95% CI. Hiệu ứng treatment
được báo thêm bằng median paired delta `remote - LAN` với CI theo cặp seed.
`attempted_delivery_ratio` chỉ là KPI chẩn đoán phụ. Không báo p99 vì số
observation dưới 1.000/profile.

## 5.2. Fault matrix RQ1

| Case | Injection/schedule | Ground truth |
|---|---|---|
| F1 | exception sau telemetry insert | outer transaction rollback DB và rule state |
| F2 | exception giữa alert write và trước commit | không còn alert/history dở dang |
| F3 | restart service rồi retry cùng identity | đúng một telemetry, một logical alert, một history |
| F4 | duplicate cùng `(device, boot, stream, seq)` | `duplicate`; không evaluate rule lần hai |
| F5 | current boot nhận sequence lùi | `out_of_order`; không đổi device/rule |
| F6 | `boot-A online -> boot-B telemetry -> boot-A offline LWT` | boot B vẫn current; boot A `stale` |

Notification chỉ enqueue sau commit. Lỗi notification không được rollback
telemetry/rule/alert đã commit.

## 5.3. Profile RQ2

| Profile | Điểm chèn | Ý nghĩa hợp lệ |
|---|---|---|
| `lan-baseline` | trước publish | không chủ động delay/drop logical message |
| `remote-app-emulated` | trước publish | schedule delay/jitter/drop/outage tái lập ở tầng ứng dụng |

Cả hai artifact phải ghi:

```text
profile_kind=app_impairment
injection_point=before_mqtt_publish
network_claim=none
```

Với `remote-app-emulated`, `intentionally_dropped` là logical message runner
không attempt. Không gọi đây là packet loss đo được.

## 5.4. KPI và denominator

Mỗi sample được correlate bằng `(device_id, boot_id, stream, seq)` và tách các
mốc:

```text
scheduled -> intentionally_dropped hoặc publish_attempted
          -> published -> ingested -> api_observed
```

Hai KPI chính:

```text
scheduled_observation_ratio = unique_api_observed / scheduled
schedule_to_api_upper_bound_ms = api_observed_monotonic - scheduled_slot_monotonic
```

KPI coverage chính giữ `intentionally_dropped` trong mẫu số `scheduled`, nên
phản ánh đúng ảnh hưởng của app impairment lên toàn lịch. KPI phụ
`attempted_delivery_ratio = unique_api_observed / unique_logical_publish_attempted`
chỉ trả lời message đã attempt có được quan sát hay không; alias
`delivery_ratio` chỉ được giữ để tương thích consumer cũ. `attempt_count` là số
lần gửi vật lý; retry không làm tăng mẫu số logical. Duplicate, rejected, stale
và out-of-order phải báo thành disposition riêng.

Percentile chỉ xuất cho run `completed` có tối thiểu 20 message được quan sát.
Vì message bị drop không có latency, p50/p95 schedule-to-API là phân phối có
điều kiện trên message được quan sát và phải đọc cùng coverage. Đồng hồ monotonic
cùng host bao gồm scheduled delay/jitter/outage, thời gian publish/xử lý và sai
số API polling; đây là upper-bound của pipeline ứng dụng, không phải one-way
network latency. Publish-to-API upper-bound chỉ là chẩn đoán phụ. Với node vật lý
chưa đồng bộ clock, chỉ báo ingest-to-decision hoặc RTT request/response.

## 5.5. Runner và evidence

Dry-run matched:

```powershell
python -m simulator.experiment --profile lan-baseline --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
python -m simulator.experiment --profile remote-app-emulated --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
```

Measured campaign v5 chỉ thực hiện khi broker/edge đang chạy. Mỗi seed dùng
hai run ID matched có prefix riêng; ví dụ seed 1:

```powershell
python -m simulator.experiment --profile lan-baseline --scenario normal --count 30 --seed 1 --interval 0.25 --polling-resolution-ms 100 --observe-timeout 5 --device-id health-node-01 --run-id nt532-rq2-v5-lan-001 --output-dir evidence/runs
python -m simulator.experiment --profile remote-app-emulated --scenario normal --count 30 --seed 1 --interval 0.25 --polling-resolution-ms 100 --observe-timeout 5 --device-id health-node-01 --run-id nt532-rq2-v5-remote-001 --output-dir evidence/runs
```

Campaign lặp mẫu trên cho seed `1..30`, sau đó aggregate fail-closed chỉ nhận
prefix `nt532-rq2-v5-`. Không tái dùng evidence v1-v4.

Mỗi run phải tạo:

```text
evidence/runs/<run_id>/
|-- manifest.json
|-- samples.jsonl
`-- summary.json
```

Manifest tối thiểu có artifact version `5.0`, run/profile/version, seed,
scenario, commit, schema, config hash, clock domain, polling resolution,
injection point, claim và `source_provenance` gồm `source_state`, SHA-256 và danh
sách file được băm. Summary tách đầy đủ denominator/counter/KPI; aggregator tự
tính lại từ `samples.jsonl`, xác minh schedule/timeline và paired seed. Evidence
không chứa username, password, token, raw exception, filesystem path hoặc
endpoint nhạy cảm.

## 5.6. Rủi ro đối với độ giá trị

- **Internal validity:** baseline/hardened lệch config hoặc fault schedule sẽ làm
  sai attribution; dùng pinned commit, config hash và cùng fixture.
- **Construct validity:** app drop không đại diện packet loss; giữ
  `network_claim=none` trong mọi artifact/UI/report.
- **Measurement error:** polling làm schedule-to-API thành upper-bound; message
  bị drop không có latency nên percentile có điều kiện trên observed message.
  Phải báo coverage cạnh latency, cùng polling resolution/error và clock domain.
- **Statistical validity:** deterministic repeats chỉ chứng minh repeatability;
  CI theo run chỉ dùng seed độc lập.
- **External validity:** một laptop, một broker và node/simulator không đại diện
  fleet sản phẩm, mạng nhà cung cấp hoặc 5G thương mại.
- **Evidence staleness:** ảnh DHT11 cũ không được dùng cho schema v3/cockpit mới.

# 6. Thiết kế implementation mục tiêu

## 6.1. Atomic ingestion

Một outer transaction duy nhất sở hữu commit/rollback. Các DB mutation nhận
connection từ outer transaction và không tự commit. Rule engine snapshot toàn bộ
state RAM liên quan trước evaluate và restore khi transaction rollback. Chỉ
enqueue notification sau commit.

**Trạng thái:** `VERIFIED` trong phạm vi fault fixtures và full suite ở Mục 7;
implementation đã được commit tại `935c393e03a68465e538f624ff3405cd4560eb49`.

## 6.2. Session policy

| Session/message | Disposition mục tiêu |
|---|---|
| Current boot + seq tăng | nhận; gap chỉ ghi nhận, không tự gọi telemetry loss |
| Current boot + seq bằng | duplicate; không chạy rule lần hai |
| Current boot + seq lùi | out-of-order; không đổi device/rule |
| Boot đã supersede | stale; không đổi current device/rule |
| Unknown boot + offline status/LWT | stale; không promote |
| Unknown boot + telemetry/event/online status | promote boot mới; supersede boot cũ |

Sequence được đánh giá riêng theo stream; status/event không được mặc nhiên tính
thành mất telemetry.

**Trạng thái:** `VERIFIED` bằng regression session/sequence và probe old LWT ở
Mục 7.2.

## 6.3. Experiment cockpit

Dashboard mục tiêu tách Edge/node, measurement state, experiment state,
protocol/runtime metadata và KPI theo run. UI không aggregate chéo run, không
dùng màu làm dấu hiệu duy nhất, có bảng tương đương biểu đồ và gắn nhãn mô phỏng
cho mọi app-impairment KPI.

**Trạng thái:** browser smoke `VERIFIED` ở bốn viewport 320/360/768/1440 px.
Đây không phải tuyên bố tuân thủ WCAG; screen reader thủ công và zoom 400% vẫn
`NOT_VERIFIED`.

# 7. Kết quả

## 7.1. Phạm vi evidence cuối

Kết quả kỹ thuật được khóa theo artifact, command và test ID. Baseline có commit
pin; implementation hardened hiện ở commit
`935c393e03a68465e538f624ff3405cd4560eb49`. RQ1 bổ sung scoped source hash cho
bốn file xử lý lõi. RQ2 v5 bổ sung source hash cho allowlist 13 file được ghi
trong aggregate. Artifact đo trước commit vẫn giữ `worktree_uncommitted` như
metadata lịch sử; source bàn giao phải khớp scoped hash, không được dùng giá trị
baseline trong trường `commit`/`controls.commit` như commit của hardened.

RQ1 lặp cùng deterministic fixture 30 lần để kiểm tra repeatability; các lần lặp
không phải sample độc lập nên không tính inferential CI. RQ2 dùng 30 seed độc lập
cho mỗi profile và bootstrap percentile 95% CI theo run với 5.000 resample,
bootstrap seed 532. Mỗi run có 30 message được lập lịch.

## 7.2. Kết quả RQ1 - atomic/session-aware processing

Probe A/B thực tế bao phủ hai counterexample đã xác định trước:

| Probe case | Baseline pass/30 | Hardened pass/30 | Ground truth quan sát | Evidence | Trạng thái |
|---|---:|---:|---|---|---|
| Crash sau telemetry insert, restart và retry | 0/30 | 30/30 | Baseline giữ telemetry nhưng không có alert/history; retry bị coi là duplicate. Hardened rollback rồi retry tạo đúng 1 telemetry, 1 alert và 1 history. | `evidence/analysis/baseline-reliability.json`; `evidence/analysis/hardened-reliability.json` | `VERIFIED` |
| `boot-A online -> boot-B telemetry -> boot-A offline LWT` | 0/30 | 30/30 | Baseline bị rewind về boot A/offline. Hardened giữ boot B online và phân loại LWT cũ là `stale`. | cùng hai artifact trên | `VERIFIED` |

Các case rollback sau alert write, duplicate, out-of-order và session migration
có regression fixture riêng trong `tests/test_db.py` và
`tests/test_ingestion.py`; chúng nằm trong source regression suite cuối
`257 passed`.
Tuy nhiên,
chúng không có A/B artifact lặp 30 lần, nên báo cáo không gán số `30/30` cho các
case đó.

**Kết luận RQ1:** H1 được ủng hộ **một phần trong phạm vi evidence A/B đã chạy**:
working tree hardened loại bỏ cả hai counterexample deterministic mà baseline
tái hiện `30/30` lần thất bại. Kết quả chứng minh repeatability của fixture, không
phải ước lượng xác suất lỗi ngoài thực địa hay bảo đảm exactly-once end-to-end.

## 7.3. Kết quả RQ2 - app impairment trước publish

| Profile | Run hợp lệ | Message/run | Median scheduled observation (95% CI) | Median schedule→API p50 (95% CI), ms | Median schedule→API p95 (95% CI), ms | Median intentional drop (95% CI) | Attempted delivery phụ | Trạng thái |
|---|---:|---:|---|---|---|---|---|---|
| `lan-baseline` | 30 | 30 | 1,0 [1,0; 1,0] | 235,0 [234,0; 254,087] | 305,525 [289,8; 348,4] | 0,0 [0,0; 0,0] | 1,0 [1,0; 1,0] | `VERIFIED` |
| `remote-app-emulated` | 30 | 30 | 0,833333 [0,8; 0,866667] | 632,75 [539,0; 710,75] | 969,925 [885,575; 1.101,75] | 0,166667 [0,133333; 0,2] | 1,0 [1,0; 1,0] | `VERIFIED_WITH_BOUNDARY` |

Paired effect `remote-app-emulated - lan-baseline` trên 30 cặp seed:

| KPI paired | Median delta | Bootstrap 95% CI | Diễn giải hợp lệ |
|---|---:|---:|---|
| Scheduled observation ratio | -0,166667 | [-0,2; -0,133333] | app impairment làm giảm coverage của toàn lịch |
| Schedule→API p50 upper-bound | +363,0 ms | [+316,5; +472,25] | tăng upper-bound pipeline trên message được quan sát |
| Schedule→API p95 upper-bound | +634,275 ms | [+564,875; +760,025] | tăng upper-bound pipeline trên message được quan sát |
| Attempted delivery ratio | 0,0 | [0,0; 0,0] | mọi message đã attempt vẫn được API quan sát trong campaign |

Measurement boundary được khóa trong artifact v5:
`host_monotonic_same_process`, polling resolution `100 ms`,
`primary_latency_kind=schedule_to_api_polling_upper_bound`,
`diagnostic_latency_kind=publish_to_api_polling_upper_bound`,
`injection_point=before_mqtt_publish`, `network_claim=none` và
`measured_5g=false`.

Với `remote-app-emulated`, runner có logical drop cố ý **trước publish**. KPI
chính giữ các message này trong mẫu số scheduled, nên coverage `0,833333` phản
ánh ảnh hưởng trên toàn lịch. Attempted delivery `1,0` chỉ nói rằng mọi logical
message đã attempt đều được API quan sát; nó không được dùng để che coverage đã
giảm. P50/p95 không gán latency cho dropped message và vì vậy có điều kiện trên
message được quan sát. Paired delta định lượng treatment app-level đã cấu hình,
không phải packet loss, network latency, TCP behavior hay hiệu năng 5G.

## 7.4. Validation ledger

| Gate | Trạng thái | Bằng chứng |
|---|---|---|
| Provenance RQ1 | `VERIFIED_WITH_LIMITATION` | Baseline `commit_clean`, scoped SHA-256 `760429f9dceed614279cb6c937d111a66fb1cb63ca813ed615c7de1bbd24c280`; artifact hardened sinh với `worktree_uncommitted`, scoped SHA-256 `4bce098e63c53ab20bc7d9ab37162848504160b620c4a1a7ebba6ccfe7de5419`; source hiện ở commit `935c393e03a68465e538f624ff3405cd4560eb49`; phạm vi bốn file lõi |
| Provenance RQ2 v5 | `VERIFIED_WITH_LIMITATION` | Artifact sinh với `worktree_uncommitted`; allowlisted source SHA-256 `f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280` khớp commit `935c393e03a68465e538f624ff3405cd4560eb49`; file set nằm trong aggregate |
| One-command verification/final fingerprint | `VERIFIED` | `evidence/analysis/verification-latest.json`, artifact `1.3`, SHA-256 `9e82fe7fa3848812eb18fc0491f01fc250ac71032beb4e94c8d61f55e8eb0c69`; exact invocation `.\scripts\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware`; `commit_clean` tại `935c393e03a68465e538f624ff3405cd4560eb49`; portable verification-input SHA-256 `df8660c0e5ff35364bab282e4cd6f6fb9c684682921df8ebd383f7b1acbea413` |
| Source regression suite | `VERIFIED` | `257 passed` |
| RQ1 deterministic probe | `VERIFIED` | baseline artifact SHA-256 `02c854020b2d04a85b1b76cd8c8ff5d1b025154bd6e390dbb0d8a2a976e764a1`; hardened artifact SHA-256 `8396bb41cc01a9f6017d8554b8926b6943d9decb02f3cb010316407eec6bd0d4` |
| RQ2 v5, 30 matched seed/profile | `VERIFIED` | `evidence/analysis/rq2-v5-experiments.json`, SHA-256 `b2bb2e80edee83bd8a89531d079e4148ddb1442e7a9734cb2de353e4cddd4ffb` |
| JavaScript syntax/browser smoke | `VERIFIED_WITH_LIMITATION` | `evidence/ui/browser-smoke.json`, artifact `1.1`, SHA-256 `e03c63d8849751fd57742839c0da802499f5eb757abaf55140b174012c210a02`; 320/360/768/1440 px pass; UI source SHA-256 `ad606917fe23f33f373f536bd7741eed5b30979da8e44d3f7ff78b438f7747c9`; served asset `0719c500352f`; không suy ra WCAG conformance |
| Screen reader thủ công/zoom 400% | `NOT_VERIFIED` | cần kiểm tra thủ công riêng |
| Compose config/live | `VERIFIED` | resolved config pass; live `/healthz` và capability boundary pass trong one-command verification |
| Firmware `nodemcuv2` build-only | `VERIFIED_WITH_LIMITATION` | PlatformIO build thành công; RAM 43,0%, flash 29,5%; không dùng launcher/upload và không suy ra node vật lý đang chạy |
| Physical node demo | `NOT_VERIFIED` | tùy chọn; không dùng bằng chứng build để suy ra node vật lý đang chạy |
| Research evidence bundle | `VERIFIED` | `evidence/final/nt532-mqtt-mvp-evidence-v5.zip`, SHA-256 `def22cfdfbaf36acdd651bec0639ecda83e9f4cc20ea8cb69c00cc28aa60093f`; 189 file allowlist, aggregate tái tính khớp, 185 text file redaction pass; 60 `desktop.ini` bị loại |
| Software acceptance bundle | `VERIFIED` | `evidence/final/nt532-software-e2e-acceptance.zip`, SHA-256 `da9c4a8d21ab40cd5e99c793973d77c775b570305d3f57d9ab6a57b780e7fe3a`; đúng 14 payload allowlist, 10 text file redaction pass; tách riêng để không tự tham chiếu hash |
| Software E2E qua broker thật | `VERIFIED` | `plans/reports/260814-073149-software-e2e-acceptance/`: normal, motion artifact, low SpO2 và ACK đều pass; focused `49/49`, full regression `235/235`; không upload firmware |
| DOCX render/visual/a11y QA | `VERIFIED_WITH_LIMITATION` | Word render đủ 32/32 trang; đã xem toàn bộ từng trang và contact sheet, không thấy clipping/overlap/glyph lỗi; audit tự động high/medium/low = `0/0/0`; bìa A4 đã áp dụng theo báo cáo tham chiếu do người dùng cung cấp, không được gọi là mẫu chính thức của trường |

# 8. Kịch bản demo nghiệm thu

Luồng demo chi tiết và câu lệnh nằm tại [docs/demo-nt532.md](../docs/demo-nt532.md).
Thứ tự tối thiểu:

1. `normal`: schema/topic/session và không alert;
2. `motion_artifact`: HR/SpO2 invalid/null, quality-aware suppression;
3. `low_spo2`: dữ liệu hợp lệ qua hold time, đúng một logical alert và ACK;
4. fault matrix: crash/retry, duplicate, out-of-order và old LWT;
5. dry-run hai profile matched;
6. measured experiment, reconciliation và evidence export;
7. secret scan và phát biểu ba claim boundary.

Không trình chiếu KPI khi run chỉ ở trạng thái `planned`, `partial` hoặc có ít
hơn minimum sample.

Lượt nghiệm thu phần mềm ngày 14/08/2026 đã chạy ba scenario qua Mosquitto và
Edge live bằng đúng namespace ACL `health-node-01`. Mỗi lượt có 20 telemetry,
seq `1..20` và boot ID riêng. Normal không tạo alert; motion artifact làm
HR/SpO2 thành `null` với cờ invalid và fault `ppg_motion_artifact`; low SpO2
hợp lệ tạo đúng một logical alert `demo_low_spo2`. ACK lặp hai lần vẫn giữ cùng
alert ở trạng thái `acknowledged`. Snapshot, exact command/seed và browser
evidence nằm trong biên bản
`plans/reports/260814-073149-software-e2e-acceptance/`.

# 9. Thảo luận và giới hạn tuyên bố

Các câu sau được evidence hiện có hỗ trợ trong đúng phạm vi:

- “Trong hai deterministic A/B probe đã chạy, hardened đạt 30/30 còn baseline
  đạt 0/30”;
- “Trên simulator cùng host, app impairment làm median scheduled observation
  ratio giảm 0,166667 và làm p50/p95 schedule-to-API upper-bound tăng
  363,0/634,275 ms theo paired seed”;
- “Attempted delivery ratio có median 1,0 ở cả hai profile, nhưng đây là KPI phụ
  và không thay thế coverage của toàn lịch”;
- “Kết quả là đóng góp cấp đồ án môn học về reliability/observability.”

Các câu không được dùng:

- “Hệ thống theo dõi/chẩn đoán bệnh nhân chính xác”;
- “Đã đo trên mạng 5G” hoặc “5G giảm latency”;
- “MQTT đảm bảo exactly-once toàn hệ thống”;
- “Profile mô phỏng tái tạo packet loss/TCP/nhà mạng”;
- “Đề xuất giao thức MQTT mới”;
- “Tuân thủ WCAG 2.2 AA” khi chưa audit tự động và thủ công đầy đủ.

# 10. Lộ trình phát triển sản phẩm không thêm thiết bị

## 10.1. Hoàn tất MVP môn học

- đã đóng gate atomic/session và source regression;
- đã chạy campaign v5 với 30 cặp seed, khóa aggregate/evidence bằng SHA-256;
- đã hoàn thiện experiment cockpit; browser artifact và one-command verification
  đã được khóa bằng source fingerprint và SHA-256;
- đã nghiệm thu software E2E qua broker thật cho normal, motion artifact,
  low SpO2 và ACK idempotent; biên bản giữ rõ giới hạn không upload phần cứng;
- đã sinh/render/QA DOCX, điền đủ thông tin hành chính Nhóm 3 và áp dụng bìa A4
  theo báo cáo tham chiếu do người dùng cung cấp.

## 10.2. Hardening sản phẩm bằng phần mềm hiện có

- persistent event outbox và idempotency key cho logical delivery;
- runtime broker configuration an toàn, không rebuild firmware khi IP đổi;
- migration versioned và normalized telemetry adapter;
- auth/RBAC cho dashboard nếu mở khỏi loopback;
- backup/retention, audit log, health metrics và alert delivery observability;
- per-device credential/provisioning policy, TLS/CA hoặc VPN/private overlay;
- WoT Thing Description và capability matrix có evidence, không claim compliance.

## 10.3. Validation backhaul 5G tương lai

Không mua thêm modem, board hay sensor. Chỉ thực hiện nếu có endpoint đầu xa
được cấp/miễn phí và điện thoại/hotspot hiện có cung cấp tuyến 5G:

1. đặt broker/edge tại đầu xa, không public plaintext TCP 1883;
2. ghi endpoint redacted, route/network mode, nhà mạng, thời gian và topology;
3. bảo vệ transport bằng TLS/CA đã kiểm chứng hoặc VPN/private overlay;
4. dùng cùng payload, publish rate, duration và seed cho 5G path và baseline phù
   hợp;
5. chọn measurement point/clock method; nếu không đồng bộ, chỉ báo RTT hoặc
   latency cùng clock domain;
6. báo loss/delay theo phương pháp đo thực, không tái sử dụng
   `intentionally_dropped` của app impairment;
7. giữ kết quả tách khỏi RQ/kết luận MVP hiện tại.

# 11. Kết luận

Đồ án đã được cải tiến thành testbed đánh giá độ tin cậy xử lý bản tin MQTT ở
edge mà không mua thêm thiết bị. Hai counterexample deterministic cho atomic
alert và old LWT đều tái hiện thất bại trên baseline `0/30` và đạt trên working
tree hardened `30/30`; source regression suite cuối đạt `257 passed`. RQ2 v5 hoàn
thành 30 cặp seed. App impairment làm median scheduled observation ratio giảm
`0,166667`, đồng thời làm p50/p95 schedule-to-API polling upper-bound tăng
`363,0/634,275 ms` theo paired seed. Attempted delivery vẫn là `1,0` ở cả hai
profile nhưng chỉ là KPI phụ; không thể dùng nó để kết luận toàn bộ lịch không
mất message. Đây là kết quả pipeline ứng dụng cùng host, không phải network
latency.

Kết quả kỹ thuật ủng hộ giá trị của transaction boundary, session/sequence
policy, evidence runner và experiment cockpit trong phạm vi testbed. Nó không
chứng minh exactly-once end-to-end, độ tin cậy ngoài thực địa, độ chính xác y tế
hay hiệu năng 5G. Bản báo cáo mang trạng thái
`READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS`: thông tin hành chính và mẫu
bìa tham chiếu đã được áp dụng, còn rubric/learning outcome chính thức chưa được
cung cấp nên không được suy diễn thành đối sánh môn học đã được giảng viên xác
nhận.

# Tài liệu tham khảo

1. OASIS, [MQTT Version 3.1.1 - OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html), 2014.
2. 3GPP, [5G System Overview](https://www.3gpp.org/technologies/5g-system-overview), truy cập ngày 14/08/2026.
3. IETF, [RFC 9341 - Alternate-Marking Method](https://www.rfc-editor.org/rfc/rfc9341.html), 2022.
4. Dự án, [Hợp đồng dữ liệu MQTT](../docs/data-contract.md).
5. Dự án, [Kiến trúc và phạm vi](../docs/architecture-and-scope.md).
6. Dự án, [Chế độ mạng và bảo mật](../docs/network-and-security.md).
7. Dự án, [Checklist kiểm thử MVP](../docs/test-checklist.md).
8. Dự án, [Kế hoạch NT532 IoT Protocol MVP](../plans/260814-nt532-iot-protocol-mvp/plan.md).

# Phụ lục A - Lệnh tái lập tối thiểu

```powershell
.\scripts\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware
python -m pytest -q
python -m simulator --device-id health-node-01 --scenario normal --count 20 --seed 101
python -m simulator --device-id health-node-01 --scenario motion_artifact --count 20 --seed 102
python -m simulator --device-id health-node-01 --scenario low_spo2 --count 20 --seed 103
python -m simulator.experiment --profile lan-baseline --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
python -m simulator.experiment --profile remote-app-emulated --scenario normal --count 30 --seed 20260814 --output-dir evidence/runs --dry-run
python -m simulator.aggregate --input-dir evidence/runs --output evidence/analysis/rq2-v5-experiments.json --run-prefix nt532-rq2-v5- --min-seeds 30
```

# Phụ lục B - Traceability matrix

| Requirement/RQ | Source | Test/command | Raw evidence | Figure/table | Trạng thái |
|---|---|---|---|---|---|
| RQ1 atomic rollback/retry | `edge/service.py`, `edge/db.py`, `edge/rules.py` | `tests/test_ingestion.py::test_fault_after_telemetry_insert_rolls_back_and_retry_opens_one_alert`; `tests/test_ingestion.py::test_fault_after_alert_write_restores_rule_state_and_notifies_only_after_commit`; `tests/test_db.py::test_outer_transaction_rolls_back_device_session_and_telemetry` | `evidence/analysis/baseline-reliability.json`; `evidence/analysis/hardened-reliability.json` | Bảng 7.2 | `VERIFIED` |
| RQ1 session/old LWT | `edge/db.py::Database.admit_session`, `edge/service.py` | `tests/test_ingestion.py::test_old_lwt_after_new_boot_cannot_rewind_current_session`; `tests/test_ingestion.py::test_sequence_is_classified_independently_per_stream` | hai artifact RQ1 trên | Bảng 7.2 | `VERIFIED` |
| RQ2 deterministic schedule | `simulator/network_profiles.py`, `simulator/experiment.py` | `tests/test_network_profiles.py::test_remote_app_schedule_is_deterministic_and_truthfully_labeled`; experiment prefix `nt532-rq2-v5-` | `evidence/runs/nt532-rq2-v5-*` | Bảng 7.3 | `VERIFIED` |
| RQ2 scheduled/attempted denominator | `simulator/experiment.py` | `tests/test_experiment_runner.py::test_summary_uses_scheduled_and_attempted_denominators_separately` | v5 summaries/samples | Bảng 7.3 | `VERIFIED` |
| RQ2 aggregate/paired KPI/clock | `simulator/aggregate.py` | `tests/test_experiment_aggregate.py::test_aggregate_reconciles_30_matched_seeds_and_reports_paired_treatment_metrics`; tamper/latency-boundary tests | `evidence/analysis/rq2-v5-experiments.json` | Bảng 7.3 | `VERIFIED` |
| UI responsive/a11y smoke | `edge/static/index.html`, `edge/static/styles.css`, `edge/static/app.js` | `scripts/dashboard-browser-smoke.js`; dashboard static tests | `evidence/ui/browser-smoke.json` và bốn PNG có SHA-256 đối chiếu | Ledger | `VERIFIED_WITH_LIMITATION` |
| Software E2E scenarios + ACK | `simulator/mqtt_simulator.py`, `edge/service.py`, `edge/app.py` | ba exact command/seed trong Phụ lục A; ACK lặp trên cùng alert | `plans/reports/260814-073149-software-e2e-acceptance/scenario-acceptance.json` và `scenario-observations.json` | Mục 8/Ledger | `VERIFIED` |
| Research evidence/redaction | `simulator/experiment.py`, `simulator/aggregate.py` | allowlist + duplicate-key/secret/path scan trong `scripts/package_final_evidence.py` | `evidence/final/nt532-mqtt-mvp-evidence-v5.zip`, SHA-256 `def22cfdfbaf36acdd651bec0639ecda83e9f4cc20ea8cb69c00cc28aa60093f` | Ledger | `VERIFIED` |
| Software acceptance packaging | `scripts/package_software_acceptance.py` | exact 14-file allowlist, API/browser/dry-run reconciliation, duplicate-key/secret/path/self-hash scan | `evidence/final/nt532-software-e2e-acceptance.zip`, SHA-256 `da9c4a8d21ab40cd5e99c793973d77c775b570305d3f57d9ab6a57b780e7fe3a` | Mục 8/Ledger | `VERIFIED` |
| 5G claim boundary | `docs/network-and-security.md` | review + aggregate boundary validation | `network_claim=none`; `measured_5g=false` | Mục 2.3/10.3 | `VERIFIED` |

# Phụ lục C - Checklist trước khi đổi trạng thái nộp bài

- [x] Điền trường/khoa, GV, nhóm, họ tên-MSSV, lớp, học kỳ/năm học và ngày nộp.
- [x] Áp dụng mẫu bìa tham chiếu do người dùng cung cấp và giữ kiểu trích dẫn
  đánh số; page limit/rubric chính thức chưa được cung cấp và được nêu rõ như
  một giới hạn thay vì tự suy đoán.
- [x] Giữ đúng `worktree_uncommitted` như provenance lịch sử của artifact đo;
  khóa source hiện tại tại commit `935c393e03a68465e538f624ff3405cd4560eb49`
  và đối chiếu bằng scoped SHA-256.
- [x] Điền RQ1 và aggregate RQ2 v5 bằng kết quả có căn cứ; giữ nguyên
  `NOT_VERIFIED` cho node vật lý và manual a11y.
- [x] Cập nhật traceability matrix và bảng kết quả từ evidence mới.
- [x] Chạy software E2E qua broker thật cho normal, motion artifact, low SpO2
  và ACK; lưu exact command/seed, source provenance và snapshot API redacted.
- [x] Sinh DOCX, render đủ toàn bộ trang và kiểm clipping/overlap/glyph/bảng/TOC;
  audit accessibility tự động không có finding high/medium/low.
- [x] Chạy allowlist/redaction scan trên final evidence và khóa bundle hash;
  DOCX/render được kiểm tra riêng ở gate kế tiếp.
- [x] Đổi trạng thái sang `READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS` sau
  khi hoàn tất thông tin hành chính, render và QA cuối.
