# Completion report - NT532 MQTT reliability MVP

**Thời điểm:** 14/08/2026, Asia/Saigon

**Kết quả:** hoàn thành kỹ thuật trước deadline 23:59 15/08/2026
**Chi phí phần cứng bổ sung:** 0

## Kết quả bàn giao

- Backend xử lý telemetry/rule/alert trong một transaction, restore state khi
  rollback và chỉ notify sau commit.
- Session/sequence được lưu bền theo boot và stream; duplicate, out-of-order,
  stale boot và old Last Will không rewind current device.
- Experiment runner/validator artifact v5 ghi timeline đo trực tiếp, tách
  scheduled coverage khỏi attempted delivery và fail-closed khi evidence lệch.
- Dashboard tiếng Việt tách Edge/node/run, công bố clock/measurement boundary,
  coverage/truncation và không gán app impairment thành packet loss hay 5G.
- Báo cáo, demo runbook, one-command verification và evidence bundle đã được
  tạo; không mua hoặc gắn thêm thiết bị.

## Kết quả kiểm chứng

| Gate | Kết quả |
|---|---|
| Full pytest | 257 passed |
| RQ1 baseline -> hardened | 0/30 -> 30/30 ở cả hai counterexample |
| RQ2 | 60/60 run completed, 30 matched seed/profile |
| LAN median coverage; p50/p95 | 1,0; 235,0/305,525 ms |
| Remote app impairment | 0,833333; 632,75/969,925 ms |
| Browser | 4 viewport pass, source/served-asset bound |
| Compose/Docker live | pass |
| Firmware | build-only pass; không upload |
| DOCX | 32 trang; đã xem từng trang; a11y high/medium/low = 0/0/0 |

Paired median remote trừ LAN: scheduled coverage `-0,166667`, p50
`+363,0 ms`, p95 `+634,275 ms`. Attempted delivery vẫn `1,0` ở cả hai profile
và chỉ là KPI phụ. Đây là app impairment trước MQTT publish trên cùng host,
`network_claim=none`, `measured_5g=false`.

## Artifact chính

- Báo cáo nguồn: `deliverables/BAO-CAO-NT532-MQTT-MVP.md`
- Báo cáo Word: `deliverables/BAO-CAO-NT532-MQTT-MVP.docx`
- Demo: `docs/demo-nt532.md`
- Aggregate: `evidence/analysis/rq2-v5-experiments.json`
- Verification: `evidence/analysis/verification-latest.json`
- Research bundle: `evidence/final/nt532-mqtt-mvp-evidence-v5.zip`
- Software acceptance bundle: `evidence/final/nt532-software-e2e-acceptance.zip`

Research bundle SHA-256:
`def22cfdfbaf36acdd651bec0639ecda83e9f4cc20ea8cb69c00cc28aa60093f`.
Software acceptance bundle SHA-256:
`da9c4a8d21ab40cd5e99c793973d77c775b570305d3f57d9ab6a57b780e7fe3a`.

## Giới hạn còn lại

- Không claim đo packet loss, TCP behavior, carrier network hoặc 5G thật.
- Không claim chẩn đoán, độ chính xác y tế hoặc runtime node vật lý mới.
- Screen reader thủ công và zoom 400% chưa kiểm chứng.
- Thông tin hành chính và bìa đã hoàn thiện theo báo cáo tham chiếu do người
  dùng cung cấp. Rubric/page limit chính thức chưa được cung cấp; giới hạn này
  được công khai trong báo cáo và không bị suy diễn thành đối sánh đã xác nhận.
