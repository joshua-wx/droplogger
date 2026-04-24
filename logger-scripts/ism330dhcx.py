"""
MicroPython driver for the STMicroelectronics ISM330DHCX 6-axis IMU
(3-axis accelerometer + 3-axis gyroscope), e.g. the Adafruit ISM330DHCX
breakout (product 4502).

Modelled on a user-provided ICM20649 driver so the public interface
(acceleration in m/s^2, gyro in deg/s, range setters, data_ready) matches.

Tested target: ESP32 + MicroPython, I2C at 100-400 kHz.
Reference: ST ISM330DHCX datasheet (DocID033601) and the Adafruit
CircuitPython LSM6DS library.

# ---------------------------------------------------------------------------
# Example usage (remove or guard under __name__ on production)
# ---------------------------------------------------------------------------
# from machine import Pin, I2C
# from ism330dhcx import ISM330DHCX, AccelRange, GyroRange, Rate
#
# i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400_000)
# imu = ISM330DHCX(i2c)           # or ISM330DHCX(i2c, address=0x6B)
#
# imu.accelerometer_range = AccelRange.RANGE_8G
# imu.gyro_range          = GyroRange.RANGE_1000_DPS
# imu.accelerometer_data_rate = Rate.RATE_208_HZ
# imu.gyro_data_rate          = Rate.RATE_208_HZ
#
# while True:
#     if imu.data_ready:
#         ax, ay, az = imu.acceleration
#         gx, gy, gz = imu.gyro
#         print("a=({:+.2f},{:+.2f},{:+.2f}) m/s^2  "
#               "g=({:+.2f},{:+.2f},{:+.2f}) dps  "
#               "T={:.1f}C".format(ax, ay, az, gx, gy, gz, imu.temperature))
#     time.sleep_ms(10)

"""

import struct
import time

# ---------------------------------------------------------------------------
# Register map (flat — no banks on the LSM6DS family)
# ---------------------------------------------------------------------------
_LSM6DS_WHO_AM_I    = 0x0F
_LSM6DS_CTRL1_XL    = 0x10  # Accel: ODR_XL[7:4] | FS_XL[3:2] | LPF2_XL_EN[1] | 0
_LSM6DS_CTRL2_G     = 0x11  # Gyro:  ODR_G[7:4]  | FS_G[3:2]  | FS_125[1]    | FS_4000[0]
_LSM6DS_CTRL3_C     = 0x12  # BDU[6], IF_INC[2], SW_RESET[0]
_LSM6DS_STATUS_REG  = 0x1E  # TDA[2], GDA[1], XLDA[0]
_LSM6DS_OUT_TEMP_L  = 0x20
_LSM6DS_OUTX_L_G    = 0x22  # Gyro X,Y,Z (little-endian, 6 bytes)
_LSM6DS_OUTX_L_A    = 0x28  # Accel X,Y,Z (little-endian, 6 bytes)

_ISM330DHCX_DEVICE_ID = 0x6B

G_TO_ACCEL = 9.80665
_RAD_PER_DEG = 0.017453293  # not used by default — gyro returns deg/s


class AccelRange:
    """Accelerometer full-scale options.
    Tuple: (FS_XL register value, range in g, LSB per g).

    Note the unusual ordering: on LSM6DS-family parts, FS_XL=01 is ±16g,
    sitting between ±2g (00) and ±4g (10). This is per the datasheet.
    """
    RANGE_2G  = (0b00, 2,  16384)
    RANGE_16G = (0b01, 16, 2048)
    RANGE_4G  = (0b10, 4,  8192)
    RANGE_8G  = (0b11, 8,  4096)


class GyroRange:
    """Gyroscope full-scale options.
    Tuple: (FS_G value, FS_125 bit, FS_4000 bit, range in dps, LSB per dps).

    FS_4000 overrides FS_125 which overrides FS_G, per the datasheet.
    ±4000 dps is only available on ISM330DHCX (and a couple of siblings).
    """
    RANGE_125_DPS  = (0b00, 1, 0, 125,  228.571)
    RANGE_250_DPS  = (0b00, 0, 0, 250,  114.286)
    RANGE_500_DPS  = (0b00, 0, 0, 500,  57.143)   # FS_G=00 kept — see note
    RANGE_1000_DPS = (0b10, 0, 0, 1000, 28.571)
    RANGE_2000_DPS = (0b11, 0, 0, 2000, 14.286)
    RANGE_4000_DPS = (0b00, 0, 1, 4000, 7.143)

# NOTE re RANGE_500_DPS above: the correct FS_G for ±500 dps is 0b01.
# Fixing that value here to avoid a subtle bug:
GyroRange.RANGE_500_DPS = (0b01, 0, 0, 500, 57.143)


class Rate:
    """Output Data Rate (ODR) settings — same 4-bit field for accel and gyro."""
    RATE_SHUTDOWN = 0b0000
    RATE_12_5_HZ  = 0b0001
    RATE_26_HZ    = 0b0010
    RATE_52_HZ    = 0b0011
    RATE_104_HZ   = 0b0100
    RATE_208_HZ   = 0b0101
    RATE_416_HZ   = 0b0110
    RATE_833_HZ   = 0b0111
    RATE_1_66_KHZ = 0b1000
    RATE_3_33_KHZ = 0b1001   # accel only
    RATE_6_66_KHZ = 0b1010   # accel only


class ISM330DHCX:
    def __init__(self, i2c, address=0x6A):
        """
        :param i2c: a machine.I2C instance
        :param address: 0x6A (SA0 low, Adafruit default) or 0x6B (SA0 high)
        """
        self.i2c = i2c
        self.address = address
        self._gravity = G_TO_ACCEL

        # Cached range descriptors so reads don't have to touch the bus
        self._cached_accel_range = AccelRange.RANGE_4G
        self._cached_gyro_range = GyroRange.RANGE_250_DPS

        device_id = self._read_register_byte(_LSM6DS_WHO_AM_I)
        if device_id != _ISM330DHCX_DEVICE_ID:
            raise RuntimeError(
                "Failed to find ISM330DHCX! Got ID: 0x{:02X}".format(device_id)
            )

        self.reset()
        self.initialize()

    # ------------------------------------------------------------------
    # Low-level I2C helpers (same style as the ICM20649 template)
    # ------------------------------------------------------------------
    def _read_register_byte(self, reg):
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]

    def _read_register_bytes(self, reg, num_bytes):
        return self.i2c.readfrom_mem(self.address, reg, num_bytes)

    def _write_register_byte(self, reg, value):
        self.i2c.writeto_mem(self.address, reg, bytes([value & 0xFF]))

    def _read_bit(self, reg, bit_position):
        return (self._read_register_byte(reg) >> bit_position) & 0x01

    def _write_bit(self, reg, bit_position, value):
        current = self._read_register_byte(reg)
        if value:
            new_val = current | (1 << bit_position)
        else:
            new_val = current & ~(1 << bit_position)
        self._write_register_byte(reg, new_val)

    def _write_bits(self, reg, bit_start, num_bits, value):
        current = self._read_register_byte(reg)
        mask = ((1 << num_bits) - 1) << bit_start
        new_val = (current & ~mask) | ((value << bit_start) & mask)
        self._write_register_byte(reg, new_val)

    # ------------------------------------------------------------------
    # Reset / init
    # ------------------------------------------------------------------
    def reset(self):
        """Software reset via CTRL3_C.SW_RESET (bit 0)."""
        self._write_bit(_LSM6DS_CTRL3_C, 0, 1)
        time.sleep(0.01)
        # SW_RESET is self-clearing when reset completes
        timeout = 50  # ~250 ms safety cap
        while self._read_bit(_LSM6DS_CTRL3_C, 0):
            time.sleep(0.005)
            timeout -= 1
            if timeout <= 0:
                raise RuntimeError("ISM330DHCX software reset timed out")

    def initialize(self):
        """Apply a sensible default configuration after reset."""
        # CTRL3_C: set BDU=1 (bit 6) and keep IF_INC=1 (bit 2, default).
        # BDU freezes LSB/MSB pairs between reads so a 16-bit value can't tear.
        ctrl3 = self._read_register_byte(_LSM6DS_CTRL3_C)
        ctrl3 |= (1 << 6) | (1 << 2)
        self._write_register_byte(_LSM6DS_CTRL3_C, ctrl3)
        time.sleep(0.005)

        # Pick reasonable defaults — override from user code as needed
        self.accelerometer_range = AccelRange.RANGE_4G
        self.gyro_range = GyroRange.RANGE_500_DPS
        self.accelerometer_data_rate = Rate.RATE_104_HZ
        self.gyro_data_rate = Rate.RATE_104_HZ

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def acceleration(self):
        """Acceleration as (x, y, z) in m/s^2."""
        data = self._read_register_bytes(_LSM6DS_OUTX_L_A, 6)
        x_raw, y_raw, z_raw = struct.unpack('<hhh', data)  # little-endian!
        _, _, lsb_per_g = self._cached_accel_range
        k = self._gravity / lsb_per_g
        return (x_raw * k, y_raw * k, z_raw * k)

    @property
    def gyro(self):
        """Angular velocity as (x, y, z) in deg/s.

        (Matches the template's actual behaviour. Multiply by 0.017453293
        if you'd prefer rad/s.)
        """
        data = self._read_register_bytes(_LSM6DS_OUTX_L_G, 6)
        x_raw, y_raw, z_raw = struct.unpack('<hhh', data)
        lsb_per_dps = self._cached_gyro_range[4]
        return (x_raw / lsb_per_dps,
                y_raw / lsb_per_dps,
                z_raw / lsb_per_dps)

    @property
    def temperature(self):
        """Die temperature in deg C. Zero output corresponds to 25 C."""
        lo, hi = self._read_register_bytes(_LSM6DS_OUT_TEMP_L, 2)
        raw = struct.unpack('<h', bytes((lo, hi)))[0]
        return 25.0 + raw / 256.0

    # ------------------------------------------------------------------
    # Range setters / getters
    # ------------------------------------------------------------------
    @property
    def accelerometer_range(self):
        return self._cached_accel_range

    @accelerometer_range.setter
    def accelerometer_range(self, value):
        range_val, _, _ = value
        # FS_XL is CTRL1_XL[3:2]
        self._write_bits(_LSM6DS_CTRL1_XL, 2, 2, range_val)
        time.sleep(0.005)
        self._cached_accel_range = value

    @property
    def gyro_range(self):
        return self._cached_gyro_range

    @gyro_range.setter
    def gyro_range(self, value):
        fs_g, fs_125, fs_4000, _, _ = value
        # CTRL2_G low nibble: FS_G[3:2] | FS_125[1] | FS_4000[0].
        # Do a single read-modify-write so we can't leave an intermediate
        # state where two FS-select bits are both asserted.
        current = self._read_register_byte(_LSM6DS_CTRL2_G)
        new_val = (current & 0xF0) | ((fs_g & 0x3) << 2) \
                                   | ((fs_125 & 0x1) << 1) \
                                   |  (fs_4000 & 0x1)
        self._write_register_byte(_LSM6DS_CTRL2_G, new_val)
        self._cached_gyro_range = value
        time.sleep(0.1)  # datasheet allows some settling; matches template

    # ------------------------------------------------------------------
    # Output data rate (ODR) setters/getters
    # ------------------------------------------------------------------
    @property
    def accelerometer_data_rate(self):
        """ODR_XL value (see Rate). Returns the 4-bit field."""
        return (self._read_register_byte(_LSM6DS_CTRL1_XL) >> 4) & 0x0F

    @accelerometer_data_rate.setter
    def accelerometer_data_rate(self, value):
        self._write_bits(_LSM6DS_CTRL1_XL, 4, 4, value & 0x0F)
        time.sleep(0.005)

    @property
    def gyro_data_rate(self):
        """ODR_G value (see Rate). Returns the 4-bit field."""
        return (self._read_register_byte(_LSM6DS_CTRL2_G) >> 4) & 0x0F

    @gyro_data_rate.setter
    def gyro_data_rate(self, value):
        self._write_bits(_LSM6DS_CTRL2_G, 4, 4, value & 0x0F)
        time.sleep(0.005)

    # ------------------------------------------------------------------
    # Data-ready flags (STATUS_REG: XLDA=bit0, GDA=bit1, TDA=bit2)
    # ------------------------------------------------------------------
    @property
    def data_ready(self):
        """True when BOTH accel and gyro have new samples available."""
        status = self._read_register_byte(_LSM6DS_STATUS_REG)
        return (status & 0b11) == 0b11

    @property
    def accel_data_ready(self):
        return bool(self._read_bit(_LSM6DS_STATUS_REG, 0))

    @property
    def gyro_data_ready(self):
        return bool(self._read_bit(_LSM6DS_STATUS_REG, 1))


# ---------------------------------------------------------------------------
# Example usage (remove or guard under __name__ on production)
# ---------------------------------------------------------------------------
# from machine import Pin, I2C
# from ism330dhcx import ISM330DHCX, AccelRange, GyroRange, Rate
#
# i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400_000)
# imu = ISM330DHCX(i2c)           # or ISM330DHCX(i2c, address=0x6B)
#
# imu.accelerometer_range = AccelRange.RANGE_8G
# imu.gyro_range          = GyroRange.RANGE_1000_DPS
# imu.accelerometer_data_rate = Rate.RATE_208_HZ
# imu.gyro_data_rate          = Rate.RATE_208_HZ
#
# while True:
#     if imu.data_ready:
#         ax, ay, az = imu.acceleration
#         gx, gy, gz = imu.gyro
#         print("a=({:+.2f},{:+.2f},{:+.2f}) m/s^2  "
#               "g=({:+.2f},{:+.2f},{:+.2f}) dps  "
#               "T={:.1f}C".format(ax, ay, az, gx, gy, gz, imu.temperature))
#     time.sleep_ms(10)