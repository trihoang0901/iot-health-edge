# Health Node firmware

PlatformIO firmware for a NodeMCU ESP8266 prototype that samples MAX30102, a
supported MPU-6050 or MPU-6500-compatible motion sensor, and a powered
three-wire DS18B20 probe, then
publishes quality-tagged MQTT telemetry.

> This is a non-clinical teaching and demonstration prototype. It does not
> diagnose, treat, dispatch emergency services, or provide medical-grade heart
> rate, SpO2, wrist-surface temperature, or fall detection.

## Wiring

| Part | NodeMCU | Notes |
|---|---|---|
| MAX30102 SDA | D2 / GPIO4 | Shared I2C bus, address `0x57` |
| MAX30102 SCL | D1 / GPIO5 | Keep wires short |
| MPU motion SDA | D2 / GPIO4 | Shared I2C bus, address `0x68`; keep AD0 low |
| MPU motion SCL | D1 / GPIO5 | MPU-6050 or MPU-6500-compatible module |
| DS18B20 DATA | D5 / GPIO14 | Powered three-wire mode; `0x28` family only |
| Optional buzzer | D6 / GPIO12 | Through 1 kOhm base resistor and 2N2222 |
| Optional ACK button | D7 / GPIO13 | Button to GND; firmware uses `INPUT_PULLUP` |

Power the sensor breakout boards from 3.3 V unless their exact board schematic
proves that its logic-level pull-ups are safe for the ESP8266. Join all grounds.
The ESP8266 GPIO pins are not 5 V tolerant.

A DS18B20 DATA line needs a **4.7 kOhm pull-up to 3.3 V**. Connect VDD to 3.3 V,
GND to the common ground, and DATA to D5/GPIO14. Parasite-power mode is rejected
because the asynchronous conversion path does not provide a strong pull-up.
Firmware `0.3.1` also enables the ESP8266's weak internal pull-up as a fallback
for short prototype wiring. That fallback is not a substitute for the external
4.7 kOhm resistor; a stable wearable build still requires the external
DATA-to-3.3 V pull-up.
The probe reports local wrist-surface contact temperature only; it does not
measure core body temperature and is not a clinical thermometer.

Firmware `0.3.1` probes the motion sensor at I2C address `0x68` and then reads
register `WHO_AM_I` (`0x75`). It accepts only `0x68` for MPU-6050 or `0x70` for
an MPU-6500-compatible device. The I2C address and identity value are different
checks: an address scan alone is not proof that the supported sensor is ready.
Bring-up must also read a complete 14-byte motion frame beginning at register
`0x3B` and produce fresh finite acceleration and gyro telemetry. An unknown
identity, NACK, or partial frame fails closed. For contract compatibility, both
variants use the existing fault name `mpu6050_unavailable` when unavailable.

The buzzer and button are not in the original component list, so both are
compile-time optional and disabled by default. If a raw magnetic buzzer is
added, verify the particular 2N2222 pinout and add suitable flyback protection.
The built-in active-low LED remains enabled as a lightweight indicator:

- short pulse every 2 seconds: MQTT online;
- short pulse every second: offline/reconnecting;
- rapid pulse pattern: local fall alarm.

Acknowledgement through the edge dashboard is the primary MVP flow. A local
button only changes the firmware alarm when explicitly enabled.

## Configure, build, and flash

1. Install PlatformIO Core or use the PlatformIO IDE extension.
2. Copy `include/secrets.example.h` to `include/secrets.h`.
3. Put the hotspot credentials, laptop MQTT broker IPv4 address, the
   `health_node` broker account, and `DEVICE_ID` in the local file. The device
   ID must match the value passed to `Initialize-Mosquitto.ps1` (the default is
   `health-node-01`). Never commit the local file.
4. Connect the NodeMCU with a data-capable USB cable.
5. Run:

```powershell
pio run
pio run --target upload
pio device monitor
```

The project pins the tested dependency targets in `platformio.ini`. To enable
optional local hardware, change only these build flags to `1`:

```ini
-D ENABLE_LOCAL_BUZZER=1
-D ENABLE_LOCAL_ACK_BUTTON=1
```

## MQTT contract

The firmware only uses these per-device topics:

```text
iot-health/v1/devices/{device_id}/telemetry
iot-health/v1/devices/{device_id}/event
iot-health/v1/devices/{device_id}/status
```

Telemetry uses schema `health.telemetry.v3`. `vitals` contains HR and SpO2;
`wearable.wrist_surface_temp_c` contains the DS18B20 contact reading and is
paired with `quality.wrist_surface_temp_valid`. Measurements are JSON `null`
when invalid; JSON `NaN` is never emitted. `motion.accel_g` and
`motion.gyro_dps` are vector magnitudes. `quality.ppg` is a bounded 0..1
signal-quality heuristic, not a clinical confidence score.

Fall events use schema `health.event.v1` and type `fall_suspected_demo`. The
status topic uses retained `health.status.v1` messages and a retained MQTT Last
Will with `online=false`.

PubSubClient publishes at QoS 0. To reduce loss without pretending to provide
delivery guarantees, each fall event is kept in a four-entry RAM queue and sent
three times with the same `event_id`; the edge must deduplicate by `event_id`.
The queue does not survive power loss. If it overflows, the oldest event is
replaced and the sticky `event_queue_overflow` fault appears in later
telemetry/status. Telemetry is intentionally not queued, so reconnecting cannot
flood the broker with stale readings.

## Bounded sampling behavior

- The supported MPU-6050/MPU-6500-compatible motion sensor is sampled at 50 Hz.
- MAX30102 is drained every loop. Firmware `0.3.1` retains the `0.2.2` recovery
  behavior and does not reject a read from
  a pre-read `OVF_COUNTER`: after a startup overflow, a saturated counter can
  require a complete sample to be consumed before it clears, so using it as a
  gate can trap sampling in a clear-and-return loop.
- Continuity still fails closed. A sampling gap over 250 ms or four or more
  samples returned by SparkFun `check()` into its four-slot local buffer
  invalidates the current PPG window instead of publishing discontinuous data.
- The reference MAXIM HR/SpO2 calculation runs over a 100-sample rolling window
  no more than once per second.
- DS18B20 runs at 12-bit resolution. Firmware discovers an exact family-`0x28`
  ROM with addressed 1-Wire operations, requests a conversion, continues
  servicing MAX30102, motion, Wi-Fi, and MQTT for 750 ms, then reads the saved
  family-`0x28` address. There is no conversion delay in the application loop.
  The internal ESP8266 pull-up is only a prototype fail-safe; the external
  4.7 kOhm pull-up remains part of the supported wearable wiring.
  Missing, parasite-powered, disconnected, power-on-reset, insufficient-power,
  85 °C startup, non-finite, or out-of-range readings publish `null` with
  `ds18b20_unavailable`; discovery retries after 10 seconds.
- I2C clock stretching is limited to 50 µs per edge. Bus status is checked
  between MAX30102 and motion-sensor work; a failed bus is released/reinitialized,
  both sensors are marked unavailable, and an invalid motion sample cancels an
  in-progress fall candidate.
- Wi-Fi and MQTT retries use exponential backoff from 1 to 30 seconds with
  jitter. An MQTT TCP attempt can still block for the configured 1-second socket
  timeout, which is why FIFO backlog invalidates the current PPG window.

PubSubClient connection establishment is synchronous. TCP/DNS and MQTT CONNACK
can therefore interrupt motion/fall sampling for roughly two seconds per
backed-off reconnect attempt. The next sample gap cancels any partial fall
candidate and invalidates PPG, but an event occurring entirely inside that gap
can be missed. This explicit MVP limitation is another reason the prototype is
not a safety or clinical device.

## Demo calibration and quality caveats

The starting fall rule is low-g below 0.5 g for 150 ms, followed by impact over
2.5 g within 1 second and then at least 1.5 seconds of stillness. An impact-first
path handles demonstrations without a measurable low-g interval. These are
starting values, not universal fall thresholds. Record labeled sitting,
walking, lying down, dropping the device onto padding, and controlled mannequin
traces before changing them. Never test falls on a person.

MAX30102 readings depend on breakout design, ambient light, finger pressure,
skin perfusion, motion, and placement. The hard-coded finger threshold is only
a bring-up value. The firmware suppresses HR/SpO2 during motion artifact,
insufficient samples, unavailable motion-sensor quality data, implausible algorithm
output, or finger removal. It does not repeat a stale value as current.

The recovery diagnostic proved the raw optical path: bypassing the pre-read
overflow gate yielded about 25 samples/s, maximum observed loop gaps of 10-37
ms, and zero local-storage overflow hits. No-finger IR was about 812-853; an
earlier finger probe reached about 219,000-225,000. These values prove sensor
response, not medical accuracy. A later production check on firmware `0.2.2`
recorded 20 consecutive samples with `finger_present=true`, PPG quality
0.66-0.81, and valid HR/SpO2 outputs with stable placement. Firmware `0.3.1`
was uploaded during the 2026-08-14 bring-up after the host CH340 driver was
rolled back from `3.9.2024.9` to `3.7.2022.1`. An A/B scanner found no ROM in
the `external_only` branch; with the internal-pull-up fallback it found a valid
family-`0x28` ROM, valid CRC, addressed external power, and `27.3125 °C`.
After a hard reset, production boot `a164b119f1fd90b3` reported firmware
`0.3.1`, Wi-Fi at `192.168.137.37`, and MQTT connected. Fresh telemetry at
sequences 23, 25, and 28 reported `27.3125 °C`, valid wrist temperature,
valid/idle motion, and an empty `sensor_faults` list in all three samples.
MAX30102 no longer reported unavailable or `ppg_sample_loss`; because no finger
was present, HR and SpO2 correctly remained `null`. The dashboard showed the
node online, `27.3 °C` valid, firmware `0.3.1`, and no browser errors. This is
still not a new finger-present HR/SpO2 pass.

DS18B20 reports wrist-surface contact temperature only. A value within the
firmware's 0-50 °C validity range does not imply calibration, core-temperature
accuracy, or medical accuracy.

## Bring-up checks

1. Before treating the motion sensor as working, verify address `0x68`, then
   `WHO_AM_I=0x68` or `0x70`, a complete frame from `0x3B`, and fresh finite
   `motion.accel_g`/`motion.gyro_dps` values. Do not use an I2C ACK alone as a
   hardware pass.
2. Boot with each sensor disconnected in turn; MQTT/status must continue with a
   fault and nullable values, including `ds18b20_unavailable` for DS18B20.
3. Verify MAX30102 raw red/IR changes clearly between no-finger and a stable,
   correctly positioned finger. Raw optical response alone is not an HR/SpO2
   pass.
4. Remove a finger from MAX30102; HR and SpO2 must become `null`.
5. Move the board while collecting PPG; `motion_artifact` should suppress the
   derived values.
6. Disconnect the hotspot for five minutes; local sampling and LED behavior
   must continue, then MQTT must recover without a telemetry burst.
7. Verify repeated fall events share one `event_id` and the edge creates one
   alert.
8. Run for at least 60 minutes and watch free heap and resets.

Some phone hotspots isolate clients. Both the NodeMCU and laptop must be able to
reach each other, Mosquitto must listen beyond localhost, and Windows Firewall
must allow the chosen private network. Traffic between two clients on the same
hotspot may remain local Wi-Fi; do not claim measured 5G backhaul unless the
broker or edge endpoint is actually remote across the cellular link.
