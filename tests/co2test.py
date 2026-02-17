from time import sleep

from machine import UART, Pin


def main():
    uart1 = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=500)
    uart1.init(9600, bits=8, parity=None, stop=1)
    uart1.flush()
    sleep(1)
    
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
                
                print(co2)
        else:
            print("Nothing to read...")

if __name__ == "__main__":
    main()