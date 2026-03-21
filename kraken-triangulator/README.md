# KrakenSDR Bearing Verification Web App

A **laptop-side** web application for verifying KrakenSDR bearing estimates and performing signal-source triangulation. Inspired by the official KrakenSDR Android app.

> **Runs on the commander laptop — not the Raspberry Pi 5.**  
> This sub-project is self-contained and has no runtime dependency on the Pi-side GCS pipeline.

---

## What This Does

1. **Ingests bearing estimates** from KrakenSDR receivers (mock data in dev, live data via Pi 5 later).
2. **Triangulates** the signal source position using the Least Squares Angle-of-Arrival (LS-AoA) method from multiple receiver stations.
3. **Displays** results on an interactive GPS map (Leaflet.js), a bearing confidence heatmap, and a live bearing log.

---

## Directory Structure

```
kraken-triangulator/
├── README.md                  # This file
├── requirements.txt           # Python backend dependencies
├── server/
│   └── kraken_server.py       # Flask dev server (mock API, later: KrakenSDR proxy)
├── data/
│   └── mock_bearings.json     # Static development fixture (2 stations, mock bearings)
└── app/
    ├── index.html             # SPA shell (Map, Heatmap, Log, Settings tabs)
    ├── style.css              # Dark mode, premium aesthetic
    └── js/
        ├── main.js            # App init and tab routing
        ├── map.js             # Leaflet GPS map + bearing line overlays
        ├── heatmap.js         # Leaflet.heat bearing accumulation heatmap
        ├── triangulation.js   # LS-AoA triangulation math
        └── data_feed.js       # Polling from /api/bearings endpoint
```

---

## Quick Start

### Prerequisites
- Python 3.8+
- A modern browser (Chrome, Firefox, Edge)

### 1. Install backend dependencies
```bash
cd kraken-triangulator
pip install -r requirements.txt
```

### 2. Run the dev server
```bash
python server/kraken_server.py
```

The server starts on **http://localhost:5050**. Open that URL in your laptop browser.

### 3. Open the app
```
http://localhost:5050
```

You should see the map with two mock stations, bearing lines, and a triangulation estimate marker.

---

## Connecting to a Live KrakenSDR (Future)

When the Pi 5 KrakenSDR integration is ready:

1. Set the `KRAKEN_API_URL` environment variable to point at the Pi's KrakenSDR HTTP API endpoint:
   ```bash
   KRAKEN_API_URL=http://<pi5-tailscale-ip>:8080 python server/kraken_server.py
   ```
2. No changes to the frontend are needed — `data_feed.js` always polls `localhost:5050/api/bearings`.

---

## Relationship to the Main Pipeline

| Component | Location | Runs On |
|---|---|---|
| GCS Telemetry Pipeline | `scripts/` | Raspberry Pi 5 |
| Pi-side GUI Monitor | `web/` | Raspberry Pi 5 |
| **KrakenSDR Triangulator** | **`kraken-triangulator/`** | **Commander Laptop** |

---

## Planned Features
- [ ] Live KrakenSDR HTTP API proxy
- [ ] Multi-station selector (add/remove stations at runtime)
- [ ] Export triangulation session to GeoJSON
- [ ] UAV telemetry overlay (lat/lon from `gcs_translator.py`)
- [ ] Uncertainty ellipse visualization
- [ ] Unit tests for `triangulation.js` math
