# Drop Logger — User Guide

![logo](droplogger_logo.png)

## Table of Contents

- [Overview](#overview)
- [Hardware Connections](#hardware-connections)
- [Device Modes](#device-modes)
  - [Fall Detection](#fall-detection)
  - [Button Press Detection](#button-press-detection)
- [Data Logging](#data-logging)
  - [Starting a Log](#starting-a-log)
  - [Stopping a Log](#stopping-a-log)
  - [Output Files](#output-files)
  - [Binary File Format](#binary-file-format)
- [Downloading Data](#downloading-data)
  - [Option 1: WiFi File Server (Recommended)](#option-1-wifi-file-server-recommended)
  - [Option 2: USB (via serial tools)](#option-2-usb-via-serial-tools)
- [Converting Binary Files to CSV](#converting-binary-files-to-csv)
- [Configuration](#configuration)
  - [Device Name](#device-name)
  - [Fall Detection Sensitivity](#fall-detection-sensitivity)
- [Code Overview — `drop_logger.py`](#code-overview--drop_loggerpy)
  - [Imports and Helpers](#imports-and-helpers)
  - [Sensor Initialisation](#sensor-initialisation)
  - [The Logging Loop](#the-logging-loop)
  - [Key Variables You Might Want to Change](#key-variables-you-might-want-to-change)
- [File Structure Summary](#file-structure-summary)

---

## Overview

The Drop Logger is an ESP32-S3-based data logger designed to record barometric pressure, acceleration, and gyroscope data at high frequency. It uses two sensors over I2C:

- **BMP581** — barometric pressure sensor (records pressure difference from a reference taken at startup)
- **ICM20649** — 6-axis accelerometer and gyroscope (records acceleration magnitude in m/s² and 3-axis rotation in °/s)

The device is designed to be mounted inside a 3D-printed hailstone and dropped from a drone at heights of 100–250 m. The recorded data allows characterisation of tumbling motions and fall dynamics of non-spherical hailstones.

The device is controlled entirely with the **BOOT button** (GPIO 0) and provides feedback through an **onboard LED** (GPIO 2).

---

## Hardware Connections

| Component | ESP32-S3 Pin |
|-----------|-------------|
| I2C SCL | GPIO 6 |
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
| **Fall detected** | Logging starts automatically | LED on |
| **Short button press** (<2 s) | Logging starts manually | Single flash, then LED on |
| **Long button press** (≥2 s) | WiFi file server starts | LED blinks while held, then triple blink |

The serial console prints the available options on startup:

```
Waiting to start...
  Short press / fall detected = start data logger
  Long press (2s)             = start WiFi file server
```

### Fall Detection

The device continuously reads the accelerometer and computes total acceleration magnitude (`√(aX² + aY² + aZ²)`). If this value drops below **5 m/s²** for **5 consecutive readings**, the device assumes it is in freefall and starts logging automatically. This means you can power on the device before mounting it in the hailstone, and logging will begin on its own when dropped.

### Button Press Detection

While the BOOT button is held down, the LED blinks to provide feedback. If held for more than 2 seconds the LED switches to a fast blink pattern to indicate the long press has been registered. On release:

- **Short press** — a brief flash confirms the press, and logging begins.
- **Long press** — a triple blink confirms file server mode, then the WiFi access point starts.

---

## Data Logging

### Starting a Log

Logging starts via any of the three triggers described above. Once running, the **LED stays on** to indicate data is being recorded.

### Stopping a Log

Press the **BOOT button** at any time to stop recording. The button is checked on every sample iteration:

1. **Press the BOOT button** — recording stops immediately.
2. The **LED turns off** and the serial console prints `Finished`.
3. The data file is flushed and closed.

Logging will also stop automatically if free storage drops below ~50 KB.

### Output Files

Data files are saved to the `/data/` directory on the ESP32's flash filesystem in binary format. Each run creates a new `.bin` file with an auto-incrementing number using the device name: `droplogger_1.bin`, `droplogger_2.bin`, etc. (or `{device_name}_1.bin` if you've changed the device name).

### Binary File Format

Each file uses the `DL01` binary format, consisting of a header followed by fixed-size data rows.

**Header (8 bytes):**

| Field | Type | Description |
|-------|------|-------------|
| Magic | 4 bytes | `DL01` — format identifier |
| Reference pressure | float32 | Absolute pressure in hPa at startup |

**Row (16 bytes each):**

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `time_ms` | uint32 | milliseconds | Elapsed time since logging started |
| `p_diff` | int32 | milli-hPa | `(ref_pressure − current_pressure) × 1000`. Positive values mean pressure has decreased (altitude increased). |
| `a_mag` | uint16 | centi-m/s² | Acceleration magnitude × 100 (`√(aX² + aY² + aZ²)`), with a scale correction applied |
| `gX` | int16 | °/s | Rotation rate around X axis (integer) |
| `gY` | int16 | °/s | Rotation rate around Y axis (integer) |
| `gZ` | int16 | °/s | Rotation rate around Z axis (integer) |

All values are big-endian. To reconstruct absolute pressure: `absolute_pressure = ref_pressure − (p_diff / 1000)`.

---

## Downloading Data

There are two ways to get data off the device: over WiFi using the built-in file server, or over USB.

### Option 1: WiFi File Server (Recommended)

This is the easiest method and doesn't require any software on your computer beyond a web browser.

1. **Power on** the device.
2. **Long-press the BOOT button** (hold for ≥2 seconds). The LED will blink while held and then triple-blink to confirm.
3. The device creates a **WiFi access point** named after the device (default: `droplogger`). The password is `hailstone`.
4. **Connect your phone or laptop** to this WiFi network.
5. **Open a browser** and navigate to `http://192.168.4.1`.
6. You'll see a file listing page where you can **download** or **delete** individual files, or **delete all** files at once.

The device name (and therefore WiFi AP name) is read from `device_name.txt` on the ESP32's filesystem. See [Configuration](#configuration) for details.

### Option 2: USB (via serial tools)

Connect to the ESP32-S3 over USB and use one of these tools:

- **Thonny IDE** — Connect to the board, navigate to `/data/` in the file browser, right-click a file and choose "Download to…".
- **mpremote** — `mpremote cp :/data/droplogger_1.bin .`
- **ampy** — `ampy --port /dev/ttyUSB0 get /data/droplogger_1.bin > droplogger_1.bin`

Replace the serial port (`/dev/ttyUSB0`, `COM3`, etc.) as appropriate for your system.

---

## Converting Binary Files to CSV

If you have `.bin` files from the logger (binary format, identified by the `DL01` magic header), you can convert them to CSV on your desktop computer using `unpack_droplogger_binary.py`. This is a standard Python script (not MicroPython) — run it on your PC.

> **Note:** The unpack script currently expects the older binary format with individual aX/aY/aZ columns (20-byte rows), but the logger now writes acceleration magnitude only (16-byte rows). The unpack script needs to be updated to match — see the note below.

**Basic usage:**

```bash
python unpack_droplogger_binary.py droplogger_1.bin
```

This produces `droplogger_1.csv` alongside the original file.

**Specify output path:**

```bash
python unpack_droplogger_binary.py droplogger_1.bin -o output.csv
```

**Batch convert a folder:**

```bash
python unpack_droplogger_binary.py /path/to/folder/
python unpack_droplogger_binary.py /path/to/folder/ --replace
```

---

## Configuration

### Device Name

The device name is read from a file called `device_name.txt` on the ESP32's filesystem. If the file doesn't exist or is empty, the default name `droplogger` is used. This name is used for both the WiFi access point SSID and the binary file naming.

To change the device name, create or edit `device_name.txt` on the ESP32 (e.g. via Thonny or mpremote):

```
my-hailstone-1
```

### Fall Detection Sensitivity

In `main.py`, these variables control the automatic fall trigger:

```python
fall_trigger_counter_limit = 5    # consecutive low-g readings required
fall_trigger_a_threshold = 5      # m/s² — readings below this count as freefall
```

Lowering the threshold or increasing the counter limit makes fall detection less sensitive (fewer false triggers). Raising the threshold or lowering the limit makes it more sensitive.

---

## Code Overview — `drop_logger.py`

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

An accelerometer scale correction factor is applied to compensate for sensor bias: `accel_scale_correction = 9.80665 / a_mag_at_rest` where `a_mag_at_rest` is the measured magnitude when stationary (currently `10.21 m/s²`).

### The Logging Loop

The core loop runs as fast as the I2C reads allow (no explicit delay):

1. **Read pressure** and compute the difference from the reference.
2. **Read acceleration** — 3-axis values are read and combined into a single magnitude (`√(aX² + aY² + aZ²)`), then scale-corrected.
3. **Read gyroscope** — 3-axis values in °/s (written as integers).
4. **Timestamp** using `utime.ticks_us()` for microsecond resolution (stored as milliseconds).
5. **Pack and write** a binary row to the open file.

The BOOT button is checked on every iteration and will immediately stop recording if pressed. Every 500 rows the file buffer is flushed to flash storage and available disk space is checked.

### Key Variables You Might Want to Change

- **`verbose`** — Set to `True` to print each row to the serial console. Useful for debugging but significantly slows down logging.
- **`a_mag_at_rest`** — The measured acceleration magnitude at rest, used to compute the scale correction factor. Recalibrate this for each sensor unit.
- **Sensor oversampling** — Increase `pressure_oversample_rate` or `temperature_oversample_rate` (e.g., `OSR4`, `OSR8`) for lower noise at slower sample rates.
- **Gyro range** — Lower the range (e.g., `RANGE_2000_DPS`, `RANGE_1000_DPS`) if you don't need ±4,000 °/s; this gives finer angular precision.
- **Flush interval** — The `500` sample threshold before flushing. Lower values reduce data loss risk if power is cut but add I/O overhead.
- **Data directory and naming** — Change the path or naming convention for output files in the `filename` variable.

---

## File Structure Summary

| File | Runs on | Role |
|------|---------|------|
| `main.py` | ESP32 | Entry point — fall detection, button handling, launches logger or file server |
| `drop_logger.py` | ESP32 | Core high-speed sensor logging to binary |
| `file_server.py` | ESP32 | WiFi access point and HTTP file server for downloading/deleting data |
| `bmpxxx.py` | ESP32 | MicroPython driver for BMP581/585/390/280/BME280 pressure sensors |
| `icm20649.py` | ESP32 | MicroPython driver for ICM20649 accelerometer/gyroscope |
| `i2c_helpers.py` | ESP32 | Low-level I2C register read/write utilities used by the BMP driver |
| `boot.py` | ESP32 | MicroPython boot file (default, mostly empty) |
| `unpack_droplogger_binary.py` | Desktop PC | Converts binary `.bin` log files to CSV |
