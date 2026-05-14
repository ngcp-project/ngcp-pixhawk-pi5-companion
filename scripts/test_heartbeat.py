#!/usr/bin/env python3
from pymavlink import mavutil
import sys
print("Listening on udp:127.0.0.1:14601...")
m = mavutil.mavlink_connection("udp:127.0.0.1:14601")
msg = m.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
if msg:
    print("HEARTBEAT received:", msg)
else:
    print("NO HEARTBEAT after 5s")
    sys.exit(1)
