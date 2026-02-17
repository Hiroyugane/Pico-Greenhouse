# SD Card Integration Helper
# Dennis Hiro, 2024-06-08
#
# Lightweight utilities for SD card mounting and availability checks.
# Used by hardware_factory and buffer_manager.

import os
import sys
import time

# Patchable flag: True when running on the Pico, False on host/CPython.
# Tests can override this to exercise device-only code paths.
_IS_DEVICE = (sys.implementation.name == 'micropython')

# Type checkers don't know about MicroPython-specific os functions;
# the host shim in host_shims/os.py provides them for host testing.
if False:  # This block exists only for type checking
    from os import mount as _mount_typecheck  # noqa: F401


def mount_sd(spi, cs_pin, mount_point: str = '/sd'):
    """
    Attempt to mount SD card on specified mount point.
    
    Args:
        spi: machine.SPI instance (already initialized)
        cs_pin: machine.Pin object or int for chip select
        mount_point (str): Mount point path (default: '/sd')
    
    Returns:
        tuple: (bool, SDCard | None) -- success flag and the SDCard instance
    """
    try:
        if not _IS_DEVICE:
            os.makedirs(mount_point, exist_ok=True)
            print(f'[SD] Host mount simulated at {mount_point}')
            return True, None
        from machine import Pin

        from lib import sdcard
        
        # Ensure cs_pin is a Pin object
        if isinstance(cs_pin, int):
            cs_pin = Pin(cs_pin)
        
        sd = sdcard.SDCard(spi, cs_pin)
        os.mount(sd, mount_point)  # type: ignore[attr-defined]
        return True, sd
    except Exception as e:
        print(f'[SD] Mount failed at {mount_point}: {e}')
        return False, None


def is_mounted(sd, spi=None, return_instances: bool = False):
    """
    Check if SD card is inserted in reader.

    If an existing SDCard or SPI instance is provided, reuse it to avoid
    reinitializing hardware and contending with active mounts.
    """
    try:
        if not _IS_DEVICE:
            return (True, sd, spi) if return_instances else True
        from machine import SPI, Pin

        from config import DEVICE_CONFIG
        from lib import sdcard

        spi_config = DEVICE_CONFIG.get('spi', {})
        spi_id = spi_config.get('id', 1)
        baudrate = spi_config.get('baudrate', 40000000)
        sck = spi_config.get('sck', 10)
        mosi = spi_config.get('mosi', 11)
        miso = spi_config.get('miso', 12)
        cs = spi_config.get('cs', 13)
        mount_point = spi_config.get('mount_point', '/sd')

        def _init_sd_local():
            if isinstance(cs, int):
                cs_pin = Pin(cs)
            else:
                cs_pin = cs
            new_spi = SPI(
                spi_id,
                baudrate=baudrate,
                sck=Pin(sck),
                mosi=Pin(mosi),
                miso=Pin(miso)
            )
            try:
                sd_local = sdcard.SDCard(new_spi, cs_pin)
                os.mount(sd_local, mount_point)  # type: ignore[attr-defined]
                return sd_local, new_spi
            except Exception:
                try:
                    new_spi.deinit()
                except Exception:
                    pass
                raise

        def _safe_umount():
            try:
                os.umount(mount_point)  # type: ignore[attr-defined]
            except Exception:
                pass

        def _read_mbr(sd_obj):
            buf = bytearray(512)
            sd_obj.readblocks(0, buf)

        if sd is None:
            sd, spi = _init_sd_local()

        try:
            _read_mbr(sd)
            return (True, sd, spi) if return_instances else True
        except Exception:
            _safe_umount()
            try:
                if spi is not None:
                    spi.deinit()
            except Exception:
                pass
            time.sleep_ms(200)
            sd, spi = _init_sd_local()
            _read_mbr(sd)
            return (True, sd, spi) if return_instances else True
    except Exception as e:
        print(f'[SD] SD card not accessible: {e}')
        return (False, None, None) if return_instances else False