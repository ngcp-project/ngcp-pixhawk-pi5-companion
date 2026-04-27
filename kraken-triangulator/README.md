# KrakenSDR Triangulator Web App

A professional **laptop-side** web application designed for verifying KrakenSDR bearing estimates and performing advanced signal-source triangulation. This tooling is built specifically for Commander laptops during NGCP UAV signal-hunting operations.

> **Note:** This runs on the ground station laptop — not the Raspberry Pi 5. It is self-contained and operates independently of the Pi-side GCS telemetry pipeline.

---

## What This Does

1. **Ingests Bearing Estimates:** Receives live data from KrakenSDR receiver networks or replays localized historical `.json` files.
2. **Advanced Triangulation Math:** Computes the estimated target origin using two distinct mathematical modes:
   - **Bayesian Spatial Heatmap:** A probability-density field generated from accumulated intersection uncertainties.
   - **Least Squares Angle-of-Arrival (LS-AoA):** A rigid matrix-solver designed for clean, intersecting geometries.
3. **Interactive Spatial Filtering:** Features UI-driven spatial masking tools ("Draw Area" and "Draw Polygon") to dynamically filter out rogue bearings, reflections, or corrupted data physically tracking outside a designated zone.
4. **Professional GUI:** Displays real-time results on an interactive map (Leaflet.js) sporting a dark, premium, utilitarian aesthetic with Playback console controls, a bearing log, and customizable mapping layers.

---

## Quick Start Guide

Follow these step-by-step commands to get the application running on your local machine using the built-in playback data environment.

### 1. Clone the Repository
Open your terminal or command prompt and clone the main project repository:
```bash
git clone https://github.com/JanPastor/NGCP-Kraken-Triangulator-App.git
cd NGCP-Kraken-Triangulator-App/kraken-triangulator
```

### 2. Install Backend Dependencies
The application relies on a lightweight Python server (Flask) to handle spatial mathematics and serve the frontend interface. You need Python 3.8+ installed.
```bash
pip install -r requirements.txt
```

### 3. Start the Application Server
Run the Python backend server. By default, it will automatically load a dense, pre-recorded mock dataset (`data/bearings_20260313_154333.json`) so you can test the triangulation math immediately.
```bash
python server/kraken_server.py
```
*The server will boot up and bind to **http://localhost:5050**.*

### 4. Open the Web App
Open any modern web browser (Chrome, Firefox, Edge) and navigate to:
```url
http://localhost:5050
```
You are now in the app! Use the **Data Playback** console at the top to hit **Play (▶)** and watch the historical triangulation happen in real-time.

---

## Directory Structure
```text
kraken-triangulator/
├── README.md                  # This file
├── requirements.txt           # Python backend dependencies
├── server/
│   └── kraken_server.py       # Flask backend & math/playback engine
├── data/
│   └── bearings_*.json        # Pre-recorded JSON telemetry for playback testing
└── app/
    ├── index.html             # The main Single Page Application GUI
    ├── style.css              # Dark mode styling and CSS definitions
    └── js/
        ├── main.js            # App initialization, settings, and playback state
        ├── map.js             # Leaflet GPS map, heatmap, and custom overlays
        ├── triangulation.js   # Core LS-AoA / Bayesian solvers & Spatial Filtering
        └── data_feed.js       # Asynchronous data polling from the Python backend
```

---

## Live Hardware Integration

When you are ready to connect a live KrakenSDR unit instead of using Playback data, invoke the server by passing the Kraken's API URL as an environment variable:

**Linux / Mac:**
```bash
KRAKEN_API_URL=http://<kraken-ip-address>:8080 python server/kraken_server.py
```

**Windows (PowerShell):**
```powershell
$env:KRAKEN_API_URL="http://<kraken-ip-address>:8080"
python server/kraken_server.py
```


---

## Packaging as a Standalone Executable

The app can be packaged into a standalone Windows `.exe` so GCS operators can install and run it with **zero Python setup**.

### Prerequisites (Build Machine Only)

- Python 3.8+ with pip
- [Inno Setup 6](https://jrsoftware.org/isdl.php) — only for creating the installer (optional)

### One-Click Build

```powershell
# Full build: executable + portable ZIP + installer
.\build.ps1

# Without installer (no Inno Setup needed)
.\build.ps1 -SkipInstaller
```

### What Gets Produced

| Artifact | Location | Description |
|----------|----------|-------------|
| Executable folder | `dist/KrakenSDR-Triangulator/` | Run `KrakenSDR-Triangulator.exe` directly |
| Portable ZIP | `dist/KrakenSDR-Triangulator-v1.7.0-portable.zip` | Extract anywhere and run |
| Windows Installer | `Output/KrakenSDR-Triangulator-Setup-v1.7.0.exe` | Professional setup wizard with shortcuts |

### GCS Operator Installation

1. Receive the `.exe` installer (or `.zip` for portable use)
2. Run the installer → **Next → Next → Install**
3. Launch from the **Desktop shortcut** or Start Menu
4. The app opens automatically in your default browser at `http://localhost:5050`

> **Note:** The console window stays visible intentionally — it shows server logs, UDP telemetry status, and MAVLink connection state, which are useful during field operations.

---

## Updating the Executable

When you make changes to the app (new features, bug fixes, etc.), rebuilding the executable is straightforward:

### Quick Update Workflow

```powershell
# 1. Make your code changes (edit server/kraken_server.py, app/js/*.js, etc.)

# 2. Rebuild (takes ~30-60 seconds)
.\build.ps1

# 3. Distribute the new installer or ZIP to operators
```

### What Triggers a Rebuild

| Change Type | Rebuild Required? | Notes |
|-------------|-------------------|-------|
| Python backend (`server/*.py`) | **Yes** | Run `.\build.ps1` |
| Frontend (`app/*.html`, `app/js/*.js`, `app/style.css`) | **Yes** | Run `.\build.ps1` |
| Vendored libraries (`app/vendor/*`) | **Yes** | Only if upgrading Leaflet, Turf, etc. |
| Sample data (`data/*.json`) | **Yes** | Only if bundled data changes |
| Configuration (env vars, ports) | **No** | These are set at runtime, not baked in |

### Version Bumping

Update the version in three places:
1. `app/index.html` → About section (`v1.7.0`)
2. `installer.iss` → `#define MyAppVersion`
3. `build.ps1` → `$Version` variable

---

## License

This is Free and Open Source Software (FOSS) developed for the **Northrop Grumman Collaboration Project** (NGCP). 
It is distributed under the [MIT License](LICENSE).
