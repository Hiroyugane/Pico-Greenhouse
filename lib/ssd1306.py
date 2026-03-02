# SSD1306 OLED display driver for MicroPython (I2C interface)
# Adapted from the official MicroPython SSD1306 driver (MIT License).
# Vendored: excluded from lint/test (see pyproject.toml).
#
# Supports 128×64 monochrome OLED displays on I2C bus.
# Typical I2C address: 0x3C (default) or 0x3D.

import framebuf

try:
    from micropython import const
except ImportError:
    def const(x):
        return x

# ── SSD1306 command bytes ───────────────────────────────────────────────────
_SET_CONTRAST        = const(0x81)
_SET_ENTIRE_ON       = const(0xA4)
_SET_NORM_INV        = const(0xA6)
_SET_DISP            = const(0xAE)
_SET_MEM_ADDR        = const(0x20)
_SET_COL_ADDR        = const(0x21)
_SET_PAGE_ADDR       = const(0x22)
_SET_DISP_START_LINE = const(0x40)
_SET_SEG_REMAP       = const(0xA0)
_SET_MUX_RATIO       = const(0xA8)
_SET_COM_OUT_DIR     = const(0xC0)
_SET_DISP_OFFSET     = const(0xD3)
_SET_COM_PIN_CFG     = const(0xDA)
_SET_DISP_CLK_DIV    = const(0xD5)
_SET_PRECHARGE       = const(0xD9)
_SET_VCOM_DESEL      = const(0xDB)
_SET_CHARGE_PUMP     = const(0x8D)


class SSD1306(framebuf.FrameBuffer):
    """
    SSD1306 OLED controller base class.

    Extends FrameBuffer so all drawing primitives are inherited.
    Call show() to transfer the in-memory buffer to the display.
    """

    def __init__(self, width: int, height: int, external_vcc: bool = False):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        self.init_display()

    def init_display(self):
        for cmd in (
            _SET_DISP,                              # display off
            _SET_MEM_ADDR, 0x00,                    # horizontal addressing
            _SET_DISP_START_LINE | 0,               # start at line 0
            _SET_SEG_REMAP | 0x01,                  # column address 127 mapped to SEG0
            _SET_MUX_RATIO, self.height - 1,
            _SET_COM_OUT_DIR | 0x08,                # scan from COM[N] to COM0
            _SET_DISP_OFFSET, 0x00,
            _SET_COM_PIN_CFG, 0x12 if (self.height != 32 or self.width != 64) else 0x02,
            _SET_DISP_CLK_DIV, 0x80,
            _SET_PRECHARGE, 0x22 if self.external_vcc else 0xF1,
            _SET_VCOM_DESEL, 0x30,                  # 0.83 × Vcc
            _SET_CONTRAST, 0xFF,
            _SET_ENTIRE_ON,                         # output follows RAM
            _SET_NORM_INV,                          # not inverted
            _SET_CHARGE_PUMP, 0x10 if self.external_vcc else 0x14,
            _SET_DISP | 0x01,                       # display on
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(_SET_DISP)

    def poweron(self):
        self.write_cmd(_SET_DISP | 0x01)

    def contrast(self, contrast: int):
        self.write_cmd(_SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert: bool):
        self.write_cmd(_SET_NORM_INV | (invert & 1))

    def rotate(self, rotate: bool):
        self.write_cmd(_SET_COM_OUT_DIR | ((rotate & 1) << 3))
        self.write_cmd(_SET_SEG_REMAP | (rotate & 1))

    def show(self):
        x0 = 0
        x1 = self.width - 1
        self.write_cmd(_SET_COL_ADDR)
        self.write_cmd(x0)
        self.write_cmd(x1)
        self.write_cmd(_SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        self.write_data(self.buffer)

    def write_cmd(self, cmd):
        raise NotImplementedError

    def write_data(self, buf):
        raise NotImplementedError


class SSD1306_I2C(SSD1306):
    """
    SSD1306 OLED driver using I2C interface.

    Args:
        width (int): Display width in pixels (typically 128)
        height (int): Display height in pixels (typically 64)
        i2c: machine.I2C instance (shared bus)
        addr (int): I2C device address (default: 0x3C)
        external_vcc (bool): True if display uses external VCC rail (default: False)

    Example::

        from machine import I2C, Pin
        from lib.ssd1306 import SSD1306_I2C
        i2c = I2C(0, sda=Pin(0), scl=Pin(1))
        oled = SSD1306_I2C(128, 64, i2c)
        oled.text("Hello!", 0, 0, 1)
        oled.show()
    """

    def __init__(self, width: int, height: int, i2c, addr: int = 0x3C, external_vcc: bool = False):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)
        self.write_list = [b"\x40", None]  # Co=0, D/C#=1 → data stream
        super().__init__(width, height, external_vcc)

    def write_cmd(self, cmd: int):
        self.temp[0] = 0x80  # Co=1, D/C#=0 → single command byte
        self.temp[1] = cmd
        self.i2c.writeto(self.addr, self.temp)

    def write_data(self, buf):
        self.write_list[1] = buf
        self.i2c.writeto(self.addr, b"\x40" + bytes(buf))
