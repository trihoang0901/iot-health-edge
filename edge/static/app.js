"use strict";

const BASE_POLL_MS = 2000;
const MAX_POLL_MS = 30000;
const MAX_CHART_POINTS = 60;
const VALID_WINDOWS = new Set(["15m", "60m", "360m", "1440m"]);

const elements = {
  deviceSelect: document.querySelector("#device-select"),
  runSelect: document.querySelector("#run-select"),
  profileSelect: document.querySelector("#profile-select"),
  windowSelect: document.querySelector("#window-select"),
  refreshButton: document.querySelector("#refresh-button"),
  refreshTime: document.querySelector("#refresh-time"),
  edgeStatusPill: document.querySelector("#edge-status-pill"),
  edgeStatusText: document.querySelector("#edge-status-text"),
  edgeStatusDetail: document.querySelector("#edge-status-detail"),
  connectionPill: document.querySelector("#connection-pill"),
  connectionText: document.querySelector("#connection-text"),
  lastUpdate: document.querySelector("#last-update"),
  experimentStatus: document.querySelector("#experiment-status"),
  experimentStatusText: document.querySelector("#experiment-status-text"),
  experimentStatusDetail: document.querySelector("#experiment-status-detail"),
  stateAnnouncer: document.querySelector("#state-announcer"),
  protocolValue: document.querySelector("#protocol-value"),
  topicNamespace: document.querySelector("#topic-namespace"),
  mqttObserved: document.querySelector("#mqtt-observed"),
  injectionPoint: document.querySelector("#injection-point"),
  impairmentNotice: document.querySelector("#impairment-notice"),
  kpiClaimLabel: document.querySelector("#kpi-claim-label"),
  latestDataState: document.querySelector("#latest-data-state"),
  measurementState: document.querySelector("#measurement-state"),
  measurementStateText: document.querySelector("#measurement-state-text"),
  heartRate: document.querySelector("#heart-rate"),
  spo2: document.querySelector("#spo2"),
  wristTemp: document.querySelector("#wrist-temp"),
  heartQuality: document.querySelector("#heart-quality"),
  spo2Quality: document.querySelector("#spo2-quality"),
  wristTempQuality: document.querySelector("#wrist-temp-quality"),
  qualitySummary: document.querySelector("#quality-summary"),
  fingerState: document.querySelector("#finger-state"),
  ppgQuality: document.querySelector("#ppg-quality"),
  motionArtifact: document.querySelector("#motion-artifact"),
  fallState: document.querySelector("#fall-state"),
  rssi: document.querySelector("#rssi"),
  firmware: document.querySelector("#firmware"),
  bootId: document.querySelector("#boot-id"),
  experimentEmpty: document.querySelector("#experiment-empty"),
  experimentContent: document.querySelector("#experiment-content"),
  experimentIdentity: document.querySelector("#experiment-identity"),
  experimentScenario: document.querySelector("#experiment-scenario"),
  experimentProfile: document.querySelector("#experiment-profile"),
  experimentClock: document.querySelector("#experiment-clock"),
  experimentPolling: document.querySelector("#experiment-polling"),
  experimentPrimaryLatency: document.querySelector("#experiment-primary-latency"),
  experimentDiagnosticLatency: document.querySelector("#experiment-diagnostic-latency"),
  kpiDeliveryRatio: document.querySelector("#kpi-delivery-ratio"),
  kpiDeliveryDetail: document.querySelector("#kpi-delivery-detail"),
  kpiObserved: document.querySelector("#kpi-observed"),
  kpiAttempts: document.querySelector("#kpi-attempts"),
  kpiP50: document.querySelector("#kpi-p50"),
  kpiP95: document.querySelector("#kpi-p95"),
  chart: document.querySelector("#chart"),
  chartEmpty: document.querySelector("#chart-empty"),
  chartSeries: document.querySelector("#chart-series"),
  chartMetric: document.querySelector("#chart-metric"),
  chartMax: document.querySelector("#chart-max"),
  chartMid: document.querySelector("#chart-mid"),
  chartMin: document.querySelector("#chart-min"),
  chartStartTime: document.querySelector("#chart-start-time"),
  chartEndTime: document.querySelector("#chart-end-time"),
  chartDesc: document.querySelector("#chart-desc"),
  chartWindowLabel: document.querySelector("#chart-window-label"),
  chartCoverage: document.querySelector("#chart-coverage"),
  chartTableBody: document.querySelector("#chart-table-body"),
  chartTableCaption: document.querySelector("#chart-table-caption"),
  activeAlerts: document.querySelector("#active-alerts"),
  resolvedAlerts: document.querySelector("#resolved-alerts"),
  alertCount: document.querySelector("#alert-count"),
  dashboardMessage: document.querySelector("#dashboard-message"),
  ackDialog: document.querySelector("#ack-dialog"),
  ackForm: document.querySelector("#ack-form"),
  ackActor: document.querySelector("#ack-actor"),
  ackNote: document.querySelector("#ack-note"),
  ackError: document.querySelector("#ack-error"),
  ackCancel: document.querySelector("#ack-cancel"),
  ackConfirm: document.querySelector("#ack-confirm"),
};

const chartDefinitions = {
  heart_rate_bpm: {
    label: "Nhịp tim", unit: "bpm", group: "vitals", validKey: "heart_rate_valid", digits: 0,
  },
  spo2_pct: {
    label: "SpO₂", unit: "%", group: "vitals", validKey: "spo2_valid", digits: 1,
  },
  wrist_surface_temp_c: {
    label: "Nhiệt độ bề mặt cổ tay", unit: "°C", group: "wearable", validKey: "wrist_surface_temp_valid", digits: 1,
  },
};

const fallStateLabels = {
  idle: "Bình thường",
  normal: "Bình thường",
  low_g: "Pha giảm gia tốc",
  impact: "Pha va chạm",
  verify_stillness: "Đang xác minh bất động",
  alarm: "Cảnh báo ngã demo",
  refractory: "Thời gian khóa sau sự kiện",
  suspected: "Nghi ngờ ngã",
  fall_suspected: "Nghi ngờ ngã",
  confirmed: "Sự kiện ngã demo",
  unknown: "Chưa xác định",
};

const runStatusLabels = {
  planned: "Đã lập kế hoạch",
  running: "Đang chạy",
  completed: "Hoàn tất",
  partial: "Minh chứng chưa đủ",
  failed: "Thất bại",
};

function readUrlState() {
  const params = new URLSearchParams(window.location.search || "");
  const metric = params.get("metric");
  const windowValue = params.get("window");
  return {
    device: params.get("device") || "",
    run: params.get("run") || "",
    profile: params.get("profile") || "",
    window: VALID_WINDOWS.has(windowValue) ? windowValue : "15m",
    metric: Object.hasOwn(chartDefinitions, metric) ? metric : "heart_rate_bpm",
  };
}

const initialUrlState = readUrlState();
const dashboardState = {
  selectedDevice: initialUrlState.device,
  selectedRun: initialUrlState.run,
  selectedProfile: initialUrlState.profile,
  selectedWindow: initialUrlState.window,
  selectedMetric: initialUrlState.metric,
  history: [],
  historyMeta: {},
  experiments: [],
  capabilities: null,
  refreshGeneration: 0,
  refreshController: null,
  refreshTimer: null,
  consecutiveFailures: 0,
  announcedStates: new Map(),
  knownAlertIds: new Set(),
  alertsInitialized: false,
  ackAlertId: "",
  ackTrigger: null,
};

elements.windowSelect.value = dashboardState.selectedWindow;
elements.chartMetric.value = dashboardState.selectedMetric;

class DashboardRequestError extends Error {
  constructor(kind, message, cause, statusCode = null) {
    super(message);
    this.name = "DashboardRequestError";
    this.kind = kind;
    this.statusCode = statusCode;
    if (cause !== undefined) this.cause = cause;
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000, parentSignal = null) {
  const controller = new AbortController();
  const abortFromParent = () => controller.abort();
  if (parentSignal) {
    if (parentSignal.aborted) controller.abort();
    else parentSignal.addEventListener("abort", abortFromParent, { once: true });
  }
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
    if (parentSignal) parentSignal.removeEventListener("abort", abortFromParent);
  }
}

async function fetchJson(url, options = {}, parentSignal = null) {
  let response;
  try {
    response = await fetchWithTimeout(url, options, 5000, parentSignal);
  } catch (error) {
    throw new DashboardRequestError("network", "request_failed", error);
  }
  if (!response.ok) {
    throw new DashboardRequestError("http", `HTTP ${response.status}`, undefined, response.status);
  }
  try {
    return await response.json();
  } catch (error) {
    throw new DashboardRequestError("invalid_json", "invalid_json", error);
  }
}

function formatNumber(value, digits = 0) {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("vi-VN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

function formatInteger(value) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(value))
    : "—";
}

function formatPercent(value) {
  if (!Number.isFinite(value)) return "—";
  const normalized = value > 1 ? value / 100 : value;
  return new Intl.NumberFormat("vi-VN", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(normalized);
}

function parseTime(value) {
  const timestamp = Date.parse(value || "");
  return Number.isFinite(timestamp) ? timestamp : null;
}

function formatTime(value) {
  const timestamp = parseTime(value);
  if (timestamp === null) return value ? "không xác định" : "chưa có";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(timestamp);
}

function formatAxisTime(timestamp) {
  if (!Number.isFinite(timestamp)) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

function localTimeZoneLabel() {
  return Intl.DateTimeFormat("vi-VN").resolvedOptions().timeZone || "múi giờ trình duyệt";
}

function setDashboardMessage(message = "", isError = false) {
  elements.dashboardMessage.className = `dashboard-message${isError ? " error" : ""}`;
  elements.dashboardMessage.textContent = message;
}

function announceStateTransition(key, label) {
  const previous = dashboardState.announcedStates.get(key);
  dashboardState.announcedStates.set(key, label);
  if (previous && previous !== label) {
    elements.stateAnnouncer.textContent = `${key}: ${label}`;
  }
}

function setStateBadge(pill, textElement, className, label) {
  pill.className = `state-badge ${className}`;
  textElement.textContent = label;
}

function setEdgeState(health, runtime, overviewAvailable = true) {
  const runtimeEdge = runtime && runtime.edge ? runtime.edge : {};
  const rawStatus = String((health && health.status) || runtimeEdge.status || runtimeEdge.state || "").toLowerCase();
  let className = "state-unknown";
  let label = overviewAvailable ? "Chưa xác nhận" : "Không phản hồi";
  if (["ok", "ready", "healthy", "online"].includes(rawStatus)) {
    className = "state-online";
    label = "Sẵn sàng";
  } else if (["offline", "unreachable", "failed"].includes(rawStatus) || !overviewAvailable) {
    className = "state-offline";
    label = "Không phản hồi";
  } else if (rawStatus) {
    className = "state-degraded";
    label = "Suy giảm";
  }
  setStateBadge(elements.edgeStatusPill, elements.edgeStatusText, className, label);

  const healthDatabase = health && health.database ? health.database.healthy : undefined;
  const databaseHealthy = healthDatabase !== undefined ? healthDatabase : runtimeEdge.database_healthy;
  const ingestion = {
    ...((health && health.ingestion) || {}),
    ...((runtime && runtime.ingestion) || {}),
  };
  const mqtt = {
    ...((health && health.mqtt) || {}),
    ...((runtime && runtime.mqtt) || {}),
  };
  const databaseState = databaseHealthy === true
    ? "database sẵn sàng"
    : databaseHealthy === false ? "database lỗi" : "database chưa xác nhận";
  const workerState = ingestion.worker_alive === true
    ? "worker sẵn sàng"
    : ingestion.worker_alive === false ? "worker dừng" : "worker chưa xác nhận";
  const processingErrorState = Number.isFinite(ingestion.processing_errors)
    ? Number(ingestion.processing_errors) > 0
      ? `${formatInteger(ingestion.processing_errors)} lỗi xử lý`
      : "không có lỗi xử lý"
    : "lỗi xử lý chưa xác nhận";
  let mqttState = "MQTT chưa xác nhận";
  if (mqtt.enabled === false) {
    mqttState = "MQTT tắt theo cấu hình";
  } else if (mqtt.enabled === true && mqtt.connected === true && mqtt.subscribed === true) {
    mqttState = "MQTT kết nối + subscribe";
  } else if (mqtt.enabled === true && mqtt.connected === true && mqtt.subscribed === false) {
    mqttState = "MQTT chưa subscribe";
  } else if (mqtt.enabled === true && mqtt.connected === false) {
    mqttState = "MQTT mất kết nối";
  }
  elements.edgeStatusDetail.textContent = overviewAvailable
    ? `${databaseState}; ${workerState}; ${processingErrorState}; ${mqttState}.`
    : "Không thể tải API dashboard; dữ liệu node đã được xóa khỏi màn hình.";
  announceStateTransition("Edge", label);

  if (mqtt.enabled === false) {
    elements.mqttObserved.textContent = "Tắt theo cấu hình";
  } else if (mqtt.connected && mqtt.subscribed) {
    elements.mqttObserved.textContent = "Đã quan sát: kết nối + subscribe";
  } else if (mqtt.connected) {
    elements.mqttObserved.textContent = "Đã kết nối; chưa xác nhận subscribe";
  } else if (Object.keys(mqtt).length) {
    elements.mqttObserved.textContent = "Chưa quan sát kết nối";
  } else {
    elements.mqttObserved.textContent = "Runtime chưa công bố";
  }
}

function setConnection(device) {
  if (!device) {
    setStateBadge(elements.connectionPill, elements.connectionText, "state-unknown", "Chưa có node");
    elements.lastUpdate.textContent = "Chưa nhận dữ liệu từ thiết bị.";
    announceStateTransition("Node", "Chưa có node");
    return;
  }
  const online = Boolean(device.online);
  const label = online ? "Đang trực tuyến" : "Ngoại tuyến";
  setStateBadge(
    elements.connectionPill,
    elements.connectionText,
    online ? "state-online" : "state-offline",
    label,
  );
  elements.lastUpdate.textContent = `${online ? "Cập nhật gần nhất" : "Dữ liệu cuối"}: ${formatTime(device.last_seen_at)}`;
  announceStateTransition("Node", label);
}

function setMeasurementState(key, label) {
  const classByState = {
    valid: "state-online",
    measuring: "state-degraded",
    waiting: "state-unknown",
    noisy: "state-degraded",
    fault: "state-offline",
    stale: "state-offline",
  };
  elements.measurementState.dataset.state = key;
  setStateBadge(elements.measurementState, elements.measurementStateText, classByState[key] || "state-unknown", label);
}

function setQualityLabel(element, valid, invalidText) {
  element.className = `quality-label ${valid ? "quality-good" : "quality-warning"}`;
  element.textContent = valid ? "Hợp lệ" : invalidText;
}

const ppgStateLabels = {
  valid: "Đã xác nhận",
  legacy: "Hợp lệ (legacy)",
  no_finger: "Chờ đặt ngón tay",
  warming_up: "Đang xác nhận",
  motion: "Có nhiễu chuyển động",
  clipping: "Tín hiệu quang bị clipping",
  low_perfusion: "Tín hiệu quang yếu",
  unstable: "Đang xác nhận",
  sample_loss: "Mất mẫu PPG",
};

function ppgInvalidLabel(quality) {
  if (["valid", "legacy"].includes(quality.ppg_state)) return "Đang xác nhận";
  return ppgStateLabels[quality.ppg_state]
    || (quality.finger_present ? "Đang xác nhận" : "Chờ đặt ngón tay");
}

function confirmedMeasurement(latest, key, legacyValue) {
  const measurement = latest.measurements && latest.measurements[key];
  return measurement && Object.hasOwn(measurement, "confirmed_value")
    ? measurement.confirmed_value
    : legacyValue;
}

function clearLatest() {
  [elements.heartRate, elements.spo2, elements.wristTemp].forEach((item) => { item.textContent = "—"; });
  [elements.heartQuality, elements.spo2Quality, elements.wristTempQuality].forEach((item) => {
    item.className = "quality-label";
    item.textContent = "Chưa có dữ liệu";
  });
  elements.latestDataState.hidden = true;
  elements.qualitySummary.textContent = "Chưa có dữ liệu";
  elements.qualitySummary.className = "quality-badge";
  [elements.fingerState, elements.ppgQuality, elements.motionArtifact, elements.fallState,
    elements.rssi, elements.firmware, elements.bootId].forEach((item) => { item.textContent = "—"; });
  setMeasurementState("waiting", "Chưa có dữ liệu");
}

function deriveMeasurementState(latest, online) {
  if (!online) return ["stale", "Dữ liệu cũ"];
  const quality = latest.quality || {};
  const faults = latest.system && Array.isArray(latest.system.faults) ? latest.system.faults : [];
  const sensorFault = faults.some((fault) => /(unavailable|fault|error|timeout)/i.test(String(fault)));
  if (sensorFault) return ["fault", "Lỗi cảm biến"];
  if (!quality.finger_present) return ["waiting", "Chờ đặt ngón tay"];
  if (quality.motion_artifact) return ["noisy", "Có nhiễu chuyển động"];
  if (quality.ppg_state && !["valid", "legacy"].includes(quality.ppg_state)) {
    return ["measuring", ppgInvalidLabel(quality)];
  }
  const schema = latest.schema || latest.schema_version;
  const allValid = quality.heart_rate_valid && quality.spo2_valid
    && (!["health.telemetry.v3", "health.telemetry.v4"].includes(schema) || quality.wrist_surface_temp_valid);
  return allValid ? ["valid", "Mẫu hợp lệ"] : ["measuring", "Đang tích lũy mẫu"];
}

function renderLatest(latest, online) {
  if (!latest) {
    clearLatest();
    return;
  }
  const vitals = latest.vitals || {};
  const wearable = latest.wearable || {};
  const quality = latest.quality || {};
  const motion = latest.motion || {};
  const system = latest.system || {};
  const stale = !online;
  const schema = latest.schema || latest.schema_version;
  const isWearableV3 = ["health.telemetry.v3", "health.telemetry.v4"].includes(schema);

  elements.heartRate.textContent = formatNumber(
    confirmedMeasurement(latest, "heart_rate", vitals.heart_rate_bpm),
  );
  elements.spo2.textContent = formatNumber(
    confirmedMeasurement(latest, "spo2", vitals.spo2_pct),
    1,
  );
  elements.wristTemp.textContent = isWearableV3
    ? formatNumber(wearable.wrist_surface_temp_c, 1)
    : "—";

  if (stale) {
    [elements.heartQuality, elements.spo2Quality].forEach((item) => {
      item.className = "quality-label quality-warning";
      item.textContent = "Dữ liệu cũ";
    });
    elements.wristTempQuality.className = "quality-label quality-warning";
    elements.wristTempQuality.textContent = isWearableV3
      ? "Dữ liệu cũ"
      : "Không có trong telemetry v1/v2";
  } else {
    setQualityLabel(
      elements.heartQuality,
      quality.heart_rate_valid,
      ppgInvalidLabel(quality),
    );
    setQualityLabel(
      elements.spo2Quality,
      quality.spo2_valid,
      ppgInvalidLabel(quality),
    );
    if (isWearableV3) {
      setQualityLabel(elements.wristTempQuality, quality.wrist_surface_temp_valid, "DS18B20 không sẵn sàng");
    } else {
      elements.wristTempQuality.className = "quality-label";
      elements.wristTempQuality.textContent = "Không có trong telemetry v1/v2";
    }
  }

  const [measurementKey, measurementLabel] = deriveMeasurementState(latest, online);
  setMeasurementState(measurementKey, measurementLabel);
  const allValid = quality.heart_rate_valid && quality.spo2_valid
    && (!isWearableV3 || quality.wrist_surface_temp_valid);
  elements.qualitySummary.className = `quality-badge ${allValid && !stale ? "quality-good" : "quality-warning"}`;
  elements.qualitySummary.textContent = stale
    ? "Dữ liệu cũ"
    : (allValid ? "Dữ liệu hợp lệ" : measurementLabel);
  elements.latestDataState.hidden = !stale;
  elements.fingerState.textContent = quality.finger_present ? "Đã phát hiện" : "Chưa đặt ngón tay";
  const ppgStateText = ppgStateLabels[quality.ppg_state];
  elements.ppgQuality.textContent = Number.isFinite(quality.ppg)
    ? `${formatPercent(quality.ppg)}${ppgStateText ? ` · ${ppgStateText}` : ""}`
    : (ppgStateText || "Không có");
  elements.motionArtifact.textContent = quality.motion_artifact ? "Có nhiễu" : "Không phát hiện";
  elements.fallState.textContent = fallStateLabels[motion.fall_state] || motion.fall_state || "—";
  elements.rssi.textContent = Number.isFinite(system.rssi_dbm)
    ? `${formatNumber(system.rssi_dbm)} dBm${stale ? " (giá trị cuối)" : ""}`
    : (stale ? "Không có giá trị cuối" : "Không có");
  elements.firmware.textContent = system.fw || "—";
  elements.bootId.textContent = latest.boot_id || "—";
}

function metricValue(item, key) {
  const definition = chartDefinitions[key];
  const schema = item && (item.schema || item.schema_version);
  if (key === "wrist_surface_temp_c" && !["health.telemetry.v3", "health.telemetry.v4"].includes(schema)) return null;
  return item && definition && item[definition.group] ? item[definition.group][key] : null;
}

function metricIsValid(item, key) {
  const value = metricValue(item, key);
  if (!Number.isFinite(value)) return false;
  const quality = item.quality || {};
  return quality[chartDefinitions[key].validKey] !== false;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function sampleSegment(segment, targetCount) {
  if (segment.length <= targetCount || targetCount < 2) return segment;
  const indexes = new Set();
  for (let index = 0; index < targetCount; index += 1) {
    indexes.add(Math.round(index * (segment.length - 1) / (targetCount - 1)));
  }
  return [...indexes].sort((a, b) => a - b).map((index) => segment[index]);
}

function makeTableCell(text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

function renderChartTable(points, definition, validCount) {
  elements.chartTableBody.replaceChildren();
  if (!points.length) {
    const row = document.createElement("tr");
    const cell = makeTableCell("Chưa có mẫu hợp lệ.");
    cell.colSpan = 4;
    row.append(cell);
    elements.chartTableBody.append(row);
    elements.chartTableCaption.textContent = `Không có mẫu hợp lệ cho ${definition.label}.`;
    return;
  }
  points.forEach((point) => {
    const row = document.createElement("tr");
    row.append(
      makeTableCell(formatTime(point.item.received_at)),
      makeTableCell(`${formatNumber(point.value, definition.digits)} ${definition.unit}`),
      makeTableCell("Hợp lệ"),
      makeTableCell(formatInteger(point.item.seq)),
    );
    elements.chartTableBody.append(row);
  });
  elements.chartTableCaption.textContent = `${definition.label}: bảng hiển thị ${formatInteger(points.length)} trong ${formatInteger(validCount)} mẫu hợp lệ đang được biểu diễn.`;
}

function renderChart() {
  const key = elements.chartMetric.value;
  const definition = chartDefinitions[key];
  const timed = dashboardState.history
    .map((item, sourceIndex) => ({ item, sourceIndex, time: parseTime(item.received_at) }))
    .filter((point) => point.time !== null)
    .sort((a, b) => a.time - b.time);
  const intervals = [];
  for (let index = 1; index < timed.length; index += 1) {
    const interval = timed[index].time - timed[index - 1].time;
    if (interval > 0) intervals.push(interval);
  }
  const advertisedInterval = Number(dashboardState.historyMeta.interval_ms);
  const typicalInterval = Number.isFinite(advertisedInterval) && advertisedInterval > 0
    ? advertisedInterval
    : median(intervals);
  const gapThreshold = typicalInterval ? typicalInterval * 1.5 : Number.POSITIVE_INFINITY;
  const rawSegments = [];
  let currentSegment = [];
  let previousTimed = null;
  let gapCount = 0;
  let invalidCount = 0;

  timed.forEach((point) => {
    const gap = previousTimed && point.time - previousTimed.time > gapThreshold;
    if (gap) {
      gapCount += 1;
      if (currentSegment.length) rawSegments.push(currentSegment);
      currentSegment = [];
    }
    if (!metricIsValid(point.item, key)) {
      invalidCount += 1;
      if (currentSegment.length) rawSegments.push(currentSegment);
      currentSegment = [];
      previousTimed = point;
      return;
    }
    currentSegment.push({ ...point, value: metricValue(point.item, key) });
    previousTimed = point;
  });
  if (currentSegment.length) rawSegments.push(currentSegment);

  const validCount = rawSegments.reduce((count, segment) => count + segment.length, 0);
  const sampledSegments = rawSegments.map((segment) => {
    const share = validCount ? Math.round(MAX_CHART_POINTS * segment.length / validCount) : 2;
    return sampleSegment(segment, Math.max(2, share));
  });
  const sampledPoints = sampledSegments.flat();
  renderChartTable(sampledPoints, definition, validCount);

  const metadata = dashboardState.historyMeta || {};
  const total = Number.isFinite(Number(metadata.total_available))
    ? Number(metadata.total_available)
    : Number.isFinite(Number(metadata.total)) ? Number(metadata.total) : timed.length;
  const returned = Number.isFinite(Number(metadata.returned)) ? Number(metadata.returned) : dashboardState.history.length;
  const truncatedText = metadata.truncated === true
    ? "có cắt dữ liệu"
    : metadata.truncated === false ? "không cắt dữ liệu" : "API chưa công bố cắt dữ liệu";
  const serverDownsampling = metadata.downsampling || metadata.aggregation || "không công bố";
  const clientDownsampling = sampledPoints.length < validCount
    ? `giao diện chọn ${formatInteger(sampledPoints.length)}/${formatInteger(validCount)} mẫu hợp lệ`
    : "giao diện không giảm mẫu";
  const coverageStart = metadata.coverage_from || metadata.coverage_start || (timed[0] && timed[0].item.received_at);
  const coverageEnd = metadata.coverage_to || metadata.coverage_end || (timed[timed.length - 1] && timed[timed.length - 1].item.received_at);
  const requestedStart = metadata.requested_from;
  const requestedEnd = metadata.requested_to;
  const metricValidity = metadata.validity && metadata.validity[key];
  const windowValid = metricValidity && Number.isFinite(Number(metricValidity.valid))
    ? Number(metricValidity.valid) : validCount;
  const windowTotal = metricValidity && Number.isFinite(Number(metricValidity.total))
    ? Number(metricValidity.total) : total;
  elements.chartCoverage.textContent = [
    `Yêu cầu ${elements.windowSelect.options[elements.windowSelect.selectedIndex]?.textContent || dashboardState.selectedWindow}: ${formatTime(requestedStart)} → ${formatTime(requestedEnd)} (${localTimeZoneLabel()})`,
    `độ phủ ${formatTime(coverageStart)} → ${formatTime(coverageEnd)} (${localTimeZoneLabel()})`,
    `hợp lệ/tổng cửa sổ ${formatInteger(windowValid)}/${formatInteger(windowTotal)}`,
    `API ${formatInteger(returned)}/${formatInteger(total)}; ${truncatedText}`,
    `downsampling: ${serverDownsampling}; ${clientDownsampling}`,
    `gap: ${formatInteger(gapCount)}; invalid: ${formatInteger(invalidCount)}`,
  ].join(" · ");
  elements.chartWindowLabel.textContent = `${elements.windowSelect.options[elements.windowSelect.selectedIndex]?.textContent || "Khung đã chọn"} gần nhất`;

  elements.chartSeries.replaceChildren();
  if (validCount < 2 || sampledPoints.length < 2) {
    elements.chart.classList.remove("visible");
    elements.chartEmpty.hidden = false;
    elements.chartDesc.textContent = `Chưa đủ dữ liệu hợp lệ cho ${definition.label}.`;
    return;
  }

  const allValues = rawSegments.flat().map((point) => point.value);
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const padding = Math.max((rawMax - rawMin) * 0.12, key === "wrist_surface_temp_c" ? 0.2 : 1);
  const min = rawMin - padding;
  const max = rawMax + padding;
  const timeStart = timed[0].time;
  const timeEnd = timed[timed.length - 1].time;
  const timeSpan = Math.max(timeEnd - timeStart, 1);
  const xStart = 64;
  const xEnd = 876;
  const yTop = 28;
  const yBottom = 246;

  sampledSegments.filter((segment) => segment.length).forEach((segment) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const coordinates = segment.map((point) => {
      const x = xStart + ((point.time - timeStart) / timeSpan) * (xEnd - xStart);
      const y = yBottom - ((point.value - min) / (max - min)) * (yBottom - yTop);
      return { x, y };
    });
    const commands = coordinates
      .map(({ x, y }, index) => `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
      .join(" ");
    path.setAttribute("d", commands);
    path.setAttribute("class", "chart-line");
    elements.chartSeries.append(path);
    if (coordinates.length === 1) {
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      marker.setAttribute("cx", coordinates[0].x.toFixed(1));
      marker.setAttribute("cy", coordinates[0].y.toFixed(1));
      marker.setAttribute("r", "5");
      marker.setAttribute("class", "chart-point");
      elements.chartSeries.append(marker);
    }
  });

  elements.chartMax.textContent = formatNumber(max, definition.digits);
  elements.chartMid.textContent = formatNumber((max + min) / 2, definition.digits);
  elements.chartMin.textContent = formatNumber(min, definition.digits);
  elements.chartStartTime.textContent = formatAxisTime(timeStart);
  elements.chartEndTime.textContent = formatAxisTime(timeEnd);
  elements.chartDesc.textContent = `${definition.label}: ${formatNumber(rawMin, definition.digits)} đến ${formatNumber(rawMax, definition.digits)} ${definition.unit}; ${formatInteger(validCount)} mẫu hợp lệ trong ${formatInteger(timed.length)} mẫu, ${formatInteger(gapCount)} khoảng gián đoạn.`;
  elements.chartEmpty.hidden = true;
  elements.chart.classList.add("visible");
}

function getManifest(detail) {
  return detail && detail.manifest ? detail.manifest : (detail || {});
}

function getSummary(detail) {
  return detail && detail.summary ? detail.summary : {};
}

function getProfile(detail) {
  const manifest = getManifest(detail);
  return manifest && typeof manifest.profile === "object" ? manifest.profile : {};
}

function getProfileName(detail) {
  const manifest = getManifest(detail);
  const profile = getProfile(detail);
  return profile.name || (typeof manifest.profile === "string" ? manifest.profile : "");
}

function getRunId(detail) {
  const manifest = getManifest(detail);
  return manifest.run_id || (detail && detail.run_id) || "";
}

function renderCapabilities(payload) {
  dashboardState.capabilities = payload || null;
  const protocol = payload && payload.protocol;
  let namespace = payload && payload.topic_namespace;
  if (protocol && typeof protocol === "object") {
    const protocolName = [protocol.name, protocol.version].filter(Boolean).join(" ");
    elements.protocolValue.textContent = [protocolName, protocol.transport]
      .filter(Boolean)
      .join(" · ") || "Chưa công bố";
    namespace = protocol.topic_namespace || namespace;
  } else {
    elements.protocolValue.textContent = protocol ? String(protocol) : "Chưa công bố";
  }
  elements.topicNamespace.textContent = Array.isArray(namespace)
    ? namespace.join(" · ")
    : (namespace ? String(namespace) : "Chưa công bố");
}

function renderProfileOptions(capabilities, experiments) {
  const profiles = new Map();
  const configured = capabilities && Array.isArray(capabilities.profiles) ? capabilities.profiles : [];
  configured.forEach((profile) => {
    if (typeof profile === "string") profiles.set(profile, { name: profile });
    else if (profile && profile.name) profiles.set(profile.name, profile);
  });
  experiments.forEach((detail) => {
    const profile = getProfile(detail);
    const name = getProfileName(detail);
    if (name && !profiles.has(name)) profiles.set(name, { ...profile, name });
  });

  elements.profileSelect.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "Tất cả hồ sơ";
  elements.profileSelect.append(allOption);
  profiles.forEach((profile, name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = profile.description_vi ? `${name} — ${profile.description_vi}` : name;
    elements.profileSelect.append(option);
  });
  if (!profiles.has(dashboardState.selectedProfile)) dashboardState.selectedProfile = "";
  elements.profileSelect.value = dashboardState.selectedProfile;
}

function renderRunOptions(payload) {
  dashboardState.experiments = payload && Array.isArray(payload.data) ? payload.data : [];
  renderProfileOptions(dashboardState.capabilities, dashboardState.experiments);
  const filtered = dashboardState.selectedProfile
    ? dashboardState.experiments.filter((detail) => getProfileName(detail) === dashboardState.selectedProfile)
    : dashboardState.experiments;
  elements.runSelect.replaceChildren();
  if (!filtered.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = dashboardState.selectedProfile
      ? "Chưa có run cho hồ sơ này"
      : "Chưa có bộ minh chứng";
    elements.runSelect.append(option);
    dashboardState.selectedRun = "";
    return;
  }
  filtered.forEach((detail) => {
    const manifest = getManifest(detail);
    const runId = getRunId(detail);
    const option = document.createElement("option");
    option.value = runId;
    option.textContent = `${runId} · ${getProfileName(detail) || "không rõ profile"} · ${runStatusLabels[manifest.status] || manifest.status || "chưa rõ"}`;
    elements.runSelect.append(option);
  });
  if (!filtered.some((detail) => getRunId(detail) === dashboardState.selectedRun)) {
    dashboardState.selectedRun = getRunId(filtered[0]);
  }
  elements.runSelect.value = dashboardState.selectedRun;
}

function clearExperiment() {
  elements.experimentEmpty.hidden = false;
  elements.experimentEmpty.textContent = "Chưa có bộ minh chứng phù hợp. Chạy runner bên ngoài dashboard rồi làm mới dữ liệu.";
  elements.experimentContent.hidden = true;
  elements.experimentIdentity.textContent = "Không có run";
  setStateBadge(elements.experimentStatus, elements.experimentStatusText, "state-unknown", "Chưa chọn run");
  elements.experimentStatusDetail.textContent = "Chỉ hiển thị dữ liệu đã được runner ghi lại.";
  elements.experimentPrimaryLatency.textContent = "—";
  elements.experimentDiagnosticLatency.textContent = "—";
  elements.injectionPoint.textContent = "Không áp dụng";
  elements.impairmentNotice.hidden = true;
  elements.kpiClaimLabel.hidden = true;
}

function renderExperiment(detail) {
  if (!detail || !getRunId(detail)) {
    clearExperiment();
    return;
  }
  const manifest = getManifest(detail);
  const summary = getSummary(detail);
  const profile = getProfile(detail);
  if (summary.run_id && manifest.run_id && summary.run_id !== manifest.run_id) {
    elements.experimentEmpty.hidden = false;
    elements.experimentEmpty.textContent = "Bộ minh chứng không nhất quán: run_id trong manifest và summary không khớp.";
    elements.experimentContent.hidden = true;
    elements.experimentIdentity.textContent = manifest.run_id;
    setStateBadge(elements.experimentStatus, elements.experimentStatusText, "state-offline", "Minh chứng lỗi");
    elements.experimentStatusDetail.textContent = "Dashboard đã chặn KPI để tránh tổng hợp chéo run.";
    elements.impairmentNotice.hidden = true;
    elements.kpiClaimLabel.hidden = true;
    return;
  }
  if (summary.status && manifest.status && summary.status !== manifest.status) {
    elements.experimentEmpty.hidden = false;
    elements.experimentEmpty.textContent = "Bộ minh chứng chưa finalize: trạng thái manifest và summary không khớp.";
    elements.experimentContent.hidden = true;
    elements.experimentIdentity.textContent = manifest.run_id || summary.run_id || "Run không rõ";
    setStateBadge(elements.experimentStatus, elements.experimentStatusText, "state-offline", "Minh chứng lỗi");
    elements.experimentStatusDetail.textContent = "Dashboard đã chặn KPI của run đang chuyển trạng thái.";
    elements.impairmentNotice.hidden = true;
    elements.kpiClaimLabel.hidden = true;
    return;
  }
  const profileName = getProfileName(detail) || "không rõ";
  const status = manifest.status || summary.status || "partial";
  const statusLabel = runStatusLabels[status] || status;
  const statusClass = status === "completed"
    ? "state-online"
    : (status === "running" || status === "planned" || status === "partial" ? "state-degraded" : "state-offline");
  setStateBadge(elements.experimentStatus, elements.experimentStatusText, statusClass, statusLabel);
  elements.experimentStatusDetail.textContent = `Run ${getRunId(detail)} · tạo ${formatTime(manifest.created_at)}.`;
  announceStateTransition("Thí nghiệm", statusLabel);

  elements.experimentEmpty.hidden = true;
  elements.experimentContent.hidden = false;
  elements.experimentIdentity.textContent = `${getRunId(detail)} · seed ${manifest.seed ?? "—"} · ${formatInteger(manifest.count)} lịch phát`;
  elements.experimentScenario.textContent = manifest.scenario || "—";
  elements.experimentProfile.textContent = profile.description_vi
    ? `${profileName} — ${profile.description_vi}`
    : profileName;
  elements.experimentClock.textContent = manifest.clock_domain || "Chưa công bố";
  elements.experimentPolling.textContent = Number.isFinite(summary.polling_resolution_ms || manifest.polling_resolution_ms)
    ? `${formatInteger(summary.polling_resolution_ms || manifest.polling_resolution_ms)} ms`
    : "Chưa công bố";
  const claims = manifest.claims || {};
  elements.experimentPrimaryLatency.textContent = claims.primary_latency_kind === "schedule_to_api_polling_upper_bound"
    ? "schedule → API polling upper-bound"
    : "Không hợp lệ";
  elements.experimentDiagnosticLatency.textContent = claims.diagnostic_latency_kind === "publish_to_api_polling_upper_bound"
    ? "publish → API polling upper-bound"
    : "Không hợp lệ";

  const logicalAttempted = Number(summary.unique_logical_publish_attempted);
  const observed = Number(summary.api_observed);
  const scheduled = Number(summary.scheduled);
  const scheduledObservationRatio = Number(summary.scheduled_observation_ratio);
  const attemptedDeliveryRatio = Number(summary.attempted_delivery_ratio);
  const attemptCount = Number(summary.attempt_count);
  const intentionallyDropped = Number(summary.intentionally_dropped);
  const isPlanned = status === "planned";
  elements.kpiDeliveryRatio.textContent = isPlanned ? "Chưa đo" : formatPercent(scheduledObservationRatio);
  elements.kpiDeliveryDetail.textContent = isPlanned
    ? "Run planned; chưa có observation"
    : Number.isFinite(scheduled)
      ? `${formatInteger(observed)} API observed / ${formatInteger(scheduled)} scheduled · attempted delivery ${formatPercent(attemptedDeliveryRatio)}`
      : "Chưa có mẫu số";
  elements.kpiObserved.textContent = isPlanned
    ? "Chưa đo"
    : Number.isFinite(logicalAttempted) ? `${formatInteger(observed)} / ${formatInteger(logicalAttempted)}` : "—";
  elements.kpiAttempts.textContent = isPlanned
    ? "Chưa có attempt vật lý"
    : `${formatInteger(attemptCount)} attempt vật lý · ${formatInteger(intentionallyDropped)} intentionally dropped`;

  const percentileCount = Number(summary.schedule_to_api_latency_sample_count);
  const percentilesAvailable = summary.percentiles_available === true && percentileCount >= 20;
  elements.kpiP50.textContent = isPlanned
    ? "Chưa đo"
    : percentilesAvailable && Number.isFinite(summary.schedule_to_api_upper_bound_p50_ms)
      ? `${formatNumber(summary.schedule_to_api_upper_bound_p50_ms, 1)} ms`
      : "Chưa đủ mẫu";
  elements.kpiP95.textContent = isPlanned
    ? "Chưa đo"
    : percentilesAvailable && Number.isFinite(summary.schedule_to_api_upper_bound_p95_ms)
      ? `${formatNumber(summary.schedule_to_api_upper_bound_p95_ms, 1)} ms`
      : "Chưa đủ mẫu";

  const profileKind = profile.profile_kind || manifest.profile_kind;
  const networkClaim = summary.network_claim || profile.network_claim || manifest.network_claim;
  const appImpairment = profileKind === "app_impairment" || networkClaim === "none";
  elements.impairmentNotice.hidden = !appImpairment;
  elements.kpiClaimLabel.hidden = !appImpairment;
  elements.injectionPoint.textContent = profile.injection_point || manifest.injection_point || "Không công bố";
}

function makeAlertItem(alert, active) {
  const article = document.createElement("article");
  const severity = alert.severity === "critical" ? "critical" : "warning";
  article.className = `alert-item ${severity}`;

  const marker = document.createElement("span");
  marker.className = "severity-marker";
  marker.textContent = severity === "critical" ? "NGHIÊM TRỌNG" : "CẢNH BÁO";

  const body = document.createElement("div");
  const title = document.createElement("p");
  title.className = "alert-title";
  title.textContent = alert.message || "Cảnh báo không có mô tả";
  const meta = document.createElement("p");
  meta.className = "alert-meta";
  const stateText = alert.state === "acknowledged"
    ? "Đã xem"
    : alert.state === "resolved" ? "Đã kết thúc" : "Chưa xem";
  const session = alert.boot_id || alert.session_id || "chưa công bố";
  meta.textContent = `${alert.device_id || dashboardState.selectedDevice || "không rõ thiết bị"} · session ${session} · ${stateText} · lần cuối ${formatTime(alert.last_seen_at)} · ${formatInteger(alert.occurrence_count)} lần`;
  body.append(title, meta);
  article.append(marker, body);

  if (active) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ack-button";
    button.textContent = alert.state === "acknowledged" ? "Đã xem" : "Đánh dấu đã xem";
    button.disabled = alert.state === "acknowledged";
    button.addEventListener("click", () => openAckDialog(alert, button));
    article.append(button);
  }
  return article;
}

function renderUnavailableAlertState(container) {
  container.replaceChildren();
  const message = document.createElement("p");
  message.className = "empty-state";
  message.textContent = "Không thể xác nhận cảnh báo. Hãy thử làm mới dữ liệu.";
  container.append(message);
}

function announceNewAlerts(alerts) {
  const currentIds = new Set(alerts.map((alert) => alert.id).filter(Boolean));
  if (dashboardState.alertsInitialized) {
    const newCount = [...currentIds].filter((id) => !dashboardState.knownAlertIds.has(id)).length;
    if (newCount > 0) {
      elements.stateAnnouncer.textContent = `${formatInteger(newCount)} cảnh báo mới.`;
    }
  }
  dashboardState.knownAlertIds = currentIds;
  dashboardState.alertsInitialized = true;
}

function renderAlerts(container, alerts, active) {
  container.replaceChildren();
  if (!alerts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = active ? "Chưa có cảnh báo đang hoạt động." : "Chưa có lịch sử cảnh báo.";
    container.append(empty);
    return;
  }
  alerts.forEach((alert) => container.append(makeAlertItem(alert, active)));
}

function openAckDialog(alert, trigger) {
  dashboardState.ackAlertId = alert.id;
  dashboardState.ackTrigger = trigger;
  elements.ackActor.value = "";
  elements.ackNote.value = "";
  elements.ackError.textContent = "";
  elements.ackConfirm.disabled = false;
  elements.ackConfirm.textContent = "Ghi nhận đã xem";
  if (typeof elements.ackDialog.showModal === "function") {
    elements.ackDialog.showModal();
    elements.ackActor.focus();
  }
}

function closeAckDialog() {
  if (elements.ackDialog.open && typeof elements.ackDialog.close === "function") {
    elements.ackDialog.close();
  }
}

async function submitAcknowledgement(event) {
  event.preventDefault();
  const actor = elements.ackActor.value.trim();
  if (!actor) {
    elements.ackError.textContent = "Nhập tên người đánh dấu để tiếp tục.";
    elements.ackActor.focus();
    return;
  }
  elements.ackError.textContent = "";
  elements.ackConfirm.disabled = true;
  elements.ackConfirm.textContent = "Đang ghi nhận…";
  try {
    const response = await fetchWithTimeout(`/api/v1/alerts/${encodeURIComponent(dashboardState.ackAlertId)}/ack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor,
        note: elements.ackNote.value.trim() || "Đã xem trên dashboard",
      }),
    });
    if (response.status === 409) {
      elements.ackError.textContent = "Cảnh báo đã tự kết thúc. Đóng hộp thoại và làm mới danh sách.";
      return;
    }
    if (!response.ok) throw new DashboardRequestError("http", `HTTP ${response.status}`, undefined, response.status);
    closeAckDialog();
    setDashboardMessage("Đã ghi nhận: Đã xem. Cảnh báo vẫn hoạt động cho tới khi dữ liệu hồi phục.");
    elements.stateAnnouncer.textContent = "Đã ghi nhận cảnh báo là đã xem.";
    await refreshDashboard("ack");
  } catch (error) {
    console.warn("alert_ack_failed", error);
    elements.ackError.textContent = "Không thể ghi nhận lúc này. Kiểm tra Edge rồi thử lại.";
  } finally {
    elements.ackConfirm.disabled = false;
    elements.ackConfirm.textContent = "Ghi nhận đã xem";
  }
}

function renderDeviceOptions(payload) {
  const devices = payload && Array.isArray(payload.data) ? payload.data : [];
  elements.deviceSelect.replaceChildren();
  if (!devices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Chưa có thiết bị";
    elements.deviceSelect.append(option);
    dashboardState.selectedDevice = "";
    return;
  }
  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.device_id;
    option.textContent = `${device.device_id} — ${device.online ? "trực tuyến" : "ngoại tuyến"}`;
    elements.deviceSelect.append(option);
  });
  if (!devices.some((device) => device.device_id === dashboardState.selectedDevice)) {
    dashboardState.selectedDevice = devices[0].device_id;
  }
  elements.deviceSelect.value = dashboardState.selectedDevice;
}

function clearDashboardContext() {
  clearLatest();
  dashboardState.history = [];
  dashboardState.historyMeta = {};
  renderChart();
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Không thể xác nhận thiết bị";
  elements.deviceSelect.replaceChildren(option);
  elements.deviceSelect.value = "";
  setStateBadge(elements.connectionPill, elements.connectionText, "state-unknown", "Không xác định");
  announceStateTransition("Node", "Không xác định");
  elements.lastUpdate.textContent = "Không thể xác nhận thời điểm cập nhật.";
  renderUnavailableAlertState(elements.activeAlerts);
  renderUnavailableAlertState(elements.resolvedAlerts);
  elements.alertCount.textContent = "— cảnh báo";
}

function syncUrlState() {
  if (!window.history || typeof window.history.replaceState !== "function") return;
  const params = new URLSearchParams(window.location.search || "");
  const values = {
    device: dashboardState.selectedDevice,
    run: dashboardState.selectedRun,
    profile: dashboardState.selectedProfile,
    window: dashboardState.selectedWindow,
    metric: dashboardState.selectedMetric,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
    else params.delete(key);
  });
  const query = params.toString();
  const nextUrl = `${window.location.pathname || "/"}${query ? `?${query}` : ""}${window.location.hash || ""}`;
  window.history.replaceState(null, "", nextUrl);
}

function setRefreshBusy(busy) {
  elements.refreshButton.disabled = busy;
  elements.refreshButton.textContent = busy ? "Đang làm mới…" : "Làm mới dữ liệu";
  elements.refreshButton.setAttribute("aria-busy", busy ? "true" : "false");
}

function scheduleNextRefresh() {
  if (dashboardState.refreshTimer) window.clearTimeout(dashboardState.refreshTimer);
  if (document.hidden) return;
  const delay = Math.min(BASE_POLL_MS * (2 ** dashboardState.consecutiveFailures), MAX_POLL_MS);
  dashboardState.refreshTimer = window.setTimeout(() => refreshDashboard("poll"), delay);
}

function settledValue(result) {
  return result.status === "fulfilled" ? result.value : null;
}

async function refreshDashboard(reason = "manual") {
  if (document.hidden && reason === "poll") return;
  dashboardState.refreshGeneration += 1;
  const generation = dashboardState.refreshGeneration;
  if (dashboardState.refreshController) dashboardState.refreshController.abort();
  const controller = new AbortController();
  dashboardState.refreshController = controller;
  if (dashboardState.refreshTimer) window.clearTimeout(dashboardState.refreshTimer);
  const showBusy = reason !== "poll";
  if (showBusy) setRefreshBusy(true);
  let refreshStage = "devices_request";
  let succeeded = false;
  let cancelled = false;

  try {
    const devices = await fetchJson("/api/v1/devices", { cache: "no-store" }, controller.signal);
    if (generation !== dashboardState.refreshGeneration) return;
    refreshStage = "render";
    renderDeviceOptions(devices);
    syncUrlState();

    const query = new URLSearchParams({ window: dashboardState.selectedWindow });
    if (dashboardState.selectedDevice) query.set("device_id", dashboardState.selectedDevice);
    refreshStage = "overview_request";
    const [overviewResult, healthResult, runtimeResult, capabilitiesResult, experimentsResult] = await Promise.allSettled([
      fetchJson(`/api/v1/overview?${query.toString()}`, { cache: "no-store" }, controller.signal),
      fetchJson("/healthz", { cache: "no-store" }, controller.signal),
      fetchJson("/api/v1/runtime", { cache: "no-store" }, controller.signal),
      fetchJson("/api/v1/capabilities", { cache: "no-store" }, controller.signal),
      // Strict registry validation reads raw JSONL. Keep the interactive picker
      // to the ten newest runs; the full study is consumed by the aggregate.
      fetchJson("/api/v1/experiments?limit=10", { cache: "no-store" }, controller.signal),
    ]);
    if (generation !== dashboardState.refreshGeneration) return;
    if (overviewResult.status === "rejected") throw overviewResult.reason;

    refreshStage = "render";
    const overview = overviewResult.value;
    setEdgeState(settledValue(healthResult), settledValue(runtimeResult), true);
    setConnection(overview.device);
    renderLatest(overview.latest, Boolean(overview.device && overview.device.online));
    dashboardState.history = Array.isArray(overview.history) ? overview.history : [];
    dashboardState.historyMeta = overview.history_meta
      || overview.history_metadata
      || (overview.metadata && overview.metadata.history)
      || {};
    renderChart();
    const activeAlerts = Array.isArray(overview.alerts) ? overview.alerts : [];
    renderAlerts(elements.activeAlerts, activeAlerts, true);
    announceNewAlerts(activeAlerts);
    elements.alertCount.textContent = `${formatInteger(activeAlerts.length)} cảnh báo`;

    const capabilities = settledValue(capabilitiesResult);
    renderCapabilities(capabilities);
    const experiments = settledValue(experimentsResult) || { data: [], total: 0 };
    renderRunOptions(experiments);
    syncUrlState();

    let selectedDetail = dashboardState.experiments.find((item) => getRunId(item) === dashboardState.selectedRun) || null;
    if (dashboardState.selectedRun) {
      try {
        const fetchedDetail = await fetchJson(
          `/api/v1/experiments/${encodeURIComponent(dashboardState.selectedRun)}`,
          { cache: "no-store" },
          controller.signal,
        );
        if (generation !== dashboardState.refreshGeneration) return;
        selectedDetail = fetchedDetail;
      } catch (error) {
        console.warn("experiment_detail_refresh_failed", error);
      }
    }
    renderExperiment(selectedDetail);

    if (dashboardState.selectedDevice) {
      try {
        const resolved = await fetchJson(
          `/api/v1/alerts?state=resolved&device_id=${encodeURIComponent(dashboardState.selectedDevice)}&limit=5`,
          { cache: "no-store" },
          controller.signal,
        );
        if (generation !== dashboardState.refreshGeneration) return;
        renderAlerts(elements.resolvedAlerts, resolved.data || [], false);
      } catch (error) {
        console.warn("resolved_alerts_refresh_failed", error);
        renderUnavailableAlertState(elements.resolvedAlerts);
      }
    } else {
      renderAlerts(elements.resolvedAlerts, [], false);
    }

    const optionalFailures = [healthResult, runtimeResult, capabilitiesResult, experimentsResult]
      .filter((result) => result.status === "rejected").length;
    if (optionalFailures > 0) {
      setDashboardMessage("Dữ liệu node đã tải, nhưng một số metadata runtime/thí nghiệm chưa sẵn sàng. Hệ thống sẽ tự thử lại.");
    } else if (!elements.dashboardMessage.textContent.includes("Đã ghi nhận")) {
      setDashboardMessage();
    }
    elements.refreshTime.textContent = formatTime(overview.generated_at || new Date().toISOString());
    dashboardState.consecutiveFailures = 0;
    succeeded = true;
  } catch (error) {
    if (generation !== dashboardState.refreshGeneration) return;
    if (controller.signal.aborted) {
      cancelled = true;
      return;
    }
    console.error("dashboard_refresh_failed", error);
    clearDashboardContext();
    setEdgeState(null, null, false);
    const renderFailure = refreshStage === "render";
    const responseFailure = error instanceof DashboardRequestError
      && (error.kind === "http" || error.kind === "invalid_json");
    setDashboardMessage(
      renderFailure
        ? "Edge đã gửi dữ liệu nhưng giao diện không thể hiển thị. Hãy tải lại trang."
        : responseFailure
          ? "Edge có phản hồi nhưng dữ liệu trả về không hợp lệ. Hệ thống sẽ tự thử lại."
          : "Không tải được dữ liệu Edge. Hệ thống sẽ tự thử lại với khoảng chờ tăng dần.",
      true,
    );
    dashboardState.consecutiveFailures = Math.min(dashboardState.consecutiveFailures + 1, 4);
  } finally {
    if (generation === dashboardState.refreshGeneration) {
      if (showBusy) setRefreshBusy(false);
      if (!cancelled) scheduleNextRefresh();
      if (!succeeded && !cancelled) elements.refreshTime.textContent = "Đồng bộ thất bại";
    }
  }
}

function refreshFromControlChange() {
  syncUrlState();
  refreshDashboard("control");
}

elements.deviceSelect.addEventListener("change", () => {
  dashboardState.selectedDevice = elements.deviceSelect.value;
  refreshFromControlChange();
});

elements.runSelect.addEventListener("change", () => {
  dashboardState.selectedRun = elements.runSelect.value;
  refreshFromControlChange();
});

elements.profileSelect.addEventListener("change", () => {
  dashboardState.selectedProfile = elements.profileSelect.value;
  dashboardState.selectedRun = "";
  refreshFromControlChange();
});

elements.windowSelect.addEventListener("change", () => {
  dashboardState.selectedWindow = elements.windowSelect.value;
  refreshFromControlChange();
});

elements.chartMetric.addEventListener("change", () => {
  dashboardState.selectedMetric = elements.chartMetric.value;
  syncUrlState();
  renderChart();
});

elements.refreshButton.addEventListener("click", () => refreshDashboard("manual"));
elements.ackForm.addEventListener("submit", submitAcknowledgement);
elements.ackCancel.addEventListener("click", closeAckDialog);
elements.ackDialog.addEventListener("close", () => {
  if (dashboardState.ackTrigger && typeof dashboardState.ackTrigger.focus === "function") {
    dashboardState.ackTrigger.focus();
  }
  dashboardState.ackTrigger = null;
  dashboardState.ackAlertId = "";
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (dashboardState.refreshTimer) window.clearTimeout(dashboardState.refreshTimer);
    if (dashboardState.refreshController) dashboardState.refreshController.abort();
    elements.refreshTime.textContent = "Tạm dừng khi tab ẩn";
  } else {
    refreshDashboard("visible");
  }
});

window.addEventListener("popstate", () => {
  const urlState = readUrlState();
  dashboardState.selectedDevice = urlState.device;
  dashboardState.selectedRun = urlState.run;
  dashboardState.selectedProfile = urlState.profile;
  dashboardState.selectedWindow = urlState.window;
  dashboardState.selectedMetric = urlState.metric;
  elements.windowSelect.value = dashboardState.selectedWindow;
  elements.chartMetric.value = dashboardState.selectedMetric;
  refreshDashboard("history");
});

clearLatest();
clearExperiment();
refreshDashboard("initial");
