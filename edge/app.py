from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
from typing import Annotated, Any, AsyncIterator, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import AlertAlreadyResolvedError, Database, isoformat_utc, utc_now
from .experiments import ExperimentNotFoundError, ExperimentRegistry
from .mqtt_client import EdgeMqttClient
from .notifications import TelegramApiClient, TelegramNotifier
from .rules import RuleEngine
from .schemas import AckRequest, DeviceCommand, OpenProvisioningRequest
from .service import IngestionService
from simulator.mqtt_simulator import SCENARIOS
from simulator.network_profiles import public_profiles


STATIC_DIR = Path(__file__).with_name("static")
WINDOW_RE = re.compile(r"^(?P<minutes>[1-9][0-9]*)(?:m)?$")
STATIC_ASSET_NAMES = ("favicon.svg", "styles.css", "app.js")
COMMAND_TTL_MS = 30_000
UINT32_MODULUS = 2**32


def _dashboard_asset_version() -> str:
    digest = sha256()
    for name in STATIC_ASSET_NAMES:
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


DASHBOARD_ASSET_VERSION = _dashboard_asset_version()
DASHBOARD_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace(
    "__ASSET_VERSION__", DASHBOARD_ASSET_VERSION
)


def _parse_window_minutes(value: str) -> int:
    match = WINDOW_RE.fullmatch(value.strip())
    if not match:
        raise HTTPException(
            status_code=422,
            detail="window phải là số phút, ví dụ 15 hoặc 15m",
        )
    minutes = int(match.group("minutes"))
    if minutes > 1440:
        raise HTTPException(status_code=422, detail="window phải từ 1 đến 1440 phút")
    return minutes


def _effective_device(device: dict[str, Any], offline_after_seconds: float) -> dict[str, Any]:
    result = dict(device)
    last_seen = result.get("last_seen_at")
    if result.get("online") and last_seen:
        parsed = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        result["online"] = (utc_now() - parsed).total_seconds() <= offline_after_seconds
        if not result["online"]:
            result["connection_reason"] = "telemetry_timeout"
    elif not result.get("online"):
        result["connection_reason"] = result.get("status_reason") or "offline"
    return result


def _stop_runtime_services(
    mqtt_client: EdgeMqttClient | None,
    ingestion: IngestionService,
    notifier: TelegramNotifier | None,
) -> None:
    try:
        if mqtt_client:
            mqtt_client.stop()
    finally:
        try:
            ingestion.stop()
        finally:
            if notifier:
                notifier.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(
        settings.database_path,
        telemetry_retention_rows=settings.telemetry_retention_rows,
    )
    rules = RuleEngine(database, settings.rules)
    notifier: TelegramNotifier | None = None
    if settings.telegram_enabled:
        bot_token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if bot_token is None or chat_id is None:  # Guard the validated Settings invariant.
            raise ValueError("Telegram credentials are required when notifications are enabled")
        notifier = TelegramNotifier(
            client=TelegramApiClient(
                bot_token=bot_token,
                chat_id=chat_id,
                timeout_seconds=settings.telegram_request_timeout_seconds,
            ),
            queue_size=settings.telegram_queue_size,
            max_attempts=settings.telegram_max_attempts,
            retry_base_seconds=settings.telegram_retry_base_seconds,
            retry_max_seconds=settings.telegram_retry_max_seconds,
            shutdown_timeout_seconds=settings.telegram_shutdown_timeout_seconds,
        )
    ingestion = IngestionService(
        database,
        rules,
        queue_size=settings.queue_size,
        max_payload_bytes=settings.max_payload_bytes,
        notifier=notifier,
    )
    mqtt_client = EdgeMqttClient(settings, ingestion) if settings.mqtt_enabled else None
    experiments = ExperimentRegistry(settings.experiment_evidence_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        if notifier:
            notifier.start()
        try:
            ingestion.start()
            if mqtt_client:
                mqtt_client.start()
            yield
        finally:
            _stop_runtime_services(mqtt_client, ingestion, notifier)

    app = FastAPI(
        title="IoT Health Edge API",
        version="1.0.0",
        description="API cục bộ cho prototype phi lâm sàng; không dùng để chẩn đoán.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.rules = rules
    app.state.ingestion = ingestion
    app.state.mqtt = mqtt_client
    app.state.notifications = notifier
    app.state.experiments = experiments

    def runtime_health_snapshot() -> dict[str, Any]:
        """Return one health truth used by both machine- and UI-facing APIs."""
        db_ok = database.is_healthy()
        ingestion_health = ingestion.metrics()
        mqtt_health = (
            mqtt_client.health()
            if mqtt_client
            else {
                "enabled": False,
                "connected": False,
                "subscribed": False,
                "last_error": None,
            }
        )
        ingestion_ok = bool(ingestion_health.get("worker_alive")) and not bool(
            ingestion_health.get("processing_errors")
        )
        mqtt_ok = not mqtt_client or bool(
            mqtt_health.get("connected") and mqtt_health.get("subscribed")
        )
        return {
            "status": "ok" if db_ok and ingestion_ok and mqtt_ok else "degraded",
            "database_healthy": db_ok,
            "ingestion": ingestion_health,
            "mqtt": mqtt_health,
        }

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if (
            request.url.path == "/"
            or request.url.path.startswith("/static/")
            or request.url.path.startswith("/api/")
            or request.url.path == "/healthz"
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        snapshot = runtime_health_snapshot()
        ingestion_health = snapshot["ingestion"]
        mqtt_health = snapshot["mqtt"]
        ingestion_public = {
            key: value
            for key, value in ingestion_health.items()
            if key != "last_error"
        }
        ingestion_public["has_error"] = bool(ingestion_health.get("last_error"))
        mqtt_public = {
            key: value for key, value in mqtt_health.items() if key != "last_error"
        }
        mqtt_public["has_error"] = bool(mqtt_health.get("last_error"))
        return {
            "status": snapshot["status"],
            "database": {"healthy": snapshot["database_healthy"]},
            "mqtt": mqtt_public,
            "ingestion": ingestion_public,
            "non_clinical": True,
        }

    @app.get("/api/v1/runtime")
    def runtime() -> dict[str, Any]:
        snapshot = runtime_health_snapshot()
        ingestion_health = snapshot["ingestion"]
        mqtt_health = snapshot["mqtt"]
        ingestion_public = {
            key: ingestion_health[key]
            for key in (
                "accepted",
                "duplicates",
                "rejected",
                "queue_dropped",
                "processing_errors",
                "queue_depth",
                "worker_alive",
            )
            if key in ingestion_health
        }
        mqtt_public = {
            key: mqtt_health[key]
            for key in ("enabled", "connected", "subscribed")
            if key in mqtt_health
        }
        return {
            "generated_at": isoformat_utc(utc_now()),
            "edge": {
                "status": snapshot["status"],
                "database_healthy": snapshot["database_healthy"],
            },
            "mqtt": mqtt_public,
            "ingestion": ingestion_public,
            "sanitized": True,
        }

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "course_track": "IoT Protocol",
            "protocol": {
                "name": "MQTT",
                "version": "3.1.1",
                "transport": "TCP",
                "topic_namespace": "iot-health/v1/devices/{device_id}/{stream}",
                "streams": ["telemetry", "event", "status"],
                "command_topic_namespace": (
                    "iot-health/v1/devices/{device_id}/command/{boot_id}"
                ),
                "command": {
                    "schema": "health.command.v1",
                    "actions": ["open_provisioning"],
                    "qos": 1,
                    "retain": False,
                    "execution_receipt_reason": "provisioning_started",
                },
            },
            "scenarios": list(SCENARIOS),
            "profiles": public_profiles(),
            "claims": {
                "non_clinical": True,
                "measured_5g": False,
                "app_impairment_is_network_measurement": False,
                "primary_latency_kind": "schedule_to_api_polling_upper_bound",
                "diagnostic_latency_kind": "publish_to_api_polling_upper_bound",
            },
        }

    @app.get("/api/v1/experiments")
    def list_experiments(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        items = experiments.list_runs(limit=limit)
        return {"data": items, "total": len(items)}

    @app.get("/api/v1/experiments/{run_id}")
    def get_experiment(run_id: str) -> dict[str, Any]:
        try:
            return experiments.get_run(run_id)
        except ExperimentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm") from exc

    @app.get("/api/v1/devices")
    def list_devices() -> dict[str, Any]:
        devices = [
            _effective_device(item, settings.offline_after_seconds)
            for item in database.list_devices()
        ]
        return {"data": devices, "total": len(devices)}

    @app.get("/api/v1/devices/{device_id}")
    def get_device(device_id: str) -> dict[str, Any]:
        device = database.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
        return _effective_device(device, settings.offline_after_seconds)

    @app.post(
        "/api/v1/devices/{device_id}/commands/open-provisioning",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def open_provisioning(
        device_id: str,
        body: OpenProvisioningRequest | None = None,
    ) -> dict[str, Any]:
        device = database.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")

        command_mqtt = app.state.mqtt
        mqtt_health = command_mqtt.health() if command_mqtt is not None else {}
        if not (
            command_mqtt is not None
            and mqtt_health.get("connected") is True
            and mqtt_health.get("subscribed") is True
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Kênh lệnh MQTT chưa sẵn sàng",
            )

        now = utc_now()
        effective = _effective_device(device, settings.offline_after_seconds)
        last_status_at = device.get("last_status_at")
        if not effective.get("online") or not last_status_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thiết bị không có trạng thái trực tuyến còn mới",
            )
        status_received = datetime.fromisoformat(last_status_at.replace("Z", "+00:00"))
        status_age_seconds = (now - status_received).total_seconds()
        if status_age_seconds < 0 or status_age_seconds > settings.offline_after_seconds:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Trạng thái trực tuyến của thiết bị đã cũ",
            )
        if (
            device.get("last_status_reason") != "heartbeat"
            or device.get("last_status_retained") is not False
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chưa nhận heartbeat trực tiếp, không-retained của thiết bị",
            )

        boot_id = device.get("boot_id")
        stored_session = device.get("command_session_id")
        if not boot_id or not stored_session:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Thiết bị chưa công bố command session hiện tại",
            )
        try:
            command_session_id = UUID(stored_session)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Command session hiện tại không hợp lệ",
            ) from exc
        if (
            body is not None
            and body.expected_command_session_id is not None
            and body.expected_command_session_id != command_session_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Command session đã thay đổi; hãy tải lại trạng thái thiết bị",
            )

        latest = database.latest_telemetry(device_id)
        if latest is None or latest.get("boot_id") != boot_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chưa có telemetry của boot hiện tại để tính hạn lệnh",
            )
        latest_received = datetime.fromisoformat(
            str(latest["received_at"]).replace("Z", "+00:00")
        )
        telemetry_age_seconds = (now - latest_received).total_seconds()
        if (
            telemetry_age_seconds < 0
            or telemetry_age_seconds > settings.offline_after_seconds
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Telemetry của boot hiện tại đã cũ",
            )
        estimated_uptime_ms = (
            int(latest["uptime_ms"]) + int(telemetry_age_seconds * 1000)
        ) % UINT32_MODULUS
        expires_uptime_ms = (estimated_uptime_ms + COMMAND_TTL_MS) % UINT32_MODULUS
        command = DeviceCommand(
            schema="health.command.v1",
            device_id=device_id,
            target_boot_id=boot_id,
            command_id=uuid4(),
            command_session_id=command_session_id,
            action="open_provisioning",
            expires_uptime_ms=expires_uptime_ms,
        )
        try:
            mid = command_mqtt.publish_command(command)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Không thể xếp lệnh MQTT vào hàng gửi",
            ) from exc
        return {
            **command.model_dump(mode="json", by_alias=True),
            "qos": 1,
            "retain": False,
            "mqtt_mid": mid,
            "broker_acked": True,
            "execution_acknowledged": False,
        }

    @app.get("/api/v1/devices/{device_id}/latest")
    def get_latest(device_id: str) -> dict[str, Any]:
        if database.get_device(device_id) is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
        latest = database.latest_telemetry(device_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="Thiết bị chưa có dữ liệu")
        return latest

    @app.get("/api/v1/devices/{device_id}/telemetry")
    def telemetry_history(
        device_id: str,
        from_time: datetime | None = Query(default=None, alias="from"),
        to_time: datetime | None = Query(default=None, alias="to"),
        limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    ) -> dict[str, Any]:
        if database.get_device(device_id) is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
        items = database.telemetry_history(
            device_id,
            from_time=isoformat_utc(from_time) if from_time else None,
            to_time=isoformat_utc(to_time) if to_time else None,
            limit=limit,
        )
        return {"data": items, "total": len(items)}

    @app.get("/api/v1/alerts")
    def list_alerts(
        state_filter: Literal["active", "open", "acknowledged", "resolved"] | None = Query(
            default=None, alias="state"
        ),
        device_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        items = database.list_alerts(
            state=state_filter, device_id=device_id, limit=limit
        )
        return {"data": items, "total": len(items)}

    @app.get("/api/v1/alerts/{alert_id}")
    def get_alert(alert_id: str) -> dict[str, Any]:
        alert = database.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo")
        return alert

    @app.post("/api/v1/alerts/{alert_id}/ack")
    def acknowledge_alert(alert_id: str, body: AckRequest) -> dict[str, Any]:
        try:
            alert = database.acknowledge_alert(alert_id, body.actor, body.note)
        except AlertAlreadyResolvedError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cảnh báo đã được hệ thống tự kết thúc",
            ) from exc
        if alert is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo")
        return {
            **alert,
            "acknowledgement_meaning": "Đã xem; không có nghĩa là tình trạng đã được xử lý",
        }

    @app.get("/api/v1/rules")
    def get_rules() -> dict[str, Any]:
        return {
            "data": rules.public_rules(),
            "warning": "Các ngưỡng chỉ phục vụ demo phi lâm sàng.",
        }

    @app.get("/api/v1/overview")
    def overview(
        device_id: str | None = None,
        window: str = "15m",
    ) -> dict[str, Any]:
        window_minutes = _parse_window_minutes(window)
        generated_at = utc_now()
        requested_to = generated_at
        requested_from = generated_at - timedelta(minutes=window_minutes)
        requested_from_text = isoformat_utc(requested_from)
        requested_to_text = isoformat_utc(requested_to)
        empty_history_meta = {
            "requested_from": requested_from_text,
            "requested_to": requested_to_text,
            "coverage_from": None,
            "coverage_to": None,
            "total_available": 0,
            "returned": 0,
            "truncated": False,
            "downsampling": "none",
            "validity": {
                metric: {"valid": 0, "total": 0}
                for metric in (
                    "heart_rate_bpm",
                    "spo2_pct",
                    "wrist_surface_temp_c",
                )
            },
        }
        devices = database.list_devices()
        if device_id:
            device = database.get_device(device_id)
            if device is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
        else:
            device = devices[0] if devices else None
        if device is None:
            return {
                "generated_at": requested_to_text,
                "device": None,
                "latest": None,
                "history": [],
                "history_meta": empty_history_meta,
                "alerts": [],
                "window_minutes": window_minutes,
                "non_clinical": True,
            }
        selected_id = device["device_id"]
        history, history_meta = database.telemetry_history_window(
            selected_id,
            from_time=requested_from_text,
            to_time=requested_to_text,
            limit=1000,
        )
        history_meta = {
            "requested_from": requested_from_text,
            "requested_to": requested_to_text,
            **history_meta,
        }
        return {
            "generated_at": requested_to_text,
            "device": _effective_device(device, settings.offline_after_seconds),
            "latest": database.latest_telemetry(selected_id),
            "history": history,
            "history_meta": history_meta,
            "alerts": database.list_alerts(
                state="active", device_id=selected_id, limit=100
            ),
            "window_minutes": window_minutes,
            "non_clinical": True,
        }

    return app


app = create_app()
