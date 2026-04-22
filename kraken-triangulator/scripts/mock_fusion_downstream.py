#!/usr/bin/env python3
import socket
import json
import time
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MOCK_JSON = BASE_DIR / "data" / "bearings_20260417_140805.json"
UDP_IP = "127.0.0.1"
UDP_PORT = 5051
HZ = 10.0

print(f"Loading {MOCK_JSON}...")
with open(MOCK_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)

waypoints = data.get("waypoint_sequence", [])
print(f"Found {len(waypoints)} fusion waypoints. Streaming UDP at {HZ} Hz...")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

for idx, wp in enumerate(waypoints):
    payload = json.dumps(wp).encode('utf-8')
    sock.sendto(payload, (UDP_IP, UDP_PORT))
    print(f"Sent wp {idx+1}/{len(waypoints)}", end='\r')
    time.sleep(1.0 / HZ)

print("\nFinished mock live sequence.")
