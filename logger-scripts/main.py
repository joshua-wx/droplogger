import time
from machine import Pin, I2C
from math import sqrt
import icm20649
import drop_logger

# Set the device name here! Used for wifi AP name and binary file naming.
try:
    with open('config/device_name.txt', 'r') as f:
        device_name = f.read().strip()
    if not device_name:
        device_name = 'droplogger'
except OSError:
    device_name = 'droplogger'

LONG_PRESS_MS = 2000  # Hold boot button for 2s = file server mode

# Init LED
led = Pin(2, Pin.OUT)
led.value(0)

# The BOOT button is connected to GPIO 0 on the ESP32-C3
boot_pin = Pin(0, Pin.IN, Pin.PULL_UP)

# Accelerometer (ICM20649)
i2c = I2C(scl=Pin(6), sda=Pin(5))
icm = icm20649.ICM20649(i2c, address=0x68)
icm.gyro_range = icm20649.GyroRange.RANGE_4000_DPS

# Fall detection settings
fall_trigger_counter = 0
fall_trigger_counter_limit = 5
fall_trigger_a_threshold = 5  # m/s/s

print('Waiting to start...')
print('  Short press / fall detected = start data logger')
print('  Long press (2s)             = start WiFi file server')

while True:
    # Check for fall detection
    a_x, a_y, a_z = icm.acceleration
    a_total = sqrt(a_x * a_x + a_y * a_y + a_z * a_z)

    if a_total <= fall_trigger_a_threshold:
        fall_trigger_counter += 1
    else:
        fall_trigger_counter = 0

    # Fall detected - start logger immediately
    if fall_trigger_counter >= fall_trigger_counter_limit:
        print("Fall detected - starting logger")
        drop_logger.main(device_name)
        break

    # Boot button pressed - determine short vs long press
    if boot_pin.value() == 0:
        press_start = time.ticks_ms()

        # Blink LED while held
        blink_state = True
        while boot_pin.value() == 0:
            led.value(blink_state)
            blink_state = not blink_state
            time.sleep(0.1)

            held_ms = time.ticks_diff(time.ticks_ms(), press_start)
            if held_ms > LONG_PRESS_MS:
                # Fast blink to indicate long press registered
                led.value(1)
                time.sleep(0.05)
                led.value(0)
                time.sleep(0.05)

        held_ms = time.ticks_diff(time.ticks_ms(), press_start)
        led.value(0)

        if held_ms >= LONG_PRESS_MS:
            # Long press - file server mode
            for _ in range(3):
                led.value(1)
                time.sleep(0.3)
                led.value(0)
                time.sleep(0.3)

            print('Starting WiFi file server...')
            import file_server
            file_server.start_ap(ssid=device_name, password='hailstone')
            break
        else:
            # Short press - start logger
            print("Starting logger")
            led.value(1)
            time.sleep(0.1)
            led.value(0)
            drop_logger.main(device_name)
            break

    time.sleep(0.05)