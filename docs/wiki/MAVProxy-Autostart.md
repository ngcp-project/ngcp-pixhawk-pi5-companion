# MAVProxy Autostart (Pi 5 Desktop Validation)

This page documents the helper scripts in this repository that open a terminal at desktop login and
run MAVProxy for a quick, visual confirmation that MAVLink UART telemetry is flowing between the
Pixhawk and the Raspberry Pi 5.

## What the scripts do

There are two primary helpers:

- `ngcp-mavproxy-telemetry` runs MAVProxy against the configured UART device and baud rate.
- `ngcp-mavproxy-autostart` chooses a terminal emulator and launches the telemetry script.

A third helper (`install-mavproxy-autostart.sh`) installs both scripts into `~/.local/bin` and
creates the desktop autostart entry at `~/.config/autostart/ngcp-mavproxy.desktop`.

## Installation (one-time)

From the repo root:

```bash
./scripts/install-mavproxy-autostart.sh
```

This writes:

- `~/.local/bin/ngcp-mavproxy-telemetry`
- `~/.local/bin/ngcp-mavproxy-autostart`
- `~/.config/autostart/ngcp-mavproxy.desktop`

## Install MAVProxy (Ubuntu 24.04)

Ubuntu 24.04 does not ship a `mavproxy` package in the default repositories. Use one of the
Python-based installation methods below.

### Recommended: pipx

```bash
sudo apt update
sudo apt install -y pipx
pipx ensurepath
pipx install MAVProxy
```

### Alternative: pip (user install)

```bash
sudo apt update
sudo apt install -y python3-pip
pip3 install --user MAVProxy
```

Ensure `~/.local/bin` is on your PATH if you use the pip method.

## How it runs on boot

- When the GNOME desktop session logs in, the autostart entry launches
  `ngcp-mavproxy-autostart`.
- The autostart helper opens a terminal and executes `ngcp-mavproxy-telemetry`.
- MAVProxy prints live MAVLink output in that terminal window for visual confirmation.

## SSH usage (no GUI required)

If you are SSH'ed into the Pi, you can run the telemetry helper directly for immediate
feedback:

```bash
~/.local/bin/ngcp-mavproxy-telemetry
```

The GUI autostart only triggers when someone logs into the desktop session.

## Configuration overrides

Set any of these environment variables before running:

```bash
export MAVPROXY_MASTER=/dev/ttyAMA0
export MAVPROXY_BAUD=57600
export MAVPROXY_EXTRA_ARGS="--map --aircraft test"
export TERMINAL_EMULATOR=gnome-terminal
```

- `MAVPROXY_MASTER` and `MAVPROXY_BAUD` control the UART device and baud rate.
- `MAVPROXY_EXTRA_ARGS` adds extra MAVProxy flags (space-separated).
- `TERMINAL_EMULATOR` forces a specific terminal emulator.

## Troubleshooting

- **"mavproxy.py not found"**: Install MAVProxy using pipx or pip as noted above.
- **No terminal appears on boot**: Ensure a user logs into the GNOME desktop session and that
  `~/.config/autostart/ngcp-mavproxy.desktop` exists.
- **No MAVLink data**: Verify the Pixhawk UART wiring and parameters, and confirm the Pi UART
  device is `/dev/ttyAMA0`.
