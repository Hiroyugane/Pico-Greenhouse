# SD Card Integration Helper
# Dennis Hiro, 2024-06-08
#
# Lightweight utilities for SD card mounting and availability checks.
# Used by hardware_factory and buffer_manager.

import os
import sys


def mount_sd(spi, cs_pin, mount_point: str = '/sd') -> bool:
    """
    Attempt to mount SD card on specified mount point.
    
    Args:
        spi: machine.SPI instance (already initialized)
        cs_pin: machine.Pin object or int for chip select
        mount_point (str): Mount point path (default: '/sd')
    
    Returns:
        bool: True if mounted successfully, False on error
    """
    try:
        if sys.implementation.name != 'micropython':
            os.makedirs(mount_point, exist_ok=True)
            print(f'[SD] Host mount simulated at {mount_point}')
            return True
        from lib import sdcard
        from machine import Pin
        
        # Ensure cs_pin is a Pin object
        if isinstance(cs_pin, int):
            cs_pin = Pin(cs_pin)
        
        sd = sdcard.SDCard(spi, cs_pin)
        os.mount(sd, mount_point)
        return True
    except Exception as e:
        print(f'[SD] Mount failed at {mount_point}: {e}')
        return False


def is_mounted(sd) -> bool:
    """
    Check if SD card is inserted in reader.

    If an existing SDCard or SPI instance is provided, reuse it to avoid
    reinitializing hardware and contending with active mounts.
    """
    try:
        if sys.implementation.name != 'micropython':
            return True
        from config import DEVICE_CONFIG
        from machine import Pin, SPI
        from lib import sdcard
        if sd is None:
            """ 
            if spi is None:
                spi_config = DEVICE_CONFIG.get('spi', {})
                spi_id = spi_config.get('id', 1)
                baudrate = spi_config.get('baudrate', 40000000)
                sck = spi_config.get('sck', 10)
                mosi = spi_config.get('mosi', 11)
                miso = spi_config.get('miso', 12)

                spi = SPI(
                    spi_id,
                    baudrate=baudrate,
                    sck=Pin(sck),
                    mosi=Pin(mosi),
                    miso=Pin(miso)
                )

            if cs_pin is None:
                cs_pin = DEVICE_CONFIG.get('spi', {}).get('cs', 13)

            if isinstance(cs_pin, int):
                cs_pin = Pin(cs_pin)

            sd = sdcard.SDCard(spi, cs_pin)
            """
        buf = bytearray(512)
        sd.readblocks(0, buf)
        return True
    except Exception as e:
        print(f'[SD] SD card not accessible: {e}')
        return False