import uasyncio as asyncio
import os
import lib.ds3231 as ds3231
from machine import Pin, SPI
from lib import sdcard
import machine
import time 
import vfs

# Initialize RTC
rtc = ds3231.RTC(sda_pin=0, scl_pin=1)

# Initialize SD Card with error handling
spi=SPI(1,baudrate=40000000,sck=Pin(10),mosi=Pin(11),miso=Pin(12))
sd=sdcard.SDCard(spi,Pin(13))

# Mount SD card to filesystem
try:
    vfs.mount(sd,'/sd')
    sd_mounted = True
    print('[STARTUP] SD card mounted successfully')
except OSError as e:
    sd_mounted = False
    print(f'[STARTUP ERROR] Failed to mount SD card: {e}')
    print('[STARTUP ERROR] Please insert SD card and restart the device.')

async def check_sd_card():
    """
    Check SD card accessibility every 5 seconds.
    Verifies: mount status, folder structure, read/write capabilities.
    """
    while True:
        print("\n" + "="*50)
        print("SD Card Health Check")
        print("="*50)
        
        try:
            # Check 1: Filesystem mounted
            mounted = '/sd' in os.listdir('/')
            print(f"✓ SD Mount Status: {'MOUNTED' if mounted else 'NOT MOUNTED'}")
            
            if not mounted:
                print("✗ SD card not accessible - skipping further checks")
                await asyncio.sleep(5)
                continue
            
            # Check 2: Raw block read (MBR)
            try:
                buf = bytearray(512)
                sd.readblocks(0, buf)
                print("✓ MBR Read: SUCCESS (512 bytes)")
            except Exception as e:
                print(f"✗ MBR Read: FAILED - {e}")

            # Check 3: Folder structure
            sd_contents = os.listdir('/sd')
            print(f"✓ Root Directory Contents: {sd_contents if sd_contents else '(empty)'}")
            
            # Check 4: Test write capability
            test_file = '/sd/test_write.txt'
            try:
                with open(test_file, 'w') as f:
                    f.write('SD write test at timestamp\n')
                print(f"✓ Write Test: SUCCESS")
            except Exception as e:
                print(f"✗ Write Test: FAILED - {e}")
            
            # Check 5: Test read capability
            try:
                with open(test_file, 'r') as f:
                    content = f.read()
                print(f"✓ Read Test: SUCCESS (read {len(content)} bytes)")
            except Exception as e:
                print(f"✗ Read Test: FAILED - {e}")
            
            # Check 6: Check dht_log.csv
            try:
                stat_info = os.stat('/sd/dht_log.csv')
                print(f"✓ dht_log.csv exists: {stat_info[6]} bytes")
            except OSError:
                print("ℹ dht_log.csv not found (may be created on first run)")
            
        except Exception as e:
            print(f"✗ SD Check Error: {e}")
        
        await asyncio.sleep(5)

async def main():
    await check_sd_card()

if __name__ == "__main__":
    asyncio.run(main())