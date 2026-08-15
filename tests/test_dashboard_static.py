from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import json
import shutil
import subprocess

import pytest


STATIC_DIR = Path(__file__).resolve().parents[1] / "edge" / "static"


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.metric_cards = 0
        self.chart_metrics: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if element_id := attributes.get("id"):
            self.ids.append(element_id)
        if tag == "article" and "metric-card" in (attributes.get("class") or "").split():
            self.metric_cards += 1
        if tag == "option" and (value := attributes.get("value")):
            self.chart_metrics.append(value)


def parse_dashboard() -> tuple[DashboardParser, str]:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    parser = DashboardParser()
    parser.feed(html)
    return parser, html


def test_dashboard_exposes_three_non_clinical_measurement_cards():
    parser, html = parse_dashboard()

    assert parser.metric_cards == 3
    assert len(parser.ids) == len(set(parser.ids))
    assert {"heart-rate", "spo2", "wrist-temp"} <= set(parser.ids)
    assert "Nhiệt độ bề mặt cổ tay" in html
    assert "không phải nhiệt độ cơ thể/lõi" in html
    assert "Prototype phi lâm sàng" in html
    assert "DHT11" not in html
    assert "Độ ẩm môi trường" not in html


def test_dashboard_charts_only_v3_wearable_temperature():
    parser, _html = parse_dashboard()
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "wrist_surface_temp_c" in parser.chart_metrics
    assert "ambient_temp_c" not in parser.chart_metrics
    assert "humidity_pct" not in parser.chart_metrics
    assert 'group: "wearable"' in script
    assert "latest.wearable || {}" in script
    assert "wearable.wrist_surface_temp_c" in script
    assert '"health.telemetry.v3", "health.telemetry.v4"' in script
    assert "skin_temp_c" not in script


def test_dashboard_withholds_unstable_raw_hr_and_shows_confirmation_state():
    fetch_implementation = r"""
async (url) => {
  if (url.includes("/devices")) {
    return { ok: true, json: async () => ({ data: [{ device_id: "node-v4", online: true }] }) };
  }
  if (url.includes("/overview")) {
    return { ok: true, json: async () => ({
      device: { online: true },
      latest: {
        schema: "health.telemetry.v4",
        vitals: { heart_rate_raw_bpm: 180, heart_rate_bpm: null, spo2_raw_pct: 97, spo2_pct: null },
        measurements: {
          heart_rate: { raw_value: 180, confirmed_value: null, valid: false, state: "unstable", reason: "unstable" },
          spo2: { raw_value: 97, confirmed_value: null, valid: false, state: "unstable", reason: "unstable" }
        },
        wearable: { wrist_surface_temp_c: 33.2 },
        quality: {
          heart_rate_valid: false, spo2_valid: false, finger_present: true,
          wrist_surface_temp_valid: true, ppg: 0.58, ppg_state: "unstable",
          motion_artifact: false, motion_valid: true
        },
        motion: { fall_state: "idle" }, system: { fw: "0.4.0", faults: [] }
      },
      history: [], alerts: []
    }) };
  }
  return { ok: true, json: async () => ({ data: [] }) };
}
"""

    state = run_dashboard_failure_harness(fetch_implementation)

    assert state["heartRate"] == "—"
    assert state["heartQuality"] == "Đang xác nhận"


def test_offline_dashboard_marks_cached_measurements_and_rssi_as_last_values():
    _parser, html = parse_dashboard()
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "Dữ liệu cũ" in html
    assert "không phải dữ liệu trực tiếp" in html
    assert 'item.textContent = "Dữ liệu cũ"' in script
    assert '"Dữ liệu cuối"' in script
    assert '" (giá trị cuối)"' in script
    assert "renderLatest(overview.latest, Boolean(overview.device && overview.device.online))" in script


def test_dashboard_keeps_responsive_and_accessible_basics():
    _parser, html = parse_dashboard()
    styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in html
    assert 'aria-live="polite"' in html
    assert 'id="state-announcer"' in html
    assert 'id="ack-dialog"' in html
    assert 'aria-labelledby="ack-dialog-title"' in html
    assert "min-width: 320px" in styles
    assert "repeat(2, minmax(0, 1fr))" in styles
    assert "prefers-reduced-motion" in styles
    assert "forced-colors: active" in styles
    assert "touch-action: manipulation" in styles


def test_dashboard_exposes_protocol_experiment_and_accessible_chart_regions():
    _parser, html = parse_dashboard()
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="edge-status-text"' in html
    assert 'id="connection-text"' in html
    assert 'id="protocol-value"' in html
    assert 'id="run-select"' in html
    assert 'id="kpi-delivery-ratio"' in html
    assert 'id="impairment-notice"' in html
    assert "Không phải packet loss đo được" in html
    assert "không phải phép đo mạng 5G" in html
    assert "Nguồn: telemetry node · không thuộc run đã chọn" in html
    assert '<table>' in html
    assert 'id="chart-table-body"' in html
    assert 'id="chart-coverage"' in html
    assert "Tỷ lệ scheduled → API observed" in html
    assert "p50 schedule → API upper-bound" in html
    assert "p95 schedule → API upper-bound" in html
    assert 'id="experiment-primary-latency"' in html
    assert 'id="experiment-diagnostic-latency"' in html
    assert 'fetchJson("/api/v1/experiments?limit=10"' in script
    assert 'createElementNS("http://www.w3.org/2000/svg", "path")' in script
    assert "typicalInterval * 1.5" in script


def test_dashboard_guards_request_races_and_uses_deep_linked_state():
    _parser, _html = parse_dashboard()
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "refreshGeneration" in script
    assert "dashboardState.refreshController.abort()" in script
    assert "generation !== dashboardState.refreshGeneration" in script
    assert "new URLSearchParams(window.location.search" in script
    assert 'window.addEventListener("popstate"' in script
    assert 'document.addEventListener("visibilitychange"' in script
    assert "2 ** dashboardState.consecutiveFailures" in script
    assert "window.setInterval" not in script
    assert "window.prompt" not in script
    assert 'new Intl.NumberFormat("vi-VN"' in script


def test_acknowledgement_uses_managed_dialog_and_specific_conflict_copy():
    _parser, html = parse_dashboard()
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="ack-actor"' in html
    assert 'autocomplete="off"' in html
    assert 'id="ack-error"' in html
    assert "response.status === 409" in script
    assert "elements.ackActor.focus()" in script
    assert "dashboardState.ackTrigger.focus()" in script
    assert "Đã xem” chỉ ghi nhận thao tác" in html


def test_dashboard_static_assets_use_a_shared_content_version_placeholder():
    _parser, html = parse_dashboard()

    assert html.count("?v=__ASSET_VERSION__") == 3
    assert '/static/app.js?v=__ASSET_VERSION__' in html
    assert '/static/styles.css?v=__ASSET_VERSION__' in html


def run_dashboard_failure_harness(
    fetch_implementation: str,
    *,
    fail_first_alert_render: bool = False,
) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the dashboard behavior check")

    app_js = STATIC_DIR / "app.js"
    harness = f"""
const fs = require("fs");
const vm = require("vm");

function element() {{
  const classes = new Set(["visible"]);
  const children = [];
  const listeners = new Map();
  const attributes = new Map();
  const node = {{
    className: "quality-label quality-good",
    textContent: "Hợp lệ",
    hidden: false,
    value: "heart_rate_bpm",
    open: false,
    dataset: {{}},
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
    }},
    addEventListener(name, listener) {{ listeners.set(name, listener); }},
    dispatch(name, event = {{}}) {{ return listeners.get(name)?.(event); }},
    children,
    get options() {{ return children; }},
    get selectedIndex() {{
      const index = children.findIndex((child) => child.value === this.value);
      return index >= 0 ? index : 0;
    }},
    replaceChildren(...items) {{ children.splice(0, children.length, ...items); }},
    append(...items) {{ children.push(...items); }},
    setAttribute(name, value) {{ attributes.set(name, value); }},
    focus() {{}},
    showModal() {{ this.open = true; }},
    close() {{ this.open = false; listeners.get("close")?.(); }},
  }};
  return node;
}}

const nodes = new Map();
let failAlertRender = {json.dumps(fail_first_alert_render)};
const document = {{
  hidden: false,
  querySelector(selector) {{
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  }},
  createElement(tag) {{
    if (tag === "article" && failAlertRender) {{
      failAlertRender = false;
      throw new Error("simulated render failure");
    }}
    return element();
  }},
  createElementNS() {{ return element(); }},
  addEventListener() {{}},
}};
const window = {{
  setTimeout() {{ return 1; }},
  clearTimeout() {{}},
  addEventListener() {{}},
  location: {{ search: "", pathname: "/", hash: "" }},
  history: {{ replaceState() {{}} }},
}};
const context = {{
  AbortController,
  Intl,
  URLSearchParams,
  console: {{ error() {{}}, warn() {{}}, log() {{}} }},
  document,
  fetch: {fetch_implementation},
  setTimeout,
  clearTimeout,
  window,
}};
vm.runInNewContext(fs.readFileSync({json.dumps(str(app_js))}, "utf8"), context);
setTimeout(() => {{
  const output = {{
    connection: nodes.get("#connection-text").textContent,
    heartRate: nodes.get("#heart-rate").textContent,
    heartQuality: nodes.get("#heart-quality").textContent,
    wristTemp: nodes.get("#wrist-temp").textContent,
    wristTempQuality: nodes.get("#wrist-temp-quality").textContent,
    cacheNoticeHidden: nodes.get("#latest-data-state").hidden,
    chartVisible: nodes.get("#chart").classList.contains("visible"),
    chartEmptyHidden: nodes.get("#chart-empty").hidden,
    deviceOption: nodes.get("#device-select").children[0]?.textContent,
    lastUpdate: nodes.get("#last-update").textContent,
    alertCount: nodes.get("#alert-count").textContent,
    activeAlertState: nodes.get("#active-alerts").children[0]?.textContent,
    resolvedAlertState: nodes.get("#resolved-alerts").children[0]?.textContent,
    edge: nodes.get("#edge-status-text").textContent,
    edgeDetail: nodes.get("#edge-status-detail").textContent,
    mqttObserved: nodes.get("#mqtt-observed").textContent,
    experimentStatus: nodes.get("#experiment-status-text").textContent,
    deliveryRatio: nodes.get("#kpi-delivery-ratio").textContent,
    observed: nodes.get("#kpi-observed").textContent,
    p50: nodes.get("#kpi-p50").textContent,
    p95: nodes.get("#kpi-p95").textContent,
    primaryLatency: nodes.get("#experiment-primary-latency").textContent,
    diagnosticLatency: nodes.get("#experiment-diagnostic-latency").textContent,
    impairmentNoticeHidden: nodes.get("#impairment-notice").hidden,
    protocol: nodes.get("#protocol-value").textContent,
    chartSegments: nodes.get("#chart-series").children.length,
    chartRows: nodes.get("#chart-table-body").children.length,
    coverage: nodes.get("#chart-coverage").textContent,
    error: nodes.get("#dashboard-message").textContent,
  }};
  process.stdout.write(JSON.stringify(output));
}}, 10);
"""
    result = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return json.loads(result.stdout)


def assert_dashboard_context_is_cleared(state: dict[str, object]) -> None:
    assert state["heartRate"] == "—"
    assert state["heartQuality"] == "Chưa có dữ liệu"
    assert state["wristTemp"] == "—"
    assert state["wristTempQuality"] == "Chưa có dữ liệu"
    assert state["cacheNoticeHidden"] is True
    assert state["chartVisible"] is False
    assert state["chartEmptyHidden"] is False
    assert state["deviceOption"] == "Không thể xác nhận thiết bị"
    assert state["lastUpdate"] == "Không thể xác nhận thời điểm cập nhật."
    assert state["alertCount"] == "— cảnh báo"
    assert state["activeAlertState"] == (
        "Không thể xác nhận cảnh báo. Hãy thử làm mới dữ liệu."
    )
    assert state["resolvedAlertState"] == (
        "Không thể xác nhận cảnh báo. Hãy thử làm mới dữ liệu."
    )


def test_dashboard_clears_all_live_looking_state_when_edge_does_not_respond():
    state = run_dashboard_failure_harness(
        'async () => { throw new Error("edge unavailable"); }'
    )

    assert_dashboard_context_is_cleared(state)
    assert state["connection"] == "Không xác định"
    assert state["edge"] == "Không phản hồi"
    assert state["error"] == (
        "Không tải được dữ liệu Edge. Hệ thống sẽ tự thử lại với khoảng chờ tăng dần."
    )


def test_dashboard_distinguishes_http_or_json_errors_from_no_response():
    state = run_dashboard_failure_harness(
        "async () => ({ ok: false, status: 503, json: async () => ({}) })"
    )

    assert_dashboard_context_is_cleared(state)
    assert state["connection"] == "Không xác định"
    assert state["edge"] == "Không phản hồi"
    assert state["error"] == (
        "Edge có phản hồi nhưng dữ liệu trả về không hợp lệ. "
        "Hệ thống sẽ tự thử lại."
    )


def test_dashboard_distinguishes_render_failure_after_valid_overview():
    fetch_implementation = r"""
async (url) => {
  if (url.includes("/devices")) {
    return { ok: true, json: async () => ({ data: [{ device_id: "health-node-01", online: true }] }) };
  }
  if (url.includes("/overview")) {
    return { ok: true, json: async () => ({
      device: { online: true, last_seen_at: "2026-08-12T15:00:00Z" },
      latest: {
        schema: "health.telemetry.v3",
        vitals: { heart_rate_bpm: null, spo2_pct: null },
        wearable: { wrist_surface_temp_c: 33.2 },
        quality: {
          heart_rate_valid: false, spo2_valid: false, finger_present: false,
          wrist_surface_temp_valid: true, ppg: 0,
          motion_artifact: false, motion_valid: false
        },
        motion: { fall_state: "unknown" },
        system: { rssi_dbm: -30, fw: "0.2.0" }
      },
      history: [],
      alerts: [{ id: "alert-1", severity: "warning" }]
    }) };
  }
  return { ok: true, json: async () => ({ data: [] }) };
}
"""
    state = run_dashboard_failure_harness(
        fetch_implementation,
        fail_first_alert_render=True,
    )

    assert_dashboard_context_is_cleared(state)
    assert state["connection"] == "Không xác định"
    assert state["edge"] == "Không phản hồi"
    assert state["error"] == (
        "Edge đã gửi dữ liệu nhưng giao diện không thể hiển thị. "
        "Hãy tải lại trang."
    )


def test_dashboard_never_relabels_legacy_temperature_as_wrist_surface():
    fetch_implementation = r"""
async (url) => {
  if (url.includes("/devices")) {
    return { ok: true, json: async () => ({ data: [{ device_id: "legacy-node", online: true }] }) };
  }
  if (url.includes("/overview")) {
    return { ok: true, json: async () => ({
      device: { online: true, last_seen_at: "2026-08-13T15:00:00Z" },
      latest: {
        schema: "health.telemetry.v2",
        vitals: { heart_rate_bpm: 72, spo2_pct: 98 },
        wearable: { wrist_surface_temp_c: 34.7 },
        environment: { ambient_temp_c: 28.5, humidity_pct: 47 },
        quality: {
          heart_rate_valid: true, spo2_valid: true, finger_present: true,
          wrist_surface_temp_valid: true, ppg: 0.9,
          motion_artifact: false, motion_valid: true
        },
        motion: { fall_state: "idle" },
        system: { rssi_dbm: -30, fw: "legacy" }
      },
      history: [], alerts: []
    }) };
  }
  return { ok: true, json: async () => ({ data: [] }) };
}
"""

    state = run_dashboard_failure_harness(fetch_implementation)

    assert state["wristTemp"] == "—"
    assert state["wristTempQuality"] == "Không có trong telemetry v1/v2"


def test_dashboard_renders_measured_experiment_kpis_without_a_5g_claim():
    fetch_implementation = r"""
(() => {
  const detail = {
    manifest: {
      run_id: "run-26a", status: "completed", scenario: "normal", seed: 814,
      count: 26, created_at: "2026-08-14T03:00:00Z",
      clock_domain: "laptop_monotonic", polling_resolution_ms: 200,
      profile: {
        name: "remote-app-emulated", description_vi: "Trễ và drop có lịch định trước",
        profile_kind: "app_impairment", network_claim: "none",
        injection_point: "simulator_before_publish"
      },
      claims: {
        primary_latency_kind: "schedule_to_api_polling_upper_bound",
        diagnostic_latency_kind: "publish_to_api_polling_upper_bound"
      }
    },
    summary: {
      run_id: "run-26a", status: "completed", intentionally_dropped: 2,
      unique_logical_publish_attempted: 24, attempt_count: 25, api_observed: 22,
      scheduled: 26, attempted_delivery_ratio: 22 / 24,
      scheduled_observation_ratio: 22 / 26,
      delivery_ratio: 22 / 24, latency_sample_count: 22,
      publish_to_api_upper_bound_p50_ms: 46.2,
      publish_to_api_upper_bound_p95_ms: 118.7,
      schedule_to_api_latency_sample_count: 22,
      schedule_to_api_upper_bound_p50_ms: 131.2,
      schedule_to_api_upper_bound_p95_ms: 218.7,
      percentiles_available: true, network_claim: "none"
    }
  };
  return async (url) => {
    if (url.includes("/devices")) {
      return { ok: true, json: async () => ({ data: [{ device_id: "node-01", online: true }] }) };
    }
    if (url.includes("/overview")) {
      return { ok: true, json: async () => ({
        generated_at: "2026-08-14T03:01:00Z", device: { online: true },
        latest: null, history: [], alerts: []
      }) };
    }
    if (url.endsWith("/healthz")) {
      return { ok: true, json: async () => ({
        status: "ok", database: { healthy: true },
        mqtt: { enabled: true, connected: true, subscribed: true },
        ingestion: { worker_alive: true }
      }) };
    }
    if (url.includes("/runtime")) {
      return { ok: true, json: async () => ({
        edge: { status: "ready", database_healthy: true },
        mqtt: { enabled: true, connected: true, subscribed: true },
        ingestion: { worker_alive: true }
      }) };
    }
    if (url.includes("/capabilities")) {
      return { ok: true, json: async () => ({
        protocol: {
          name: "MQTT", version: "3.1.1", transport: "TCP",
          topic_namespace: "health/+/telemetry"
        },
        profiles: [detail.manifest.profile]
      }) };
    }
    if (url.includes("/experiments/run-26a")) {
      return { ok: true, json: async () => detail };
    }
    if (url.includes("/experiments?limit=10")) {
      return { ok: true, json: async () => ({ data: [detail], total: 1 }) };
    }
    return { ok: true, json: async () => ({ data: [] }) };
  };
})()
"""

    state = run_dashboard_failure_harness(fetch_implementation)

    assert state["experimentStatus"] == "Hoàn tất"
    assert str(state["deliveryRatio"]).startswith("84,6")
    assert state["observed"] == "22 / 24"
    assert state["p50"] == "131,2 ms"
    assert state["p95"] == "218,7 ms"
    assert state["primaryLatency"] == "schedule → API polling upper-bound"
    assert state["diagnosticLatency"] == "publish → API polling upper-bound"
    assert state["impairmentNoticeHidden"] is False
    assert state["protocol"] == "MQTT 3.1.1 · TCP"


def test_dashboard_explains_degraded_edge_and_does_not_invent_missing_health():
    degraded_fetch = r"""
async (url) => {
  if (url.includes("/devices")) return { ok: true, json: async () => ({ data: [] }) };
  if (url.includes("/overview")) return { ok: true, json: async () => ({ device: null, latest: null, history: [], alerts: [] }) };
  if (url.endsWith("/healthz")) return { ok: true, json: async () => ({
    status: "degraded", database: { healthy: true },
    ingestion: { worker_alive: true, processing_errors: 2 },
    mqtt: { enabled: true, connected: false, subscribed: false }
  }) };
  if (url.includes("/runtime")) return { ok: true, json: async () => ({
    edge: { status: "degraded", database_healthy: true },
    ingestion: { worker_alive: true, processing_errors: 2 },
    mqtt: { enabled: true, connected: false, subscribed: false }
  }) };
  return { ok: true, json: async () => ({ data: [], total: 0 }) };
}
"""
    degraded = run_dashboard_failure_harness(degraded_fetch)
    assert degraded["edge"] == "Suy giảm"
    assert degraded["edgeDetail"] == (
        "database sẵn sàng; worker sẵn sàng; 2 lỗi xử lý; MQTT mất kết nối."
    )
    assert degraded["mqttObserved"] == "Chưa quan sát kết nối"

    missing_fetch = r"""
async (url) => {
  if (url.includes("/devices")) return { ok: true, json: async () => ({ data: [] }) };
  if (url.includes("/overview")) return { ok: true, json: async () => ({ device: null, latest: null, history: [], alerts: [] }) };
  if (url.endsWith("/healthz")) return { ok: true, json: async () => ({}) };
  if (url.includes("/runtime")) return { ok: true, json: async () => ({ edge: {} }) };
  return { ok: true, json: async () => ({ data: [], total: 0 }) };
}
"""
    missing = run_dashboard_failure_harness(missing_fetch)
    assert missing["edge"] == "Chưa xác nhận"
    assert missing["edgeDetail"] == (
        "database chưa xác nhận; worker chưa xác nhận; lỗi xử lý chưa xác nhận; MQTT chưa xác nhận."
    )
    assert missing["mqttObserved"] == "Runtime chưa công bố"


def test_dashboard_breaks_time_series_at_a_real_timestamp_gap():
    fetch_implementation = r"""
async (url) => {
  if (url.includes("/devices")) {
    return { ok: true, json: async () => ({ data: [{ device_id: "node-gap", online: true }] }) };
  }
  if (url.includes("/overview")) {
    const sample = (received_at, seq, value) => ({
      received_at, seq, schema: "health.telemetry.v3",
      vitals: { heart_rate_bpm: value },
      quality: { heart_rate_valid: true }
    });
    return { ok: true, json: async () => ({
      generated_at: "2026-08-14T03:01:00Z", device: { online: true }, latest: null,
      history: [
        sample("2026-08-14T03:00:00Z", 1, 70),
        sample("2026-08-14T03:00:02Z", 2, 71),
        sample("2026-08-14T03:00:10Z", 3, 72),
        sample("2026-08-14T03:00:12Z", 4, 73)
      ],
      history_meta: {
        requested_from: "2026-08-14T02:46:00Z",
        requested_to: "2026-08-14T03:01:00Z",
        coverage_from: "2026-08-14T03:00:00Z",
        coverage_to: "2026-08-14T03:00:12Z",
        total_available: 4, returned: 4, truncated: false,
        downsampling: "none", interval_ms: 2000,
        validity: { heart_rate_bpm: { valid: 4, total: 4 } }
      },
      alerts: []
    }) };
  }
  return { ok: true, json: async () => ({ data: [] }) };
}
"""

    state = run_dashboard_failure_harness(fetch_implementation)

    assert state["chartVisible"] is True
    assert state["chartSegments"] == 2
    assert state["chartRows"] == 4
    assert "gap: 1" in str(state["coverage"])
    assert "không cắt dữ liệu" in str(state["coverage"])
    assert "hợp lệ/tổng cửa sổ 4/4" in str(state["coverage"])
    assert "API 4/4" in str(state["coverage"])
    assert "downsampling: none" in str(state["coverage"])
