import struct
import time

# Register addresses
_ICM20X_WHO_AM_I = 0x00
_ICM20X_REG_BANK_SEL = 0x7F
_ICM20X_PWR_MGMT_1 = 0x06
_ICM20X_ACCEL_XOUT_H = 0x2D
_ICM20X_GYRO_XOUT_H = 0x33
_ICM20X_GYRO_CONFIG_1 = 0x01
_ICM20X_ACCEL_CONFIG_1 = 0x14
_ICM20X_ACCEL_SMPLRT_DIV_1 = 0x10
_ICM20X_GYRO_SMPLRT_DIV = 0x00
_ICM20X_REG_INT_STATUS_1 = 0x1A

_ICM20649_DEVICE_ID = 0xE1
_ICM20948_DEVICE_ID = 0xEA

G_TO_ACCEL = 9.80665
_ICM20X_RAD_PER_DEG = 0.017453293

class AccelRange:
    """Accelerometer range options"""
    # ICM20649
    RANGE_4G = (0, 4, 8192)
    RANGE_8G = (1, 8, 4096.0)
    RANGE_16G = (2, 16, 2048)
    RANGE_30G = (3, 30, 1024)
    
class GyroRange:
    """Gyro range options"""
    # ICM20649
    RANGE_500_DPS = (0, 500, 65.5)
    RANGE_1000_DPS = (1, 1000, 32.8)
    RANGE_2000_DPS = (2, 2000, 16.4) #0.061 deg/s precision
    RANGE_4000_DPS = (3, 4000, 8.2) #0.122 deg/s precision

class ICM20649:
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self._gravity = G_TO_ACCEL
        
        # Cache for current settings
        self._cached_accel_range = AccelRange.RANGE_8G
        self._cached_gyro_range = GyroRange.RANGE_500_DPS
        
        # Set bank 0 and check device ID
        self._bank = 0
        device_id = self._read_register_byte(_ICM20X_WHO_AM_I)
        if device_id != _ICM20649_DEVICE_ID:
            raise RuntimeError(f"Failed to find ICM20649! Got ID: 0x{device_id:02X}")
        
        self.reset()
        self.initialize()
    
    @property
    def _bank(self):
        """Get current register bank"""
        val = self._read_register_byte(_ICM20X_REG_BANK_SEL)
        return val >> 4
    
    @_bank.setter
    def _bank(self, value):
        """Set register bank (0-3)"""
        self._write_register_byte(_ICM20X_REG_BANK_SEL, value << 4)
    
    def _read_register_byte(self, reg):
        """Read a single byte from register"""
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]
    
    def _read_register_bytes(self, reg, num_bytes):
        """Read multiple bytes from register"""
        return self.i2c.readfrom_mem(self.address, reg, num_bytes)
    
    def _write_register_byte(self, reg, value):
        """Write a single byte to register"""
        self.i2c.writeto_mem(self.address, reg, bytes([value]))
    
    def _read_bit(self, reg, bit_position):
        """Read a specific bit from a register"""
        val = self._read_register_byte(reg)
        return (val >> bit_position) & 0x01
    
    def _write_bit(self, reg, bit_position, value):
        """Write a specific bit to a register"""
        current = self._read_register_byte(reg)
        if value:
            new_val = current | (1 << bit_position)
        else:
            new_val = current & ~(1 << bit_position)
        self._write_register_byte(reg, new_val)
    
    def _read_bits(self, reg, bit_start, num_bits):
        """Read multiple bits from a register"""
        val = self._read_register_byte(reg)
        mask = ((1 << num_bits) - 1) << bit_start
        return (val & mask) >> bit_start
    
    def _write_bits(self, reg, bit_start, num_bits, value):
        """Write multiple bits to a register"""
        current = self._read_register_byte(reg)
        mask = ((1 << num_bits) - 1) << bit_start
        value_shifted = (value << bit_start) & mask
        new_val = (current & ~mask) | value_shifted
        self._write_register_byte(reg, new_val)
    
    def reset(self):
        """Reset the device"""
        self._bank = 0
        time.sleep(0.005)
        
        # Set reset bit
        self._write_bit(_ICM20X_PWR_MGMT_1, 7, 1)
        time.sleep(0.005)
        
        # Wait for reset to complete
        while self._read_bit(_ICM20X_PWR_MGMT_1, 7):
            time.sleep(0.005)
    
    def initialize(self):
        """Initialize with default settings"""
        # Wake up from sleep
        self._bank = 0
        time.sleep(0.005)
        self._write_bit(_ICM20X_PWR_MGMT_1, 6, 0)  # Clear sleep bit
        time.sleep(0.005)
        
        # Set ranges
        self.accelerometer_range = AccelRange.RANGE_8G
        self.gyro_range = GyroRange.RANGE_500_DPS
        
        # Set data rates
        self.accelerometer_data_rate_divisor = 20  # ~53.57Hz
        self.gyro_data_rate_divisor = 10  # ~100Hz
    
    @property
    def acceleration(self):
        """Read acceleration data in m/s^2"""
        #self._bank = 0
        data = self._read_register_bytes(_ICM20X_ACCEL_XOUT_H, 6)
        
        # Unpack as big-endian signed 16-bit values
        x_raw, y_raw, z_raw = struct.unpack('>hhh', data)
        
        # Scale using current range
        _, _, lsb = self._cached_accel_range
        x = (x_raw / lsb) * self._gravity
        y = (y_raw / lsb) * self._gravity
        z = (z_raw / lsb) * self._gravity
        
        return (x, y, z)
    
    @property
    def gyro(self):
        """Read gyro data in rad/s"""
        #self._bank = 0
        data = self._read_register_bytes(_ICM20X_GYRO_XOUT_H, 6)
        
        # Unpack as big-endian signed 16-bit values
        x_raw, y_raw, z_raw = struct.unpack('>hhh', data)
        
        # Scale using current range
        _, _, lsb = self._cached_gyro_range
        x = (x_raw / lsb)
        y = (y_raw / lsb)
        z = (z_raw / lsb)
        
        return (x, y, z)
    
    @property
    def accelerometer_range(self):
        """Get current accelerometer range"""
        return self._cached_accel_range
    
    @accelerometer_range.setter
    def accelerometer_range(self, value):
        """Set accelerometer range"""
        self._bank = 2
        time.sleep(0.005)
        range_val, _, _ = value
        self._write_bits(_ICM20X_ACCEL_CONFIG_1, 1, 2, range_val)
        time.sleep(0.005)
        self._cached_accel_range = value
        self._bank = 0
    
    @property
    def gyro_range(self):
        """Get current gyro range"""
        return self._cached_gyro_range
    
    @gyro_range.setter
    def gyro_range(self, value):
        """Set gyro range"""
        self._bank = 2
        time.sleep(0.005)
        range_val, _, _ = value
        self._write_bits(_ICM20X_GYRO_CONFIG_1, 1, 2, range_val)
        time.sleep(0.005)
        self._cached_gyro_range = value
        self._bank = 0
        time.sleep(0.100)  # Let new range settle
    
    @property
    def accelerometer_data_rate_divisor(self):
        """Get accelerometer data rate divisor"""
        self._bank = 2
        # Read 2-byte big-endian value
        data = self._read_register_bytes(_ICM20X_ACCEL_SMPLRT_DIV_1, 2)
        divisor = struct.unpack('>H', data)[0]
        self._bank = 0
        return divisor
    
    @accelerometer_data_rate_divisor.setter
    def accelerometer_data_rate_divisor(self, value):
        """Set accelerometer data rate divisor (12-bit, 0-4095)"""
        self._bank = 2
        time.sleep(0.005)
        data = struct.pack('>H', value)
        self.i2c.writeto_mem(self.address, _ICM20X_ACCEL_SMPLRT_DIV_1, data)
        time.sleep(0.005)
    
    @property
    def gyro_data_rate_divisor(self):
        """Get gyro data rate divisor"""
        self._bank = 2
        divisor = self._read_register_byte(_ICM20X_GYRO_SMPLRT_DIV)
        self._bank = 0
        return divisor
    
    @gyro_data_rate_divisor.setter
    def gyro_data_rate_divisor(self, value):
        """Set gyro data rate divisor (8-bit, 0-255)"""
        self._bank = 2
        time.sleep(0.005)
        self._write_register_byte(_ICM20X_GYRO_SMPLRT_DIV, value)
        time.sleep(0.005)
    
    @property
    def data_ready(self):
        """Check if new data is available"""
        self._bank = 0
        return bool(self._read_bit(_ICM20X_REG_INT_STATUS_1, 0))