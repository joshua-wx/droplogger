"""
Acceleration calibration helper

Measure 1000 samples at rest and print the mean magnitude in m/s^2.
Optionally saves the detected value to config/accel_calibration.txt.
"""

import time
from machine import Pin, I2C
from math import sqrt
import icm20649

SAMPLES = 1000
DELAY_S = 0.01  # 10 ms between samples for ~10 Hz

# Setup I2C and IMU
print("Initializing ICM20649...")
i2c = I2C(scl=Pin(6), sda=Pin(5))
icm = icm20649.ICM20649(i2c, address=0x68)
icm.gyro_range = icm20649.GyroRange.RANGE_4000_DPS
print("✓ ICM20649 initialized")

print(f"Collecting {SAMPLES} accelerometer samples. Keep board still...")
accum = 0.0
for i in range(1, SAMPLES + 1):
    ax, ay, az = icm.acceleration
    mag = sqrt(ax * ax + ay * ay + az * az)
    accum += mag
    if i % 100 == 0:
        print(f"  {i} samples: interim mean = {accum / i:.4f} m/s^2")
    time.sleep(DELAY_S)

mean_accel = accum / SAMPLES
print("\nCalibration complete")
print(f"Mean acceleration magnitude at rest: {mean_accel:.6f} m/s^2")

# Save to config file
try:
    with open('config/accel_calibration.txt', 'w') as f:
        f.write(str(mean_accel))
    print("Saved to config/accel_calibration.txt")
except OSError as e:
    print(f"Could not save to config/accel_calibration.txt: {e}")

print("Done.")
