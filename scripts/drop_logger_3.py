import os
import time
import utime
from math import sqrt
import struct
from machine import Pin, I2C
#accelerometer library
import icm20649
#pressure sensor library
from bmpxxx import BMP581

#set verbose for debugging
verbose = False

# Binary format constants
FILE_MAGIC = b'DL01'       # 4 bytes: file identifier + version
HEADER_FORMAT = '>4sf'     # magic(4s), ref_pressure(f)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 8 bytes
ROW_FORMAT = '>IiHhhh'    # time_ms(I), p_diff(i), a_mag(H), gX(h), gY(h), gZ(h)
ROW_SIZE = struct.calcsize(ROW_FORMAT)        # 20 bytes

# Encoding:
#   time      : uint32 milliseconds since start (max ~49 days)
#   pressure  : int32  milli-hPa difference from ref (±2,147,483 hPa, covers ±2000m+)
#   accel     : uint16 magnitude × 100 (max 655 m/s² ≈ 66g, covers ±16g)
#   gyro  x3  : int16  deg/s as integer (±32767, covers ±4000)

def count_files(path, extension):
    #check the number of data files in a directory
    return sum(1 for f in os.listdir(path) if f.endswith(extension))

def main(device_name='droplogger'):
    print('Logger software activated')

    # The BOOT button is connected to GPIO 9 on the ESP32-C3. Use to stop logging
    boot_pin = Pin(9, Pin.IN, Pin.PULL_UP)
    
    #init led
    led = Pin(2, Pin.OUT)
    led.value(0)  # Turn the LED OFF

    #Accelometer (ICM20649)
    i2c = I2C(scl=Pin(7), sda=Pin(6))
    icm = icm20649.ICM20649(i2c, address=0x68)
    icm.gyro_range = icm20649.GyroRange.RANGE_4000_DPS #set gyro range to 4000 deg/s
    
    #Barometer (BMP581)
    bmp = BMP581(i2c, address=0x47)
    bmp.pressure_oversample_rate = bmp.OSR1   # 1x oversampling
    bmp.temperature_oversample_rate = bmp.OSR1  # 1x oversampling
    bmp.iir_coefficient = bmp.COEF_0  # No filtering
        
    # Oddly first pressure measure after power-on return wrong value.
    # so we "burn" one measure
    _ = bmp.pressure
    #get a reference pressure to improve compression
    ref_pressure = bmp.pressure #hPa
    
    # Change filename and fileformat here.
    next_file_int = count_files('/data', '.bin') + 1
    filename = f"data/{device_name}_{next_file_int}.bin"

    # Save file in path /
    print('Start logging')
    write_count = 0
    with open(filename, "a") as f:
        # Write header
        header = struct.pack(HEADER_FORMAT, FILE_MAGIC, ref_pressure)
        f.write(header)
        start_time = utime.ticks_us()
        led.value(1)
        while True:
            #read new data
            pressure_diff = ref_pressure-bmp.pressure #hPa
            ax, ay, az = icm.acceleration # read the accelerometer [ms^-2]
            a_mag = sqrt(ax * ax + ay * ay + az * az)
            gx, gy, gz = icm.gyro   # read the gyro [deg/s]
            
            #time of obs
            elapsed_ms = utime.ticks_diff(utime.ticks_us(), start_time) // 1000
            
            # Pack and write row
            row = struct.pack(ROW_FORMAT,
                elapsed_ms,
                int(round(pressure_diff * 1000)),  # milli-hPa
                int(round(a_mag * 100)),            # centi-m/s²
                int(round(gx)),                     # deg/s
                int(round(gy)),
                int(round(gz)),
            )
            f.write(row)
            write_count += 1
            #write_count += 1
            if verbose:
                print('NEW data')
                print(f"t={elapsed_ms}ms p={pressure_diff:.3f} a={a_mag:.2f} g=({gx},{gy},{gz})")
                print('')
            #kill loop if boot pin is pressed
            if boot_pin.value() == 0:
                print('aborting due to storage limits')
                f.flush()
                led.value(0)
                break
            #run checks
            if write_count == 500:
                #flush cache
                f.flush()
                #reset counter
                write_count = 0
                #check storage
                stat = os.statvfs('/data')
                free_bytes = stat[0] * stat[3]  # block_size * free_blocks
                if free_bytes < 50_000:  # ~50KB safety margin
                    print('aborting due to storage limits')
                    led.value(0)
                    break
                else:
                    print('storage now at', free_bytes)
    print('Finished')

if __name__ == "__main__":
    main()    
#todo:
#test without blocking pressure sensor...
#test S3 and multi threading to reduce time spent writting.

