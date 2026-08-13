from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from edge.db import Database
from edge.schemas import Telemetry, TelemetryV2, TelemetryV3


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


def test_v1_v2_and_v3_rows_share_database_with_normalized_additive_responses(
    tmp_path,
    valid_telemetry_payload,
    valid_telemetry_v2_payload,
    valid_telemetry_v3_payload,
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

    v1, v2, v3 = database.telemetry_history("health-node-01")
    assert v1["schema"] == v1["schema_version"] == "health.telemetry.v1"
    assert v1["vitals"]["skin_temp_c"] == 34.5
    assert v1["environment"] == {"ambient_temp_c": None, "humidity_pct": None}
    assert v1["wearable"] == {"wrist_surface_temp_c": None}
    assert v1["quality"]["ambient_temp_valid"] is False
    assert v1["quality"]["humidity_valid"] is False
    assert v1["quality"]["wrist_surface_temp_valid"] is False
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
