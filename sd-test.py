import uasyncio as asyncio
import os
import time
from machine import Pin, SPI
from lib import sdcard
import vfs

SPI_ID = 1
SPI_BAUDRATE = 40000000
PIN_SCK = 10
PIN_MOSI = 11
PIN_MISO = 12
PIN_CS = 13
MOUNT_POINT = '/sd'

spi = None
sd = None


def _deinit_spi():
    global spi
    try:
        if spi is not None:
            spi.deinit()
    except Exception:
        pass
    spi = None


def _init_sd():
    global spi, sd
    _deinit_spi()
    spi = SPI(
        SPI_ID,
        baudrate=SPI_BAUDRATE,
        sck=Pin(PIN_SCK),
        mosi=Pin(PIN_MOSI),
        miso=Pin(PIN_MISO),
    )
    sd = sdcard.SDCard(spi, Pin(PIN_CS))
    vfs.mount(sd, MOUNT_POINT)


def _safe_umount():
    try:
        vfs.umount(MOUNT_POINT)
    except Exception:
        pass


# Initial mount
try:
    _init_sd()
    print('[STARTUP] SD card mounted successfully')
except OSError as e:
    print(f'[STARTUP ERROR] Failed to mount SD card: {e}')
    print('[STARTUP ERROR] Please insert SD card and restart the device.')

async def check_sd_card():
    poll_ok_ms = 5000
    poll_missing_ms = 1000
    recovery_backoff_ms = 1000
    max_backoff_ms = 8000
    consecutive_failures = 0
    last_state_ok = True

    while True:
        try:
            mbr_ok = False

            try:
                buf = bytearray(512)
                sd.readblocks(0, buf) # type: ignore
                mbr_ok = True
                consecutive_failures = 0
                recovery_backoff_ms = 1000
            except Exception as e:
                if last_state_ok:
                    print(f"MBR Read Error: {e}")
                consecutive_failures += 1

                # Only attempt remount periodically with exponential backoff
                try:
                    _safe_umount()
                    time.sleep_ms(200)
                    _init_sd()
                    print('[RECOVERY] SD card mounted successfully')
                    buf = bytearray(512)
                    sd.readblocks(0, buf) # type: ignore
                    mbr_ok = True
                    consecutive_failures = 0
                    recovery_backoff_ms = 1000
                except Exception as remount_error:
                    if consecutive_failures == 1 or (consecutive_failures % 5 == 0):
                        print(f"[RECOVERY ERROR] Failed to re-mount SD card: {remount_error}")
                    recovery_backoff_ms = min(recovery_backoff_ms * 2, max_backoff_ms)

            if mbr_ok != last_state_ok:
                print(
                    "MBR: {mbr}".format(
                        mbr='OK' if mbr_ok else 'NOT ACCESSIBLE',
                    )
                )
                last_state_ok = mbr_ok
            elif mbr_ok:
                print("MBR: OK")
        except Exception as e:
            print(f"SD Check Error: {e}")

        if mbr_ok:
            await asyncio.sleep_ms(poll_ok_ms)
        else:
            await asyncio.sleep_ms(max(poll_missing_ms, recovery_backoff_ms))

async def main():
    await check_sd_card()

if __name__ == "__main__":
    asyncio.run(main())