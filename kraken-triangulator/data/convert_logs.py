#!/usr/bin/env python3
"""
convert_logs.py — KrakenSDR Log Fusion & Converter
====================================================
Fuses a raw KrakenSDR DOA bearing log (doa_*.jsonl) with a paired telemetry
log (telemetry_*.jsonl) and converts the result into the kraken_server.py
`mock_bearings.json` format for use in the triangulator web app.

The DOA files from real hardware sessions have lat_deg=0 / lon_deg=0 because
the KrakenSDR's internal GPS was inactive. This script substitutes the UAV's
GPS position from the paired telemetry log (aligned by timestamp).

Usage:
    # Auto-detect the best telemetry match for a DOA file:
    python data/convert_logs.py --doa data/raw_logs/doa_20260313_154333.jsonl

    # Specify telemetry file explicitly:
    python data/convert_logs.py \\
        --doa  data/raw_logs/doa_20260313_154333.jsonl \\
        --tel  data/telemetry_logs/telemetry_20260313_154342_20260313_155502.jsonl

    # Override output path:
    python data/convert_logs.py --doa data/raw_logs/doa_20260313_154333.jsonl \\
        --out data/bearings_20260313.json

Output is saved as: data/bearings_<run_id>.json
    (or to --out path)
"""

import argparse
import bisect
import json
import sys
from pathlib import Path

# ── Quality filters (matches fusion_logger.py defaults) ──────────────────────
MAX_TIME_DIFF_MS      = 250     # Max ms difference between DOA and telemetry timestamps
MIN_CONFIDENCE        = 0.4     # Kraken confidence_0_1 threshold (raw value, not %)
MAX_ROLL_DEG          = 30.0    # Max roll angle — discard banked samples
MIN_GROUND_SPEED_FT_S = 3.0     # Min ground speed — discard near-hover samples
MAX_WAYPOINTS         = 500     # Cap output size for web app performance

FREQUENCY_HZ = 462_637_500      # Default assumed frequency (update if known)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] {path.name}:{lineno} — skipping bad JSON: {e}")
    return records


def build_ts_index(records: list[dict]) -> list[int]:
    return [r["t_rx_ms"] for r in records]


def find_nearest(timestamps: list[int], target: int) -> int:
    n = len(timestamps)
    if n == 0:
        raise ValueError("Empty timestamp list")
    pos = bisect.bisect_left(timestamps, target)
    if pos == 0:
        return 0
    if pos == n:
        return n - 1
    before, after = pos - 1, pos
    return before if abs(timestamps[before] - target) <= abs(timestamps[after] - target) else after


def doa_to_compass(doa_deg: float, gps_heading_deg: float) -> float:
    """
    The KrakenSDR outputs DOA in unit-circle convention (0°=East, CCW positive).
    Convert to a compass bearing (0°=North, CW positive) using the vehicle heading.
    
    absolute_bearing = (gps_heading_deg - doa_deg + 360) % 360
    
    Note: if gps_heading_deg from the KrakenSDR is 0 (GPS inactive), 
    the vehicle heading from the telemetry yaw_deg is used instead.
    """
    return (gps_heading_deg - doa_deg + 360.0) % 360.0


def auto_find_telemetry(doa_path: Path, tel_dir: Path) -> Path | None:
    """Find the best matching telemetry file by overlapping run_id timestamp."""
    doa_ts_str = doa_path.stem.replace("doa_", "")  # e.g. "20260313_154333"
    doa_date = doa_ts_str[:8]                         # "20260313"
    candidates = sorted(tel_dir.glob(f"telemetry_{doa_date}_*.jsonl"))
    return candidates[0] if candidates else None


# ── Main ──────────────────────────────────────────────────────────────────────

def convert(doa_path: Path, tel_path: Path, out_path: Path):
    print(f"\n[convert_logs] DOA file  : {doa_path.name}")
    print(f"[convert_logs] Telemetry : {tel_path.name}")

    doa_records = load_jsonl(doa_path)
    tel_records = load_jsonl(tel_path)

    print(f"  DOA records loaded      : {len(doa_records)}")
    print(f"  Telemetry records loaded: {len(tel_records)}")

    if not doa_records:
        print("[ERROR] DOA log is empty. Aborting.")
        sys.exit(1)
    if not tel_records:
        print("[ERROR] Telemetry log is empty. Aborting.")
        sys.exit(1)

    tel_records.sort(key=lambda r: r["t_rx_ms"])
    tel_timestamps = build_ts_index(tel_records)

    waypoints = []
    n_skipped_dt = 0
    n_skipped_qual = 0
    seq = 0

    for k in doa_records:
        k_ts = k["t_rx_ms"]
        idx = find_nearest(tel_timestamps, k_ts)
        t = tel_records[idx]
        dt_ms = t["t_rx_ms"] - k_ts

        # Time-sync gate
        if abs(dt_ms) > MAX_TIME_DIFF_MS:
            n_skipped_dt += 1
            continue

        confidence   = k.get("confidence_0_1")
        roll         = t.get("roll_deg")
        ground_speed = t.get("ground_speed_ft_s")
        lat          = t.get("lat_deg")
        lon          = t.get("lon_deg")
        doa_deg      = k.get("doa_deg")
        yaw_deg      = t.get("yaw_deg", 0.0)

        # Quality gate
        if confidence is None or confidence < MIN_CONFIDENCE:
            n_skipped_qual += 1
            continue
        if roll is None or abs(roll) > MAX_ROLL_DEG:
            n_skipped_qual += 1
            continue
        if ground_speed is None or ground_speed < MIN_GROUND_SPEED_FT_S:
            n_skipped_qual += 1
            continue
        if lat is None or lon is None or doa_deg is None:
            n_skipped_qual += 1
            continue

        # Use KrakenSDR GPS heading if available, otherwise use telemetry yaw
        kraken_heading = k.get("gps_heading_deg", 0.0) or 0.0
        heading = kraken_heading if kraken_heading != 0.0 else yaw_deg

        compass_bearing = doa_to_compass(doa_deg, heading)
        # Normalize confidence from raw ~0–5 scale to 0.0–1.0 for display
        confidence_norm = round(min(confidence / 5.0, 1.0), 3)

        waypoints.append({
            "id":          f"obs-{seq:04d}",
            "label":       f"Obs {seq:04d} | t={k_ts} | yaw={round(yaw_deg, 1)}°",
            "lat":         lat,
            "lon":         lon,
            "bearing_deg": round(compass_bearing, 2),
            "confidence":  confidence_norm,
            # Extra fields for debugging / future use
            "doa_deg_raw":       doa_deg,
            "heading_used_deg":  round(heading, 2),
            "roll_deg":          roll,
            "ground_speed_ft_s": ground_speed,
            "altitude_rel_ft":   t.get("altitude_rel_ft"),
            "dt_ms":             dt_ms,
            "t_rx_ms":           k_ts,
        })
        seq += 1

        if len(waypoints) >= MAX_WAYPOINTS:
            print(f"  [INFO] Capped at {MAX_WAYPOINTS} waypoints. Reduce MAX_WAYPOINTS or filter more aggressively.")
            break

    print(f"\n  Skipped (dt too large) : {n_skipped_dt}")
    print(f"  Skipped (quality gate) : {n_skipped_qual}")
    print(f"  Waypoints kept         : {len(waypoints)}")

    if not waypoints:
        print("[ERROR] No usable waypoints after filtering. Check quality thresholds.")
        sys.exit(1)

    run_id = doa_path.stem.replace("doa_", "")

    output = {
        "_comment":        f"Fused from {doa_path.name} + {tel_path.name}. Generated by convert_logs.py.",
        "frequency_hz":    FREQUENCY_HZ,
        "mode":            "single_mobile_kraken",
        "doa_method":      "MUSIC",
        "run_id":          run_id,
        "waypoint_sequence": waypoints,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n[convert_logs] ✓ Wrote {len(waypoints)} waypoints → {out_path}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Fuse KrakenSDR DOA log + telemetry log → kraken_server-compatible JSON"
    )
    parser.add_argument("--doa", required=True,
                        help="Path to doa_*.jsonl bearing log file")
    parser.add_argument("--tel", default=None,
                        help="Path to telemetry_*.jsonl file (auto-detected if omitted)")
    parser.add_argument("--out", default=None,
                        help="Output JSON path (default: data/bearings_<run_id>.json)")
    parser.add_argument("--max-waypoints", type=int, default=MAX_WAYPOINTS,
                        help=f"Max output waypoints (default: {MAX_WAYPOINTS})")
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE,
                        help=f"Min confidence_0_1 threshold (default: {MIN_CONFIDENCE})")
    args = parser.parse_args()

    doa_path = Path(args.doa).resolve()
    if not doa_path.exists():
        print(f"[ERROR] DOA file not found: {doa_path}")
        sys.exit(1)

    # Auto-detect telemetry file if not provided
    if args.tel:
        tel_path = Path(args.tel).resolve()
    else:
        tel_dir = doa_path.parent.parent / "telemetry_logs"
        tel_path = auto_find_telemetry(doa_path, tel_dir)
        if not tel_path:
            print(f"[ERROR] Could not auto-detect telemetry file in {tel_dir}. Use --tel.")
            sys.exit(1)
        print(f"[convert_logs] Auto-detected telemetry: {tel_path.name}")

    if not tel_path.exists():
        print(f"[ERROR] Telemetry file not found: {tel_path}")
        sys.exit(1)

    run_id = doa_path.stem.replace("doa_", "")
    out_path = Path(args.out).resolve() if args.out else (doa_path.parent.parent / f"bearings_{run_id}.json")

    convert(doa_path, tel_path, out_path)


if __name__ == "__main__":
    main()
