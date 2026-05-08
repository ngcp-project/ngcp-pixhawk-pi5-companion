#!/usr/bin/env python3
"""
telemetry_injector.py — GCS Simulator for MRA Laptop

Sends search area polygons, ERU patient coordinates, and MRA target
locations through the RFD-900x radio link (via MAVProxy) to the Pi 5.
The Pi 5's gcs_translator.py receives the messages and writes them to
/tmp/telemetry.json, which gcs_bridge.py then reads into navigation_state.json.

This tool runs on the MRA laptop and uses the same MAVProxy router that
kraken_server.py connects to.

Usage:
  # Inject default CPP search area + ERU location
  python3 telemetry_injector.py --all

  # Inject only search area
  python3 telemetry_injector.py --search-area

  # Inject custom ERU coordinates
  python3 telemetry_injector.py --eru 34.043391 -117.81441

  # Inject MRA Phase 1 refined loiter target
  python3 telemetry_injector.py --mra-refined 34.0430 -117.8145

  # Inject MRA Phase 2 final estimated location
  python3 telemetry_injector.py --mra-final 34.0432 -117.8144

  # Inject everything (full Demo Day simulation)
  python3 telemetry_injector.py --all

  # Use a custom MAVProxy endpoint
  python3 telemetry_injector.py --all --mavlink udp:127.0.0.1:14555

Data Flow:
  MRA Laptop (this script) → MAVProxy Router → RFD-900x radio
  → Pi 5 MAVProxy → gcs_translator.py → /tmp/telemetry.json
  → gcs_bridge.py → navigation_state.json

Protocol:
  - ERU/MRA targets use DEBUG_VECT messages (same as kraken_server.py)
  - Search area uses STATUSTEXT chunked JSON (same as fusion_sender.py)
"""

import argparse
import json
import math
import os
import sys
import time

try:
    from pymavlink import mavutil
except ImportError:
    print("[injector] ERROR: pymavlink not installed.")
    print("[injector] Install with: pip install pymavlink")
    sys.exit(1)

# ── Default CPP Competition Search Area ─────────────────────────────────
# 6-vertex polygon around the Cal Poly Pomona competition field.
# gcs_translator.py collects STATUSTEXT 'SA:' chunks and rebuilds the zone.
DEFAULT_SEARCH_AREA = [
    [34.044485, -117.814538],
    [34.042812, -117.812002],
    [34.040978, -117.813997],
    [34.039158, -117.815556],
    [34.040610, -117.817737],
    [34.042604, -117.816364],
]

# ── Default ERU Patient Location ────────────────────────────────────────
DEFAULT_ERU_LAT = 34.043391
DEFAULT_ERU_LON = -117.814410

# ── MAVLink Connection ──────────────────────────────────────────────────
DEFAULT_MAVLINK_URI = 'udp:127.0.0.1:14555'  # MRA laptop MAVProxy router


def send_eru(mav, lat, lon):
    """Send ERU patient location as DEBUG_VECT('ERU_TGT').
    Pi 5's gcs_translator.py already handles this message name."""
    mav.mav.debug_vect_send(
        b'ERU_TGT',
        int(time.time() * 1e6),
        lat, lon, 0.0
    )
    print(f'[injector] Sent ERU_TGT: ({lat}, {lon})')


def send_mra_refined(mav, lat, lon, spread_m=50.0):
    """Send MRA Phase 1 refined loiter target as DEBUG_VECT('MRA_LOITER')."""
    mav.mav.debug_vect_send(
        b'MRA_LOITER',
        int(time.time() * 1e6),
        lat, lon, spread_m
    )
    print(f'[injector] Sent MRA_LOITER: ({lat}, {lon}), spread={spread_m}m')


def send_mra_final(mav, lat, lon, spread_m=20.0):
    """Send MRA Phase 2 final estimated location as DEBUG_VECT('MRA_FINAL')."""
    mav.mav.debug_vect_send(
        b'MRA_FINAL',
        int(time.time() * 1e6),
        lat, lon, spread_m
    )
    print(f'[injector] Sent MRA_FINAL: ({lat}, {lon}), spread={spread_m}m')


def send_search_area(mav, coordinates):
    """Send search area as chunked STATUSTEXT messages.
    
    Protocol: STATUSTEXT with severity INFO, text starting with 'SA:'
    followed by JSON chunks. gcs_translator.py on Pi 5 reassembles them.
    
    Format: SA{seq:02d}{chunk:02d}{total:02d}:{json_payload}
    """
    payload = json.dumps({
        "zone_id": 1,
        "zone_type": "SearchArea",
        "coordinates": coordinates
    }, separators=(',', ':'))
    
    chunk_size = 40  # 50 - 10 header chars
    chunks = [payload[i:i+chunk_size] for i in range(0, len(payload), chunk_size)]
    total = len(chunks)
    seq = int(time.time()) % 100
    
    print(f'[injector] Sending search area ({len(coordinates)} vertices, {total} chunks)...')
    
    for idx, chunk in enumerate(chunks):
        text = f"SA{seq:02d}{idx:02d}{total:02d}:{chunk}"
        mav.mav.statustext_send(
            mavutil.mavlink.MAV_SEVERITY_INFO,
            text.encode().ljust(50, b'\x00')
        )
        time.sleep(0.05)  # Small gap between chunks for reliable delivery
    
    print(f'[injector] Search area sent: {total} STATUSTEXT chunks')


def send_search_area_debug_vect(mav, coordinates):
    """Fallback: Send search area vertices as individual DEBUG_VECT messages.
    
    Uses message name 'SA_VERT' with:
      x = latitude, y = longitude, z = vertex_index (0-based)
    
    Pi 5's gcs_translator.py collects these to build the zone polygon.
    A final 'SA_DONE' message signals end of transmission.
    """
    print(f'[injector] Sending search area via DEBUG_VECT ({len(coordinates)} vertices)...')
    
    for i, coord in enumerate(coordinates):
        mav.mav.debug_vect_send(
            b'SA_VERT',
            int(time.time() * 1e6),
            coord[0], coord[1], float(i)
        )
        time.sleep(0.05)
    
    # Signal end of vertex list
    mav.mav.debug_vect_send(
        b'SA_DONE',
        int(time.time() * 1e6),
        float(len(coordinates)), 0.0, 0.0
    )
    print(f'[injector] Search area complete: {len(coordinates)} vertices sent')


def main():
    parser = argparse.ArgumentParser(
        description='GCS Simulator — inject test data via RFD-900x radio',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--search-area', action='store_true',
                        help='Inject default CPP search area polygon')
    parser.add_argument('--eru', nargs='*', type=float, metavar=('LAT', 'LON'),
                        help='Inject ERU patient location (default: CPP field center)')
    parser.add_argument('--mra-refined', nargs=2, type=float, metavar=('LAT', 'LON'),
                        help='Inject MRA Phase 1 refined loiter target')
    parser.add_argument('--mra-final', nargs=2, type=float, metavar=('LAT', 'LON'),
                        help='Inject MRA Phase 2 final estimated location')
    parser.add_argument('--all', action='store_true',
                        help='Inject search area + ERU (full Demo Day sim)')
    parser.add_argument('--mavlink', type=str, default=DEFAULT_MAVLINK_URI,
                        help=f'MAVLink endpoint (default: {DEFAULT_MAVLINK_URI})')
    parser.add_argument('--loop', type=int, default=0, metavar='SECONDS',
                        help='Re-inject every N seconds (continuous mode)')
    parser.add_argument('--use-statustext', action='store_true',
                        help='Use STATUSTEXT chunking for search area (instead of DEBUG_VECT)')

    args = parser.parse_args()

    # If no flags provided, show help
    if not (args.search_area or args.eru is not None or args.mra_refined
            or args.mra_final or args.all):
        parser.print_help()
        print('\n[injector] Example: python3 telemetry_injector.py --all')
        sys.exit(0)

    # Connect to MAVProxy
    print(f'[injector] Connecting to MAVProxy at {args.mavlink}...')
    mav = mavutil.mavlink_connection(args.mavlink, source_system=254, source_component=1)
    print(f'[injector] Connected. Sending data via RFD-900x...')

    def do_inject():
        if args.search_area or args.all:
            if args.use_statustext:
                send_search_area(mav, DEFAULT_SEARCH_AREA)
            else:
                send_search_area_debug_vect(mav, DEFAULT_SEARCH_AREA)

        if args.eru is not None or args.all:
            if args.eru and len(args.eru) == 2:
                lat, lon = args.eru
            else:
                lat, lon = DEFAULT_ERU_LAT, DEFAULT_ERU_LON
            send_eru(mav, lat, lon)

        if args.mra_refined:
            send_mra_refined(mav, args.mra_refined[0], args.mra_refined[1])

        if args.mra_final:
            send_mra_final(mav, args.mra_final[0], args.mra_final[1])

    if args.loop > 0:
        print(f'[injector] Continuous mode — re-injecting every {args.loop}s. Ctrl+C to stop.')
        try:
            while True:
                do_inject()
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print('\n[injector] Stopped.')
    else:
        do_inject()
        print('[injector] Done. Pi 5 should update within ~1 second.')


if __name__ == '__main__':
    main()
