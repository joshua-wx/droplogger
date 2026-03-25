import os
import time
import utime
from math import sqrt
from machine import Pin, I2C
import icm20649
from bmpxxx import BMP581

def count_files(path, extension):
    return sum(1 for f in os.listdir(path) if f.endswith(extension))

def main(logger_name='droplogger'):
    
    print('Logger software activated')
    verbose = False
    
    # The BOOT button is connected to GPIO 9 on the ESP32-C3
    boot_pin = Pin(0, Pin.IN, Pin.PULL_UP)
    
    #init led
    led = Pin(2, Pin.OUT)
    led.value(0)  # Turn the LED OFF

    #Accelometer (ICM20649)
    i2c = I2C(scl=Pin(6), sda=Pin(5))
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
    try:
        os.mkdir('/data')
    except:
        pass
    next_file_int = count_files('/data', '.csv') + 1
    filename = f"data/{logger_name}_data_{next_file_int}.csv"

    # Save file in path /
    print('Start logging')
    write_count = 0
    with open(filename, "a") as f:
        #write header
        cols = ["time(s)","Pressure Difference(hPa)","aX(ms^-2)","aY(ms^-2)","aZ(ms^-2)","gX(deg/s)","gY(deg/s)","gZ(deg/s)"]
        f.write(",".join(cols) + "\n")
        #write reference pressure
        ref_data = "{:.3f},{:.3f},,,,,,\n".format(-0.001,ref_pressure)
        f.write(ref_data)
        start_time = utime.ticks_us()
        led.value(1)
        while True:
            #read new data
            pressure_diff = ref_pressure-bmp.pressure #hPa
            ax, ay, az = icm.acceleration # read the accelerometer [ms^-2]
            gx, gy, gz = icm.gyro   # read the gyro [deg/s]

            seconds = utime.ticks_diff(utime.ticks_us(), start_time)/10**6
            
            #write data
            row = "{:.3f},{:.3f},{:.2f},{:.2f},{:.2f},{:d},{:d},{:d}\n".format(seconds, pressure_diff, ax, ay, az, int(gx), int(gy), int(gz))
            f.write(row)
            write_count += 1
            if verbose:
                print('NEW data')
                print(row)
                print('')
            if write_count == 1000:
                f.flush()
                write_count = 0
                if verbose:
                    print('flush')
                #kill loop if boot pin is pressed
                if boot_pin.value() == 0:
                    led.value(0)
                    break
            #time.sleep(1) 
                
    print('Finished')

if __name__ == "__main__":
    main()    
#todo:
#test without blocking pressure sensor...
#test S3 and multi threading to reduce time spent writting.

