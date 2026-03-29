# Drop Logger — User Guide

![logo](droplogger_logo.png)

## Overview

The Drop Logger is an ESP32-S3-based data logger designed to record barometric pressure, acceleration, and gyroscope data at high frequency. It uses two sensors over I2C:

- **BMP581** — barometric pressure sensor (records pressure difference from a reference taken at startup)
- **ICM20649** — 6-axis accelerometer and gyroscope (records 3-axis acceleration in m/s² and 3-axis rotation in °/s)

The device is designed to be mounted inside a 3D-printed hailstone and dropped from a drone at heights of 100–250 m. The recorded data allows characterisation of tumbling motions and fall dynamics of non-spherical hailstones.

The device is controlled entirely with the **BOOT button** (GPIO 0) and provides feedback through an **onboard LED** (GPIO 2).

---

## Hardware Connections

| Component | ESP32-S3 Pin |
|-----------|-------------|
| I2C SCL | GPIO 6|
| I2C SDA | GPIO 5 |
| LED | GPIO 2 |
| BOOT button | GPIO 0 |
| BMP581 address | 0x47 |
| ICM20649 address | 0x68 |

---

## Device Modes

On power-up the device enters a waiting state and continuously monitors the accelerometer. There are three ways to proceed:

| Trigger | Action | LED Feedback |
|---------|--------|-------------|
| **Fall detected** | Logging starts automatically | Single flash, then LED on |
| **Short button press** (<2 s) | Logging starts manually | Single flash, then LED on |
| **Long button press** (≥2 s) | WiFi file server starts | LED blinks while held, then triple blink |

The serial console prints the available options on startup:

```
Waiting to start...
  Short press / fall detected = start data logger
  Long press (2s)             = start WiFi file server
```

### Fall Detection

The device continuously reads the accelerometer and computes total acceleration magnitude (`√(aX² + aY² + aZ²)`). If this value drops below **5 m/s²** for **10 consecutive readings**, the device assumes it is in freefall and starts logging automatically. This means you can power on the device before mounting it in the hailstone, and logging will begin on its own when dropped.

### Button Press Detection

While the BOOT button is held down, the LED blinks to provide feedback. If held for more than 2 seconds the LED switches to a fast blink pattern to indicate the long press has been registered. On release:

- **Short press** — a brief flash confirms the press, and logging begins.
- **Long press** — a triple blink confirms file server mode, then the WiFi access point starts.

---

## Data Logging

### Starting a Log

Logging starts via any of the three triggers described above. Once running, the **LED stays on** to indicate data is being recorded.

### Stopping a Log

The BOOT button is only checked every **1,000 samples** to minimise I/O overhead. To stop recording:

1. **Press the BOOT button** — it will be detected at the next 1,000-sample boundary.
2. The **LED turns off** and the serial console prints `Finished`.
3. The data file is flushed and closed.

### Output Files

Data files are saved to the `/data/` directory on the ESP32's flash filesystem. Each run creates a new file with an auto-incrementing number: `droplogger_data_1.csv`, `droplogger_data_2.csv`, etc.

### CSV File Format

Each file contains a header row, a reference row, and then continuous data rows.

**Header:**

```
time(s),Pressure Difference(hPa),aX(ms^-2),aY(ms^-2),aZ(ms^-2),gX(deg/s),gY(deg/s),gZ(deg/s)
```

**Reference row:** The first data row has time set to `-0.001` and the second column contains the **absolute reference pressure** in hPa at startup. Remaining columns are empty. This allows you to reconstruct absolute pressure from the differential values in subsequent rows: `absolute_pressure = ref_pressure − pressure_difference`.

**Data columns:**

| Column | Unit | Description |
|--------|------|-------------|
| `time(s)` | seconds | Elapsed time since logging started (microsecond resolution) |
| `Pressure Difference(hPa)` | hPa | `ref_pressure − current_pressure`. Positive values mean pressure has decreased (altitude increased). |
| `aX(ms^-2)` | m/s² | Acceleration along X axis |
| `aY(ms^-2)` | m/s² | Acceleration along Y axis |
| `aZ(ms^-2)` | m/s² | Acceleration along Z axis |
| `gX(deg/s)` | °/s | Rotation rate around X axis (integer) |
| `gY(deg/s)` | °/s | Rotation rate around Y axis (integer) |
| `gZ(deg/s)` | °/s | Rotation rate around Z axis (integer) |

---

## Downloading Data

There are two ways to get data off the device: over WiFi using the built-in file server, or over USB.

### Option 1: WiFi File Server (Recommended)

This is the easiest method and doesn't require any software on your computer beyond a web browser.

1. **Power on** the device.
2. **Long-press the BOOT button** (hold for ≥2 seconds). The LED will blink while held and then triple-blink to confirm.
3. The device creates a **WiFi access point** named after the device (default: `droplogger-test`). The password is `hailstone`.
4. **Connect your phone or laptop** to this WiFi network.
5. **Open a browser** and navigate to `http://192.168.4.1`.
6. You'll see a file listing page where you can **download** or **delete** individual files, or **delete all** files at once.

The WiFi name and password can be changed by editing `logger_name` and the password string in `main.py`.

### Option 2: USB (via serial tools)

Connect to the ESP32-S3 over USB and use one of these tools:

- **Thonny IDE** — Connect to the board, navigate to `/data/` in the file browser, right-click a file and choose "Download to…".
- **mpremote** — `mpremote cp :/data/droplogger_data_1.csv .`
- **ampy** — `ampy --port /dev/ttyUSB0 get /data/droplogger_data_1.csv > droplogger_data_1.csv`

Replace the serial port (`/dev/ttyUSB0`, `COM3`, etc.) as appropriate for your system.

---

## Converting Binary Files to CSV

If you have `.bin` files from the logger (binary format, identified by the `DL01` magic header), you can convert them to CSV on your desktop computer using `unpack_droplogger_binary.py`. This is a standard Python script (not MicroPython) — run it on your PC.

**Basic usage:**

```bash
python unpack_droplogger_binary.py droplogger_data_1.bin
```

This produces `droplogger_data_1.csv` alongside the original file.

**Specify output path:**

```bash
python unpack_droplogger_binary.py droplogger_data_1.bin -o output.csv
```

The binary format uses an 8-byte header (4-byte magic + float32 reference pressure) followed by 20-byte rows, so binary files are significantly smaller than their CSV equivalents.

---

## Configuration

### Device Name

Edit `logger_name` at the top of `main.py` to change the device name. This is used as the WiFi access point name:

```python
logger_name = 'droplogger-test'
```

### Fall Detection Sensitivity

In `main.py`, these variables control the automatic fall trigger:

```python
fall_trigger_counter_limit = 10   # consecutive low-g readings required
fall_trigger_a_threshold = 5      # m/s² — readings below this count as freefall
```

Lowering the threshold or increasing the counter limit makes fall detection less sensitive (fewer false triggers). Raising the threshold or lowering the limit makes it more sensitive.

---

## Code Overview — `drop_logger_3.py`

This section walks through the main logging script for anyone wanting to modify it.

### Imports and Helpers

```python
def count_files(path, extension):
    return sum(1 for f in os.listdir(path) if f.endswith(extension))
```

This utility counts existing files in `/data/` with a given extension so the next file gets an incremented filename.

### Sensor Initialisation

The `main()` function sets up both sensors on a shared I2C bus:

- **ICM20649** is configured with a gyro range of ±4,000 °/s (`RANGE_4000_DPS`) to capture fast rotations without clipping.
- **BMP581** is configured for speed over precision: 1× oversampling on both pressure and temperature, no IIR filtering (`COEF_0`). This gives the fastest possible sample rate at the cost of some noise.

A "burn" read (`_ = bmp.pressure`) discards the first pressure measurement after power-on, which can be unreliable. The second read is saved as the reference pressure.

### The Logging Loop

The core loop runs as fast as the I2C reads allow (no explicit delay):

1. **Read pressure** and compute the difference from the reference.
2. **Read acceleration** — raw 3-axis values in m/s².
3. **Read gyroscope** — raw 3-axis values in °/s (written as integers).
4. **Timestamp** using `utime.ticks_us()` for microsecond resolution.
5. **Write** a formatted CSV row to the open file.

Every 1,000 rows the file buffer is flushed to flash storage and the BOOT button is checked. This batching approach keeps I/O overhead low during fast sampling.

### Key Variables You Might Want to Change

- **`verbose`** (line 15) — Set to `True` to print each row to the serial console. Useful for debugging but significantly slows down logging.
- **Sensor oversampling** (lines 31–33) — Increase `pressure_oversample_rate` or `temperature_oversample_rate` (e.g., `OSR4`, `OSR8`) for lower noise at slower sample rates.
- **Gyro range** (line 27) — Lower the range (e.g., `RANGE_2000_DPS`, `RANGE_1000_DPS`) if you don't need ±4,000 °/s; this gives finer angular precision.
- **Flush interval** (line 72) — The `1000` sample threshold before flushing. Lower values reduce data loss risk if power is cut but add I/O overhead.
- **Output format** (line 65) — Edit the format string and `cols` list on line 49 if you want to change precision or add/remove columns.
- **Data directory and naming** (lines 41–42) — Change the path or naming convention for output files.

---

## File Structure Summary

| File | Runs on | Role |
|------|---------|------|
| `main.py` | ESP32 | Entry point — fall detection, button handling, launches logger or file server |
| `drop_logger_3.py` | ESP32 | Core high-speed sensor logging to CSV |
| `file_server.py` | ESP32 | WiFi access point and HTTP file server for downloading/deleting data |
| `bmpxxx.py` | ESP32 | MicroPython driver for BMP581/585/390/280/BME280 pressure sensors |
| `icm20649.py` | ESP32 | MicroPython driver for ICM20649 accelerometer/gyroscope |
| `i2c_helpers.py` | ESP32 | Low-level I2C register read/write utilities used by the BMP driver |
| `boot.py` | ESP32 | MicroPython boot file (default, mostly empty) |
| `unpack_droplogger_binary.py` | Desktop PC | Converts binary `.bin` log files to CSV |
