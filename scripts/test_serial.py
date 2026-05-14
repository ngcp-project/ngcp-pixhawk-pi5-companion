#!/usr/bin/env python3
import serial
import sys
try:
    s = serial.Serial("/dev/ttyUSB0", 115200, timeout=1)
    print("opened:", s.name)
    s.close()
    print("closed OK")
except Exception as e:
    print("FAILED:", e)
    sys.exit(1)
