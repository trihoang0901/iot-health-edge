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
    assert 'schema !== "health.telemetry.v3"' in script
    assert "skin_temp_c" not in script


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
    assert "repeat(3, minmax(0, 1fr))" in styles
    assert "repeat(2, minmax(0, 1fr))" in styles
    assert "prefers-reduced-motion" in styles


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
  return {{
    className: "quality-label quality-good",
    textContent: "Hợp lệ",
    hidden: false,
    value: "heart_rate_bpm",
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
    }},
    addEventListener() {{}},
    children,
    replaceChildren(...items) {{ children.splice(0, children.length, ...items); }},
    append(...items) {{ children.push(...items); }},
    setAttribute() {{}},
  }};
}}

const nodes = new Map();
let failAlertRender = {json.dumps(fail_first_alert_render)};
const document = {{
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
}};
const window = {{
  setTimeout,
  clearTimeout,
  setInterval() {{ return 1; }},
  prompt() {{ return null; }},
}};
const context = {{
  AbortController,
  Intl,
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
    assert state["lastUpdate"] == "Không thể xác nhận thời điểm cập nhật"
    assert state["alertCount"] == "— cảnh báo"
    assert state["activeAlertState"] == "Không thể xác nhận cảnh báo."
    assert state["resolvedAlertState"] == "Không thể xác nhận cảnh báo."


def test_dashboard_clears_all_live_looking_state_when_edge_does_not_respond():
    state = run_dashboard_failure_harness(
        'async () => { throw new Error("edge unavailable"); }'
    )

    assert_dashboard_context_is_cleared(state)
    assert state["connection"] == "○ Edge không phản hồi"
    assert state["error"] == "Không tải được dữ liệu. Hệ thống sẽ tự thử lại."


def test_dashboard_distinguishes_http_or_json_errors_from_no_response():
    state = run_dashboard_failure_harness(
        "async () => ({ ok: false, status: 503, json: async () => ({}) })"
    )

    assert_dashboard_context_is_cleared(state)
    assert state["connection"] == "○ Edge trả dữ liệu lỗi"
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
    assert state["connection"] == "○ Lỗi hiển thị dashboard"
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
