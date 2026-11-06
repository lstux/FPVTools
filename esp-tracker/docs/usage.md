# Usage guide

Everything you need to go from parts to a working tracker. For *how it works* see
[architecture.md](architecture.md).

## 1. What you need

* A radio with an ExpressLRS TX module **that has a Backpack** (RadioMaster GX12, TX16S, Nomad...), and
  an ExpressLRS receiver on a drone that sends GPS telemetry (flight controller with GPS, CRSF telemetry
  enabled).
* An ESP32-C3, ESP32-S2 or classic ESP32 board (USB native on C3/S2, USB-UART bridge on most classic ones).
  The LilyGO **TTGO TS v1.2** has its own build with the status screen and buttons.
* Optional, on the tracker: a GPS module (automatic home), a compass + accelerometer (automatic north, level
  check) and a barometer, e.g. a "10DOF" I2C board. See [Sensors on the tracker](#sensors-on-the-tracker).
* Two hobby servos (pan + tilt) and a 5 V supply for them (a BEC or a power bank, **not** the board's 3.3 V pin).
* A computer for the ground station: Raspberry Pi 3B, Orange Pi, a PC... (Linux amd64/arm64, Windows, macOS: it is
  plain Python).

## 2. Wiring

| Signal | Board pin |
| --- | --- |
| Pan servo signal | `PIN_PAN` (C3: GPIO4, S2: GPIO5, ESP32: GPIO25) |
| Tilt servo signal | `PIN_TILT` (C3: GPIO5, S2: GPIO6, ESP32: GPIO26) |
| Servo power | external 5 V |
| Ground | servo ground **and** board ground joined |
| Board power / data | USB to the host |
| I2C sensors SDA / SCL (optional) | `PIN_SDA` / `PIN_SCL` (C3: 6/7, S2: 8/9, ESP32 and TTGO TS: 21/22), module powered from 3.3 V |
| GPS TX → board (optional) | `PIN_GPS_RX` (C3: 20, S2: 18, ESP32: 16, TTGO TS: 32); GPS powered from 3.3 V or 5 V as its board says |

These pin defaults are build flags in [`firmware/platformio.ini`](../firmware/platformio.ini). **Check them against
your board's pinout** (a pin may be used by an SD card slot, a display, a strapping function...) and change
`-DPIN_PAN` / `-DPIN_TILT` if needed. An optional activity LED (`-DPIN_LED=<gpio>`, `-DLED_ON_LEVEL=LOW` for active-low
LEDs) blinks on each GPS frame.

Mounting: tilt `0°` = antennas horizontal pointing in the pan direction, `90°` = vertical, `180°` = horizontal pointing
the opposite way. With two 180° servos the tracker reaches the whole circle by going "over the top" (see
[architecture](architecture.md#pointing-maths)).

### Sensors on the tracker

All optional and detected at boot; the **Sensors on the tracker** block of the *Tracker* panel (and the TTGO screen)
shows what was found.

| Part | Chips recognised | What it does |
| --- | --- | --- |
| GPS module (UART, NMEA) | any: BN-880, BN-220, NEO-6M/M8N... (GPS, GLONASS, Galileo, BeiDou talkers) | **automatic home**: after a good fix (≥ `min_sats`, HDOP ≤ 2.5) it averages 20 positions (~10 s) and sets the tracker position and altitude. The speed is detected (9600, 38400, 57600, 115200...) unless you `SET gps_baud`. |
| Compass | HMC5883L, QMC5883L (GY-271, GY-87, BN-880), AK8963 (inside an MPU9250, GY-91) | **automatic north**: once calibrated, the azimuth of the pan centre (`offset`) follows the compass, so you no longer measure it by hand. |
| Accelerometer | MPU6050, MPU6500, MPU9250, ADXL345 | tilt compensation of the compass and a **level** reading (the tracker should stand within a few degrees of level). The gyro is not used: the tracker does not move. |
| Barometer | BMP085/BMP180, BMP280, BME280 | pressure and temperature at the field (shown in the UI). |

A "10DOF" board such as the GY-87 (MPU6050 + HMC5883L or QMC5883L + BMP180) provides the last three on one I2C bus;
its compass sits behind the MPU6050 and is reached through the MPU's bypass mode, which the firmware enables.

**Mounting the compass.** Put it on the **fixed base** of the tracker (not on the part that pans), flat, components up,
at least 10 cm away from the servos, the VRX and any steel or magnet. Point the arrow printed for the X axis in the
direction the antenna looks at pan = 0 (`AIM 0 0`). If you cannot, measure the angle between the two and enter it as
*Compass mounting* (`SET compass_mount <deg>`, positive clockwise).

**Calibrating.** Required once per mounting (the screws, the servos and the board itself shift the readings):
*Tracker → Calibrate compass* (or `CAL MAG START`), turn the whole tracker slowly through one full circle, **keeping it
flat**, in about 20 s, then *Finish calibration* (`CAL MAG STOP`) and *Save to tracker* (`SAVE`). The progress shows the
share of the circle covered; if the turn was incomplete the tracker says so and keeps the previous calibration. *Forget
calibration* (`CAL MAG CLEAR`) goes back to raw readings.

**Declination.** GPS bearings are relative to true north, the compass to magnetic north: enter your local magnetic
declination (east positive, a couple of degrees east in France in 2026; look yours up with the NOAA
[magnetic field calculator](https://www.ngdc.noaa.gov/geomag/calculators/magcalc.shtml)) as *Magnetic declination*
(`SET declination 2.1`).

**North from compass / Typed azimuth** (`SET auto_north 1|0`) chooses whether the compass or the number you typed sets
the pan centre azimuth. Automatic north only applies once the compass is calibrated.

**Automatic home** (`SET auto_home 1|0`) applies when no home was chosen by hand: a home taken from the drone, the map or
typed coordinates is never overwritten. *Use tracker GPS* (`HOME GPS`) measures it again (e.g. after moving the
tracker). A home that came from the tracker GPS is re-measured at every power-up, since the tracker may be at a new field.

**Height from drone baro** (`SET alt_src 1`): the elevation angle normally uses the drone's GPS altitude minus the tracker
altitude. GPS altitude wanders by several metres; the flight controller's barometer is much steadier but measures from
where the drone was powered. If you plug the battery in next to the tracker, this gives a better elevation, especially
close in. It falls back to GPS when the drone sends no baro altitude.

### LilyGO TTGO TS v1.2

Build `ttgo_ts`. The board has a 1.8" ST7735 screen (160×128), three buttons and the I2C pins on its header:

| Use | GPIO |
| --- | --- |
| Pan / tilt servos | 26 / 33 |
| I2C sensors SDA / SCL | 21 / 22 |
| GPS module TX → | 32 |
| Buttons 1 / 2 / 3 | 34 / 35 / 39 |
| Screen (internal) | CS 16, DC 17, MOSI 23, SCLK 5, backlight 27 |

The screen lets you check everything without a computer. The coloured top bar is green when telemetry arrives, amber
when it stopped, red when the receiver is not set up (no UID).

* **Link**: LQ and RSSI (big), the UID and whether ESP-NOW runs, packets per second and the age of the last one, drone
  satellites, battery and flight mode, TX power, tracker GPS and home state.
* **Track**: distance and height above home (big), azimuth/elevation, pan/tilt (and *FLIP* when going over the top),
  auto/manual and tracking state, the pan offset (and whether the compass sets it), the height source, home position.
* **Sensors**: compass heading (big), accelerometer and level, compass calibration state, barometer, tracker GPS details.

Buttons: **1** next page; **hold 2** sets the home (tracker GPS if it has a fix, otherwise the drone's position), or
starts/finishes the compass calibration on the *Sensors* page; **hold 3** saves to flash. A message on the last line
confirms each action. If the buttons are in another order on your board, swap `PIN_BTN1..3` in `platformio.ini`; if the
picture is shifted by a few pixels or the colours are wrong, try `-DTFT_TAB=INITR_BLACKTAB` (or `INITR_REDTAB`) and
`-DTFT_SWAP_RB=1`.

## 3. Flash the firmware

Install [PlatformIO](https://platformio.org/install/cli) (`pip install platformio`), then from `firmware/`:

```sh
pio run -e esp32c3 -t upload      # ESP32-C3
pio run -e esp32s2 -t upload      # ESP32-S2 (hold BOOT while plugging in if it is not detected)
pio run -e esp32   -t upload      # classic ESP32 dev board
pio run -e ttgo_ts -t upload      # LilyGO TTGO TS v1.2 (screen + buttons)
pio device monitor                # JSON lines scroll by; type HELP
```

On Linux your user must be in the `dialout` group to open `/dev/ttyACM*` / `/dev/ttyUSB*`
(`sudo usermod -aG dialout $USER`, then log in again).

## 4. Configure the radio (GX12 / any ELRS TX with a Backpack)

1. Make sure the ELRS TX module firmware is **3.4.0 or newer** and its Backpack is up to date.
2. On the radio: **SYS → ExpressLRS.lua → Backpack → Telemetry → ESPNOW**, then exit the script.
   (Set it back to *Off* when you do not use the tracker: it reduces 2.4 GHz noise.)
3. Telemetry must be flowing normally: power the drone, wait for the link and check that GPS coordinates show on the
   radio's telemetry screen. The ELRS docs suggest a telemetry ratio between about 1:2 and 1:16 depending on packet rate.
4. Keep the tracker board within **5 m of the radio, 10 m at most**: the Backpack-to-board link is a plain Wi-Fi-class
   link with a tiny antenna.

### Bind phrase → UID

The Backpack and the tracker must share the same 6-byte ELRS **UID**, which ExpressLRS derives from your **bind phrase**.
Send the same phrase to the tracker (once, it is stored in flash):

```
BIND my secret phrase          # exactly the phrase you flashed into your TX module / receiver
```

The board stores the derived UID and reboots. The phrase itself is never stored, and the web UI hides it in its console.
If your devices were set up without a phrase, or you know the UID bytes (the ExpressLRS tools print them as
`UID bytes: 59,147,59,55,177,228`), set them directly instead:

```
UID 59,147,59,55,177,228       # or 12 hex digits: UID 3b933b37b1e4
```

Check it worked: `STATUS` should show `"espnow":true` and the packet counters in the `stat` line should start growing
once the drone is linked (section 7).

## 5. Run the ground station

```sh
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install .
esptracker --port auto            # picks the ESP32 USB device; or --port /dev/ttyACM0, --port COM5
```

Open <http://127.0.0.1:8080>. Useful options:

| Option | Meaning |
| --- | --- |
| `--simulate` | fake tracker and flight, no hardware (great to try the UI) |
| `--log flight.jsonl` / `--replay flight.jsonl [--speed 4] [--loop]` | record events, replay them later |
| `--home LAT,LON,ALT` | send `HOME` to the tracker each time it connects (fixed launch site) |
| `--host 0.0.0.0` | reach the UI from your phone/laptop on the same network. **There is no authentication**: anyone on that network can move the tracker and change its settings |
| `--http-port 8080` | web port |
| `--mbtiles map.mbtiles` | offline raster map tiles |
| `--tile-url URL` | other online tile server (`{z}/{x}/{y}` template) |
| `--video auto` / `--video /dev/video0` / `--video test` | show the goggles / VRX video behind the HUD (see [Video](#video-from-the-goggles-or-vrx)); `test` is an ffmpeg test pattern |
| `--video-size 1920x1080 --video-fps 30` | capture mode, must be one the dongle offers [1280x720, 30] |
| `--video-format yuyv422` | for a dongle without MJPEG (re-encoded, costs CPU) [mjpeg] |
| `--no-weather` / `--weather-cache FILE` | disable the forecast panel / where the last forecast is kept [~/.cache/esptracker/weather.json] |

The serial port is opened with DTR/RTS low so it does not reset the board. If the tracker is unplugged the
application keeps retrying and reconnects by itself.

### Video from the goggles or VRX

Walksnail Avatar / Avatar VRX / Ascent Pro and HDZero goggles or VRX have an HDMI output. A cheap HDMI → USB capture
dongle (MacroSilicon MS2109 / MS2130 and similar) shows up on Linux as a webcam (a *UVC* device, `/dev/video0`), no
driver needed. Check it with:

```sh
sudo apt install ffmpeg v4l-utils
v4l2-ctl --list-devices                         # find /dev/videoN of the dongle
v4l2-ctl -d /dev/video0 --list-formats-ext      # modes it offers (look for MJPG)
```

Two ways to show it, picked in **Display → Video → Source**:

* **Capture dongle on the ground station** (start with `--video auto` or `--video /dev/video0`): the backend runs ffmpeg
  and relays the picture as MJPEG to every browser, including your phone. The dongle already produces MJPEG, so frames are
  copied, not re-encoded: fine on a Raspberry Pi 3B. Capture only runs while somebody is watching. 720p30 is a good
  default; 1080p works too but is 3–6 MB/s per viewer over Wi-Fi.
* **Camera on this device**: the browser opens the dongle itself (plug it into the computer that shows the UI). Lowest
  latency, nothing goes through the backend, but browsers only allow it on `http://localhost` or `https`.

Expect ~50–150 ms of extra delay from the dongle: right for watching the flight and the HUD, not for flying through it.
If HDZero/Walksnail outputs a mode the dongle cannot take (e.g. 1080p60 into an MS2109), set the goggles' HDMI output to
720p/1080p30.

### Weather

The **Weather** panel uses [Open-Meteo](https://open-meteo.com) (free, no API key, CC BY 4.0) for the tracker position
(or the drone's when no home is set): wind and direction at 10/80/120/180 m above ground plus higher levels up to about
3 km (from the model's pressure levels), gusts, visibility, low/mid/high clouds, an estimated cloud base (from the dew
point spread, an approximation), rain probability, CAPE (convection, thermals and storms), freezing level and
sunrise/sunset, then the next 12 hours. Colours follow the two wind thresholds you set in **Display** (default 25 and
40 km/h). OpenWeather gives wind and visibility only at ground level and needs an API key, which is why it is not used.

The last forecast is saved on disk. At a field without internet the panel shows it with its age (fetch it at home before
leaving, it covers the next 48 hours).

### Raspberry Pi with a touch screen (kiosk)

A Raspberry Pi 3B with a 10.1" HDMI touch screen (1024×600) makes a self-contained ground station: the tracker and the
HDMI capture dongle on its USB ports, Chromium full screen on the cockpit. The image is prepared by
[`gen2install/DietPi/DietPi_Customize.sh`](https://github.com/lstux/gen2install/tree/main/DietPi) with `-G on`: it
installs ffmpeg and this backend on the first boot, runs it as a service and opens the kiosk on it.

Kiosk mode itself is a page option: open the UI once with `?kiosk` (the browser remembers it, `?kiosk=0` turns it off).
It makes the targets bigger for a resistive touch screen (whose pointer moves a few pixels between press and release:
a press released slightly off a button still clicks it), lets you drag the side panel to scroll it, hides the
full-screen button and draws the HUD 30 times a second instead of 60 (*Display → HUD refresh*), which leaves the Pi 3B's
CPU to the video. Keys, from a keyboard or the Pi's push buttons:

| Action | Keys | Pi push button (GPIO keys of the kiosk image) |
| --- | --- | --- |
| Swap video and map | `S`, Page Down | GPIO27 |
| Close the panel | Esc, Back | GPIO22 |
| Back to the main view (video in front, no panel, map following) | `H`, Home | GPIO17 |
| Open a panel: Tracker, Weather, Link, Console, Display | `1` … `5` | |
| Reload the page (long press: power off) | | GPIO23 |

On a Pi 3B the browser decodes the MJPEG video in software: keep the capture at 1280×720 (or 1024×576 if the dongle
offers it) and 30 fps; 1080p is too much for it.

### Offline maps

Online maps use OpenStreetMap tiles (see the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/);
fine for personal use). In the field without internet, make a **raster** MBTiles of your flying area (QGIS: *Generate XYZ
tiles (MBTiles)*; MOBAC and similar tools also export MBTiles) and start with `--mbtiles area.mbtiles`. A layer switch
(top right of the map) selects *Local tiles*, *OpenStreetMap* or *No map* (the trail and markers still work).

### Start automatically on a Raspberry Pi

```ini
# /etc/systemd/system/esptracker.service
[Unit]
Description=ESP tracker ground station
After=network.target

[Service]
User=pi
SupplementaryGroups=dialout
ExecStart=/home/pi/esp-tracker/backend/.venv/bin/esptracker --port auto --host 0.0.0.0 --log /home/pi/flights.jsonl
Restart=always

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now esptracker`.

## 6. Using the interface

The screen is laid out like a glass cockpit. Colours always mean the same thing: **green** normal, **amber** caution,
**red** warning, **cyan** tracker / target values, **magenta** home and the way back, **yellow** the drone itself.

* **Top strip**: tracker USB link, radio link (LQ and RSSI), drone GPS satellites, battery (pack and per-cell voltage),
  flight mode, armed time, clock, and the panel buttons.
* **Main view**: the video with the head-up display over it, or a synthetic horizon (blue sky / brown ground) when there
  is no video. The HUD shows:
  * pitch ladder and roll scale (from the FC attitude telemetry);
  * heading tape at the top (GPS course when moving faster than 10 km/h, FC yaw otherwise) with a magenta caret at the
    bearing to home, and below it a magenta arrow pointing home with the distance;
  * ground speed tape on the left (km/h), altitude tape on the right with the vario bar and vertical speed. The altitude
    is above home when the tracker home is set, else the FC baro altitude, else GPS altitude above sea level (choose in
    **Display**);
  * bottom left: flight mode, armed time, battery voltage per cell, mAh used; top right: LQ, RSSI, satellites;
  * warnings in the middle: FAILSAFE, TELEMETRY LOST, LINK %, BATTERY, GPS SATS, NO TRACKER.
* **Mini-map** bottom right: tap it (or press `S`) to swap map and video; the video then becomes the inset with a compact
  HUD. On the map: the drone (yellow arrow), its trail (cyan), the tracker (magenta H) and the line home. *Follow* keeps
  the drone centred (dragging the map turns it off), *Fit* frames the whole trail.
* **Bottom strip**: distance home (2D and 3D), height, speed, current and mAh, tracker azimuth/elevation and state, RSSI and
  SNR, wind at 120 m.
* **Panels** (top right buttons): *Tracker* (home, pointing, manual sliders, save), *Weather*, *Link* (radio details,
  flight statistics, reset trail, GPX download, raw position, tracker device counters), *Console* (what the tracker
  answers, type any command, e.g. `HELP`) and *Display* (video source, night/day map, HUD altitude source, battery cell
  count and low-cell voltage, wind thresholds, full screen). Display settings are remembered by the browser.

Armed time is guessed from the flight mode text: Betaflight adds `*` while disarmed, iNav sends `OK`/`WAIT`. Battery cell
count is guessed from the highest voltage seen (set it in **Display** if you plug a partly used pack).

### Telling the tracker where it is ("home")

The tracker needs its own position **and altitude above sea level**, because the elevation angle uses the height
difference to the drone. With a GPS module on the tracker this is automatic (see
[Sensors on the tracker](#sensors-on-the-tracker)); otherwise use one of these:

| Button | When to use it |
| --- | --- |
| **Use drone position** | Best: put the drone next to the tracker, wait for 6+ satellites, press it. Uses the drone's own GPS fix and altitude, so it is consistent with the telemetry. |
| **Pick on map** | Click the map where the tracker stands. Altitude: the *Altitude of the tracker* field, else the current home altitude, else the drone's altitude. Check it. |
| **Use this device** | Uses the browser's geolocation (needs `https` or `http://localhost`, so not over a plain LAN address). |
| **Clear** | Forget it; the tracker holds position. |

`Save to tracker` stores the home, the offset and all settings in the board's flash so they survive a power cycle
(otherwise home is forgotten at boot, which is usually what you want for a new site).

### Calibration

1. **Servo travel.** Switch to *Manual*, move the sliders to the ends and look at the mechanics. The defaults map
   0–180° to 500–2500 µs. Adjust to your servos and mount: `SET pan_min_us 600`, `SET pan_max_us 2400`, same for
   `tilt_*`. Use `SET pan_invert 1` / `SET tilt_invert 1` if a servo moves the wrong way. Then `SAVE`.
2. **Pan zero azimuth** (skip this with a calibrated compass and *North from compass*). Point the pan servo at 0° (`AIM 0 0`) and measure the compass bearing the antenna now points
   to (a phone compass is fine; add your local magnetic declination, GPS bearings are relative to *true* north).
   Enter it in *Azimuth of the pan centre* (or `SET offset 215`). Then `SAVE`.
3. **Check** in *Auto* mode with the drone (or `--simulate`): the tracker status says *tracking* and the antennas follow.
   Turning your body 180° around the tracker is a good test of the over-the-top flip near the pan limits.

Other settings (`SET key value`): `hyst` (flip hysteresis, °), `slew` (max servo speed, °/s), `min_sats` (GPS quality gate),
`lost_ms` (how long a GPS frame counts as recent). `STATUS` prints them all.

## 7. Serial command reference

One command per line, case-insensitive; the answers are JSON lines (`ack`, `err`, ...).

| Command | Effect |
| --- | --- |
| `HELP`, `PING`, `STATUS` | help text, liveness check, dump of hello/config/tracker/stat lines |
| `BIND <phrase>` | derive and store the ELRS UID from a bind phrase, then reboot |
| `UID <12 hex \| d,d,d,d,d,d>` | store the UID directly, then reboot |
| `HOME <lat> <lon> <alt>` | tracker position (degrees, metres above sea level) |
| `HOME DRONE` | use the drone's current GPS position; `HOME CLEAR` forgets it |
| `HOME GPS` | measure the home again with the tracker's own GPS (averaged over ~10 s) |
| `CAL MAG START` / `CAL MAG STOP` / `CAL MAG CLEAR` | compass calibration: start, finish (keeps it if the turn was complete), forget |
| `MODE AUTO` / `MODE MANUAL` | follow the drone / hold the servos where you put them |
| `AIM <pan> <tilt>` | manual angles 0–180 (implies manual mode) |
| `SET <key> <value>` | `offset hyst slew pan_min_us pan_max_us tilt_min_us tilt_max_us pan_invert tilt_invert min_sats lost_ms`, and for the tracker sensors `alt_src` (0 GPS, 1 drone baro), `auto_home`, `auto_north` (0/1), `compass_mount`, `declination` (degrees), `gps_baud` (0 = detect) |
| `SAVE` | persist the configuration (including home) in flash |
| `FACTORY` | erase the stored configuration and reboot |
| `REBOOT` | restart the board |

## 8. Troubleshooting

Open the console or `pio device monitor` and read the `stat` line (every 2 s):

| Symptom | Likely cause |
| --- | --- |
| `hello` says `"espnow":false` and `"uid":null` | No UID yet: use `BIND` or `UID`. |
| `espnow` stays 0 | Radio *Backpack → Telemetry* is not `ESPNOW`; wrong UID / bind phrase; board too far from the radio; drone not linked (no telemetry at all). Check telemetry on the radio's own screen first. |
| `espnow` grows but `msp_ok` stays 0 | Radio interference or a non-ELRS sender with the same MAC. |
| `msp_ok` grows, `crsf_ok` does not | Telemetry frames not decodable: update the ELRS/Backpack firmware. |
| `crsf_ok` grows but no `gps` line | The drone does not send GPS telemetry (enable the CRSF GPS sensor on the flight controller) or has no fix; `crsf_other` counts frame types the tracker ignores. |
| `gps` lines arrive but the tracker is "waiting for GPS" | Fewer satellites than `min_sats` (default 6) or the home is not set. |
| `dropped` > 0 | The board's main loop was starved (long serial blocking); keep the host connected or reduce other USB load. |
| UI says "no tracker" | Wrong port, missing `dialout` permission, or another program (serial monitor) holds the port. |
| Antenna points the wrong way | Pan zero azimuth, or servo inversion, or a mirrored mount: see calibration. |
| `sens` says the compass is not found | Wrong SDA/SCL, module not powered, or a compass the firmware does not know (the console shows the detected chips at boot in the `sens` line). |
| Heading jumps when the servos move | The compass is too close to the servos' magnets / currents: move it away, on the fixed base, and calibrate again. |
| Heading is off by a constant angle | Declination or compass mounting angle; or the compass X arrow is not aligned with pan = 0. |
| Tracker GPS shows no NMEA | GPS TX not on `PIN_GPS_RX`, or no common ground; check the `tgps` line: `good` must grow. |
| Servos jitter or the board resets when they move | Servo power is shared with the board: give the servos their own 5 V supply and a common ground. |

## 9. Known limits and ideas

* Not validated on real hardware yet; pins and defaults need checking on your boards.
* Only ESP32-C3/S2/ESP32. ESP8266 boards (Wemos D1 mini) work for ESP-NOW in principle but need a different
  ESP-NOW/servo API: not implemented.
* No GPS or compass on the tracker (planned: auto home, automatic north).
* Pan is limited to 180° per servo (a continuous/stepper pan would remove the flip logic).
* Android: the same JSON lines could be exposed over BLE (C3 / classic ESP32). Not implemented.
