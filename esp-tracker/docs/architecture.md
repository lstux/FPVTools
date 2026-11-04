# Architecture and implementation notes

## Data path

```
FC --CRSF--> ELRS RX ==2.4 GHz==> TX module (ESP32) --serial MSP v2--> TX Backpack (ESP)
   --ESP-NOW (channel 1, unicast to MAC = UID)--> tracker board --USB JSON lines--> backend --WebSocket--> browser
                                                        \--PWM--> pan / tilt servos
```

1. The flight controller sends CRSF telemetry frames (GPS, battery, attitude, flight mode) to the receiver; ELRS carries
   them down the radio link to the TX module, which also generates link statistics frames itself.
2. When the radio's *Backpack → Telemetry* option is `ESPNOW`, the TX module wraps **each CRSF frame in an MSP v2
   packet** (function `0x0011`, `MSP_ELRS_BACKPACK_CRSF_TLM`) and sends it to the TX Backpack over their serial link.
3. The Backpack sends that MSP packet as an **ESP-NOW unicast** to the MAC address equal to the ELRS UID.
4. The tracker board, whose Wi-Fi MAC is set to the same address, receives it.

Sources read to write this (ExpressLRS `master`, November 2026), useful when something changes upstream:

* `ExpressLRS/ExpressLRS`: `src/lib/Backpack/devBackpack.cpp` (`sendCRSFTelemetryToBackpack`),
  `src/src/tx_main.cpp` (which frames are forwarded), `src/python/build_flags.py` (UID from bind phrase).
* `ExpressLRS/Backpack`: `src/Tx_main.cpp` (`SetSoftMACAddress`, `sendMSPViaEspnow`, `OnDataRecv`, `setup`),
  `lib/MSP/msp.cpp`, `lib/MSP/msptypes.h`.
* ELRS documentation, *Backpack Telemetry* page (feature available from ELRS 3.4).

## Wire formats

### ESP-NOW payload = MSP v2 packet

```
'$' 'X' '<'  flags(1)  function(2, LE)  size(2, LE)  payload(size)  crc8_d5
```

`crc8_d5` is CRC-8 with polynomial `0xD5` (DVB-S2), init 0, over `flags … payload`. One ESP-NOW payload holds one packet
(the firmware still loops over the bytes with a streaming parser, like the Backpack does). Only function `0x0011` is
used; other functions (VTX config, bind...) are ignored.

### MSP payload = one complete CRSF frame

```
addr(1)  len(1)  type(1)  payload(len-2)  crc8_d5          len counts type + payload + crc; frame = len + 2 bytes
```

CRC over `type … payload`. Multi-byte values are big endian. Decoded frames:

| Type | Name | Payload layout | JSON event |
| --- | --- | --- | --- |
| `0x02` | GPS | lat int32 (°·1e7), lon int32, groundspeed u16 (0.1 km/h), heading u16 (0.01°), altitude u16 (m + 1000), sats u8 | `gps` |
| `0x08` | Battery | voltage u16 (0.1 V), current u16 (0.1 A), capacity u24 (mAh), remaining u8 (%) | `bat` |
| `0x14` | Link statistics | up RSSI1 (−dBm), up RSSI2, up LQ, up SNR i8, antenna, rf mode, tx power index, down RSSI (−dBm), down LQ, down SNR i8 | `link` |
| `0x1E` | Attitude | pitch, roll, yaw: i16, rad·10000 | `att` |
| `0x21` | Flight mode | NUL-terminated string | `mode` |

Other frame types are counted (`crsf_other`) and ignored. The "tx power index" is mapped to mW
(0, 10, 25, 100, 500, 1000, 2000, 250, 50); the "rf mode" is reported raw because its meaning depends on the band.

### UID, MAC address and channel

The ELRS UID is the first 6 bytes of `MD5('-DMY_BINDING_PHRASE="' + phrase + '"')` (that is literally what the ELRS build
scripts hash, quotes included). The Backpack soft-sets its Wi-Fi MAC to the UID **with bit 0 of the first byte cleared**
(a MAC must be unicast), uses Wi-Fi channel 1, and sends to that same address. The tracker therefore:

* derives the UID with its own MD5 (`lib/tracker_core/md5.cpp`, tested against Python's `hashlib`),
* sets `esp_wifi_set_mac(WIFI_IF_STA, uid & ~1)`, channel 1, `esp_now_init()`,
* accepts only frames whose source MAC equals that address.

### ESP-NOW reception

`startEspNow()` in `firmware/src/main.cpp` mirrors the Backpack's own `SetSoftMACAddress()`: STA mode, protocols
`11b/g/n/LR`, the `WiFi.begin(…, channel 1)` + `disconnect()` sequence (which selects channel 1), then the MAC. It additionally
disables Wi-Fi power save, since the radio only listens. The receive callback runs in the Wi-Fi task, so it only copies the
packet into a FreeRTOS queue (16 slots); `loop()` drains it. The callback has two signatures depending on the Arduino-ESP32
core (2.x passes a MAC pointer, 3.x an info struct): both are handled with `ESP_ARDUINO_VERSION_MAJOR`. The project pins
core 2.0.17 (`platform = espressif32@6.9.0`).

## Firmware

`firmware/lib/tracker_core` is plain C++11 with no Arduino dependency, so it is compiled and tested on a PC:

| File | Role |
| --- | --- |
| `crc8`, `md5` | checksums; bind phrase → UID → MAC; UID parsing (hex or decimal list) |
| `msp` | streaming MSP v2 parser (CRC check, oversize protection, error counters) |
| `crsf` | frame validation and decoders |
| `geo` | bearing, haversine distance, elevation, pan/tilt mapping with flip, servo slew limiter, angle → µs |
| `tracker_config` | persisted configuration struct, defaults, `SET` parameter table with range checks |
| `tracker` | the tracking engine (GPS in → target pan/tilt → slewed servo angles), no hardware access |
| `proto` | JSON event writers and the command parser |

`firmware/src/main.cpp` is the glue: NVS (`Preferences`) load/save of one `TrackerConfig` blob, ESP32Servo output at
50 Hz, ESP-NOW startup/queue, the serial line reader, periodic reports. Loop structure: drain ESP-NOW queue → read commands →
update servos every 20 ms → emit `trk` (0.5 s), `stat` (2 s), `hello` (10 s).

Design choices worth knowing:

* **No bind phrase in the firmware image.** It is a runtime command (`BIND`), stored as a UID, so one binary serves
  everyone and no secret ever sits in the repo.
* **USB-CDC never blocks.** On C3/S2 `Serial.setTxTimeoutMs(0)` is set, otherwise printing with no host connected stalls the
  loop and the servos with it.
* **Hold, do not wander.** When GPS quality is below `min_sats` or frames stop, the target is kept; `tracking` just turns false.
* **The host does not close the loop.** All real-time work (parsing, maths, servos) is on the board, so the tracker keeps
  working with the host unplugged (if a home was saved).

### Pointing maths

Azimuth is the great-circle initial bearing from the tracker to the drone, elevation is `atan2(Δaltitude, ground distance)`
clamped to 0–90° (altitudes are MSL on both sides). Two 180° servos cover a full circle with the **over-the-top**
trick: let `rel = (azimuth − offset) mod 360`.

* `rel ≤ 180`: `pan = rel`, `tilt = elevation`
* `rel > 180`: `pan = rel − 180`, `tilt = 180 − elevation` (the antenna passes over vertical and points backwards)

`offset` is the azimuth the antenna points to at `pan = 0, tilt = 0`. A hysteresis band (`hyst`, default 3°) around
`rel = 180` prevents flip-flopping. The slew limiter (`slew`, default 120°/s) moves the servos toward the target at a
bounded speed every 20 ms, which hides GPS update jitter and protects the mechanics. Angles become pulse widths with
`pan_min_us … pan_max_us` for 0…180° (optionally inverted).

## Serial protocol (board ↔ host)

Lines of UTF-8, `\n` terminated. Anything that is not a JSON object (boot ROM messages) is ignored/shown raw by the host.

**Board → host** (`ms` = board uptime in ms):

| `e` | Fields |
| --- | --- |
| `hello` | `fw`, `chip`, `uid` (hex or null), `espnow` (bool) |
| `gps` | `ms lat lon alt gs hdg sats` (deg, deg, m MSL, km/h, deg, count) |
| `bat` | `ms v a mah pct` |
| `link` | `ms rssi1 rssi2 lq snr ant rfmode txpwr drssi dlq dsnr` |
| `att` | `ms pitch roll yaw` (deg) |
| `mode` | `ms m` (flight mode text) |
| `trk` | `ms mode home hlat hlon halt tracking pan tilt tpan ttilt flip gps_age az el dist dist3d` (`az el dist dist3d` are null until home and GPS are known; `tpan/ttilt` are the targets, `pan/tilt` the current slewed angles) |
| `stat` | `ms espnow msp_ok msp_bad crsf_ok crsf_bad crsf_other dropped` |
| `cfg` | `uid home hlat hlon halt offset hyst slew pan_min_us pan_max_us tilt_min_us tilt_max_us pan_invert tilt_invert min_sats lost_ms` |
| `ack` / `err` / `help` | `cmd` / `msg` / `text` |

**Host → board**: the ASCII commands of the [usage guide](usage.md#7-serial-command-reference). The backend only forwards
commands whose first word is in a whitelist and rejects anything multi-line.

`backend/tests/fixtures/firmware_events.jsonl` is generated by the real firmware formatting code
(`make -C firmware/tests golden`) and is fed to the Python tests, so both sides are checked against each other.

## Backend

```
SerialSource | SimulatorSource | ReplaySource      (one thread each, push events)
        │  State.ingest_line / ingest
        ▼
      State (lock-protected: latest event per kind, track ring buffer, console, flight stats) ──► EventLogger (JSONL)
        ▲                                   │
        │ Source.send(cmd)                  ▼
   POST /api/cmd                     WebSocket /ws  (5 Hz: state + new track points + new console lines)
```

* `sources.py`: `SerialSource` reads bytes and splits lines itself (robust to partial lines), opens the port with
  DTR/RTS low (no accidental reset), reconnects forever, sends `STATUS` after each connection, and writes commands under a
  lock. `SimulatorSource` implements the firmware's command set and emits all event kinds from a circular flight; it
  reuses the same maths (`geo.py`) so the UI can be exercised end to end. `ReplaySource` replays a `--log` file.
* `state.py`: keeps the latest event of each kind with the host receive time, so the snapshot carries an `age` per section
  and the UI can dim stale data. The GPS trail only appends when the drone moved ≥ 2 m and has ≥ 4 satellites. The trail
  is a ring buffer (50 000 points) addressed by a monotonic index and a generation counter, so each WebSocket client
  gets exactly the points it has not seen and never loses sync, even after *Clear trail*.
* `server.py` (FastAPI): `GET /api/state`, `GET /api/config`, `POST /api/cmd`, `POST /api/track/clear`,
  `GET /api/track.gpx`, `GET /tiles/{z}/{x}/{y}` (MBTiles, converting the XYZ row to TMS), `WS /ws`, and the static UI.
* `static/`: no build step, Leaflet is vendored (works offline). The bind phrase is masked in the console echo.
* Security: the server listens on localhost by default. `--host 0.0.0.0` exposes unauthenticated control of the tracker to
  the network; use it on trusted networks only.

## Tests and what has (not) been verified

| Suite | Command | Covers |
| --- | --- | --- |
| C++ core | `make -C firmware/tests test` | 247 checks, built with `-Wall -Wextra -Werror` and AddressSanitizer/UBSan: CRC check value, MD5 against `hashlib` vectors (incl. padding boundaries), UID parsing, MSP/CRSF parsing (corruption, truncation, oversize, back-to-back packets), all decoders, geodesy, pan/tilt flip + hysteresis, tracker engine (slew, quality gate, hold, manual/auto), command parser, config limits, JSON output |
| Firmware glue | `make -C firmware/tests syntax` | `src/main.cpp` compiles (syntax and types) against stub Arduino-ESP32 headers for the three pin/LED variants |
| Backend | `cd backend && pytest` | 48 tests: state/track/console logic fed with real firmware output, command validation, simulator, serial loopback, log/replay, REST, WebSocket, MBTiles, CLI errors |
| UI | manual | Exercised in headless Chromium against the simulator (no JS errors, home/offset/manual/console/map-click flows) |

**Not verified**: a PlatformIO build of the three environments (toolchain downloads were not reachable where this was
written), running on a real board, the actual ESP-NOW link with a GX12 Backpack, and servo behaviour. The stubs only model
the Arduino-ESP32 calls used, so API mismatches with the real core would only show up at the first real build.

## Ideas

* BLE UART service on C3/ESP32 exposing the same JSON lines, for an Android client.
* ESP8266 (D1 mini) port.
* GPS + magnetometer on the tracker for automatic home and north.
* Stepper-driven continuous pan (removes the flip logic), `ESP-NOW` channel/`UID` sniffing to learn the UID automatically.
