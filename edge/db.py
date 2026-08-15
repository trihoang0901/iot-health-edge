from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from .schemas import (
    DeviceStatus,
    Telemetry,
    TelemetryMessage,
    TelemetryV2,
    TelemetryV3,
    TelemetryV4,
)


ACTIVE_STATES = ("open", "acknowledged")
SessionDisposition = Literal["accepted", "duplicate", "out_of_order", "stale"]
_STREAM_SEQUENCE_COLUMNS = {
    "telemetry": "last_telemetry_seq",
    "event": "last_event_seq",
    "status": "last_status_seq",
}
_LWT_REASONS = {"mqtt_lost", "connection_lost"}
_RECOVERY_REASONS = {
    "recovered_provisioning",
    "recovered_wifi_profile",
    "recovered_broker_ip_change",
    "recovered_dns_fallback",
    "recovered_mqtt_transport",
}
_CONNECTION_START_REASONS = {"connected", "simulator_started", *_RECOVERY_REASONS}


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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Own one serialized SQLite transaction for a complete ingestion unit."""
        with self._write_lock, self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def _write_scope(
        self, connection: sqlite3.Connection | None
    ) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
            return
        with self.transaction() as owned_connection:
            yield owned_connection

    @contextmanager
    def _read_scope(
        self, connection: sqlite3.Connection | None
    ) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
            return
        with self.connection() as owned_connection:
            yield owned_connection

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
                    last_status_reason TEXT,
                    last_status_retained INTEGER CHECK (
                        last_status_retained IS NULL OR last_status_retained IN (0, 1)
                    ),
                    status_reason TEXT,
                    status_reason_at TEXT,
                    last_recovery_reason TEXT,
                    last_recovery_at TEXT,
                    command_session_id TEXT,
                    correlation_id TEXT,
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
                    heart_rate_raw_bpm REAL,
                    heart_rate_bpm REAL,
                    spo2_raw_pct REAL,
                    spo2_pct REAL,
                    skin_temp_c REAL,
                    ambient_temp_c REAL,
                    humidity_pct REAL,
                    wrist_surface_temp_c REAL,
                    accel_g REAL,
                    gyro_dps REAL,
                    fall_state TEXT NOT NULL,
                    ppg REAL,
                    ppg_state TEXT NOT NULL DEFAULT 'legacy',
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

                CREATE TABLE IF NOT EXISTS device_sessions (
                    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                    boot_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    superseded_at TEXT,
                    last_telemetry_seq INTEGER,
                    last_event_seq INTEGER,
                    last_status_seq INTEGER,
                    connection_epoch INTEGER NOT NULL DEFAULT 0,
                    expected_lwt_seq INTEGER,
                    PRIMARY KEY(device_id, boot_id)
                );

                CREATE INDEX IF NOT EXISTS device_sessions_current
                    ON device_sessions(device_id, superseded_at);
                """
            )
            self._migrate_device_columns(connection)
            self._migrate_telemetry_columns(connection)
            self._migrate_device_session_columns(connection)
            self._backfill_device_sessions(connection)
            self._migrate_legacy_alert_history(connection)
            self._resolve_retired_surface_alerts(connection)
            connection.commit()

    @staticmethod
    def _migrate_device_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(devices)").fetchall()
        }
        additions = {
            "status_reason_at": "TEXT",
            "last_recovery_reason": "TEXT",
            "last_recovery_at": "TEXT",
            "last_status_reason": "TEXT",
            "last_status_retained": "INTEGER",
            "command_session_id": "TEXT",
            "correlation_id": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE devices ADD COLUMN {name} {declaration}"  # noqa: S608
                )

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
            ("heart_rate_raw_bpm", "REAL"),
            ("spo2_raw_pct", "REAL"),
            ("ppg_state", "TEXT NOT NULL DEFAULT 'legacy'"),
        )
        for name, declaration in additions:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE telemetry ADD COLUMN {name} {declaration}"  # noqa: S608
                )
        connection.execute(
            """
            UPDATE telemetry
            SET heart_rate_raw_bpm = heart_rate_bpm,
                spo2_raw_pct = spo2_pct,
                ppg_state = 'legacy'
            WHERE schema_version IN (
                'health.telemetry.v1',
                'health.telemetry.v2',
                'health.telemetry.v3'
            )
              AND (
                  heart_rate_raw_bpm IS NOT heart_rate_bpm
                  OR spo2_raw_pct IS NOT spo2_pct
                  OR ppg_state IS NOT 'legacy'
              )
            """
        )

    @staticmethod
    def _migrate_device_session_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(device_sessions)").fetchall()
        }
        additions = {
            "connection_epoch": "INTEGER NOT NULL DEFAULT 0",
            "expected_lwt_seq": "INTEGER",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE device_sessions ADD COLUMN {name} {declaration}"  # noqa: S608
                )

    @staticmethod
    def _backfill_device_sessions(connection: sqlite3.Connection) -> None:
        """Conservatively reconstruct every telemetry-backed device session.

        ``devices.boot_id`` remains the authority for the one current boot.  All
        other boots retained in telemetry are materialized as superseded before
        ingestion resumes, so replaying an old stored row cannot promote that
        boot.  Existing status/event watermarks and connection epochs are never
        lowered because telemetry is the only historical stream recoverable
        from a pre-session database.
        """
        telemetry_rows = connection.execute(
            """
            SELECT
                telemetry.device_id,
                telemetry.boot_id,
                MIN(telemetry.received_at) AS first_seen_at,
                MAX(telemetry.received_at) AS last_seen_at,
                MAX(telemetry.seq) AS max_telemetry_seq,
                devices.boot_id AS current_boot_id,
                devices.last_seen_at AS device_last_seen_at,
                devices.updated_at AS device_updated_at
            FROM telemetry
            JOIN devices ON devices.device_id = telemetry.device_id
            GROUP BY telemetry.device_id, telemetry.boot_id
            """
        ).fetchall()
        for row in telemetry_rows:
            is_current = row["boot_id"] == row["current_boot_id"]
            first_seen_at = row["first_seen_at"]
            last_seen_at = row["last_seen_at"]
            superseded_at = None if is_current else (
                row["device_updated_at"] or row["device_last_seen_at"] or last_seen_at
            )
            existing = connection.execute(
                """
                SELECT first_seen_at, last_seen_at, superseded_at,
                       last_telemetry_seq, last_event_seq, last_status_seq,
                       connection_epoch, expected_lwt_seq
                FROM device_sessions
                WHERE device_id = ? AND boot_id = ?
                """,
                (row["device_id"], row["boot_id"]),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO device_sessions (
                        device_id, boot_id, first_seen_at, last_seen_at,
                        superseded_at, last_telemetry_seq
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["device_id"],
                        row["boot_id"],
                        first_seen_at,
                        last_seen_at,
                        superseded_at,
                        row["max_telemetry_seq"],
                    ),
                )
            else:
                merged_first_seen_at = min(existing["first_seen_at"], first_seen_at)
                merged_last_seen_at = max(existing["last_seen_at"], last_seen_at)
                merged_telemetry_seq = row["max_telemetry_seq"]
                if existing["last_telemetry_seq"] is not None:
                    merged_telemetry_seq = max(
                        existing["last_telemetry_seq"], merged_telemetry_seq
                    )
                connection.execute(
                    """
                    UPDATE device_sessions
                    SET first_seen_at = ?, last_seen_at = ?,
                        superseded_at = ?, last_telemetry_seq = ?
                    WHERE device_id = ? AND boot_id = ?
                    """,
                    (
                        merged_first_seen_at,
                        merged_last_seen_at,
                        None if is_current else (existing["superseded_at"] or superseded_at),
                        merged_telemetry_seq,
                        row["device_id"],
                        row["boot_id"],
                    ),
                )

        # A current device may have no retained telemetry (for example, a status-
        # only node).  Preserve/create its active session without inventing any
        # unrecoverable stream watermark.
        current_rows = connection.execute(
            """
            SELECT device_id, boot_id, last_seen_at, updated_at
            FROM devices
            WHERE boot_id IS NOT NULL
            """
        ).fetchall()
        for row in current_rows:
            seen_at = row["last_seen_at"] or row["updated_at"]
            connection.execute(
                """
                INSERT OR IGNORE INTO device_sessions (
                    device_id, boot_id, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?)
                """,
                (row["device_id"], row["boot_id"], seen_at, seen_at),
            )

        connection.execute(
            """
            UPDATE device_sessions
            SET superseded_at = CASE
                WHEN boot_id = (
                    SELECT devices.boot_id FROM devices
                    WHERE devices.device_id = device_sessions.device_id
                ) THEN NULL
                ELSE COALESCE(
                    superseded_at,
                    (SELECT devices.updated_at FROM devices
                     WHERE devices.device_id = device_sessions.device_id),
                    last_seen_at
                )
            END
            WHERE EXISTS (
                SELECT 1 FROM devices
                WHERE devices.device_id = device_sessions.device_id
            )
            """
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

    def admit_session(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream: Literal["telemetry", "event", "status"],
        seq: int,
        received: datetime,
        online: bool | None = None,
        reason: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> SessionDisposition:
        """Classify a message before it is allowed to mutate current device state."""
        sequence_column = _STREAM_SEQUENCE_COLUMNS[stream]
        received_at = isoformat_utc(received)
        with self._write_scope(connection) as active_connection:
            device = active_connection.execute(
                """
                SELECT boot_id, online, last_seen_at, last_status_at,
                       status_reason, updated_at
                FROM devices WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            current_boot_id = None if device is None else device["boot_id"]
            session = active_connection.execute(
                """
                SELECT * FROM device_sessions
                WHERE device_id = ? AND boot_id = ?
                """,
                (device_id, boot_id),
            ).fetchone()

            if session is not None and session["superseded_at"] is not None:
                return "stale"

            if current_boot_id == boot_id:
                if session is None:
                    first_seen_at = (
                        device["last_seen_at"] or device["updated_at"] or received_at
                    )
                    active_connection.execute(
                        """
                        INSERT INTO device_sessions (
                            device_id, boot_id, first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (device_id, boot_id, first_seen_at, received_at),
                    )
                    session = active_connection.execute(
                        """
                        SELECT * FROM device_sessions
                        WHERE device_id = ? AND boot_id = ?
                        """,
                        (device_id, boot_id),
                    ).fetchone()

                if (
                    stream == "status"
                    and online is False
                    and reason in _LWT_REASONS
                ):
                    expected_lwt_seq = session["expected_lwt_seq"]
                    if expected_lwt_seq is not None and seq != expected_lwt_seq:
                        return "out_of_order"
                    if (
                        not bool(device["online"])
                        and device["status_reason"] in _LWT_REASONS
                    ):
                        return "duplicate"
                    active_connection.execute(
                        """
                        UPDATE device_sessions
                        SET expected_lwt_seq = COALESCE(expected_lwt_seq, ?),
                            last_seen_at = ?
                        WHERE device_id = ? AND boot_id = ?
                        """,
                        (seq, received_at, device_id, boot_id),
                    )
                    return "accepted"

                previous_seq = session[sequence_column]

                # A migrated database cannot recover historical status sequence.
                # Do not let the first unanchored non-LWT offline status rewind an
                # existing online state; an online status safely establishes the
                # stream watermark, while events remain idempotent by event_id.
                if (
                    stream == "status"
                    and previous_seq is None
                    and device["last_status_at"] is not None
                    and online is False
                ):
                    if (
                        not bool(device["online"])
                        and device["status_reason"] == reason
                    ):
                        return "duplicate"
                    return "out_of_order"

                if previous_seq is not None:
                    if seq == previous_seq:
                        return "duplicate"
                    if seq < previous_seq:
                        return "out_of_order"
                if (
                    stream == "status"
                    and online is True
                    and reason in _CONNECTION_START_REASONS
                ):
                    expected_lwt_seq = seq if reason == "simulator_started" else max(seq - 1, 0)
                    active_connection.execute(
                        f"""
                        UPDATE device_sessions
                        SET {sequence_column} = ?, last_seen_at = ?,
                            connection_epoch = connection_epoch + 1,
                            expected_lwt_seq = ?
                        WHERE device_id = ? AND boot_id = ?
                        """,  # noqa: S608 -- column is selected from a fixed internal mapping.
                        (
                            seq,
                            received_at,
                            expected_lwt_seq,
                            device_id,
                            boot_id,
                        ),
                    )
                else:
                    active_connection.execute(
                        f"""
                        UPDATE device_sessions
                        SET {sequence_column} = ?, last_seen_at = ?
                        WHERE device_id = ? AND boot_id = ?
                        """,  # noqa: S608 -- column is selected from a fixed internal mapping.
                        (seq, received_at, device_id, boot_id),
                    )
                return "accepted"

            # A known non-current boot is never allowed to become current again.
            if session is not None:
                return "stale"

            # A retained/offline Last Will cannot prove that an unknown boot is current.
            if stream == "status" and online is False:
                return "stale"

            if current_boot_id:
                legacy_seen_at = (
                    device["last_seen_at"] or device["updated_at"] or received_at
                )
                active_connection.execute(
                    """
                    INSERT OR IGNORE INTO device_sessions (
                        device_id, boot_id, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (device_id, current_boot_id, legacy_seen_at, legacy_seen_at),
                )
                active_connection.execute(
                    """
                    UPDATE device_sessions
                    SET superseded_at = COALESCE(superseded_at, ?)
                    WHERE device_id = ? AND superseded_at IS NULL
                    """,
                    (received_at, device_id),
                )

            # Create a minimal parent row so the session FK and the following payload
            # mutation can live in the same transaction.
            active_connection.execute(
                """
                INSERT INTO devices (device_id, boot_id, online, updated_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    boot_id = excluded.boot_id,
                    command_session_id = NULL,
                    correlation_id = NULL,
                    updated_at = excluded.updated_at
                """,
                (device_id, boot_id, received_at),
            )
            sequence_values = {
                "last_telemetry_seq": None,
                "last_event_seq": None,
                "last_status_seq": None,
            }
            sequence_values[sequence_column] = seq
            is_connection_start = (
                stream == "status"
                and online is True
                and reason in _CONNECTION_START_REASONS
            )
            expected_lwt_seq = None
            if is_connection_start:
                expected_lwt_seq = (
                    seq if reason == "simulator_started" else max(seq - 1, 0)
                )
            active_connection.execute(
                """
                INSERT INTO device_sessions (
                    device_id, boot_id, first_seen_at, last_seen_at,
                    last_telemetry_seq, last_event_seq, last_status_seq,
                    connection_epoch, expected_lwt_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    boot_id,
                    received_at,
                    received_at,
                    sequence_values["last_telemetry_seq"],
                    sequence_values["last_event_seq"],
                    sequence_values["last_status_seq"],
                    1 if is_connection_start else 0,
                    expected_lwt_seq,
                ),
            )
            return "accepted"

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
        self,
        telemetry: TelemetryMessage,
        received: datetime,
        raw_json: str,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[int | None, bool]:
        received_at = isoformat_utc(received)
        if isinstance(telemetry, TelemetryV4):
            heart_rate_raw_bpm = telemetry.vitals.heart_rate_raw_bpm
            spo2_raw_pct = telemetry.vitals.spo2_raw_pct
            ppg_state = telemetry.quality.ppg_state
        else:
            heart_rate_raw_bpm = telemetry.vitals.heart_rate_bpm
            spo2_raw_pct = telemetry.vitals.spo2_pct
            ppg_state = "legacy"
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
        elif isinstance(telemetry, (TelemetryV3, TelemetryV4)):
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
        with self._write_scope(connection) as active_connection:
            duplicate = active_connection.execute(
                """
                SELECT id FROM telemetry
                WHERE device_id = ? AND boot_id = ? AND seq = ?
                """,
                (telemetry.device_id, telemetry.boot_id, telemetry.seq),
            ).fetchone()
            if duplicate is not None:
                return None, False

            self._upsert_device_from_telemetry(active_connection, telemetry, received_at)
            cursor = active_connection.execute(
                """
                INSERT INTO telemetry (
                    device_id, boot_id, seq, uptime_ms, received_at, schema_version,
                    heart_rate_raw_bpm, heart_rate_bpm,
                    spo2_raw_pct, spo2_pct,
                    skin_temp_c, ambient_temp_c, humidity_pct,
                    wrist_surface_temp_c,
                    accel_g, gyro_dps, fall_state,
                    ppg, ppg_state, finger_present, motion_artifact,
                    heart_rate_valid, spo2_valid, skin_temp_valid,
                    ambient_temp_valid, humidity_valid, wrist_surface_temp_valid,
                    motion_valid,
                    rssi_dbm, free_heap, fw, faults_json, raw_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    telemetry.device_id,
                    telemetry.boot_id,
                    telemetry.seq,
                    telemetry.uptime_ms,
                    received_at,
                    telemetry.schema_version,
                    heart_rate_raw_bpm,
                    telemetry.vitals.heart_rate_bpm,
                    spo2_raw_pct,
                    telemetry.vitals.spo2_pct,
                    skin_temp_c,
                    ambient_temp_c,
                    humidity_pct,
                    wrist_surface_temp_c,
                    telemetry.motion.accel_g,
                    telemetry.motion.gyro_dps,
                    telemetry.motion.fall_state,
                    telemetry.quality.ppg,
                    ppg_state,
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
            active_connection.execute(
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
            return cursor.lastrowid, True

    def update_status(
        self,
        status: DeviceStatus,
        received: datetime,
        connection: sqlite3.Connection | None = None,
        *,
        retained: bool | None = None,
    ) -> None:
        received_at = isoformat_utc(received)
        is_recovery = status.online and status.reason in _RECOVERY_REASONS
        command_session_id = (
            str(status.command_session_id) if status.command_session_id is not None else None
        )
        correlation_id = (
            str(status.correlation_id) if status.correlation_id is not None else None
        )
        with self._write_scope(connection) as active_connection:
            active_connection.execute(
                """
                INSERT INTO devices (
                    device_id, boot_id, online, last_seen_at, last_status_at,
                    last_status_reason, last_status_retained, status_reason,
                    status_reason_at, last_recovery_reason, last_recovery_at,
                    command_session_id, correlation_id, rssi_dbm, free_heap,
                    fw, faults_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    boot_id = excluded.boot_id,
                    online = excluded.online,
                    last_seen_at = CASE
                        WHEN excluded.online = 1 THEN excluded.last_seen_at
                        ELSE devices.last_seen_at
                    END,
                    last_status_at = excluded.last_status_at,
                    last_status_reason = excluded.last_status_reason,
                    last_status_retained = excluded.last_status_retained,
                    status_reason = CASE
                        WHEN excluded.status_reason = 'heartbeat'
                        THEN devices.status_reason
                        ELSE excluded.status_reason
                    END,
                    status_reason_at = CASE
                        WHEN excluded.status_reason = 'heartbeat'
                        THEN devices.status_reason_at
                        ELSE excluded.status_reason_at
                    END,
                    last_recovery_reason = COALESCE(
                        excluded.last_recovery_reason,
                        devices.last_recovery_reason
                    ),
                    last_recovery_at = COALESCE(
                        excluded.last_recovery_at,
                        devices.last_recovery_at
                    ),
                    command_session_id = COALESCE(
                        excluded.command_session_id,
                        devices.command_session_id
                    ),
                    correlation_id = CASE
                        WHEN excluded.command_session_id IS NOT NULL
                         AND excluded.command_session_id != devices.command_session_id
                        THEN excluded.correlation_id
                        ELSE COALESCE(excluded.correlation_id, devices.correlation_id)
                    END,
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
                    None if retained is None else int(retained),
                    status.reason,
                    received_at,
                    status.reason if is_recovery else None,
                    received_at if is_recovery else None,
                    command_session_id,
                    correlation_id,
                    status.system.rssi_dbm,
                    status.system.free_heap,
                    status.system.fw,
                    json.dumps(status.system.faults, ensure_ascii=False),
                    received_at,
                ),
            )

    def ensure_device(
        self,
        device_id: str,
        boot_id: str,
        received: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        received_at = isoformat_utc(received)
        with self._write_scope(connection) as active_connection:
            active_connection.execute(
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

    def open_or_touch_alert(
        self,
        *,
        device_id: str,
        rule_id: str,
        severity: str,
        message: str,
        happened: datetime,
        value: float | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        happened_at = isoformat_utc(happened)
        with self._write_scope(connection) as active_connection:
            active = active_connection.execute(
                """
                SELECT * FROM alerts
                WHERE device_id = ? AND rule_id = ?
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id, rule_id),
            ).fetchone()
            if active:
                active_connection.execute(
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
                active_connection.execute(
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
                active_connection.execute(
                    """
                    INSERT INTO alert_history (alert_id, action, happened_at)
                    VALUES (?, 'opened', ?)
                    """,
                    (alert_id, happened_at),
                )
            row = active_connection.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            return self._alert_dict(row)

    def record_fall_event(
        self,
        *,
        device_id: str,
        event_id: str,
        happened: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], bool]:
        happened_at = isoformat_utc(happened)
        with self._write_scope(connection) as active_connection:
            duplicate = active_connection.execute(
                """
                SELECT alert_id FROM alert_history
                WHERE source_device_id = ? AND source_event_id = ?
                """,
                (device_id, event_id),
            ).fetchone()
            if duplicate:
                row = active_connection.execute(
                    "SELECT * FROM alerts WHERE id = ?", (duplicate["alert_id"],)
                ).fetchone()
                return self._alert_dict(row), False

            active = active_connection.execute(
                """
                SELECT * FROM alerts
                WHERE device_id = ? AND rule_id = 'fall_suspected_demo'
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id,),
            ).fetchone()
            if active:
                alert_id = active["id"]
                active_connection.execute(
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
                active_connection.execute(
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
            active_connection.execute(
                """
                INSERT INTO alert_history (
                    alert_id, action, happened_at, source_device_id, source_event_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (alert_id, action, happened_at, device_id, event_id),
            )
            row = active_connection.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            return self._alert_dict(row), True

    def resolve_alert(
        self,
        device_id: str,
        rule_id: str,
        happened: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        happened_at = isoformat_utc(happened)
        with self._write_scope(connection) as active_connection:
            active = active_connection.execute(
                """
                SELECT id FROM alerts
                WHERE device_id = ? AND rule_id = ?
                  AND state IN ('open', 'acknowledged')
                """,
                (device_id, rule_id),
            ).fetchone()
            if not active:
                return False
            active_connection.execute(
                """
                UPDATE alerts
                SET state = 'resolved', resolved_at = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (happened_at, happened_at, active["id"]),
            )
            active_connection.execute(
                """
                INSERT INTO alert_history (alert_id, action, happened_at)
                VALUES (?, 'resolved', ?)
                """,
                (active["id"], happened_at),
            )
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

    def get_active_alert(
        self,
        device_id: str,
        rule_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        with self._read_scope(connection) as active_connection:
            row = active_connection.execute(
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
        connection: sqlite3.Connection | None = None,
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
        with self._read_scope(connection) as active_connection:
            rows = active_connection.execute(
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

    def telemetry_history_window(
        self,
        device_id: str,
        *,
        from_time: str,
        to_time: str,
        limit: int = 1000,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Read a bounded chart slice and full-window coverage in one snapshot."""
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        parameters = (device_id, from_time, to_time)
        with self.connection() as connection:
            connection.execute("BEGIN")
            stats = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_available,
                    MIN(received_at) AS coverage_from,
                    MAX(received_at) AS coverage_to,
                    COALESCE(SUM(
                        CASE WHEN heart_rate_valid = 1
                                   AND heart_rate_bpm IS NOT NULL
                             THEN 1 ELSE 0 END
                    ), 0) AS heart_rate_valid_count,
                    COALESCE(SUM(
                        CASE WHEN spo2_valid = 1 AND spo2_pct IS NOT NULL
                             THEN 1 ELSE 0 END
                    ), 0) AS spo2_valid_count,
                    COALESCE(SUM(
                        CASE WHEN wrist_surface_temp_valid = 1
                                   AND wrist_surface_temp_c IS NOT NULL
                             THEN 1 ELSE 0 END
                    ), 0) AS wrist_surface_temp_valid_count
                FROM telemetry
                WHERE device_id = ? AND received_at >= ? AND received_at <= ?
                """,
                parameters,
            ).fetchone()
            rows = connection.execute(
                """
                SELECT * FROM telemetry
                WHERE device_id = ? AND received_at >= ? AND received_at <= ?
                ORDER BY received_at DESC, id DESC LIMIT ?
                """,
                (*parameters, limit),
            ).fetchall()

        total_available = int(stats["total_available"])
        history = [self._telemetry_dict(row) for row in reversed(rows)]
        validity = {
            "heart_rate_bpm": {
                "valid": int(stats["heart_rate_valid_count"]),
                "total": total_available,
            },
            "spo2_pct": {
                "valid": int(stats["spo2_valid_count"]),
                "total": total_available,
            },
            "wrist_surface_temp_c": {
                "valid": int(stats["wrist_surface_temp_valid_count"]),
                "total": total_available,
            },
        }
        return history, {
            "coverage_from": stats["coverage_from"],
            "coverage_to": stats["coverage_to"],
            "total_available": total_available,
            "returned": len(history),
            "truncated": total_available > len(history),
            "downsampling": "none",
            "validity": validity,
        }

    @staticmethod
    def _device_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["online"] = bool(result["online"])
        if "last_status_retained" in result:
            result["last_status_retained"] = _bool_or_none(
                result["last_status_retained"]
            )
        result["faults"] = json.loads(result.pop("faults_json") or "[]")
        return result

    @staticmethod
    def _telemetry_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        ppg_state = data["ppg_state"] or "legacy"

        def measurement(
            raw_value: float | None,
            confirmed_value: float | None,
            valid: bool,
            unit: str,
        ) -> dict[str, Any]:
            reason = None if valid else (
                ppg_state if ppg_state != "valid" else "unconfirmed"
            )
            return {
                "raw_value": raw_value,
                "confirmed_value": confirmed_value,
                "valid": valid,
                "state": ppg_state,
                "reason": reason,
                "unit": unit,
            }

        heart_rate_valid = bool(data["heart_rate_valid"])
        spo2_valid = bool(data["spo2_valid"])
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
            "measurements": {
                "heart_rate": measurement(
                    data["heart_rate_raw_bpm"],
                    data["heart_rate_bpm"],
                    heart_rate_valid,
                    "bpm",
                ),
                "spo2": measurement(
                    data["spo2_raw_pct"],
                    data["spo2_pct"],
                    spo2_valid,
                    "%",
                ),
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
                "ppg_state": ppg_state,
                "finger_present": bool(data["finger_present"]),
                "motion_artifact": bool(data["motion_artifact"]),
                "heart_rate_valid": heart_rate_valid,
                "spo2_valid": spo2_valid,
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
