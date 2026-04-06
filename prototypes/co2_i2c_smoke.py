machine = __import__("machine")
time = __import__("time")

# Self-contained hardware mapping (no config.py dependency).
I2C_ID = 0
I2C_SDA = 0
I2C_SCL = 1
I2C_FREQ = 400000

CO2_UART_ID = 1
CO2_UART_TX = 16
CO2_UART_RX = 17
CO2_UART_BAUD = 9600
CO2_QUERY = b"\xfe\x44\x00\x08\x02\x9f\x25"

UART_TIMEOUT_MS = 500
ITERATIONS = 3
REPORT_PATH = "/local/co2_i2c_smoke.json"


def _query_co2(uart):
    uart.write(CO2_QUERY)
    deadline = time.ticks_add(time.ticks_ms(), UART_TIMEOUT_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            data = uart.read()
            if data:
                return data
        time.sleep_ms(20)
    return None


def _json_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _write_report(i2c_ok, uart_ok, addresses, uart_bytes, errors):
    # Keep this self-contained: write JSON text directly without json/ujson module.
    addr_txt = ",".join(str(v) for v in addresses)
    uart_txt = ",".join(str(v) for v in uart_bytes)
    err_txt = ",".join('"{}"'.format(_json_escape(e)) for e in errors)
    payload = (
        "{"
        '"i2c_ok":' + ("true" if i2c_ok else "false") + ","
        '"uart_ok":' + ("true" if uart_ok else "false") + ","
        '"simultaneous_ok":' + ("true" if (i2c_ok and uart_ok) else "false") + ","
        '"i2c_addrs":[' + addr_txt + "],"
        '"uart_bytes":[' + uart_txt + "],"
        '"iterations":' + str(ITERATIONS) + ","
        '"errors":[' + err_txt + "]"
        "}"
    )
    try:
        with open(REPORT_PATH, "w") as handle:
            handle.write(payload)
        return REPORT_PATH
    except OSError:
        with open("co2_i2c_smoke.json", "w") as handle:
            handle.write(payload)
        return "co2_i2c_smoke.json"


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
    )

    i2c_ok = True
    uart_ok = True
    last_addrs = []
    last_uart = b""
    errors = []

    for _ in range(ITERATIONS):
        try:
            last_addrs = i2c.scan()
        except Exception as exc:
            errors.append("i2c: {}".format(exc))
            i2c_ok = False

        try:
            response = _query_co2(uart)
            if response:
                last_uart = response
            else:
                errors.append("uart: timeout")
                uart_ok = False
        except Exception as exc:
            errors.append("uart: {}".format(exc))
            uart_ok = False

    print("I2C:", "OK" if i2c_ok else "FAIL", last_addrs)
    print("UART:", "OK" if uart_ok else "FAIL", list(last_uart))
    print("SIMULTANEOUS:", "OK" if (i2c_ok and uart_ok) else "FAIL")
    print("REPORT:", _write_report(i2c_ok, uart_ok, last_addrs, list(last_uart), errors))


if __name__ == "__main__":
    main()
