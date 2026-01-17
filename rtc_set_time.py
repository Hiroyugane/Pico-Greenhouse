import asyncio
import lib.ds3231 as ds3231
import time 

rtc = ds3231.RTC(sda_pin=0, scl_pin=1)
rtc_time = rtc.ReadTime('DIN-1355-1+time') # type: ignore
print('Alt:', rtc_time)

def dec_to_bcd(val):
    return (val // 10) << 4 | (val % 10)

def get_weekday(year, month, day):
    # Zeller's Congruence Algorithm to find the day of the week
    if month < 3:
        month += 12
        year -= 1
    K = year % 100
    J = year // 100
    f = day + 13*(month + 1)//5 + K + K//4 + J//4 + 5*J
    return (f % 7 + 6) % 7

# Aktuelle Zeit vom Pi Pico auslesen
current_time = time.localtime()

# Zeit auf dem RTC Chip setzen
year = current_time[0] - 2000  # RTC erwartet Jahr im Format '00 - 99'
month = current_time[1]
day = current_time[2]
hour = current_time[3]
minute = current_time[4]
second = current_time[5]
weekday = get_weekday(current_time[0], month, day)

# Zeitdaten in BCD-Format umwandeln
time_data = bytes([
    dec_to_bcd(second),
    dec_to_bcd(minute),
    dec_to_bcd(hour),
    dec_to_bcd(weekday),  # +1 weil RTC-Chips oft Montag=1, Dienstag=2, etc. haben
    dec_to_bcd(day),
    dec_to_bcd(month),
    dec_to_bcd(year)
])

# Angenommen rtc.SetTime() ist eine Methode des RTC-Chips
rtc.SetTime(time_data)

time.sleep(2)  # Kurze Pause, um sicherzustellen, dass die Zeit gesetzt wurde
print('Neu:', rtc_time)
print('current Time:', time.localtime())
print("Zeit erfolgreich auf RTC-Chip gesetzt.")

