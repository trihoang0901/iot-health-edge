---
title: "NT532 IoT Protocol MQTT reliability MVP"
status: completed
deadline: "2026-08-15T23:59:00+07:00"
track: "IoT Protocol"
completed_at: "2026-08-14T04:15:56+07:00"
---

# Kế hoạch MVP NT532: đánh giá độ tin cậy MQTT-edge

## 1. Kết quả phải bàn giao

1. Source chạy được trong `iot-health-edge`, giữ tương thích ba topic MQTT và
   telemetry v1/v2/v3 hiện hữu.
2. Backend chống mất alert khi crash/retry và chống old LWT/boot cũ ghi đè
   session mới.
3. CLI thí nghiệm một node tạo profile `lan-baseline` và
   `remote-app-emulated`, xuất bộ bằng chứng redacted gồm manifest, từng sample
   và summary KPI. Giao diện mô tả profile thứ hai là hướng kiểm thử cho 5G,
   không phải phép đo 5G.
4. Dashboard tiếng Việt dạng IoT Protocol experiment cockpit, hiển thị độc lập
   Edge/node, protocol/runtime, experiment KPI và cảnh báo.
5. Hướng dẫn demo tái lập, script kiểm tra một lệnh và báo cáo đồ án DOCX đã
   render/kiểm tra hình thức.

Tên đề tài dùng trong MVP:

> Đánh giá độ tin cậy xử lý bản tin MQTT trong hệ thống IoT edge phi lâm sàng
> dưới lỗi cảm biến và lỗi ở tầng ứng dụng

5G là hướng mở rộng sản phẩm/validation sau MVP, không nằm trong tên hoặc kết
luận thực nghiệm hiện tại. Báo cáo dành một mục riêng mô tả cách nâng cấp sang
remote broker qua backhaul 5G khi có endpoint và route evidence.

## 2. Acceptance criteria

- Fault injection giữa telemetry insert và rule evaluation không để lại
  telemetry/alert dở dang; retry tạo đúng một telemetry và một logical alert.
- Chuỗi `boot-A online -> boot-B telemetry -> boot-A offline LWT` vẫn giữ
  `boot-B` online; telemetry/status out-of-order không rewind state hoặc rule.
- Cùng seed/profile/count tạo cùng impairment schedule. Evidence không chứa
  username, password, token hoặc raw exception từ transport.
- Evidence tách từng mốc `scheduled`, `intentionally_dropped`,
  `publish_attempted`, `published`, `ingested` và `api_observed`, correlate bằng
  `(device_id, boot_id, stream, seq)`. Summary ghi denominator, clock domain, monotonic
  start/end, polling resolution/error và injection point. Latency quan sát qua
  polling là upper-bound, không phải one-way network latency. Run dry-run phải
  ghi rõ `planned`, không giả làm measured.
- Profile `remote-app-emulated` luôn mang `profile_kind=app_impairment` và
  `network_claim=none`; planned drop không được gọi là packet loss đo được. Chỉ
  được gọi measured 5G khi có remote endpoint, route/network mode, thời gian và
  evidence.
- Mọi artifact mang cùng invariant: `run_id`, `profile_name/version`, seed,
  scenario, commit/schema/config hash, trạng thái
  `planned|running|completed|partial|failed`, sample count và reconciliation
  identity `(device_id, boot_id, stream, seq)`. `attempt_count` là số lần gửi
  vật lý; logical message count được dedupe theo identity này. Dashboard không
  được tổng hợp chéo run.
- KPI chính định nghĩa theo lịch phát: `scheduled_observation_ratio =
  unique_api_observed / scheduled`; vì vậy intentional pre-publish drop vẫn nằm
  trong mẫu số. `attempted_delivery_ratio = observed_attempted /
  unique_logical_publish_attempted` chỉ là KPI chẩn đoán phụ; `delivery_ratio`
  là alias tương thích. Retry chỉ tăng `attempt_count`, không tăng mẫu số
  logical. Duplicate/rejected/stale/out-of-order là disposition riêng.
  Độ trễ chính là `schedule_to_api_upper_bound`, tính từ slot monotonic tuyệt đối
  trước app impairment đến lần API poll quan sát mẫu; `publish_to_api` chỉ là
  chẩn đoán phụ. Mỗi mẫu ghi `scheduled_offset_ms` và `schedule_slip_ms`.
  Percentile chỉ báo cho run completed có tối thiểu 20 observed message; nếu ít
  hơn hiện “chưa đủ mẫu”. Mọi value dùng milliseconds và ghi polling upper-bound
  error.
- Dashboard không trộn trạng thái Edge với node; đổi device/run nhanh không
  render response cũ; chart dùng thời gian, công bố coverage/truncation và có
  bảng tương đương cho screen reader.
- Dashboard reflow tại 320 CSS px, keyboard/focus rõ, reduced motion và forced
  colors có fallback; không tải runtime asset từ CDN.
- URL giữ `device/run/window/metric/profile`; back/forward khôi phục state và
  GET/deep-link không tạo run. Runtime/API chỉ trả allowlist fields, không trả
  raw exception, credentials, filesystem path hay endpoint nhạy cảm.
- UI có measurement state (`waiting|measuring|valid|noisy|fault|stale`) và
  experiment state; mọi KPI/chart/export của app impairment đều gắn nhãn mô
  phỏng. Giá trị `configured` và MQTT metadata `observed` không được trộn.
- Chart dùng UTC trong API, hiển thị timezone cục bộ có nhãn; ngắt đoạn khi gap
  vượt 1,5 lần interval; phân biệt missing/invalid, báo `valid/total`, requested
  window, coverage window, total/returned/truncated/downsampling. Bảng a11y phải
  khớp chart về thời gian, đơn vị và giá trị; min/max chỉ tính mẫu hợp lệ.
- Browser E2E kiểm tra 320/360/768/1440 px, zoom 400%, text 200%, keyboard,
  long-content, loading/empty/error/offline, race, contrast/no-color-only, 44 px
  usability target, ACK dialog focus/busy/409 và live-region chỉ announce state
  transition. Axe là gate phụ; manual screen-reader/focus/forced-colors bắt buộc
  và gate là 0 vi phạm WCAG 2.2 A/AA áp dụng được chưa xử lý. Chỉ finding được
  chứng minh là false-positive hoặc tiêu chí not-applicable mới được loại trừ.
- Regression P0 và full pytest bắt buộc pass. JavaScript syntax và kiểm tra
  report bắt buộc pass nếu các artifact đó thay đổi. Docker live, firmware
  build-only và physical demo mới được phép ghi `NOT_VERIFIED`, kèm lý do và
  evidence riêng; không dùng `NOT_VERIFIED` để bỏ qua lỗi source.
- Báo cáo Word có bìa placeholder cho thông tin chưa được cung cấp, RQ, nền
  MQTT/5G, kiến trúc, implementation, thí nghiệm, kết quả, giới hạn, roadmap,
  tài liệu tham khảo và phụ lục lệnh demo.

## 3. Ngoài phạm vi

- Không mua, thay hoặc gắn thêm cảm biến/modem/board.
- Không upload firmware hay chạy launcher có thể upload nếu không cần thiết.
- Không deploy broker công khai, không mở dashboard/MQTT ra Internet.
- Không tuyên bố theo dõi bệnh nhân, chẩn đoán, độ chính xác y tế, nhiệt độ cơ
  thể, phát hiện ngã đã hiệu chuẩn hoặc kênh cảnh báo khẩn cấp.
- Không tuyên bố giao thức MQTT mới, MQTT exactly-once, benchmark nhà mạng hoặc
  5G thật khi chưa có bằng chứng tuyến.
- MVP không cần multi-tenant, RBAC, fleet provisioning hoặc 50 node thật.

## 4. Ràng buộc không thương lượng

- Deadline: 23:59 ngày 15/08/2026, múi giờ Asia/Saigon.
- Chi phí phần cứng bổ sung bằng 0; dùng node hiện có và simulator.
- MQTT 3.1.1, topic namespace và production schema hiện tại không bị phá vỡ.
- Credentials chỉ đọc từ môi trường/prompt, không ghi vào Git/evidence/report.
- API/dashboard tiếp tục loopback mặc định và ranh giới phi lâm sàng.
- App-side impairment chỉ là test profile tái lập, không phải network emulator
  cấp kernel và không đại diện cho mọi mạng 5G.

## 4.1. Câu hỏi nghiên cứu và thiết kế đánh giá

- **RQ1:** So với baseline hiện tại, xử lý atomic + session-aware thay đổi tỷ lệ
  logical alert đúng và tỷ lệ state rewind thế nào dưới crash/retry, duplicate,
  out-of-order và old LWT deterministic?
- **H1:** Thiết kế cải tiến tạo đúng một logical alert và không rewind current
  session trong toàn bộ fault matrix; baseline có ít nhất hai counterexample tái
  hiện được bằng regression fixture.
- **RQ2 phụ:** App impairment trước publish ảnh hưởng thế nào đến tỷ lệ quan sát
  trên toàn bộ lịch phát và schedule-to-API polling upper-bound latency của
  pipeline simulator? Tỷ lệ quan sát trên các bản tin đã attempt và
  publish-to-API latency chỉ là chỉ số phụ. Kết quả chỉ mô tả pipeline ứng dụng,
  không suy ra TCP, packet loss hoặc 5G.

Factor RQ1 là implementation `baseline|hardened`; baseline được pin ở commit
`7030e4b30300dec65646e3091356ca00d9eaa8f5` cùng config hash và được chạy trong
Git worktree đọc riêng, không checkout đè workspace đã harden. Giữ nguyên
payload trace, threshold, hold/hysteresis và fault schedule. Ground truth định
nghĩa theo mỗi fixture: expected current boot, expected unique
telemetry/alert/history và expected disposition. Mỗi deterministic case chạy
lặp 30 lần với database mới chỉ để chứng minh repeatability; báo số pass/30 và
không gán Wilson CI cho các lần lặp không độc lập. Nếu muốn CI suy diễn, tạo
trước quần thể seed/schedule độc lập và ghi rõ sampling unit. RQ2 dùng 30 seed
độc lập cho mỗi profile; báo median của run-level delivery ratio và p50/p95
message latency kèm bootstrap 95% CI theo run nếu đủ mẫu. Không báo p99 nếu tổng
số observation phù hợp dưới 1.000.

Traceability matrix trong report ánh xạ từng RQ/acceptance sang source, test,
raw evidence và figure/table. Artifact RQ2 dùng schema `5.0`, UUID4 cho measured
boot và `runner_source_fingerprint` trên allowlist source; fingerprint này không
được diễn giải là build fingerprint của container Edge đang chạy. Course fit
vẫn là giả định hợp lý theo danh sách
topic người dùng cung cấp; phải ghi “IoT Protocol track - user-provided brief”
cho đến khi có rubric/learning outcome chính thức.

## 5. Touchpoints và pha triển khai

### Pha A - Correctness/session

- `edge/db.py`: outer transaction duy nhất sở hữu commit/rollback; bảng/session
  policy; DB mutation nhận connection tùy chọn và không tự commit khi được
  truyền connection.
- `edge/rules.py`: rule evaluation chạy trong transaction của ingestion; trước
  evaluate phải snapshot bốn map state trong RAM và restore toàn bộ nếu outer
  transaction rollback.
- `edge/service.py`: atomic telemetry/event pipeline, disposition metrics.
- `edge/mqtt_client.py`: chuyển QoS/retain/dup/payload metadata vào ingestion.
- `tests/test_db.py`, `tests/test_ingestion.py`, `tests/test_rules.py`,
  `tests/test_mqtt_client.py`: regression đúng blast radius.

Decision table session, tính sequence riêng cho từng topic/stream:

| Session/message | Disposition |
|---|---|
| Current boot + seq tăng | Nhận; gap chỉ được ghi nhận, không tự gọi là telemetry loss |
| Current boot + seq bằng | Duplicate; không chạy rule lần hai |
| Current boot + seq lùi | Out-of-order; không đổi device/rule |
| Boot đã supersede | Stale; không đổi current device/rule |
| Unknown boot + offline status/LWT | Stale; không promote |
| Unknown boot + telemetry/event/online status | Promote boot mới, supersede boot cũ |

Fault tests bắt buộc đặt exception sau insert, giữa alert write và trước commit;
sau đó dựng lại service như restart rồi retry. Kết quả phải đúng một telemetry,
một logical alert và một history. Notification chỉ enqueue sau commit và lỗi
notification không rollback ingestion.

### Pha B - Protocol experiment/evidence

- `simulator/network_profiles.py`: schedule deterministic.
- `simulator/experiment.py`: runner MQTT + API observation + redacted artifacts.
- `edge/experiments.py`: read-only evidence registry.
- `edge/app.py`, `edge/config.py`, `pyproject.toml`, `.env.example`, Compose:
  capabilities/runtime/experiment APIs và path evidence.
- Test mới cho determinism, KPI, redaction, path safety và API.

**Gate:** chỉ bắt đầu Pha B sau khi regression P0 + full pytest của Pha A pass.
Evidence JSON và hướng dẫn CLI là deliverable protocol tối thiểu bắt buộc.

### Pha C - Dashboard/demo

- `edge/static/index.html`, `styles.css`, `app.js`: cockpit công nghiệp gọn,
  state/KPI/protocol/evidence có nguồn dữ liệu thật.
- `tests/test_dashboard_static.py`: semantics, race, no-CDN, responsive/a11y.
- `scripts/VERIFY-MVP.ps1`, `docs/demo-nt532.md`, README và network/security docs.

**Gate:** chỉ bắt đầu registry/API/cockpit sau khi Pha A pass và runner Pha B đã
tạo được evidence deterministic. Nếu gate lỗi, sửa Pha A/B trước; không dựng
card KPI giả hoặc thu hẹp acceptance để tiếp tục.

### Pha D - Báo cáo và audit

- Markdown nội dung nguồn và DOCX tại `deliverables/`.
- Render DOCX thành PNG, kiểm tra từng trang, sửa đến khi không còn clipping,
  overlap, bảng vỡ hoặc lỗi glyph.
- Chạy full validation và audit từng requirement trước khi tuyên bố hoàn thành.

**Gate:** báo cáo chỉ ghi kết quả từ validation/evidence đã sinh; mọi phần chưa
đo phải mang trạng thái planned/NOT_VERIFIED rõ ràng.

Thông tin bìa chưa được cung cấp sẽ dùng placeholder nổi bật và deliverable ghi
`DRAFT_NOT_SUBMISSION_READY`; báo cáo chỉ đổi thành submission-ready khi đã có
trường/khoa, GV, nhóm, họ tên-MSSV, lớp, học kỳ/năm học và yêu cầu citation/mẫu
bìa. Placeholder không được tính là hoàn thành thông tin hành chính.

## 6. Rủi ro và phương án

- Docker daemon không sẵn sàng: runner vẫn có dry-run deterministic; không gọi
  đó là measured. Integration live chỉ ghi kết quả khi broker/edge thật chạy.
- Thiếu thông tin sinh viên/GV/mẫu trường: dùng placeholder rõ ràng, không suy
  đoán từ metadata DOCX cũ.
- Không có đồng bộ clock trên node vật lý: chỉ đo ingest-to-decision trong edge
  hoặc RTT request/response; không claim publish-to-API hay one-way
  sensor-to-edge. Chỉ simulator chạy cùng laptop mới dùng monotonic
  emit/publish-to-API upper-bound.
- Profile app-side không tác động TCP packet-level: báo đúng injection point và
  để kernel/remote 5G validation ở roadmap.

## 7. Biên bản hoàn thành kỹ thuật

Hoàn thành lúc `2026-08-14T04:15:56+07:00`, trước deadline. Phạm vi kỹ thuật của
kế hoạch đạt các gate sau:

- source regression cuối: `258 passed`; JavaScript syntax, Compose resolved config,
  Docker live health/capability và firmware `nodemcuv2` build-only đều pass;
- RQ1 deterministic repeatability: baseline `0/30`, hardened `30/30` cho cả
  atomic alert sau crash/retry và old LWT không rewind session;
- RQ2 artifact `5.0`: đúng 30 cặp seed, 60 run completed, aggregate strict
  reconciliation pass; evidence chính thức dùng prefix `nt532-rq2-v5-`;
- browser smoke pass ở 320/360/768/1440 px và được ràng buộc với served asset;
- research bundle chứa 189 file allowlist, SHA-256
  `52aa1960e98209560a61fe9c835a98d47e46f95a5e8780bc365a6a993e083daa`;
- software acceptance bundle chứa đúng 14 payload allowlist, SHA-256
  `b6dc2e9016d97fecdb8394b653fc0dbee0eba2cd1073b099f3cf8dceff984542`;
- báo cáo Word render đủ 32 trang; visual inspection từng trang và a11y audit tự động
  high/medium/low = `0/0/0`.

Hai giới hạn không làm mở lại kế hoạch kỹ thuật: node vật lý chưa chạy lại trong
batch cuối; screen reader thủ công và zoom 400% chưa được kiểm chứng. Ngày
14/08/2026, người dùng đã cung cấp trường/khoa, giảng viên, nhóm, họ tên-MSSV,
lớp, học kỳ/năm học, ngày nộp và một báo cáo tham chiếu cho bố cục bìa. Báo cáo
được đổi sang `READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS`; rubric/page
limit chính thức chưa được cung cấp nên vẫn được nêu rõ, không tự suy đoán.
