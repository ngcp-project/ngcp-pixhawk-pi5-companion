# Pi 5 Telemetry Pipeline Autostart 

This page documents how the Raspberry Pi 5 automatically bridges the **Pixhawk Flight Controller** to the **Ground Control Station (GCS) XBee Radio** immediately upon booting up.

## What happens on boot?

When the GNOME desktop session logs in, a desktop autostart entry triggers our main script suite. The pipeline flows like this:

1. **Hardware Detection:** The script automatically finds the Pixhawk UART connection (e.g., `/dev/ttyAMA0`) and the XBee USB connection (e.g., `/dev/ttyUSB0`).
2. **GCS Translator Daemon:** A background Python script (`gcs_translator.py`) launches, listening on local UDP port `14550`.
3. **MAVProxy Ingestion:** `mavproxy.py` connects to the Pixhawk, pulling in MAVLink data at 57600 baud, and broadcasts it locally to that UDP port.
4. **Translation & Transmission:** The Translator Daemon catches the MAVLink UDP data, converts it into the proprietary GCS `Telemetry` struct (68 bytes), and streams it out of the XBee radio.

*Note: A visible terminal emulator will open on the desktop displaying MAVProxy's heartbeat output so you can visually confirm the drone is connected.*

## Installation & Setup

If setting up a fresh Pi 5, follow these steps:

### 1. Install MAVProxy
Ubuntu 24.04 requires `pipx` for safe Python package installation:
```bash
sudo apt update && sudo apt install -y pipx
pipx ensurepath
pipx install MAVProxy
```

### 2. Install the Autostart Scripts
From the repo root, run the installer:
```bash
./scripts/install-mavproxy-autostart.sh
```
*This installs the helper scripts into `~/.local/bin` and creates the `~/.config/autostart/ngcp-mavproxy.desktop` entry.*

### 3. Connect Hardware
- Plug the **Pixhawk TELEM2** port into the Pi 5 GPIO UART pins (TX to RX, RX to TX, GND to GND).
- Plug the **XBee Radio** into any available USB port.

### 4. Reboot
Simply reboot the Pi 5 and log into the desktop. The terminal will open, the daemon will start, and data will flow!

## Configuration Overrides

If you need to force specific hardware ports, you can set these environment variables before running, or export them in your shell profile:

```bash
export MAVPROXY_MASTER=/dev/ttyAMA0
export MAVPROXY_BAUD=57600
export MAVPROXY_EXTRA_ARGS="--map --aircraft test"
export TERMINAL_EMULATOR=gnome-terminal
```

## Troubleshooting

- **"pymavlink not installed"**: The translator daemon uses the MAVProxy virtual environment. Ensure MAVProxy was installed via `pipx` as instructed above.
- **No MAVLink Data**: Verify the Pixhawk is configured correctly (`SERIAL2_PROTOCOL = 2`, `SERIAL2_BAUD = 57`).
- **XBee Not Transmitting**: Ensure the XBee is using a USB interface (`/dev/ttyUSB*` or `/dev/ttyACM*`). Raw GPIO serial is not supported by the auto-detector. If no XBee is found, the daemon safely falls back into "Test Mode" and prints the hex payload to its own log.
