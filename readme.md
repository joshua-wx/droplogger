# Drop Logger

A MicroPython-based data logger for characterising the tumbling dynamics of artificial hailstones during free-fall. Designed to run on a **Seeed XIAO ESP32-C3** with a **BMP581** pressure sensor and **ICM20649** 6-axis IMU, sampling at high frequency while mounted inside a 3D-printed hailstone dropped from 100–250 m.

## Features

- **High-speed logging** — pressure, 3-axis acceleration, and 3-axis gyroscope sampled as fast as I2C allows (no fixed delay)
- **Automatic fall detection** — logging triggers automatically when freefall is detected, no button press needed
- **Wireless data download** — built-in WiFi access point and HTTP file server; download files from a phone or laptop browser
- **Compact binary format** — optional binary output (~50% smaller than CSV) with a desktop unpacker script
- **Simple one-button interface** — short press starts logging, long press starts the file server

## Hardware

| Component | Details |
|-----------|---------|
| Microcontroller | [Seeed XIAO ESP32-C3](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/) |
| Pressure sensor | Bosch BMP581 (I2C, address 0x47) |
| IMU | TDK ICM20649 (I2C, address 0x68) |
| I2C bus | SDA → GPIO 6, SCL → GPIO 7 |
| LED | GPIO 2 (onboard) |
| Button | GPIO 9 (BOOT button) |

## Quick Start

### 1. Flash MicroPython

Install [MicroPython](https://micropython.org/download/ESP32_GENERIC_C3/) on your ESP32-C3 if you haven't already.

### 2. Upload Files

Copy all `.py` files to the ESP32 and create the `/data` directory:

```bash
mpremote mkdir :/data
mpremote cp main.py bmpxxx.py icm20649.py i2c_helpers.py drop_logger_3.py file_server.py boot.py :
```

Or use [Thonny](https://thonny.org/) to upload them via the file browser.

### 3. Configure

Edit `logger_name` at the top of `main.py` to set your device name (used for WiFi AP and file naming):

```python
logger_name = 'my-hailstone'
```

### 4. Run

Power on the device. The serial console will show:

```
Waiting to start...
  Short press / fall detected = start data logger
  Long press (2s)             = start WiFi file server
```

- **Drop it** — logging starts automatically when freefall is detected
- **Short press BOOT** — starts logging manually
- **Long press BOOT (≥2 s)** — starts WiFi file server for data download

### 5. Download Data

Long-press BOOT to start the file server, then:

1. Connect your phone/laptop to the WiFi network (name = your `logger_name`, password = `hailstone`)
2. Browse to **http://192.168.4.1**
3. Download or delete files from the web interface

## File Format

Output CSV files have the following columns:

| Column | Unit | Description |
|--------|------|-------------|
| `time(s)` | s | Elapsed time (microsecond resolution) |
| `Pressure Difference(hPa)` | hPa | Reference pressure minus current pressure |
| `aX(ms^-2)` | m/s² | Acceleration X |
| `aY(ms^-2)` | m/s² | Acceleration Y |
| `aZ(ms^-2)` | m/s² | Acceleration Z |
| `gX(deg/s)` | °/s | Gyroscope X |
| `gY(deg/s)` | °/s | Gyroscope Y |
| `gZ(deg/s)` | °/s | Gyroscope Z |

The first data row (time = -0.001) stores the absolute reference pressure in hPa, allowing reconstruction of absolute pressure values.

## Binary File Conversion

If using binary output (`.bin` files), convert to CSV on your PC:

```bash
python unpack_droplogger_binary.py droplogger_data_1.bin
python unpack_droplogger_binary.py droplogger_data_1.bin -o output.csv
```

## Project Structure

```
├── main.py                        # Entry point: fall detection, button handling
├── drop_logger_3.py               # Core sensor logging loop
├── file_server.py                 # WiFi AP + HTTP file server
├── bmpxxx.py                      # BMP581/585/390/280/BME280 driver
├── icm20649.py                    # ICM20649 accelerometer/gyro driver
├── i2c_helpers.py                 # I2C register utilities
├── boot.py                        # MicroPython boot file
├── unpack_droplogger_binary.py    # Desktop tool: .bin → .csv conversion
└── docs/
    └── drop_logger_guide.md       # Detailed user guide
```

## Sensor Configuration

Default settings prioritise sample rate over noise reduction:

| Setting | Default | Notes |
|---------|---------|-------|
| Pressure oversampling | OSR1 (1×) | Increase to OSR4/OSR8 for less noise, slower rate |
| Temperature oversampling | OSR1 (1×) | Increase for more stable readings |
| IIR filter | COEF_0 (off) | Enable for smoother pressure data |
| Gyro range | ±4,000 °/s | Lower for finer precision if rotation rates permit |
| Accel range | ±8 g | Set in ICM20649 driver |

These can be changed in `drop_logger_3.py`. See the [user guide](docs/drop_logger_guide.md) for details.

## Dependencies

All sensor drivers are included in this repository — no external packages are required beyond a standard MicroPython installation. The desktop unpacker script (`unpack_droplogger_binary.py`) uses only Python standard library modules.

## License

Sensor drivers (`bmpxxx.py`, `i2c_helpers.py`) are licensed under the MIT License. See individual file headers for details.