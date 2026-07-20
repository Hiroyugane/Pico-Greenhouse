# Recoverable I2C bus guard
# Dennis Hiro, 2026-07-20
#
# Wraps the single shared I2C bus so a transient bus fault — a slave that
# clock-stretches or holds SDA/SCL low — is BOUNDED and RECOVERABLE instead
# of freezing the CPU. This is the fix for the 2026-07-19 bootloop: a
# marginal bus made the OLED framebuffer render block on [Errno 110]
# ETIMEDOUT long enough to starve the async watchdog feed, so the 8 s WDT
# reset the board every ~20 s — and because a reset does not power-cycle the
# I2C slaves, the stuck bus was still stuck on reboot (self-sustaining loop).
#
# How it defends:
# - Prefers machine.SoftI2C(timeout=...) so every transfer FAILS FAST
#   (raises OSError) instead of blocking past the watchdog. Hardware
#   machine.I2C on rp2 has no timeout kwarg and cannot be unstuck in place;
#   a blocked transfer there never returns to run recovery.
# - On OSError it drives SCL as a GPIO for a few clock pulses to release a
#   wedged slave, rebuilds the bus, and retries the transfer ONCE. Still
#   failing -> re-raises so the calling driver logs/handles it (no infinite
#   retry on the hot path).
#
# Every driver on the shared bus (DS3231, SHT31, SSD1306, PCA9685, MCP4725)
# uses only the base I2C API forwarded here, so they gain recovery with no
# driver edits. Set system.i2c_use_soft=False to revert to raw hardware I2C
# (no timeout, no recovery) on a known-good board.

try:
    from machine import I2C, Pin, SoftI2C
except ImportError:  # pragma: no cover - platform without SoftI2C
    from machine import I2C, Pin

    SoftI2C = None

try:
    from time import sleep_us
except ImportError:  # pragma: no cover - CPython host has no sleep_us

    def sleep_us(_us):
        pass


class RecoverableI2C:
    """Bounded, self-recovering proxy around one shared I2C bus.

    Forwards the base I2C transfer methods to an inner ``SoftI2C`` (bounded
    timeout) or hardware ``I2C``; on ``OSError`` it unsticks the bus and
    retries once. Drivers hold a reference to this proxy, so recovery can
    rebuild the inner bus transparently without any driver noticing.
    """

    def __init__(
        self,
        *,
        sda,
        scl,
        port=0,
        freq=100000,
        use_soft=True,
        timeout_us=50000,
        recover_on_error=True,
        recover_clocks=9,
        debug=None,
    ):
        self._sda = sda
        self._scl = scl
        self._port = port
        self._freq = freq
        # SoftI2C is the only path that bounds each transfer AND can be
        # rebuilt/unstuck; fall back to hardware I2C if it is unavailable.
        self._use_soft = bool(use_soft) and SoftI2C is not None
        self._timeout_us = timeout_us
        self._recover_on_error = recover_on_error
        self._recover_clocks = recover_clocks
        self._debug = debug
        self._i2c = None
        self.recoveries = 0  # count of recovery attempts (diagnostics)
        self._build()

    def _build(self):
        """(Re)construct the inner bus from the stored pins/params."""
        if self._use_soft:
            self._i2c = SoftI2C(
                scl=Pin(self._scl),
                sda=Pin(self._sda),
                freq=self._freq,
                timeout=self._timeout_us,
            )
        else:
            self._i2c = I2C(self._port, sda=Pin(self._sda), scl=Pin(self._scl), freq=self._freq)

    def recover(self):
        """Best-effort bus unstick: pulse SCL to release a wedged slave, then
        rebuild the bus. Never raises — recovery must not itself crash a task.
        Returns True if the bus was rebuilt after a clean unstick sequence.
        """
        self.recoveries += 1
        try:
            inner = self._i2c
            self._i2c = None
            deinit = getattr(inner, "deinit", None)
            if deinit is not None:
                try:
                    deinit()
                except Exception:
                    pass
            # Release SDA (input) and clock SCL to flush a slave that is mid
            # transfer and holding SDA low; then emit a STOP condition.
            scl = Pin(self._scl, Pin.OUT)
            Pin(self._sda, Pin.IN)
            for _ in range(self._recover_clocks):
                scl.value(0)
                sleep_us(5)
                scl.value(1)
                sleep_us(5)
            sda = Pin(self._sda, Pin.OUT)
            sda.value(0)
            sleep_us(5)
            scl.value(1)
            sleep_us(5)
            sda.value(1)  # SDA low->high while SCL high == STOP
            sleep_us(5)
            self._build()
            if self._debug:
                self._debug("i2c bus recovered")
            return True
        except Exception as exc:
            if self._debug:
                self._debug("i2c recover failed: {}".format(exc))
            # Last resort: at least try to rebuild so the next call has a bus.
            if self._i2c is None:
                try:
                    self._build()
                except Exception:
                    pass
            return False

    # ── Delegating transfer methods ───────────────────────────────────────
    # Success path stays allocation-free (explicit args, no *args/**kwargs,
    # log/format strings only on the error branch) so the regulation hot path
    # (PCA9685 writeto_mem every tick) is unaffected.

    def writeto(self, addr, buf):
        try:
            return self._i2c.writeto(addr, buf)
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.writeto(addr, buf)

    def readfrom(self, addr, nbytes):
        try:
            return self._i2c.readfrom(addr, nbytes)
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.readfrom(addr, nbytes)

    def writeto_mem(self, addr, reg, data):
        try:
            return self._i2c.writeto_mem(addr, reg, data)
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.writeto_mem(addr, reg, data)

    def readfrom_mem(self, addr, reg, length):
        try:
            return self._i2c.readfrom_mem(addr, reg, length)
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.readfrom_mem(addr, reg, length)

    def writevto(self, addr, buflist):
        try:
            return self._i2c.writevto(addr, buflist)
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.writevto(addr, buflist)

    def scan(self):
        try:
            return self._i2c.scan()
        except OSError:
            if not self._recover_on_error:
                raise
            self.recover()
            return self._i2c.scan()
