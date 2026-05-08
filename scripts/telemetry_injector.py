#!/usr/bin/env python3
"""
telemetry_injector.py — GCS Simulator for Pi 5 Testing

Writes search area polygons, ERU patient coordinates, and MRA target
locations directly to /tmp/telemetry.json, bypassing the XBee/GCS pipeline.
This lets gcs_bridge.py populate navigation_state.json for autonomous
mission testing without needing the GCS laptop or XBee radios.

Usage:
  # Inject default CPP search area + ERU location
  python3 telemetry_injector.py

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

  # Run in continuous mode (re-injects every N seconds to survive translator restarts)
  python3 telemetry_injector.py --all --loop 5

Notes:
  - This script MERGES into the existing /tmp/telemetry.json — it does NOT
    overwrite vehicle telemetry (lat/lon/alt/battery) written by gcs_translator.py.
  - gcs_bridge.py polls telemetry.json every 200ms, so changes propagate
    to navigation_state.json within ~1 second.
  - Safe to run while gcs_translator.py is active — both do atomic writes.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

TELEMETRY_PATH = Path('/tmp/telemetry.json')

# ── Default CPP Competition Search Area ─────────────────────────────────
# 6-vertex polygon around the Cal Poly Pomona competition field.
# gcs_bridge.py looks for zone_id == 1 to populate search_area in nav_state.
DEFAULT_SEARCH_AREA_ZONES = [
    {
        "zone_id": 1,
        "zone_type": "SearchArea",
        "coordinates": [
            [34.044485, -117.814538],
            [34.042812, -117.812002],
            [34.040978, -117.813997],
            [34.039158, -117.815556],
            [34.040610, -117.817737],
            [34.042604, -117.816364],
        ]
    }
]

# ── Default ERU Patient Location ─────────────────────────────────────────
DEFAULT_ERU_LAT = 34.043391
DEFAULT_ERU_LON = -117.814410


def read_existing():
    """Read existing telemetry.json, or return empty dict."""
    if not TELEMETRY_PATH.exists():
        return {}
    try:
        return json.loads(TELEMETRY_PATH.read_text())
    except Exception:
        return {}


def atomic_write(data: dict):
    """Write JSON atomically (same pattern as nav_state_utils)."""
    tmp = TELEMETRY_PATH.with_name(f'{TELEMETRY_PATH.name}.{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(data, indent=None))
        os.replace(tmp, TELEMETRY_PATH)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def inject(args):
    """Merge requested fields into telemetry.json."""
    data = read_existing()
    changes = []

    # Search area zones
    if args.search_area or args.all:
        data['zones'] = DEFAULT_SEARCH_AREA_ZONES
        n = len(DEFAULT_SEARCH_AREA_ZONES[0]['coordinates'])
        changes.append(f'search area ({n} vertices)')

    # ERU patient location
    if args.eru or args.all:
        if args.eru and len(args.eru) == 2:
            lat, lon = args.eru
        else:
            lat, lon = DEFAULT_ERU_LAT, DEFAULT_ERU_LON
        data['eru_lat'] = float(lat)
        data['eru_lon'] = float(lon)
        data['eru_received_at'] = time.time()
        data['eru_fix_id'] = 'eru_injected'
        changes.append(f'ERU ({lat}, {lon})')

    # MRA Phase 1 refined loiter target
    if args.mra_refined:
        lat, lon = args.mra_refined
        data['mra_refined_lat'] = float(lat)
        data['mra_refined_lon'] = float(lon)
        data['mra_refined_confidence'] = 50.0  # 50m spread (simulated)
        data['mra_refined_fix_id'] = 'mra_refined_injected'
        changes.append(f'MRA refined ({lat}, {lon})')

    # MRA Phase 2 final estimated location
    if args.mra_final:
        lat, lon = args.mra_final
        data['mra_final_lat'] = float(lat)
        data['mra_final_lon'] = float(lon)
        data['mra_final_confidence'] = 20.0  # 20m spread (simulated)
        data['mra_final_fix_id'] = 'mra_final_injected'
        changes.append(f'MRA final ({lat}, {lon})')

    if not changes:
        print('[injector] No fields selected. Use --help for options.')
        print('[injector] Quick start: python3 telemetry_injector.py --all')
        return False

    atomic_write(data)
    print(f'[injector] Wrote to {TELEMETRY_PATH}: {", ".join(changes)}')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='GCS Simulator — inject test data into /tmp/telemetry.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--search-area', action='store_true',
                        help='Inject default CPP search area polygon (zone_id=1)')
    parser.add_argument('--eru', nargs='*', type=float, metavar=('LAT', 'LON'),
                        help='Inject ERU patient location (default: CPP field center)')
    parser.add_argument('--mra-refined', nargs=2, type=float, metavar=('LAT', 'LON'),
                        help='Inject MRA Phase 1 refined loiter target')
    parser.add_argument('--mra-final', nargs=2, type=float, metavar=('LAT', 'LON'),
                        help='Inject MRA Phase 2 final estimated location')
    parser.add_argument('--all', action='store_true',
                        help='Inject search area + ERU (full Demo Day sim)')
    parser.add_argument('--loop', type=int, default=0, metavar='SECONDS',
                        help='Re-inject every N seconds (survives translator restarts)')

    args = parser.parse_args()

    # If no flags provided, show help
    if not (args.search_area or args.eru is not None or args.mra_refined
            or args.mra_final or args.all):
        parser.print_help()
        print('\n[injector] Example: python3 telemetry_injector.py --all')
        sys.exit(0)

    if args.loop > 0:
        print(f'[injector] Continuous mode — re-injecting every {args.loop}s. Ctrl+C to stop.')
        while True:
            inject(args)
            time.sleep(args.loop)
    else:
        inject(args)
        print('[injector] Done. gcs_bridge.py should pick this up within ~1 second.')


if __name__ == '__main__':
    main()
