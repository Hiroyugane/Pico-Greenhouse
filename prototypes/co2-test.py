from time import sleep

from machine import RTC, UART, Pin


def log_message(level, module, message):
    """
    Simple logging function for prototyping.
    Format: [LEVEL] [Module] message

    Levels: INFO, WARN, ERR, DEBUG
    """
    print(f"[{level}] [{module}] {message}")


def get_timestamp():
    """Return ISO-8601 timestamp (YYYY-MM-DD HH:MM:SS) from RTC."""
    try:
        rtc = RTC()
        dt = rtc.datetime()
        # dt format: (year, month, day, weekday, hour, minute, second, subseconds)
        return f"{dt[0]:04d}-{dt[1]:02d}-{dt[2]:02d} {dt[4]:02d}:{dt[5]:02d}:{dt[6]:02d}"
    except Exception as e:
        log_message("WARN", "Timestamp", f"Could not read RTC: {e}")
        return "UNKNOWN_TIME"


def ensure_csv_header(filepath):
    """Create CSV file with header if it doesn't exist."""
    try:
        with open(filepath, "r") as f:
            pass  # File exists, header already present
    except OSError:
        # File doesn't exist, create it with header
        try:
            with open(filepath, "w") as f:
                f.write("timestamp,co2_ppm\n")
            log_message("INFO", "CSVLogger", f"Created CSV file: {filepath}")
        except Exception as e:
            log_message("ERR", "CSVLogger", f"Failed to create CSV: {e}")


def write_co2_reading(filepath, co2_value):
    """Append a CO2 reading to CSV file."""
    try:
        timestamp = get_timestamp()
        with open(filepath, "a") as f:
            f.write(f"{timestamp},{co2_value}\n")
    except Exception as e:
        log_message("ERR", "CSVLogger", f"Failed to write reading: {e}")


def main():
    module = "CO2Test"

    # Determine log file path (prefer SD card if available)
    log_file = "/sd/co2_log.csv"
    try:
        with open(log_file, "r"):
            pass  # SD card is available
    except OSError:
        log_file = "/co2_log.csv"  # Fallback to flash
        log_message("WARN", module, "SD card not available, using flash storage")

    log_message("INFO", module, f"Logging to: {log_file}")
    ensure_csv_header(log_file)

    try:
        log_message("INFO", module, "Initializing UART for CO2 sensor")
        uart1 = UART(0, baudrate=9600, tx=Pin(16), rx=Pin(17), timeout=500)
        uart1.init(9600, bits=8, parity=None, stop=1)
        uart1.flush()
        log_message("INFO", module, "UART initialized successfully")
        sleep(5)
    except Exception as e:
        log_message("ERR", module, f"UART initialization failed: {e}")
        return

    read_count = 0
    error_count = 0

    log_message("INFO", module, "Starting CO2 reading loop")

    while True:
        try:
            uart1.flush()
            sequence_to_send = b"\xfe\x44\x00\x08\x02\x9f\x25"
            uart1.write(sequence_to_send)
            log_message("DEBUG", module, f"Sent command: {sequence_to_send.hex()}")
            sleep(5)

            if uart1.any():
                resp = uart1.read(7)
                if resp is not None and len(resp) >= 5:
                    high = resp[3]
                    low = resp[4]
                    co2 = high * 256 + low
                    read_count += 1

                    log_message("INFO", module, f"CO2 reading: {co2} ppm | reads={read_count} errors={error_count}")
                    write_co2_reading(log_file, co2)
                elif resp is not None:
                    error_count += 1
                    log_message("WARN", module, f"Incomplete response: got {len(resp)} bytes, expected 7")
                else:
                    error_count += 1
                    log_message("WARN", module, "Response is None")
            else:
                error_count += 1
                log_message("WARN", module, "No data available from UART")

        except Exception as e:
            error_count += 1
            log_message("ERR", module, f"Error during read cycle: {e}")
            sleep(5)  # Brief pause before retry


if __name__ == "__main__":
    main()
