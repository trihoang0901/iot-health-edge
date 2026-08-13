"use strict";

const POLL_MS = 2000;
const elements = {
  deviceSelect: document.querySelector("#device-select"),
  connectionPill: document.querySelector("#connection-pill"),
  connectionText: document.querySelector("#connection-text"),
  lastUpdate: document.querySelector("#last-update"),
  latestDataState: document.querySelector("#latest-data-state"),
  heartRate: document.querySelector("#heart-rate"),
  spo2: document.querySelector("#spo2"),
  ambientTemp: document.querySelector("#ambient-temp"),
  humidity: document.querySelector("#humidity"),
  heartQuality: document.querySelector("#heart-quality"),
  spo2Quality: document.querySelector("#spo2-quality"),
  ambientTempQuality: document.querySelector("#ambient-temp-quality"),
  humidityQuality: document.querySelector("#humidity-quality"),
  qualitySummary: document.querySelector("#quality-summary"),
  fingerState: document.querySelector("#finger-state"),
  ppgQuality: document.querySelector("#ppg-quality"),
  motionArtifact: document.querySelector("#motion-artifact"),
  fallState: document.querySelector("#fall-state"),
  rssi: document.querySelector("#rssi"),
  firmware: document.querySelector("#firmware"),
  chart: document.querySelector("#chart"),
  chartEmpty: document.querySelector("#chart-empty"),
  chartLine: document.querySelector("#chart-line"),
  chartMetric: document.querySelector("#chart-metric"),
  chartMax: document.querySelector("#chart-max"),
  chartMid: document.querySelector("#chart-mid"),
  chartMin: document.querySelector("#chart-min"),
  chartDesc: document.querySelector("#chart-desc"),
  activeAlerts: document.querySelector("#active-alerts"),
  resolvedAlerts: document.querySelector("#resolved-alerts"),
  alertCount: document.querySelector("#alert-count"),
  dashboardMessage: document.querySelector("#dashboard-message"),
};

const chartDefinitions = {
  heart_rate_bpm: { label: "Nhịp tim", unit: "bpm", group: "vitals" },
  spo2_pct: { label: "SpO₂", unit: "%", group: "vitals" },
  ambient_temp_c: { label: "Nhiệt độ môi trường", unit: "°C", group: "environment" },
  humidity_pct: { label: "Độ ẩm môi trường", unit: "%", group: "environment" },
};

let selectedDevice = "";
let latestHistory = [];
let refreshInFlight = false;

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

class DashboardRequestError extends Error {
  constructor(kind, message, cause) {
    super(message);
    this.name = "DashboardRequestError";
    this.kind = kind;
    if (cause !== undefined) this.cause = cause;
  }
}

async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetchWithTimeout(url, options);
  } catch (error) {
    throw new DashboardRequestError("network", "request_failed", error);
  }
  if (!response.ok) {
    throw new DashboardRequestError("http", `HTTP ${response.status}`);
  }
  try {
    return await response.json();
  } catch (error) {
    throw new DashboardRequestError("invalid_json", "invalid_json", error);
  }
}

function formatNumber(value, digits = 0) {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : "—";
}

function formatTime(value) {
  if (!value) return "chưa có";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "không xác định";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

function setQualityLabel(element, valid, invalidText) {
  element.className = `quality-label ${valid ? "quality-good" : "quality-warning"}`;
  element.textContent = valid ? "Hợp lệ" : invalidText;
}

function setConnection(device) {
  const online = Boolean(device && device.online);
  elements.connectionPill.className = `status-pill ${online ? "status-online" : "status-offline"}`;
  elements.connectionText.textContent = online ? "● Đang trực tuyến" : "○ Mất kết nối";
  elements.lastUpdate.textContent = device
    ? `${online ? "Cập nhật gần nhất" : "Dữ liệu cuối"}: ${formatTime(device.last_seen_at)}`
    : "Chưa nhận dữ liệu từ thiết bị";
}

function clearLatest() {
  [elements.heartRate, elements.spo2, elements.ambientTemp, elements.humidity].forEach((item) => { item.textContent = "—"; });
  [elements.heartQuality, elements.spo2Quality, elements.ambientTempQuality,
    elements.humidityQuality].forEach((item) => {
    item.className = "quality-label";
    item.textContent = "Chưa có dữ liệu";
  });
  elements.latestDataState.hidden = true;
  elements.qualitySummary.textContent = "Chưa có dữ liệu";
  elements.qualitySummary.className = "quality-badge";
  [elements.fingerState, elements.ppgQuality, elements.motionArtifact, elements.fallState,
    elements.rssi, elements.firmware].forEach((item) => { item.textContent = "—"; });
}

function renderUnavailableAlertState(container) {
  container.replaceChildren();
  const message = document.createElement("p");
  message.className = "empty-state";
  message.textContent = "Không thể xác nhận cảnh báo.";
  container.append(message);
}

function clearDashboardContext() {
  clearLatest();
  latestHistory = [];
  renderChart();
  selectedDevice = "";
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Không thể xác nhận thiết bị";
  elements.deviceSelect.replaceChildren(option);
  elements.deviceSelect.value = "";
  elements.lastUpdate.textContent = "Không thể xác nhận thời điểm cập nhật";
  renderUnavailableAlertState(elements.activeAlerts);
  renderUnavailableAlertState(elements.resolvedAlerts);
  elements.alertCount.textContent = "— cảnh báo";
}

function renderLatest(latest, online) {
  if (!latest) {
    clearLatest();
    return;
  }
  const vitals = latest.vitals || {};
  const environment = latest.environment || {};
  const quality = latest.quality || {};
  const motion = latest.motion || {};
  const system = latest.system || {};
  const stale = !online;
  elements.heartRate.textContent = formatNumber(vitals.heart_rate_bpm);
  elements.spo2.textContent = formatNumber(vitals.spo2_pct, 1);
  elements.ambientTemp.textContent = formatNumber(environment.ambient_temp_c, 1);
  elements.humidity.textContent = formatNumber(environment.humidity_pct, 1);

  if (stale) {
    [elements.heartQuality, elements.spo2Quality, elements.ambientTempQuality,
      elements.humidityQuality].forEach((item) => {
      item.className = "quality-label quality-warning";
      item.textContent = "Dữ liệu cũ";
    });
  } else {
    setQualityLabel(elements.heartQuality, quality.heart_rate_valid, quality.finger_present ? "Không tin cậy" : "Chưa đặt ngón tay");
    setQualityLabel(elements.spo2Quality, quality.spo2_valid, quality.finger_present ? "Không tin cậy" : "Chưa đặt ngón tay");
    setQualityLabel(elements.ambientTempQuality, quality.ambient_temp_valid, "DHT11 không sẵn sàng");
    setQualityLabel(elements.humidityQuality, quality.humidity_valid, "DHT11 không sẵn sàng");
  }

  const allValid = quality.heart_rate_valid && quality.spo2_valid
    && quality.ambient_temp_valid && quality.humidity_valid;
  elements.qualitySummary.className = `quality-badge ${allValid ? "quality-good" : "quality-warning"}`;
  elements.qualitySummary.textContent = stale
    ? "Dữ liệu cũ"
    : (allValid ? "Dữ liệu hợp lệ" : "Cần kiểm tra cảm biến");
  elements.latestDataState.hidden = !stale;
  elements.fingerState.textContent = quality.finger_present ? "✓ Đã phát hiện" : "○ Chưa đặt ngón tay";
  elements.ppgQuality.textContent = Number.isFinite(quality.ppg) ? `${Math.round(quality.ppg * 100)}%` : "Không có";
  elements.motionArtifact.textContent = quality.motion_artifact ? "⚠ Có nhiễu" : "✓ Không phát hiện";
  elements.fallState.textContent = motion.fall_state || "—";
  elements.rssi.textContent = Number.isFinite(system.rssi_dbm)
    ? `${system.rssi_dbm} dBm${stale ? " (giá trị cuối)" : ""}`
    : (stale ? "Không có giá trị cuối" : "Không có");
  elements.firmware.textContent = system.fw || "—";
}

function metricValue(item, key) {
  const definition = chartDefinitions[key];
  return item && definition && item[definition.group] ? item[definition.group][key] : null;
}

function renderChart() {
  const key = elements.chartMetric.value;
  const definition = chartDefinitions[key];
  const values = latestHistory
    .map((item, index) => ({ index, value: metricValue(item, key) }))
    .filter((point) => Number.isFinite(point.value));

  if (values.length < 2) {
    elements.chart.classList.remove("visible");
    elements.chartEmpty.hidden = false;
    elements.chartDesc.textContent = `Chưa đủ dữ liệu ${definition.label}.`;
    return;
  }
  const rawMin = Math.min(...values.map((point) => point.value));
  const rawMax = Math.max(...values.map((point) => point.value));
  const padding = Math.max((rawMax - rawMin) * 0.12, key === "ambient_temp_c" ? 0.2 : 1);
  const min = rawMin - padding;
  const max = rawMax + padding;
  const xStart = 52;
  const xEnd = 780;
  const yTop = 24;
  const yBottom = 214;
  const span = Math.max(latestHistory.length - 1, 1);
  const points = values.map(({ index, value }) => {
    const x = xStart + (index / span) * (xEnd - xStart);
    const y = yBottom - ((value - min) / (max - min)) * (yBottom - yTop);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const digits = key === "heart_rate_bpm" ? 0 : 1;
  elements.chartLine.setAttribute("points", points);
  elements.chartMax.textContent = `${max.toFixed(digits)}`;
  elements.chartMid.textContent = `${((max + min) / 2).toFixed(digits)}`;
  elements.chartMin.textContent = `${min.toFixed(digits)}`;
  elements.chartDesc.textContent = `${definition.label}: từ ${rawMin.toFixed(digits)} đến ${rawMax.toFixed(digits)} ${definition.unit} trong 15 phút gần nhất.`;
  elements.chartEmpty.hidden = true;
  elements.chart.classList.add("visible");
}

function makeAlertItem(alert, active) {
  const article = document.createElement("article");
  article.className = `alert-item ${alert.severity === "critical" ? "critical" : "warning"}`;
  const icon = document.createElement("span");
  icon.className = "alert-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = alert.severity === "critical" ? "⚠" : "!";
  const body = document.createElement("div");
  const title = document.createElement("p");
  title.className = "alert-title";
  title.textContent = alert.message;
  const meta = document.createElement("p");
  meta.className = "alert-meta";
  const stateText = alert.state === "acknowledged" ? "Đã xem" : alert.state === "resolved" ? "Đã kết thúc" : "Chưa xem";
  meta.textContent = `${stateText} · lần cuối ${formatTime(alert.last_seen_at)} · ${alert.occurrence_count} lần ghi nhận`;
  body.append(title, meta);
  article.append(icon, body);

  if (active) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ack-button";
    button.textContent = alert.state === "acknowledged" ? "Đã xem" : "Đánh dấu đã xem";
    button.disabled = alert.state === "acknowledged";
    button.addEventListener("click", () => acknowledgeAlert(alert.id));
    article.append(button);
  }
  return article;
}

function renderAlerts(container, alerts, active) {
  container.replaceChildren();
  if (!alerts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = active ? "✓ Chưa có cảnh báo đang hoạt động." : "Chưa có lịch sử cảnh báo.";
    container.append(empty);
    return;
  }
  alerts.forEach((alert) => container.append(makeAlertItem(alert, active)));
}

async function acknowledgeAlert(alertId) {
  const actor = window.prompt("Tên người đánh dấu đã xem:", "Người vận hành");
  if (!actor || !actor.trim()) return;
  try {
    const response = await fetchWithTimeout(`/api/v1/alerts/${encodeURIComponent(alertId)}/ack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: actor.trim(), note: "Đã xem trên dashboard" }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    elements.dashboardMessage.className = "dashboard-message";
    elements.dashboardMessage.textContent = "Đã ghi nhận: Đã xem. Cảnh báo vẫn hoạt động cho tới khi dữ liệu hồi phục.";
    await refreshDashboard();
  } catch (error) {
    elements.dashboardMessage.className = "dashboard-message error";
    elements.dashboardMessage.textContent = "Không thể ghi nhận trạng thái Đã xem.";
  }
}

async function fetchDevices() {
  return fetchJson("/api/v1/devices", { cache: "no-store" });
}

function renderDeviceOptions(payload) {
  const previous = selectedDevice;
  elements.deviceSelect.replaceChildren();
  if (!payload.data.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Chưa có thiết bị";
    elements.deviceSelect.append(option);
    selectedDevice = "";
    return;
  }
  payload.data.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.device_id;
    option.textContent = `${device.device_id} — ${device.online ? "trực tuyến" : "ngoại tuyến"}`;
    elements.deviceSelect.append(option);
  });
  selectedDevice = payload.data.some((device) => device.device_id === previous)
    ? previous
    : payload.data[0].device_id;
  elements.deviceSelect.value = selectedDevice;
}

async function refreshDashboard() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  let refreshStage = "devices_request";
  try {
    const devices = await fetchDevices();
    refreshStage = "render";
    renderDeviceOptions(devices);
    const query = selectedDevice ? `?device_id=${encodeURIComponent(selectedDevice)}&window=15` : "?window=15";
    refreshStage = "overview_request";
    const overview = await fetchJson(`/api/v1/overview${query}`, { cache: "no-store" });
    refreshStage = "render";
    setConnection(overview.device);
    renderLatest(overview.latest, Boolean(overview.device && overview.device.online));
    latestHistory = overview.history || [];
    renderChart();
    renderAlerts(elements.activeAlerts, overview.alerts || [], true);
    elements.alertCount.textContent = `${(overview.alerts || []).length} cảnh báo`;

    if (selectedDevice) {
      try {
        const resolved = await fetchJson(`/api/v1/alerts?state=resolved&device_id=${encodeURIComponent(selectedDevice)}&limit=5`, { cache: "no-store" });
        renderAlerts(elements.resolvedAlerts, resolved.data || [], false);
      } catch (error) {
        console.warn("resolved_alerts_refresh_failed", error);
        renderUnavailableAlertState(elements.resolvedAlerts);
      }
    } else {
      renderAlerts(elements.resolvedAlerts, [], false);
    }
    if (!elements.dashboardMessage.textContent.includes("Đã ghi nhận")) {
      elements.dashboardMessage.textContent = "";
    }
  } catch (error) {
    console.error("dashboard_refresh_failed", error);
    // Nothing from a failed refresh remains authoritative: remove measurements,
    // device freshness, and alerts together so the page cannot contradict its
    // own connection state.
    clearDashboardContext();
    const renderFailure = refreshStage === "render";
    const responseFailure = error instanceof DashboardRequestError
      && (error.kind === "http" || error.kind === "invalid_json");
    elements.connectionPill.className = "status-pill status-offline";
    elements.connectionText.textContent = renderFailure
      ? "○ Lỗi hiển thị dashboard"
      : responseFailure ? "○ Edge trả dữ liệu lỗi" : "○ Edge không phản hồi";
    elements.dashboardMessage.className = "dashboard-message error";
    elements.dashboardMessage.textContent = renderFailure
      ? "Edge đã gửi dữ liệu nhưng giao diện không thể hiển thị. Hãy tải lại trang."
      : responseFailure
        ? "Edge có phản hồi nhưng dữ liệu trả về không hợp lệ. Hệ thống sẽ tự thử lại."
        : "Không tải được dữ liệu. Hệ thống sẽ tự thử lại.";
  } finally {
    refreshInFlight = false;
  }
}

elements.deviceSelect.addEventListener("change", () => {
  selectedDevice = elements.deviceSelect.value;
  refreshDashboard();
});
elements.chartMetric.addEventListener("change", renderChart);

refreshDashboard();
window.setInterval(refreshDashboard, POLL_MS);
