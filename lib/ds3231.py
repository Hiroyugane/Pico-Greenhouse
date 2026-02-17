import machine


class RTC:
    w = ['Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag','Sonntag']
    
    def __init__(self, sda_pin=0, scl_pin=1, port=0, speed=100000, address=0x68, register=0x00, i2c=None):
        """
        Initialize DS3231 RTC.

        Args:
            sda_pin (int): SDA GPIO pin number (ignored when *i2c* is provided).
            scl_pin (int): SCL GPIO pin number (ignored when *i2c* is provided).
            port (int): I2C peripheral id (ignored when *i2c* is provided).
            speed (int): I2C bus frequency in Hz (ignored when *i2c* is provided).
            address (int): I2C address of the DS3231 (default 0x68).
            register (int): Start register for time data (default 0x00).
            i2c (machine.I2C, optional): Pre-built I2C bus instance for bus
                sharing (e.g. with an OLED display).  When provided the driver
                re-uses it instead of creating its own.
        """
        self.rtc_address = address
        self.rtc_register = register
        if i2c is not None:
            self.i2c = i2c
        else:
            sda=machine.Pin(sda_pin)
            scl=machine.Pin(scl_pin)
            self.i2c=machine.I2C(port, sda=sda, scl=scl, freq=speed)

    def SetTime(self, NowTime = b'\x00\x23\x12\x28\x14\x07\x21'):
        # NowTime (sec min hour weekday day month year)
        self.i2c.writeto_mem(int(self.rtc_address), int(self.rtc_register), NowTime)

    # Convert to binary format
    def bcd2bin(self, value):
        return (value or 0) - 6 * ((value or 0) >> 4)

    # Add a 0 in front of numbers smaller than 10
    def pre_zero(self, value):
        if value < 10:
            value = '0' + str(value)
        return str(value)

    def ReadTime(self, mode: int | str = 0):
        """
        Read current date and time from DS3231 RTC module.
        
        Supports multiple output formats for flexible timestamp representation.
        
        Args:
            mode: Output format mode. Supported values:
                - 0 or None (default): Returns tuple (second, minute, hour, weekday, day, month, year)
                - 'DIN-1355-1': Returns string 'DD.MM.YYYY' (German date format)
                - 'DIN-1355-1+time': Returns string 'DD.MM.YYYY HH:MM:SS' (German format with time)
                - 'ISO-8601': Returns string 'YYYY-MM-DD' (ISO date only)
                - 'timestamp': Returns string 'YYYY-MM-DD HH:MM:SS' (ISO 8601 with time)
                - 'time': Returns string 'HH:MM:SS' (time only)
                - 'weekday': Returns string with weekday name (German: Montag-Sonntag)
                - 'localtime': Returns tuple (year, month, day, hour, minute, second, weekday, yearday)
                - 'datetime': Returns tuple (year, month, day, weekday, hour, minute, second, 0)
        
        Returns:
            Tuple or string depending on mode parameter.
            Returns 'Error: Not connected to DS3231' if I2C communication fails.
        
        Example:
            >>> rtc = RTC(sda_pin=0, scl_pin=1)
            >>> rtc.ReadTime(1)  # Numeric mode (default)
            (45, 23, 12, 3, 14, 7, 2024)
            >>> rtc.ReadTime('timestamp')
            '2024-07-14 12:23:45'
            >>> rtc.ReadTime('DIN-1355-1+time')
            '14.07.2024 12:23:45'
        """
        try:
            buffer = self.i2c.readfrom_mem(self.rtc_address, self.rtc_register, 7)
        except:
            return 'Error: Not connected to DS3231'
        
        year = self.bcd2bin(buffer[6]) + 2000
        month = self.bcd2bin(buffer[5])
        day = self.bcd2bin(buffer[4])
        weekday = self.bcd2bin(buffer[3]) - 1
        hour = self.bcd2bin(buffer[2])
        minute = self.bcd2bin(buffer[1])
        second = self.bcd2bin(buffer[0])
        
        yearday = sum([31, 28 + (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)), 31, 30, 31, 30, 31, 31, 30, 31, 30][:month-1]) + day
        
        # Output
        if mode == 'DIN-1355-1':
            return self.pre_zero(day) + '.' + self.pre_zero(month) + '.' + str(year)
        elif mode == 'DIN-1355-1+time':
            return self.pre_zero(day) + '.' + self.pre_zero(month) + '.' + str(year) + ' ' + self.pre_zero(hour) + ':' + self.pre_zero(minute) + ':' + self.pre_zero(second)
        elif mode == 'ISO-8601':
            return str(year) + '-' + self.pre_zero(month) + '-' + self.pre_zero(day)
        elif mode == 'time':
            return self.pre_zero(hour) + ':' + self.pre_zero(minute) + ':' + self.pre_zero(second)
        elif mode == 'weekday':
            return self.w[weekday]
        elif mode == 'localtime':
            return (year, month, day, hour, minute, second, weekday, yearday)
        elif mode == 'datetime':
            return (year, month, day, weekday, hour, minute, second, 0)
        elif mode == 'timestamp':
            return str(year) + '-' + self.pre_zero(month) + '-' + self.pre_zero(day) + ' ' + self.pre_zero(hour) + ':' + self.pre_zero(minute) + ':' + self.pre_zero(second)
#        elif mode == 'RTC':
#            return (year, month, day[, hour[, minute[, second[, 0[, 0]]]]])
        else:
            return second, minute, hour, weekday, day, month, year