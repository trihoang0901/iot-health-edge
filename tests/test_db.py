from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from edge.db import Database
from edge.schemas import Telemetry, TelemetryV2, TelemetryV3, TelemetryV4


def test_initialize_additively_migrates_device_recovery_and_command_columns(tmp_path):
    path = tmp_path / "legacy-devices.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE devices (
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
            INSERT INTO devices (
                device_id, boot_id, online, last_seen_at, last_status_at,
                status_reason, faults_json, updated_at
            ) VALUES (
                'health-node-01', 'boot-old', 1,
                '2026-08-04T12:00:00.000Z', '2026-08-04T12:00:00.000Z',
                'connected', '[]', '2026-08-04T12:00:00.000Z'
            );
            """
        )

    database = Database(path)
    database.initialize()

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(devices)").fetchall()
        }
    assert {
        "status_reason_at",
        "last_recovery_reason",
        "last_recovery_at",
        "last_status_reason",
        "last_status_retained",
        "command_session_id",
        "correlation_id",
    } <= columns
    device = database.get_device("health-node-01")
    assert device["status_reason"] == "connected"
    assert device["last_recovery_reason"] is None
    assert device["command_session_id"] is None


def test_outer_transaction_rolls_back_device_session_and_telemetry(
    tmp_path, valid_telemetry_payload
):
    database = Database(tmp_path / "atomic.db")
    database.initialize()
    telemetry = Telemetry.model_validate(valid_telemetry_payload)
    received = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="fault before commit"):
        with database.transaction() as connection:
            assert database.admit_session(
                device_id=telemetry.device_id,
                boot_id=telemetry.boot_id,
                stream="telemetry",
                seq=telemetry.seq,
                received=received,
                connection=connection,
            ) == "accepted"
            database.insert_telemetry(
                telemetry,
                received,
                json.dumps(valid_telemetry_payload),
                connection=connection,
            )
            raise RuntimeError("fault before commit")

    assert database.get_device(telemetry.device_id) is None
    assert database.telemetry_history(telemetry.device_id) == []
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM device_sessions").fetchone()[0] == 0


def test_initialize_backfills_current_session_max_sequence_after_legacy_pruning(
    tmp_path, clone_payload
):
    database = Database(tmp_path / "legacy-session.db", telemetry_retention_rows=1)
    database.initialize()
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    first_payload = clone_payload()
    first_payload["boot_id"] = "boot-current"
    first_payload["seq"] = 1
    latest_payload = clone_payload()
    latest_payload["boot_id"] = "boot-current"
    latest_payload["seq"] = 100
    first = Telemetry.model_validate(first_payload)
    latest = Telemetry.model_validate(latest_payload)
    database.insert_telemetry(first, start, json.dumps(first_payload))
    database.insert_telemetry(
        latest, start + timedelta(seconds=1), json.dumps(latest_payload)
    )
    assert [row["seq"] for row in database.telemetry_history("health-node-01")] == [100]

    # Simulate an upgrade from the pre-session schema after retention already
    # pruned lower sequence rows.
    with database.connection() as connection:
        connection.execute("DROP TABLE device_sessions")
        connection.commit()
    database.initialize()

    with database.connection() as connection:
        session = connection.execute(
            """
            SELECT last_telemetry_seq, last_status_seq, last_event_seq
            FROM device_sessions
            WHERE device_id = ? AND boot_id = ?
            """,
            ("health-node-01", "boot-current"),
        ).fetchone()
    assert dict(session) == {
        "last_telemetry_seq": 100,
        "last_status_seq": None,
        "last_event_seq": None,
    }

    disposition = database.admit_session(
        device_id="health-node-01",
        boot_id="boot-current",
        stream="telemetry",
        seq=1,
        received=start + timedelta(seconds=2),
    )
    assert disposition == "out_of_order"
    assert [row["seq"] for row in database.telemetry_history("health-node-01")] == [100]


def test_upgrade_backfills_all_boots_and_old_telemetry_replay_cannot_rewind(
    tmp_path, clone_payload
):
    database = Database(tmp_path / "legacy-multi-boot.db")
    database.initialize()
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    for boot_id, seq, offset in (("boot-a", 80, 0), ("boot-b", 12, 1)):
        payload = clone_payload()
        payload["boot_id"] = boot_id
        payload["seq"] = seq
        payload["uptime_ms"] = seq * 1000
        database.insert_telemetry(
            Telemetry.model_validate(payload),
            start + timedelta(seconds=offset),
            json.dumps(payload),
        )

    # Model a pre-session database whose current device row is boot-b while
    # telemetry still contains rows from boot-a.
    with database.connection() as connection:
        connection.execute("DROP TABLE device_sessions")
        connection.commit()
    database.initialize()

    with database.connection() as connection:
        sessions = connection.execute(
            """
            SELECT boot_id, superseded_at, last_telemetry_seq
            FROM device_sessions
            WHERE device_id = ? ORDER BY boot_id
            """,
            ("health-node-01",),
        ).fetchall()
    assert [dict(row) for row in sessions] == [
        {
            "boot_id": "boot-a",
            "superseded_at": "2026-08-04T12:00:01.000Z",
            "last_telemetry_seq": 80,
        },
        {
            "boot_id": "boot-b",
            "superseded_at": None,
            "last_telemetry_seq": 12,
        },
    ]

    disposition = database.admit_session(
        device_id="health-node-01",
        boot_id="boot-a",
        stream="telemetry",
        seq=80,
        received=start + timedelta(seconds=2),
    )
    assert disposition == "stale"
    assert database.get_device("health-node-01")["boot_id"] == "boot-b"


def test_session_backfill_never_lowers_existing_stream_or_connection_watermarks(
    tmp_path, clone_payload
):
    database = Database(tmp_path / "watermark-merge.db")
    database.initialize()
    received = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    payload = clone_payload()
    payload["boot_id"] = "boot-current"
    payload["seq"] = 10
    database.insert_telemetry(
        Telemetry.model_validate(payload), received, json.dumps(payload)
    )
    database.initialize()

    with database.connection() as connection:
        connection.execute(
            """
            UPDATE device_sessions
            SET last_telemetry_seq = 99,
                last_event_seq = 77,
                last_status_seq = 88,
                connection_epoch = 3,
                expected_lwt_seq = 87
            WHERE device_id = ? AND boot_id = ?
            """,
            ("health-node-01", "boot-current"),
        )
        connection.commit()

    database.initialize()
    with database.connection() as connection:
        session = connection.execute(
            """
            SELECT last_telemetry_seq, last_event_seq, last_status_seq,
                   connection_epoch, expected_lwt_seq, superseded_at
            FROM device_sessions
            WHERE device_id = ? AND boot_id = ?
            """,
            ("health-node-01", "boot-current"),
        ).fetchone()
    assert dict(session) == {
        "last_telemetry_seq": 99,
        "last_event_seq": 77,
        "last_status_seq": 88,
        "connection_epoch": 3,
        "expected_lwt_seq": 87,
        "superseded_at": None,
    }


def test_telemetry_retention_keeps_newest_rows_per_device(tmp_path, clone_payload):
    database = Database(tmp_path / "retention.db", telemetry_retention_rows=3)
    database.initialize()
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    for device_id, count in (("device-a", 5), ("device-b", 2)):
        for seq in range(count):
            payload = clone_payload()
            payload["device_id"] = device_id
            payload["boot_id"] = f"boot-{device_id[-1]}"
            payload["seq"] = seq
            payload["uptime_ms"] = seq * 1000
            telemetry = Telemetry.model_validate(payload)
            _, inserted = database.insert_telemetry(
                telemetry,
                start + timedelta(seconds=seq),
                json.dumps(payload),
            )
            assert inserted

    assert [row["seq"] for row in database.telemetry_history("device-a")] == [2, 3, 4]
    assert [row["seq"] for row in database.telemetry_history("device-b")] == [0, 1]


def test_telemetry_history_window_reports_full_coverage_and_metric_validity(
    tmp_path, valid_telemetry_v3_payload
):
    database = Database(tmp_path / "history-window.db")
    database.initialize()
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    for seq in range(1, 5):
        payload = json.loads(json.dumps(valid_telemetry_v3_payload))
        payload["seq"] = seq
        payload["uptime_ms"] = seq * 1000
        if seq == 2:
            payload["vitals"]["heart_rate_bpm"] = None
            payload["quality"]["heart_rate_valid"] = False
        if seq == 3:
            payload["vitals"]["spo2_pct"] = None
            payload["quality"]["spo2_valid"] = False
            payload["wearable"]["wrist_surface_temp_c"] = None
            payload["quality"]["wrist_surface_temp_valid"] = False
            payload["system"]["faults"] = ["ds18b20_unavailable"]
        database.insert_telemetry(
            TelemetryV3.model_validate(payload),
            start + timedelta(seconds=seq - 1),
            json.dumps(payload),
        )

    history, metadata = database.telemetry_history_window(
        "health-node-01",
        from_time="2026-08-04T12:00:00.000Z",
        to_time="2026-08-04T12:00:02.000Z",
        limit=2,
    )

    assert [item["seq"] for item in history] == [2, 3]
    assert metadata == {
        "coverage_from": "2026-08-04T12:00:00.000Z",
        "coverage_to": "2026-08-04T12:00:02.000Z",
        "total_available": 3,
        "returned": 2,
        "truncated": True,
        "downsampling": "none",
        "validity": {
            "heart_rate_bpm": {"valid": 2, "total": 3},
            "spo2_pct": {"valid": 2, "total": 3},
            "wrist_surface_temp_c": {"valid": 2, "total": 3},
        },
    }


def test_v1_through_v4_rows_share_database_with_normalized_additive_responses(
    tmp_path,
    valid_telemetry_payload,
    valid_telemetry_v2_payload,
    valid_telemetry_v3_payload,
    valid_telemetry_v4_payload,
):
    database = Database(tmp_path / "mixed.db")
    database.initialize()
    received = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    database.insert_telemetry(
        Telemetry.model_validate(valid_telemetry_payload),
        received,
        json.dumps(valid_telemetry_payload),
    )
    database.insert_telemetry(
        TelemetryV2.model_validate(valid_telemetry_v2_payload),
        received + timedelta(seconds=1),
        json.dumps(valid_telemetry_v2_payload),
    )
    database.insert_telemetry(
        TelemetryV3.model_validate(valid_telemetry_v3_payload),
        received + timedelta(seconds=2),
        json.dumps(valid_telemetry_v3_payload),
    )
    database.insert_telemetry(
        TelemetryV4.model_validate(valid_telemetry_v4_payload),
        received + timedelta(seconds=3),
        json.dumps(valid_telemetry_v4_payload),
    )

    v1, v2, v3, v4 = database.telemetry_history("health-node-01")
    assert v1["schema"] == v1["schema_version"] == "health.telemetry.v1"
    assert v1["vitals"]["skin_temp_c"] == 34.5
    assert v1["environment"] == {"ambient_temp_c": None, "humidity_pct": None}
    assert v1["wearable"] == {"wrist_surface_temp_c": None}
    assert v1["quality"]["ambient_temp_valid"] is False
    assert v1["quality"]["humidity_valid"] is False
    assert v1["quality"]["wrist_surface_temp_valid"] is False
    assert v1["measurements"]["heart_rate"] == {
        "raw_value": 76.0,
        "confirmed_value": 76.0,
        "valid": True,
        "state": "legacy",
        "reason": None,
        "unit": "bpm",
    }
    assert v2["schema"] == v2["schema_version"] == "health.telemetry.v2"
    assert v2["vitals"]["skin_temp_c"] is None
    assert v2["quality"]["skin_temp_valid"] is False
    assert v2["environment"] == {"ambient_temp_c": 28.5, "humidity_pct": 63.0}
    assert v2["wearable"] == {"wrist_surface_temp_c": None}
    assert v2["quality"]["ambient_temp_valid"] is True
    assert v2["quality"]["humidity_valid"] is True
    assert v2["quality"]["wrist_surface_temp_valid"] is False
    assert v3["schema"] == v3["schema_version"] == "health.telemetry.v3"
    assert v3["vitals"]["skin_temp_c"] is None
    assert v3["quality"]["skin_temp_valid"] is False
    assert v3["environment"] == {"ambient_temp_c": None, "humidity_pct": None}
    assert v3["quality"]["ambient_temp_valid"] is False
    assert v3["quality"]["humidity_valid"] is False
    assert v3["wearable"] == {"wrist_surface_temp_c": 32.8}
    assert v3["quality"]["wrist_surface_temp_valid"] is True
    assert v3["measurements"]["spo2"]["raw_value"] == 97.0
    assert v3["measurements"]["spo2"]["state"] == "legacy"
    assert v4["schema"] == v4["schema_version"] == "health.telemetry.v4"
    assert v4["vitals"] == {
        "heart_rate_bpm": 76.0,
        "spo2_pct": 97.0,
        "skin_temp_c": None,
    }
    assert v4["measurements"]["heart_rate"] == {
        "raw_value": 76.4,
        "confirmed_value": 76.0,
        "valid": True,
        "state": "valid",
        "reason": None,
        "unit": "bpm",
    }
    assert v4["measurements"]["spo2"] == {
        "raw_value": 97.2,
        "confirmed_value": 97.0,
        "valid": True,
        "state": "valid",
        "reason": None,
        "unit": "%",
    }
    assert v4["quality"]["ppg_state"] == "valid"


def test_v4_unconfirmed_measurements_keep_raw_values_and_explain_invalidity(
    tmp_path, valid_telemetry_v4_payload
):
    payload = json.loads(json.dumps(valid_telemetry_v4_payload))
    payload["vitals"]["heart_rate_bpm"] = None
    payload["vitals"]["spo2_pct"] = None
    payload["quality"]["heart_rate_valid"] = False
    payload["quality"]["spo2_valid"] = False
    payload["quality"]["ppg_state"] = "unstable"
    database = Database(tmp_path / "v4-unconfirmed.db")
    database.initialize()

    database.insert_telemetry(
        TelemetryV4.model_validate(payload),
        datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        json.dumps(payload),
    )

    latest = database.latest_telemetry("health-node-01")
    assert latest["vitals"]["heart_rate_bpm"] is None
    assert latest["measurements"]["heart_rate"] == {
        "raw_value": 76.4,
        "confirmed_value": None,
        "valid": False,
        "state": "unstable",
        "reason": "unstable",
        "unit": "bpm",
    }
    assert latest["measurements"]["spo2"]["reason"] == "unstable"


def test_initialize_adds_current_columns_to_legacy_telemetry_without_data_loss(
    tmp_path, valid_telemetry_payload
):
    database = Database(tmp_path / "legacy-telemetry.db")
    database.initialize()
    received = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.insert_telemetry(
        Telemetry.model_validate(valid_telemetry_payload),
        received,
        json.dumps(valid_telemetry_payload),
    )
    with database.connection() as connection:
        legacy_row = dict(connection.execute("SELECT * FROM telemetry").fetchone())
        connection.execute("DROP TABLE telemetry")
        connection.executescript(
            """
            CREATE TABLE telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL REFERENCES devices(device_id),
                boot_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                uptime_ms INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                heart_rate_bpm REAL,
                spo2_pct REAL,
                skin_temp_c REAL,
                accel_g REAL,
                gyro_dps REAL,
                fall_state TEXT NOT NULL,
                ppg REAL,
                finger_present INTEGER NOT NULL,
                motion_artifact INTEGER NOT NULL,
                heart_rate_valid INTEGER NOT NULL,
                spo2_valid INTEGER NOT NULL,
                skin_temp_valid INTEGER NOT NULL,
                motion_valid INTEGER NOT NULL,
                rssi_dbm INTEGER,
                free_heap INTEGER,
                fw TEXT NOT NULL,
                faults_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                UNIQUE(device_id, boot_id, seq)
            );
            """
        )
        legacy_columns = (
            "id", "device_id", "boot_id", "seq", "uptime_ms", "received_at",
            "heart_rate_bpm", "spo2_pct", "skin_temp_c", "accel_g", "gyro_dps",
            "fall_state", "ppg", "finger_present", "motion_artifact",
            "heart_rate_valid", "spo2_valid", "skin_temp_valid", "motion_valid",
            "rssi_dbm", "free_heap", "fw", "faults_json", "raw_json",
        )
        connection.execute(
            f"INSERT INTO telemetry ({', '.join(legacy_columns)}) "
            f"VALUES ({', '.join('?' for _ in legacy_columns)})",
            tuple(legacy_row[name] for name in legacy_columns),
        )
        connection.commit()

    database.initialize()

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(telemetry)").fetchall()
        }
        row_count = connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    assert {
        "schema_version",
        "ambient_temp_c",
        "humidity_pct",
        "ambient_temp_valid",
        "humidity_valid",
        "wrist_surface_temp_c",
        "wrist_surface_temp_valid",
        "heart_rate_raw_bpm",
        "spo2_raw_pct",
        "ppg_state",
    } <= columns
    assert row_count == 1
    with database.connection() as connection:
        migrated_raw_json = connection.execute(
            "SELECT raw_json FROM telemetry"
        ).fetchone()[0]
    assert migrated_raw_json == legacy_row["raw_json"]
    migrated = database.latest_telemetry("health-node-01")
    assert migrated["schema"] == "health.telemetry.v1"
    assert migrated["vitals"]["skin_temp_c"] == 34.5
    assert migrated["environment"] == {"ambient_temp_c": None, "humidity_pct": None}
    assert migrated["wearable"] == {"wrist_surface_temp_c": None}
    assert migrated["quality"]["wrist_surface_temp_valid"] is False
    assert migrated["quality"]["ppg_state"] == "legacy"
    assert migrated["measurements"]["heart_rate"]["raw_value"] == 76.0
    assert migrated["measurements"]["heart_rate"]["confirmed_value"] == 76.0
    assert migrated["measurements"]["spo2"]["raw_value"] == 97.0

    with database.connection() as connection:
        changes_before = connection.total_changes
        Database._migrate_telemetry_columns(connection)
        assert connection.total_changes == changes_before


def test_initialize_resolves_active_alert_for_retired_surface_rule(tmp_path):
    database = Database(tmp_path / "retired-rule.db")
    database.initialize()
    happened = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-1", happened)
    alert = database.open_or_touch_alert(
        device_id="health-node-01",
        rule_id="surface_temp_demo",
        severity="warning",
        message="legacy",
        happened=happened,
        value=39.0,
    )

    database.initialize()

    assert database.get_active_alert("health-node-01", "surface_temp_demo") is None
    assert database.get_alert(alert["id"])["state"] == "resolved"
    with database.connection() as connection:
        history = connection.execute(
            "SELECT action, note FROM alert_history WHERE alert_id = ? ORDER BY id",
            (alert["id"],),
        ).fetchall()
    assert history[-1]["action"] == "resolved"
    assert history[-1]["note"] == "rule retired during DHT11 migration"


def test_initialize_migrates_legacy_global_event_dedupe_without_data_loss(tmp_path):
    database = Database(tmp_path / "legacy.db")
    database.initialize()
    happened = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("device-a", "boot-a", happened)
    alert, inserted = database.record_fall_event(
        device_id="device-a",
        event_id="shared-event-id",
        happened=happened,
    )
    assert inserted
    database.acknowledge_alert(alert["id"], "Tri", "Đã xem", happened)

    with database.connection() as connection:
        original_rows = connection.execute(
            """
            SELECT id, alert_id, action, happened_at, actor, note, source_event_id
            FROM alert_history ORDER BY id
            """
        ).fetchall()
        connection.execute("DROP TABLE alert_history")
        connection.execute(
            """
            CREATE TABLE alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT NOT NULL REFERENCES alerts(id),
                action TEXT NOT NULL CHECK (
                    action IN ('opened', 'event_repeated', 'acknowledged', 'resolved')
                ),
                happened_at TEXT NOT NULL,
                actor TEXT,
                note TEXT,
                source_event_id TEXT UNIQUE
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO alert_history (
                id, alert_id, action, happened_at, actor, note, source_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(row) for row in original_rows],
        )
        connection.commit()

    database.initialize()

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(alert_history)").fetchall()
        }
        migrated_rows = connection.execute(
            """
            SELECT id, alert_id, action, happened_at, actor, note,
                   source_device_id, source_event_id
            FROM alert_history ORDER BY id
            """
        ).fetchall()

    assert "source_device_id" in columns
    assert len(migrated_rows) == len(original_rows) == 2
    assert [row["id"] for row in migrated_rows] == [row["id"] for row in original_rows]
    assert migrated_rows[0]["source_device_id"] == "device-a"
    assert migrated_rows[0]["source_event_id"] == "shared-event-id"
    assert migrated_rows[1]["action"] == "acknowledged"
    assert migrated_rows[1]["actor"] == "Tri"
    assert migrated_rows[1]["note"] == "Đã xem"
    assert migrated_rows[1]["source_device_id"] is None
    assert migrated_rows[1]["source_event_id"] is None

    database.ensure_device("device-b", "boot-b", happened)
    _, second_inserted = database.record_fall_event(
        device_id="device-b",
        event_id="shared-event-id",
        happened=happened,
    )
    assert second_inserted

    with database.connection() as connection:
        event_devices = {
            row["source_device_id"]
            for row in connection.execute(
                """
                SELECT source_device_id FROM alert_history
                WHERE source_event_id = ?
                """,
                ("shared-event-id",),
            ).fetchall()
        }
    assert event_devices == {"device-a", "device-b"}
