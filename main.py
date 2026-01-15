# Pi Pico DHT22 Library
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0

# Pi Pico CSV Library
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0

# HOW TO RUN: First, check all connections on pi:
#
# SPI SD-Card Reader 
# 	MISO → GP12 (Pin 16)
# 	MOSI → GP11 (Pin 15)
# 	SCK → GP10 (Pin 14)
# 	CS → GP13 (Pin 17)
# 	VCC → 3.3 V (oder 5 V, je nach SD-Modul!)
# 	GND → GND
# DHT22:
# 	DATA → GP15 (Pin 21)
# 	VCC → 3.3 V
# 	GND → GND
# DS3231 (RTC-Modul)
# 	SDA → GP0 (Pin 1)
# 	SCL → GP1 (Pin 2)
# 	VCC → 3.3 V
# 	GND → GND
#
# Then: Run thonny, run current script "rtc_set_time.py".
# Afterwards, run current script "main.py".
# unplug and check if data is written on sd-card with current timestamp

import uasyncio as asyncio
import dht
import machine
import time
import os
import lib.ds3231 as ds3231
from machine import Pin, SPI
from lib import sdcard


rtc = ds3231.RTC(sda_pin=0, scl_pin=1)
spi=SPI(1,baudrate=40000000,sck=Pin(10),mosi=Pin(11),miso=Pin(12))
sd=sdcard.SDCard(spi,Pin(13))
os.mount(sd,'/sd')

class DHTLogger:
    def __init__(self, pin, interval=60, filename='dht_log.csv'):
        self.dht_sensor = dht.DHT22(machine.Pin(pin))
        self.interval = interval
        self.filename = filename
        
        # Check if the file exists, if not, create it and add the header
        if not self.file_exists():
            self.create_file()
    
    def file_exists(self):
        try:
            with open(self.filename, 'r'):
                return True
        except OSError:
            return False
    
    def create_file(self):
        with open(self.filename, 'w') as f:
            f.write('Timestamp,Temperature,Humidity\n')
    
    async def log_data(self):
        led = machine.Pin(25, machine.Pin.OUT)

        while True:
            try:
                led.on()
                await asyncio.sleep(1)
                led.off()

                self.dht_sensor.measure()
                temp = self.dht_sensor.temperature()
                hum = self.dht_sensor.humidity()
                #timestamp = rtc.ReadTime('timestamp')
                timestamp = rtc.ReadTime(1)

                with open(self.filename, 'a') as f:
                    f.write(f'{timestamp},{temp},{hum}\n')

                print(f'Logged: {timestamp}, {temp}C, {hum}%')
            except OSError as e:
                print('DHT error:', e)

            await asyncio.sleep(self.interval)

async def fan_control(pin_no, on_time=20, period=1800):
    relay = Pin(pin_no, Pin.OUT)
    relay.value(1)  # Relais AUS (HIGH)
    print(f'Starting fan_control')

    while True:
        relay.value(0)      # Relais EIN (LOW)
        await asyncio.sleep(on_time)
        
        relay.value(1)      # Relais AUS
        await asyncio.sleep(period)


# Example usage
async def main():
    # DHT22 connected to GPIO 14, log data every 60 seconds
    logger = DHTLogger(pin=15, interval=30, filename='/sd/dht_log.csv')

    asyncio.create_task(logger.log_data())
    asyncio.create_task(fan_control(pin_no=16))

    while True:
        await asyncio.sleep(1)
# Running the asyncio event loop
if __name__ == '__main__':
    asyncio.run(main())



