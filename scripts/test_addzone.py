#!/usr/bin/env python3
"""Test script for AddZone packet encoding/decoding.

This script exercises the same AddZone payload structure used by
scripts/gcs_translator.py when it receives a GCS AddZone command.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Make lib/gcs-packet importable even if it is not installed in the env.
# The AddZone packet module uses top-level imports like `from Command.CommandInterface import CommandInterface`
# and `from Enum import *`, so we need the Packet package root and the Packet subdirectory.
sys.path.insert(0, str(REPO_ROOT / 'lib' / 'gcs-packet'))
sys.path.insert(0, str(REPO_ROOT / 'lib' / 'gcs-packet' / 'Packet'))
sys.path.insert(0, str(REPO_ROOT))

try:
    from Packet.Command.AddZone import AddZone
    from Enum import DecodeFormat, ZoneType
except ImportError as exc:
    print('ERROR: Failed to import AddZone packet classes:', exc)
    print('Ensure lib/gcs-packet is installed or available on PYTHONPATH.')
    sys.exit(1)


def format_payload_bytes(payload: bytes) -> str:
    return ' '.join(f'{b:02x}' for b in payload)


def describe_payload(payload: bytes) -> str:
    header = payload[:8]
    command_id = header[0]
    packet_id = int.from_bytes(header[1:5], byteorder='little')
    zone = int.from_bytes(header[5:7], byteorder='little')
    zone_id = header[7]
    coords = []
    for i in range(8, len(payload), 16):
        chunk = payload[i:i + 16]
        if len(chunk) < 16:
            break
        lat = int.from_bytes(chunk[:8], byteorder='little', signed=False)
        lon = int.from_bytes(chunk[8:], byteorder='little', signed=False)
        coords.append((lat, lon))
    return (
        f'Command ID: {command_id}\n'
        f'Packet ID: {packet_id}\n'
        f'Zone: {zone}\n'
        f'Zone ID: {zone_id}\n'
        f'Coordinate pairs: {len(coords)}\n'
        'Note: raw decode of doubles is not shown here; use AddZone.DecodePacket() for semantic output.'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Test AddZone packet encoding and decoding.')
    parser.add_argument('--zone', default='KeepIn', help='Zone type: KeepIn, KeepOut, SearchArea')
    parser.add_argument('--points', type=int, default=4, help='Number of polygon points (3-6)')
    args = parser.parse_args()

    coordinates = [
        (37.4275, -122.1697),
        (37.4275, -122.1650),
        (37.4240, -122.1650),
        (37.4240, -122.1697),
        (37.4257, -122.1720),
        (37.4265, -122.1710),
    ]
    if args.points < 3 or args.points > 6:
        raise SystemExit('AddZone supports 3 to 6 coordinates in this packet format.')

    zone_type = getattr(ZoneType, args.zone, None)
    if zone_type is None:
        raise SystemExit(f'Unknown zone type: {args.zone}')

    payload_coordinates = coordinates[: args.points]
    command = AddZone(zone_type, payload_coordinates)

    payload = command.EncodePacket()
    print('=== AddZone Packet Test ===')
    print(f'Zone type: {zone_type.name} ({zone_type.value})')
    print(f'Coordinate count: {len(payload_coordinates)}')
    print(f'Payload length: {len(payload)} bytes')
    print(f'Payload bytes: {format_payload_bytes(payload)}\n')

    try:
        decoded = AddZone.DecodePacket(payload, DecodeFormat.Class)
        if decoded is None:
            raise ValueError('DecodePacket returned None')
        print('Decoded AddZone object:')
        print(f'  Command ID: {decoded.COMMAND_ID if hasattr(decoded, "COMMAND_ID") else "n/a"}')
        print(f'  Packet ID: {decoded.PacketID}')
        print(f'  Zone: {decoded.Zone} ({getattr(decoded.Zone, "value", decoded.Zone)})')
        print(f'  Zone ID: {decoded.ZoneID}')
        print(f'  Coordinates: {decoded.Coordinates}')
    except Exception as exc:
        print('AddZone.DecodePacket failed:', exc)
        json_out = AddZone.DecodePacket(payload, DecodeFormat.JSON)
        print('DecodeFormat.JSON output:')
        print(json_out)

    max_points = (72 - 8) // 16
    print(f'\nMax points allowed by 72-byte payload limit: {max_points}')


if __name__ == '__main__':
    main()
