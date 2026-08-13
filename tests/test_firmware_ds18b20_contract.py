from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "health-node"
APP_CONFIG = FIRMWARE / "include" / "AppConfig.h"
MODEL = FIRMWARE / "include" / "Model.h"
SENSOR_HUB_HEADER = FIRMWARE / "include" / "SensorHub.h"
SENSOR_HUB_SOURCE = FIRMWARE / "src" / "SensorHub.cpp"
SCHEDULE_HEADER = FIRMWARE / "include" / "Ds18b20Schedule.h"
SCHEDULE_TEST = FIRMWARE / "test" / "native" / "ds18b20_schedule_test.cpp"
MQTT_TRANSPORT = FIRMWARE / "src" / "MqttTransport.cpp"
PLATFORMIO = FIRMWARE / "platformio.ini"


def test_ds18b20_dependencies_pin_and_firmware_version_are_pinned():
    platformio = PLATFORMIO.read_text(encoding="utf-8")
    config = APP_CONFIG.read_text(encoding="utf-8")

    assert "milesburton/DallasTemperature@4.0.6" in platformio
    assert "paulstoffregen/OneWire@2.3.8" in platformio
    assert "DHT sensor library" not in platformio
    assert 'constexpr char kFirmwareVersion[] = "0.3.1";' in config
    assert "constexpr uint8_t kDs18b20Pin = D5;" in config
    assert "constexpr uint32_t kTemperatureConversionMs = 750;" in config


def test_ds18b20_conversion_is_addressed_async_and_fail_closed():
    header = SENSOR_HUB_HEADER.read_text(encoding="utf-8")
    source = SENSOR_HUB_SOURCE.read_text(encoding="utf-8")

    assert "#include <DallasTemperature.h>" in header
    assert "#include <OneWire.h>" in header
    assert "constexpr uint8_t kDs18b20Family = 0x28;" in source
    assert "setWaitForConversion(false)" in source
    assert "requestTemperaturesByAddress(ds18b20Address_)" in source
    assert "getTempC(ds18b20Address_)" in source
    assert "ds18b20Schedule_.conversionDue(nowMs)" in source
    assert "ds18b20Schedule_.retryDue(nowMs)" in source
    assert "ds18b20Schedule_.cycleDue(nowMs)" in source
    assert "ds18b20_.readPowerSupply(ds18b20Address_)" in source
    initialize_body = source.split(
        "bool SensorHub::initializeDs18b20(uint32_t nowMs)", maxsplit=1
    )[1].split("void SensorHub::tickDs18b20(uint32_t nowMs)", maxsplit=1)[0]
    pull_up = "pinMode(config::kDs18b20Pin, INPUT_PULLUP);"
    assert pull_up in initialize_body
    assert initialize_body.index(pull_up) < initialize_body.index(
        "discoverDs18b20Address()"
    )
    retry_body = source.split(
        "void SensorHub::tickDs18b20(uint32_t nowMs)", maxsplit=1
    )[1]
    assert "initializeDs18b20(nowMs);" in retry_body
    assert "external 4.7 kOhm DATA-to-3V3 pull-up remains mandatory" in source
    assert "ds18b20_.begin()" not in source
    assert "delay(" not in source
    assert "getTempCByIndex" not in source

    for rejected_value in (
        "DEVICE_DISCONNECTED_C",
        "DEVICE_POWER_ON_RESET_C",
        "DEVICE_INSUFFICIENT_POWER_C",
        "85.0F",
    ):
        assert rejected_value in source
    assert "isfinite(value)" in source
    assert "value >= 0.0F && value <= 50.0F" in source


def test_ds18b20_schedule_has_native_regressions():
    schedule = SCHEDULE_HEADER.read_text(encoding="utf-8")
    native_test = SCHEDULE_TEST.read_text(encoding="utf-8")

    assert "kConversionMs = 750" in schedule
    assert "kCycleMs = 2000" in schedule
    assert "kRetryMs = 10000" in schedule
    assert "static_cast<uint32_t>(nowMs - sinceMs)" in schedule
    assert "testConversionDeadlineAndCycleCadence" in native_test
    assert "testRetryDeadline" in native_test
    assert "testUnsignedMillisRollover" in native_test
    assert "testInvalidationCancelsPendingConversionAndCycle" in native_test
    assert "!schedule.measurementValid()" in native_test


def test_telemetry_v3_exposes_only_wrist_surface_temperature():
    model = MODEL.read_text(encoding="utf-8")
    transport = MQTT_TRANSPORT.read_text(encoding="utf-8")

    assert "NullableMeasurement wristSurfaceTempC;" in model
    assert "kFaultDs18b20" in model
    assert 'document_["schema"] = "health.telemetry.v3";' in transport
    assert '"wrist_surface_temp_c"' in transport
    assert 'quality["wrist_surface_temp_valid"]' in transport
    assert 'target.add("ds18b20_unavailable")' in transport

    active_contract = model + transport
    for retired_name in (
        "ambientTempC",
        "humidityPct",
        "ambient_temp_c",
        "humidity_pct",
        "kFaultDht11",
        "dht11_unavailable",
    ):
        assert retired_name not in active_contract
