#!/usr/bin/env python3
"""
convert_fused_jsonl_to_bearings.py

Converts an already-fused JSONL log into the JSON format expected by
mock_fusion_downstream.py:

{
  "run_id": "...",
  "frequency_hz": ...,
  "mode": "single_mobile_kraken",
  "doa_method": "...",
  "waypoint_sequence": [
    {
      "id": "...",
      "label": "...",
      "lat": ...,
      "lon": ...,
      "bearing_deg": ...,
      "confidence": ...
    }
  ]
}

Usage:
    python3 convert_fused_jsonl_to_bearings.py input.jsonl
    python3 convert_fused_jsonl_to_bearings.py input.jsonl -o bearings_20260417_115945.json
"""

import argparse
import json
from pathlib import Path

FREQUENCY_HZ = 462_637_500
DEFAULT_MODE = "single_mobile_kraken"
DEFAULT_DOA_METHOD = "MUSIC"


def doa_to_compass(doa_deg: float, yaw_deg: float) -> float:
    """
    Convert Kraken/unit-circle style DOA into compass bearing using vehicle yaw.
    Same convention used in your earlier converter:
        absolute_bearing = (heading - doa + 360) % 360
    """
    return (yaw_deg - doa_deg + 360.0) % 360.0


def normalize_confidence(confidence_raw: float) -> float:
    """
    Match the style used in convert_logs.py:
    clamp raw confidence into 0.0–1.0 by dividing by 5.
    """
    return round(min(max(confidence_raw / 5.0, 0.0), 1.0), 3)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] Skipping bad JSON on line {lineno}: {e}")
    return rows


def convert_records(records: list[dict]) -> tuple[str, list[dict]]:
    if not records:
        raise ValueError("No records found.")

    run_id = records[0].get("run_id", "unknown_run")
    waypoints = []

    for idx, r in enumerate(records):
        lat = r.get("lat_deg")
        lon = r.get("lon_deg")
        doa_deg = r.get("doa_deg")
        yaw_deg = r.get("yaw_deg")
        confidence_raw = r.get("confidence_0_1")
        t_rx_ms = r.get("t_rx_ms")

        if lat is None or lon is None or doa_deg is None or yaw_deg is None or confidence_raw is None:
            continue

        bearing_deg = round(doa_to_compass(doa_deg, yaw_deg), 2)
        confidence = normalize_confidence(confidence_raw)

        waypoints.append({
            "id": f"obs-{idx:04d}",
            "label": f"Obs {idx:04d} | t={t_rx_ms} | yaw={round(yaw_deg, 1)}°",
            "lat": lat,
            "lon": lon,
            "bearing_deg": bearing_deg,
            "confidence": confidence,

            # keep helpful debug fields too
            "doa_deg_raw": doa_deg,
            "heading_used_deg": round(yaw_deg, 2),
            "roll_deg": r.get("roll_deg"),
            "ground_speed_ft_s": r.get("ground_speed_ft_s"),
            "altitude_rel_ft": r.get("altitude_rel_ft"),
            "dt_ms": r.get("dt_ms"),
            "t_rx_ms": t_rx_ms,
            "usable_for_triangulation": r.get("usable_for_triangulation"),
        })

    return run_id, waypoints


def main():
    parser = argparse.ArgumentParser(description="Convert fused JSONL log to mock_fusion_downstream bearings JSON.")
    parser.add_argument("input", help="Path to fused JSONL input file")
    parser.add_argument("-o", "--out", help="Output JSON path")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    records = load_jsonl(input_path)
    run_id, waypoints = convert_records(records)

    if not waypoints:
        raise ValueError("No valid waypoints produced from input file.")

    output = {
        "_comment": f"Converted from fused JSONL: {input_path.name}",
        "frequency_hz": FREQUENCY_HZ,
        "mode": DEFAULT_MODE,
        "doa_method": DEFAULT_DOA_METHOD,
        "run_id": run_id,
        "waypoint_sequence": waypoints,
    }

    if args.out:
        out_path = Path(args.out).resolve()
    else:
        out_path = input_path.with_name(f"bearings_{run_id}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(waypoints)} waypoints to {out_path}")


if __name__ == "__main__":
    main()