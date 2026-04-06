machine = __import__("machine")
time = __import__("time")

# Self-contained hardware mapping (no config.py dependency).
I2C_ID = 0
I2C_SDA = 0
I2C_SCL = 1
I2C_FREQ = 400000

CO2_UART_ID = 0
CO2_UART_TX = 16
CO2_UART_RX = 17
CO2_UART_BAUD = 9600
CO2_QUERY = b"\xfe\x44\x00\x08\x02\x9f\x25"

UART_TIMEOUT_MS = 500
POLL_SECONDS = 5
RTC_ADDR = 0x68
DS3231_REG_CTRL = 0x0E
DS3231_REG_STATUS = 0x0F
DS3231_REG_TEMP = 0x11
DS3231_CTRL_CONV = 0x20
DS3231_STATUS_BSY = 0x04


def _query_co2(uart):
    uart.flush()
    uart.write(CO2_QUERY)
    deadline = time.ticks_add(time.ticks_ms(), UART_TIMEOUT_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            data = uart.read(7)
            if data and len(data) >= 5:
                return data
        time.sleep_ms(20)
    return None


def _bcd_to_dec(value):
    return (value >> 4) * 10 + (value & 0x0F)


def _read_ds3231_temp_c(i2c):
    # Trigger a fresh temperature conversion so 5s polling is meaningful.
    ctrl = i2c.readfrom_mem(RTC_ADDR, DS3231_REG_CTRL, 1)[0]
    i2c.writeto_mem(RTC_ADDR, DS3231_REG_CTRL, bytes([ctrl | DS3231_CTRL_CONV]))

    deadline = time.ticks_add(time.ticks_ms(), 250)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        status = i2c.readfrom_mem(RTC_ADDR, DS3231_REG_STATUS, 1)[0]
        if (status & DS3231_STATUS_BSY) == 0:
            break
        time.sleep_ms(10)

    temp_raw = i2c.readfrom_mem(RTC_ADDR, DS3231_REG_TEMP, 2)
    msb = temp_raw[0]
    if msb & 0x80:
        msb -= 256
    frac = (temp_raw[1] >> 6) * 0.25
    return msb + frac


def _read_rtc(i2c):
    try:
        raw = i2c.readfrom_mem(RTC_ADDR, 0x00, 7)
        sec = _bcd_to_dec(raw[0] & 0x7F)
        minute = _bcd_to_dec(raw[1] & 0x7F)
        hour = _bcd_to_dec(raw[2] & 0x3F)
        day = _bcd_to_dec(raw[4] & 0x3F)
        month = _bcd_to_dec(raw[5] & 0x1F)
        year = 2000 + _bcd_to_dec(raw[6])

        temp_c = _read_ds3231_temp_c(i2c)

        timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            year,
            month,
            day,
            hour,
            minute,
            sec,
        )
        return timestamp, temp_c, None
    except Exception as exc:
        return None, None, str(exc)


def _parse_co2_ppm(payload):
    # Match the known-good extraction from prototypes/co2-test.py.
    if payload and len(payload) >= 5:
        high = payload[3]
        low = payload[4]
        return high * 256 + low
    return None


def main():
    i2c = machine.I2C(
        I2C_ID,
        sda=machine.Pin(I2C_SDA),
        scl=machine.Pin(I2C_SCL),
        freq=I2C_FREQ,
    )
    uart = machine.UART(
        CO2_UART_ID,
        baudrate=CO2_UART_BAUD,
        tx=machine.Pin(CO2_UART_TX),
        rx=machine.Pin(CO2_UART_RX),
        timeout=UART_TIMEOUT_MS,
    )
    uart.init(CO2_UART_BAUD, bits=8, parity=None, stop=1)
    uart.flush()
    time.sleep(1)

    try:
        addrs = i2c.scan()
    except Exception:
        addrs = []

    print("I2C devices:", addrs)
    print("Polling RTC (0x68) + CO2 every {}s. Press Ctrl+C to stop.".format(POLL_SECONDS))

    while True:
        timestamp, rtc_temp_c, rtc_error = _read_rtc(i2c)

        co2_payload = _query_co2(uart)
        co2_ppm = _parse_co2_ppm(co2_payload)
        co2_raw = list(co2_payload or b"")

        if rtc_error is None:
            rtc_part = "RTC={} temp={:.2f}C".format(timestamp, rtc_temp_c)
        else:
            rtc_part = "RTC=ERROR({})".format(rtc_error)

        if co2_ppm is not None:
            co2_part = "CO2={}ppm raw={}".format(co2_ppm, co2_raw)
        else:
            co2_part = "CO2=ERROR(timeout/invalid) raw={}".format(co2_raw)

        print("{} | {}".format(rtc_part, co2_part))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
