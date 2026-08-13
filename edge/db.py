from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .schemas import DeviceStatus, Telemetry, TelemetryMessage, TelemetryV2, TelemetryV3


ACTIVE_STATES = ("open", "acknowledged")


class AlertAlreadyResolvedError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bool_or_none(value: Any) -> bool | None:
    return None if value is None else bool(value)


class Database:
    def __init__(self, path: Path | str, telemetry_retention_rows: int = 50_000) -> None:
        if telemetry_retention_rows <= 0:
            raise ValueError("telemetry_retention_rows must be greater than zero")
        self.path = Path(path)
        self.telemetry_retention_rows = telemetry_retention_rows
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    boot_id TEXT,
                    online INTEGER NOT NULL DEFAULT 0 CHECK (online IN (0, 1)),
                    last_seen_at TEXT,
                    last_status_at TEXT,
                    status_reason TEXT,
                    rssi_dbm INTEGER,
                    free_heap INTEGER,
                    fw TEXT,
                    faults_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL REFERENCES devices(device_id),
                    boot_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    uptime_ms INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT 'health.telemetry.v1',
                    heart_rate_bpm REAL,
                    spo2_pct REAL,
                    skin_temp_c REAL,
                    ambient_temp_c REAL,
                    humidity_pct REAL,
                    wrist_surface_temp_c REAL,
                    accel_g REAL,
                    gyro_dps REAL,
                    fall_state TEXT NOT NULL,
                    ppg REAL,
                    finger_present INTEGER NOT NULL,
                    motion_artifact INTEGER NOT NULL,
                    heart_rate_valid INTEGER NOT NULL,
                    spo2_valid INTEGER NOT NULL,
                    skin_temp_valid INTEGER NOT NULL,
                    ambient_temp_valid INTEGER NOT NULL DEFAULT 0,
                    humidity_valid INTEGER NOT NULL DEFAULT 0,
                    wrist_surface_temp_valid INTEGER NOT NULL DEFAULT 0,
                    motion_valid INTEGER NOT NULL,
                    rssi_dbm INTEGER,
                    free_heap INTEGER,
                    fw TEXT NOT NULL,
                    faults_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(device_id, boot_id, seq)
                );

                CREATE INDEX IF NOT EXISTS telemetry_device_received
                    ON telemetry(device_id, received_at DESC);
                CREATE INDEX IF NOT EXISTS telemetry_device_id_desc
                    ON telemetry(device_id, id DESC);

                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES devices(device_id),
                    rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
                    state TEXT NOT NULL CHECK (state IN ('open', 'acknowledged', 'resolved')),
                    message TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    last_value REAL,
                    acknowledged_at TEXT,
                    acknowledged_by TEXT,
                    acknowledgement_note TEXT,
                    resolved_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS alerts_one_active_rule
                    ON alerts(device_id, rule_id)
                    WHERE state IN ('open', 'acknowledged');
                CREATE INDEX IF NOT EXISTS alerts_state_last_seen
                    ON alerts(state, last_seen_at DESC);

                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL REFERENCES alerts(id),
                    action TEXT NOT NULL CHECK (
                        action IN ('opened', 'event_repeated', 'acknowledged', 'resolved')
                    ),
                    happened_at TEXT NOT NULL,
                    actor TEXT,
                    note TEXT,
                    source_device_id TEXT,
                    source_event_id TEXT,
                    UNIQUE(source_device_id, source_event_id)
                );
                """
            )
            self._migrate_telemetry_columns(connection)
            self._migrate_legacy_alert_history(connection)
            self._resolve_retired_surface_alerts(connection)
            connection.commit()

    @staticmethod
    def _migrate_telemetry_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(telemetry)").fetchall()
        }
        additions = (
            (
                "schema_version",
                "TEXT NOT NULL DEFAULT 'health.telemetry.v1'",
            ),
            ("ambient_temp_c", "REAL"),
            ("humidity_pct", "REAL"),
            ("ambient_temp_valid", "INTEGER NOT NULL DEFAULT 0"),
            ("humidity_valid", "INTEGER NOT NULL DEFAULT 0"),
            ("wrist_surface_temp_c", "REAL"),
            ("wrist_surface_temp_valid", "INTEGER NOT NULL DEFAULT 0"),
        )
        for name, declaration in additions:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE telemetry ADD COLUMN {name} {declaration}"  # noqa: S608
                )

    @staticmethod
    def _resolve_retired_surface_alerts(connection: sqlite3.Connection) -> None:
        active = connection.execute(
            """
            SELECT id FROM alerts
            WHERE rule_id = 'surface_temp_demo'
              AND state IN ('open', 'acknowledged')
            """
        ).fetchall()
        if not active:
            return
        happened_at = isoformat_utc(utc_now())
        connection.executemany(
            """
            UPDATE alerts
            SET state = 'resolved', resolved_at = ?, last_seen_at = ?
            WHERE id = ?
            """,
            [(happened_at, happened_at, row["id"]) for row in active],
        )
        connection.executemany(
            """
            INSERT INTO alert_history (alert_id, action, happened_at, note)
            VALUES (?, 'resolved', ?, 'rule retired during DHT11 migration')
            """,
            [(row["id"], happened_at) for row in active],
        )

    @staticmethod
    def _migrate_legacy_alert_history(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(alert_history)").fetchall()
        }
        if "source_device_id" in columns:
            return

        # Early MVP databases deduplicated source_event_id globally. Rebuild the
        # table once so existing event rows are retained and dedupe becomes
        # device-scoped without asking the operator to delete SQLite data.
        connection.executescript(
            """
            ALTER TABLE alert_history RENAME TO alert_history_legacy;

            CREATE TABLE alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT NOT NULL REFERENCES alerts(id),
                action TEXT NOT NULL CHECK (
                    action IN ('opened', 'event_repeated', 'acknowledged', 'resolved')
                ),
                happened_at TEXT NOT NULL,
                actor TEXT,
                note TEXT,
                source_device_id TEXT,
                source_event_id TEXT,
                UNIQUE(source_device_id, source_event_id)
            );

            INSERT INTO alert_history (
                id, alert_id, action, happened_at, actor, note,
                source_device_id, source_event_id
            )
            SELECT
                history.id,
                history.alert_id,
                history.action,
                history.happened_at,
                history.actor,
                history.note,
                CASE
                    WHEN history.source_event_id IS NULL THEN NULL
                    ELSE alerts.device_id
                END,
                history.source_event_id
            FROM alert_history_legacy AS history
            JOIN alerts ON alerts.id = history.alert_id;

            DROP TABLE alert_history_legacy;
            """
        )

    def is_healthy(self) -> bool:
        try:
            with self.connection() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    @staticmethod
    def _upsert_device_from_telemetry(
        connection: sqlite3.Connection, telemetry: TelemetryMessage, received_at: str
    ) -> None:
        connection.execute(
            """
            INSERT INTO devices (
                device_id, boot_id, online, last_seen_at, rssi_dbm, free_heap, fw,
                faults_json, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                boot_id = excluded.boot_id,
                online = 1,
                last_seen_at = excluded.last_seen_at,
                rssi_dbm = excluded.rssi_dbm,
                free_heap = excluded.free_heap,
                fw = excluded.fw,
                faults_json = excluded.faults_json,
                updated_at = excluded.updated_at
            """,
            (
                telemetry.device_id,
                telemetry.boot_id,
                received_at,
                telemetry.system.rssi_dbm,
                telemetry.system.free_heap,
                telemetry.system.fw,
                json.dumps(telemetry.system.faults, ensure_ascii=False),
                received_at,
            ),
        )

    def insert_telemetry(
        self, telemetry: TelemetryMessage, received: datetime, raw_json: str
    ) -> tuple[int | None, bool]:
        received_at = isoformat_utc(received)
        if isinstance(telemetry, Telemetry):
            skin_temp_c = telemetry.vitals.skin_temp_c
            skin_temp_valid = telemetry.quality.skin_temp_valid
            ambient_temp_c = None
            humidity_pct = None
            ambient_temp_valid = False
            humidity_valid = False
            wrist_surface_temp_c = None
            wrist_surface_temp_valid = False
        elif isinstance(telemetry, TelemetryV2):
            skin_temp_c = None
            skin_temp_valid = False
            ambient_temp_c = telemetry.environment.ambient_temp_c
            humidity_pct = telemetry.environment.humidity_pct
            ambient_temp_valid = telemetry.quality.ambient_temp_valid
            humidity_valid = telemetry.quality.humidity_valid
            wrist_surface_temp_c = None
            wrist_surface_temp_valid = False
        elif isinstance(telemetry, TelemetryV3):
            skin_temp_c = None
            skin_temp_valid = False
            ambient_temp_c = None
            humidity_pct = None
            ambient_temp_valid = False
            humidity_valid = False
            wrist_surface_temp_c = telemetry.wearable.wrist_surface_temp_c
            wrist_surface_temp_valid = telemetry.quality.wrist_surface_temp_valid
        else:
            raise TypeError("unsupported telemetry model")
        with self._write_lock, self.connection() as connection:
            duplicate = connection.execute(
                """
                SELECT id FROM telemetry
                WHERE device_id = ? AND boot_id = ? AND seq = ?
                """,
                (telemetry.device_id, telemetry.boot_id, telemetry.seq),
            ).fetchone()
            if duplicate is not None:
                return None, False

            self._upsert_device_from_telemetry(connection, telemetry, received_at)
            cursor = connection.execute(
                """
                INSERT INTO telemetry (
                    device_id, boot_id, seq, uptime_ms, received_at, schema_version,
                    heart_rate_bpm, spo2_pct, skin_temp_c, ambient_temp_c, humidity_pct,
                    wrist_surface_temp_c,
                    accel_g, gyro_dps, fall_state,
                    ppg, finger_present, motion_artifact,
                    heart_rate_valid, spo2_valid, skin_temp_valid,
                    ambient_temp_valid, humidity_valid, wrist_surface_temp_valid,
                    motion_valid,
                    rssi_dbm, free_heap, fw, faults_json, raw_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    telemetry.device_id,
                    telemetry.boot_id,
                    telemetry.seq,
                    telemetry.uptime_ms,
                    received_at,
                    telemetry.schema_version,
                    telemetry.vitals.heart_rate_bpm,
                    telemetry.vitals.spo2_pct,
                    skin_temp_c,
                    ambient_temp_c,
                    humidity_pct,
                    wrist_surface_temp_c,
                    telemetry.motion.accel_g,
                    telemetry.motion.gyro_dps,
                    telemetry.motion.fall_state,
                    telemetry.quality.ppg,
                    int(telemetry.quality.finger_present),
                    int(telemetry.quality.motion_artifact),
                    int(telemetry.quality.heart_rate_valid),
                    int(telemetry.quality.spo2_valid),
                    int(skin_temp_valid),
                    int(ambient_temp_valid),
                    int(humidity_valid),
                    int(wrist_surface_temp_valid),
                    int(telemetry.quality.motion_valid),
                    telemetry.system.rssi_dbm,
                    telemetry.system.free_heap,
                    telemetry.system.fw,
                    json.dumps(telemetry.system.faults, ensure_ascii=False),
                    raw_json,
                ),
            )
            connection.execute(
                """
                DELETE FROM telemetry
                WHERE device_id = ? AND id <= COALESCE(
                    (
                        SELECT id FROM telemetry
                        WHERE device_id = ?
                        ORDER BY id DESC
                        LIMIT 1 OFFSET ?
                    ),
                    0
                )
                """,
                (
                    telemetry.device_id,
                    telemetry.device_id,
                    self.telemetry_retention_rows,
                ),
            )
            connection.commit()
            return cursor.lastrowid, True

    def update_status(self, status: DeviceStatus, received: datetime) -> None:
        received_at = isoformat_utc(received)
        with self._write_lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO devices (
                    device_id, boot_id, online, last_seen_at, last_status_at,
                    status_reason, rssi_dbm, free_heap, fw, faults_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    boot_id = excluded.boot_id,
                    online = excluded.online,
                    last_seen_at = CASE
                        WHEN excluded.online = 1 THEN excluded.last_seen_at
                        ELSE devices.last_seen_at
                    END,
                    last_status_at = excluded.last_status_at,
                    status_reason = excluded.status_reason,
                    rssi_dbm = excluded.rssi_dbm,
                    free_heap = excluded.free_heap,
                    fw = excluded.fw,
                    faults_json = excluded.faults_json,
                    updated_at = excluded.updated_at
                """,
                (
                    status.device_id,
                    status.boot_id,
                    int(status.online),
                    received_at if status.online else None,
                    received_at,
                    status.reason,
                    status.system.rssi_dbm,
                    status.system.free_heap,
                    status.system.fw,
                    json.dumps(status.system.faults, ensure_ascii=False),
                    received_at,
                ),
            )
            connection.commit()

    def ensure_device(
        self, device_id: str, boot_id: str, received: datetime
    ) -> None:
        received_at = isoformat_utc(received)
        with self._write_lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO devices (device_id, boot_id, online, last_seen_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    boot_id = excluded.boot_id,
                    online = 1,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (device_id, boot_id, received_at, received_at),
            )
            connection.commit()

    def open_or_touch_alert(
        self,
        *,
        device_id: str,
        rule_id: str,
        severity: str,
        message: str,
        happened: datetime,
        value: float | None = None,
    ) -> dict[str, Any]:
        happened_at = isoformat_utc(happened)
        with self._write_lock, self.connection() as connection:
            active = connection.execute(
                """
                SELECT * FROM alerts
                WHERE device_id = ? AND rule_id = ?
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id, rule_id),
            ).fetchone()
            if active:
                connection.execute(
                    """
                    UPDATE alerts
                    SET last_seen_at = ?, occurrence_count = occurrence_count + 1,
                        last_value = ?, message = ?
                    WHERE id = ?
                    """,
                    (happened_at, value, message, active["id"]),
                )
                alert_id = active["id"]
            else:
                alert_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO alerts (
                        id, device_id, rule_id, severity, state, message,
                        first_seen_at, last_seen_at, last_value
                    ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
                    """,
                    (
                        alert_id,
                        device_id,
                        rule_id,
                        severity,
                        message,
                        happened_at,
                        happened_at,
                        value,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO alert_history (alert_id, action, happened_at)
                    VALUES (?, 'opened', ?)
                    """,
                    (alert_id, happened_at),
                )
            connection.commit()
            row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._alert_dict(row)

    def record_fall_event(
        self,
        *,
        device_id: str,
        event_id: str,
        happened: datetime,
    ) -> tuple[dict[str, Any], bool]:
        happened_at = isoformat_utc(happened)
        with self._write_lock, self.connection() as connection:
            duplicate = connection.execute(
                """
                SELECT alert_id FROM alert_history
                WHERE source_device_id = ? AND source_event_id = ?
                """,
                (device_id, event_id),
            ).fetchone()
            if duplicate:
                row = connection.execute(
                    "SELECT * FROM alerts WHERE id = ?", (duplicate["alert_id"],)
                ).fetchone()
                return self._alert_dict(row), False

            active = connection.execute(
                """
                SELECT * FROM alerts
                WHERE device_id = ? AND rule_id = 'fall_suspected_demo'
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id,),
            ).fetchone()
            if active:
                alert_id = active["id"]
                connection.execute(
                    """
                    UPDATE alerts
                    SET state = 'open', last_seen_at = ?,
                        occurrence_count = occurrence_count + 1,
                        acknowledged_at = NULL, acknowledged_by = NULL,
                        acknowledgement_note = NULL
                    WHERE id = ?
                    """,
                    (happened_at, alert_id),
                )
                action = "event_repeated"
            else:
                alert_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO alerts (
                        id, device_id, rule_id, severity, state, message,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, 'fall_suspected_demo', 'critical', 'open', ?, ?, ?)
                    """,
                    (
                        alert_id,
                        device_id,
                        "Phát hiện sự kiện ngã thử nghiệm",
                        happened_at,
                        happened_at,
                    ),
                )
                action = "opened"
            connection.execute(
                """
                INSERT INTO alert_history (
                    alert_id, action, happened_at, source_device_id, source_event_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (alert_id, action, happened_at, device_id, event_id),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._alert_dict(row), True

    def resolve_alert(self, device_id: str, rule_id: str, happened: datetime) -> bool:
        happened_at = isoformat_utc(happened)
        with self._write_lock, self.connection() as connection:
            active = connection.execute(
                """
                SELECT id FROM alerts
                WHERE device_id = ? AND rule_id = ?
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id, rule_id),
            ).fetchone()
            if not active:
                return False
            connection.execute(
                """
                UPDATE alerts
                SET state = 'resolved', resolved_at = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (happened_at, happened_at, active["id"]),
            )
            connection.execute(
                """
                INSERT INTO alert_history (alert_id, action, happened_at)
                VALUES (?, 'resolved', ?)
                """,
                (active["id"], happened_at),
            )
            connection.commit()
            return True

    def acknowledge_alert(
        self, alert_id: str, actor: str, note: str, happened: datetime | None = None
    ) -> dict[str, Any] | None:
        happened_at = isoformat_utc(happened or utc_now())
        with self._write_lock, self.connection() as connection:
            alert = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if alert is None:
                return None
            if alert["state"] == "resolved":
                raise AlertAlreadyResolvedError(alert_id)
            if alert["state"] == "acknowledged":
                return self._alert_dict(alert)
            connection.execute(
                """
                UPDATE alerts
                SET state = 'acknowledged', acknowledged_at = ?,
                    acknowledged_by = ?, acknowledgement_note = ?
                WHERE id = ?
                """,
                (happened_at, actor, note, alert_id),
            )
            connection.execute(
                """
                INSERT INTO alert_history (
                    alert_id, action, happened_at, actor, note
                ) VALUES (?, 'acknowledged', ?, ?, ?)
                """,
                (alert_id, happened_at, actor, note),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._alert_dict(row)

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return None if row is None else self._alert_dict(row)

    def get_active_alert(self, device_id: str, rule_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM alerts
                WHERE device_id = ? AND rule_id = ?
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id, rule_id),
            ).fetchone()
            return None if row is None else self._alert_dict(row)

    def list_alerts(
        self,
        *,
        state: str | None = None,
        device_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if state == "active":
            clauses.append("state IN ('open', 'acknowledged')")
        elif state in {"open", "acknowledged", "resolved"}:
            clauses.append("state = ?")
            parameters.append(state)
        if device_id:
            clauses.append("device_id = ?")
            parameters.append(device_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM alerts{where} ORDER BY last_seen_at DESC LIMIT ?",  # noqa: S608
                parameters,
            ).fetchall()
            return [self._alert_dict(row) for row in rows]

    def list_devices(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM devices ORDER BY device_id"
            ).fetchall()
            return [self._device_dict(row) for row in rows]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return None if row is None else self._device_dict(row)

    def latest_telemetry(self, device_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM telemetry
                WHERE device_id = ? ORDER BY received_at DESC, id DESC LIMIT 1
                """,
                (device_id,),
            ).fetchone()
            return None if row is None else self._telemetry_dict(row)

    def telemetry_history(
        self,
        device_id: str,
        *,
        from_time: str | None = None,
        to_time: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["device_id = ?"]
        parameters: list[Any] = [device_id]
        if from_time:
            clauses.append("received_at >= ?")
            parameters.append(from_time)
        if to_time:
            clauses.append("received_at <= ?")
            parameters.append(to_time)
        parameters.append(limit)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM telemetry WHERE {' AND '.join(clauses)}
                ORDER BY received_at DESC, id DESC LIMIT ?
                """,  # noqa: S608
                parameters,
            ).fetchall()
            return [self._telemetry_dict(row) for row in reversed(rows)]

    @staticmethod
    def _device_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["online"] = bool(result["online"])
        result["faults"] = json.loads(result.pop("faults_json") or "[]")
        return result

    @staticmethod
    def _telemetry_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data["id"],
            "schema": data["schema_version"],
            "schema_version": data["schema_version"],
            "device_id": data["device_id"],
            "boot_id": data["boot_id"],
            "seq": data["seq"],
            "uptime_ms": data["uptime_ms"],
            "received_at": data["received_at"],
            "vitals": {
                "heart_rate_bpm": data["heart_rate_bpm"],
                "spo2_pct": data["spo2_pct"],
                "skin_temp_c": data["skin_temp_c"],
            },
            "environment": {
                "ambient_temp_c": data["ambient_temp_c"],
                "humidity_pct": data["humidity_pct"],
            },
            "wearable": {
                "wrist_surface_temp_c": data["wrist_surface_temp_c"],
            },
            "motion": {
                "accel_g": data["accel_g"],
                "gyro_dps": data["gyro_dps"],
                "fall_state": data["fall_state"],
            },
            "quality": {
                "ppg": data["ppg"],
                "finger_present": bool(data["finger_present"]),
                "motion_artifact": bool(data["motion_artifact"]),
                "heart_rate_valid": bool(data["heart_rate_valid"]),
                "spo2_valid": bool(data["spo2_valid"]),
                "skin_temp_valid": bool(data["skin_temp_valid"]),
                "ambient_temp_valid": bool(data["ambient_temp_valid"]),
                "humidity_valid": bool(data["humidity_valid"]),
                "wrist_surface_temp_valid": bool(
                    data["wrist_surface_temp_valid"]
                ),
                "motion_valid": bool(data["motion_valid"]),
            },
            "system": {
                "rssi_dbm": data["rssi_dbm"],
                "free_heap": data["free_heap"],
                "fw": data["fw"],
                "faults": json.loads(data["faults_json"] or "[]"),
            },
        }

    @staticmethod
    def _alert_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)
