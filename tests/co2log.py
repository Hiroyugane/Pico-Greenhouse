from machine import UART, Pin
from time import sleep
import lib.ds3231 as ds3231


def main():
    # Initialize RTC
    rtc = ds3231.RTC(sda_pin=2, scl_pin=3, port=1)
    
    # Initialize UART for CO2 sensor
    uart1 = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=500)
    uart1.init(9600, bits=8, parity=None, stop=1)
    uart1.flush()
    sleep(1)
    
    # Open log file
    log_file = open('co2_log.csv', 'a')
    
    while True:
        uart1.flush()
        sequence_to_send = b'\xFE\x44\x00\x08\x02\x9F\x25'
        uart1.write(sequence_to_send)
        sleep(10)
                
        if uart1.any():
            resp = uart1.read(7)
            if resp is not None and len(resp) >= 5:
                high = resp[3]
                low = resp[4]
                co2 = high * 256 + low
                
                # Log to file with RTC timestamp
                timestamp = rtc.ReadTime('timestamp')
                log_file.write(f"{timestamp},{co2}\n")
                log_file.flush()
                
                print(co2)
        else:
            print("Nothing to read...")

if __name__ == "__main__":
    main()