from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import AlertAlreadyResolvedError, Database, isoformat_utc, utc_now
from .mqtt_client import EdgeMqttClient
from .notifications import TelegramApiClient, TelegramNotifier
from .rules import RuleEngine
from .schemas import AckRequest
from .service import IngestionService


STATIC_DIR = Path(__file__).with_name("static")
WINDOW_RE = re.compile(r"^(?P<minutes>[1-9][0-9]*)(?:m)?$")
STATIC_ASSET_NAMES = ("favicon.svg", "styles.css", "app.js")


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
        db_ok = database.is_healthy()
        ingestion_health = ingestion.metrics()
        mqtt_health = (
            mqtt_client.health()
            if mqtt_client
            else {"enabled": False, "connected": False, "last_error": None}
        )
        ingestion_ok = bool(ingestion_health["worker_alive"]) and not bool(
            ingestion_health["processing_errors"]
        )
        mqtt_ok = not mqtt_client or bool(
            mqtt_health["connected"] and mqtt_health.get("subscribed", False)
        )
        overall = "ok" if db_ok and ingestion_ok and mqtt_ok else "degraded"
        return {
            "status": overall,
            "database": {"healthy": db_ok},
            "mqtt": mqtt_health,
            "ingestion": ingestion_health,
            "non_clinical": True,
        }

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
        devices = database.list_devices()
        if device_id:
            device = database.get_device(device_id)
            if device is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
        else:
            device = devices[0] if devices else None
        if device is None:
            return {
                "generated_at": isoformat_utc(utc_now()),
                "device": None,
                "latest": None,
                "history": [],
                "alerts": [],
                "window_minutes": window_minutes,
                "non_clinical": True,
            }
        selected_id = device["device_id"]
        since = utc_now() - timedelta(minutes=window_minutes)
        return {
            "generated_at": isoformat_utc(utc_now()),
            "device": _effective_device(device, settings.offline_after_seconds),
            "latest": database.latest_telemetry(selected_id),
            "history": database.telemetry_history(
                selected_id, from_time=isoformat_utc(since), limit=1000
            ),
            "alerts": database.list_alerts(
                state="active", device_id=selected_id, limit=100
            ),
            "window_minutes": window_minutes,
            "non_clinical": True,
        }

    return app


app = create_app()
