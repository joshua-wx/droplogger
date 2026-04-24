"""
Simple board test script - reads and prints sensor data every 0.1 seconds
Tests: pressure sensor (BMP581) and IMU (ICM20649 gyro + accel)
"""

import time
from machine import Pin, I2C
import icm20649
import ism330dhcx
from math import sqrt
from bmpxxx import BMP581

# Initialize I2C
i2c = I2C(scl=Pin(6), sda=Pin(5))

# # Initialize Accelerometer/Gyro (ICM20649)
# print("Initializing ICM20649...")
# icm = icm20649.ICM20649(i2c, address=0x68)
# icm.gyro_range = icm20649.GyroRange.RANGE_4000_DPS
# print("✓ ICM20649 initialized")

# Initialize Accelerometer/Gyro (ISM330DHCX)
print("Initializing ISM330DHCX...")
icm = ism330dhcx.ISM330DHCX(i2c, address=0x6A)
icm.accelerometer_range     = ism330dhcx.AccelRange.RANGE_8G
icm.gyro_range              = ism330dhcx.GyroRange.RANGE_1000_DPS
icm.accelerometer_data_rate = ism330dhcx.Rate.RATE_208_HZ
icm.gyro_data_rate          = ism330dhcx.Rate.RATE_208_HZ

# Initialize Pressure Sensor (BMP581)
print("Initializing BMP581...")
bmp = BMP581(i2c, address=0x47)
bmp.pressure_oversample_rate = bmp.OSR1
bmp.temperature_oversample_rate = bmp.OSR1
bmp.iir_coefficient = bmp.COEF_0
# Burn first measurement (common issue after power-on)
_ = bmp.pressure
print("✓ BMP581 initialized")

print("\nStarting sensor readings (0.1s interval, Ctrl+C to stop)...\n")

try:
    while True:
        # Read pressure
        pressure = bmp.pressure
        
        # Read accelerometer
        ax, ay, az = icm.acceleration
        a_total = sqrt(ax * ax + ay * ay + az * az)
        
        # Read gyro
        gx, gy, gz = icm.gyro
        
        # Print readings
        print(f"Pressure: {pressure:.2f} hPa  |  "
              f"Accel: ({ax:7.2f}, {ay:7.2f}, {az:7.2f} m/s²  |  "
              f"Gyro: ({gx:7.1f}, {gy:7.1f}, {gz:7.1f}) deg/s |  "
              f"Accel mag value: ({a_total:7.2f}) m/s²")
        
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n\nTest stopped by user")
