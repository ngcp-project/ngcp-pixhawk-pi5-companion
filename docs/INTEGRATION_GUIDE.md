# Integration Guide — Connecting External Scripts to the MAVLink Bus

> **Audience:** Software Team, Autonomy Team, or any subteam whose scripts need live MAVLink data from the Pixhawk.

## What Changed (and Why)

The Pi 5 MAVLink pipeline now routes through a **publish-subscribe hub** (`mavlink_hub.py`) instead of using hardcoded static UDP ports.

### Before (old architecture)
```
Pixhawk → MAVProxy → static UDP 14550  (gcs_translator.py)
                   → static UDP 14601  (command_listener.py)   ← HARDCODED
                   → static UDP 14602  (autonomy_engine.py)    ← HARDCODED
```
Adding a new script meant editing `ngcp-mavproxy-telemetry.sh` and rebooting the Pi.

### After (current architecture)
```
Pixhawk → MAVProxy → UDP 14550 → [ mavlink_hub.py ]
                                        │ fans out to all registered clients
                                        ├── 14600  gcs_translator.py  (auto-registered)
                                        ├── 14601  command_listener.py (needs update ↓)
                                        └── 14nnn  your_script.py      (self-registers)
```
**MAVProxy only outputs to one port (the hub).** Ports 14601 and 14602 no longer receive data directly. Your scripts must self-register with the hub to receive frames.

---

## ⚠️ Action Required — Software Team Scripts

If your script was previously binding to `14601` or `14602` directly, it will now receive **no data** until updated. The fix is 4 lines.

### Step 1 — Add the registration call at startup

```python
import sys, os

# Point to the Pi 5 scripts directory (adjust path if needed)
sys.path.append('/home/ngcp25/work/ngcp-pixhawk-pi5-companion/scripts')
from mavlink_hub import register_with_hub, deregister_from_hub

# Choose any port in the 14600–14699 dynamic range
MY_PORT = 14601
register_with_hub(MY_PORT, 'command_listener.py')
```

> [!NOTE]
> `register_with_hub()` returns `True` on success and `False` if the hub is not running. It also falls back to a TCP socket on port 14555 if the Unix socket is unavailable, so it works on both Linux and Windows.

### Step 2 — Bind your UDP socket to the registered port

Your existing UDP receive code doesn't change — just make sure it's bound to the same port you registered:

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('127.0.0.1', MY_PORT))  # same as registered above

while True:
    data, _ = sock.recvfrom(512)
    # process MAVLink frame as before...
```

### Step 3 — Deregister on shutdown (optional but recommended)

```python
import atexit
atexit.register(deregister_from_hub, MY_PORT)
```

---

## Port Assignments

Reserve your port in the dynamic range below. Update this table when you claim one.

| Port  | Script                   | Team          | Status   |
|-------|--------------------------|---------------|----------|
| 14550 | Hub input (MAVProxy out) | Pi 5 / NGCP   | Reserved |
| 14600 | `gcs_translator.py`      | GCS / Pi 5    | Active   |
| 14601 | `command_listener.py`    | Software Team | ⚠️ Needs update |
| 14602 | Autonomy Engine          | Software Team | ⚠️ Needs update |
| 14603+ | *(available)*           | Any           | Free     |

---

## One-Liner Smoke Test

Run this on the Pi 5 to verify your script will receive MAVLink frames through the hub:

```bash
# Terminal 1 — check hub is running
python3 -c "
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/tmp/mavlink_hub.sock')
s.send(json.dumps({'action': 'list'}).encode())
print(s.recv(4096).decode())
"

# Terminal 2 — register and listen on port 14603
python3 -c "
import sys
sys.path.append('/home/ngcp25/work/ngcp-pixhawk-pi5-companion/scripts')
from mavlink_hub import register_with_hub
register_with_hub(14603, 'smoke_test')
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('127.0.0.1', 14603))
print('Listening on 14603...')
while True:
    d, _ = s.recvfrom(512)
    print(f'Received {len(d)} bytes')
"
```

---

## Port Monitor GUI

Active registrations are visible in the **MAVLink Port Monitor** panel in the GCS Telemetry Monitor web GUI at `http://localhost:8082`. Each registered script appears as a row with:
- 🟢 **ACTIVE** — receiving frames in the last 10 seconds
- 🔴 **SILENT** — registered but no frames received recently
- 🟡 **Pending** — registered, no frames sent yet

This lets operators see at a glance which subteam scripts are alive on the data bus.

---

## Questions?

Contact the **Pi 5 / GCS Subteam** or open an issue in this repo. See also [`TODO.md`](../TODO.md) for the current development backlog.
