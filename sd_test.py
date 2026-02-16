import uasyncio as asyncio
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPI_ID = 1
SPI_BAUDRATE = 40000000
PIN_SCK = 10
PIN_MOSI = 11
PIN_MISO = 12
PIN_CS = 13
MOUNT_POINT = '/sd'


# ---------------------------------------------------------------------------
# SD health-check state machine (testable)
# ---------------------------------------------------------------------------
async def check_sd_card(
    read_block,
    remount,
    safe_umount,
    sleep_ms_fn,
    *,
    poll_ok_ms=5000,
    poll_missing_ms=1000,
    initial_backoff_ms=1000,
    max_backoff_ms=8000,
):
    """Monitor SD card availability with exponential-backoff recovery.

    Parameters
    ----------
    read_block : callable
        ``read_block()`` succeeds silently when SD is healthy, raises on
        failure.
    remount : callable
        ``remount()`` attempts to unmount + re-mount the SD card.
    safe_umount : callable
        ``safe_umount()`` unmounts the SD, swallowing errors.
    sleep_ms_fn : awaitable callable
        ``await sleep_ms_fn(ms)`` — async sleep in milliseconds.
    """
    recovery_backoff_ms = initial_backoff_ms
    consecutive_failures = 0
    last_state_ok = True

    while True:
        try:
            mbr_ok = False

            try:
                read_block()
                mbr_ok = True
                consecutive_failures = 0
                recovery_backoff_ms = initial_backoff_ms
            except Exception as e:
                if last_state_ok:
                    print(f"MBR Read Error: {e}")
                consecutive_failures += 1

                # Attempt remount with exponential backoff
                try:
                    safe_umount()
                    time.sleep_ms(200)
                    remount()
                    print('[RECOVERY] SD card mounted successfully')
                    read_block()
                    mbr_ok = True
                    consecutive_failures = 0
                    recovery_backoff_ms = initial_backoff_ms
                except Exception as remount_error:
                    if consecutive_failures == 1 or (consecutive_failures % 5 == 0):
                        print(
                            f"[RECOVERY ERROR] Failed to re-mount SD card: "
                            f"{remount_error}"
                        )
                    recovery_backoff_ms = min(
                        recovery_backoff_ms * 2, max_backoff_ms
                    )

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
            await sleep_ms_fn(poll_ok_ms)
        else:
            await sleep_ms_fn(max(poll_missing_ms, recovery_backoff_ms))


# ---------------------------------------------------------------------------
# Hardware wiring  (device-only)
# ---------------------------------------------------------------------------
def _build_hardware():  # pragma: no cover
    """Create SPI / SD objects and return (init_fn, read_fn, umount_fn)."""
    from machine import Pin, SPI  # noqa: F811 — device import
    from lib import sdcard
    import vfs

    _spi: list = [None]
    _sd: list = [None]

    def _deinit_spi():
        try:
            if _spi[0] is not None:
                _spi[0].deinit()
        except Exception:
            pass
        _spi[0] = None

    def _init_sd():
        _deinit_spi()
        _spi[0] = SPI(
            SPI_ID,
            baudrate=SPI_BAUDRATE,
            sck=Pin(PIN_SCK),
            mosi=Pin(PIN_MOSI),
            miso=Pin(PIN_MISO),
        )
        _sd[0] = sdcard.SDCard(_spi[0], Pin(PIN_CS))
        vfs.mount(_sd[0], MOUNT_POINT)

    def _safe_umount():
        try:
            vfs.umount(MOUNT_POINT)
        except Exception:
            pass

    def _read_block():
        buf = bytearray(512)
        _sd[0].readblocks(0, buf)

    return _init_sd, _read_block, _safe_umount


async def main():  # pragma: no cover
    init_sd, read_block, safe_umount = _build_hardware()
    try:
        init_sd()
        print('[STARTUP] SD card mounted successfully')
    except OSError as e:
        print(f'[STARTUP ERROR] Failed to mount SD card: {e}')
        print('[STARTUP ERROR] Please insert SD card and restart the device.')

    await check_sd_card(
        read_block=read_block,
        remount=init_sd,
        safe_umount=safe_umount,
        sleep_ms_fn=asyncio.sleep_ms,
    )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())