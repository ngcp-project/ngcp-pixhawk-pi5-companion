import sys
import os
import time
import json

# Add necessary paths to import gcs-infrastructure
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(BASE_DIR, 'gcs-infrastructure', 'Application'))
sys.path.append(os.path.join(BASE_DIR, 'gcs-infrastructure', 'lib', 'gcs-packet'))
sys.path.append(os.path.join(BASE_DIR, 'gcs-infrastructure', 'lib', 'gcs-packet', 'Packet'))
sys.path.append(os.path.join(BASE_DIR, 'gcs-infrastructure', 'lib', 'xbee-python', 'src'))

try:
    from Infrastructure.InfrastructureInterface import LaunchGCSXBee, ReceiveTelemetry
    from PacketLibrary.PacketLibrary import PacketLibrary
    from Enum import Vehicle
except ImportError as e:
    print(f"ERROR: Failed to import gcs-infrastructure modules: {e}")
    sys.exit(1)

# ── Label mappings ─────────────────────────────────────────────────────────────

VEHICLE_STATUS_LABELS = {0: "NOT READY", 1: "ACTIVE (Nominal)"}
MESSAGE_FLAG_LABELS   = {0: "None", 1: "Package Location", 2: "Patient Location"}
PATIENT_STATUS_LABELS = {0: "Unknown", 1: "Stable", 2: "Critical"}

def vehicle_status_str(v):
    return VEHICLE_STATUS_LABELS.get(v, f"Unknown ({v})")

def message_flag_str(f):
    return MESSAGE_FLAG_LABELS.get(f, f"Unknown ({f})")

def patient_status_str(p):
    return PATIENT_STATUS_LABELS.get(p, f"Unknown ({p})")

def last_updated_str(ms):
    """Convert epoch-ms to a human-readable local time string."""
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ms / 1000.0))
    except Exception:
        return str(ms)

# ── Pretty printer ─────────────────────────────────────────────────────────────

def print_telemetry(t, packet_count):
    W  = 54           # inner width (between ║ chars)
    ts = time.strftime('%H:%M:%S')

    def row(label, value, unit=""):
        """Format one data row padded to fit the box."""
        cell = f"{value}{(' ' + unit) if unit else ''}"
        return f"║    {label:<14}: {cell:<{W - 19}}║"

    print()
    print("╔" + "═" * W + "╗")
    print(f"║  GCS TELEMETRY  #{packet_count:<6}           [{ts}]  ║")
    print("╠" + "═" * W + "╣")

    # ── Identity ──────────────────────────────────────────────────────────────
    print("║  IDENTITY                                            ║")
    print(row("Command ID",  t.CommandID))
    print(row("Packet ID",   t.PacketID))
    vid = getattr(t, 'Vehicle', None)
    print(row("Vehicle",     vid.name if vid else "N/A"))
    mac = getattr(t, 'MACAddress', '') or "N/A"
    print(row("MAC Address", mac))
    print("╠" + "═" * W + "╣")

    # ── Position ──────────────────────────────────────────────────────────────
    print("║  POSITION                                            ║")
    print(row("Latitude",    f"{t.CurrentPositionX:.7f}", "°"))
    print(row("Longitude",   f"{t.CurrentPositionY:.7f}", "°"))
    print(row("Altitude",    f"{t.Altitude:.2f}", "ft"))
    print("╠" + "═" * W + "╣")

    # ── Attitude ──────────────────────────────────────────────────────────────
    print("║  ATTITUDE                                            ║")
    print(row("Pitch",       f"{t.Pitch:.4f}", "°"))
    print(row("Roll",        f"{t.Roll:.4f}",  "°"))
    print(row("Yaw",         f"{t.Yaw:.4f}",   "°"))
    print("╠" + "═" * W + "╣")

    # ── Flight Data ───────────────────────────────────────────────────────────
    print("║  FLIGHT DATA                                         ║")
    print(row("Speed",       f"{t.Speed:.4f}", "fps"))
    print(row("Battery",     f"{t.BatteryLife:.2f}", "V"))
    print(row("Veh. Status", vehicle_status_str(t.VehicleStatus)))
    print(row("Last Updated",last_updated_str(t.LastUpdated)))
    print("╠" + "═" * W + "╣")

    # ── Message / Target ──────────────────────────────────────────────────────
    print("║  MESSAGE / TARGET                                    ║")
    print(row("Msg Flag",    message_flag_str(t.MessageFlag)))
    if t.MessageFlag > 0:
        print(row("Target Lat",  f"{t.MessageLat:.7f}", "°"))
        print(row("Target Lon",  f"{t.MessageLon:.7f}", "°"))
        print(row("Patient Stat",patient_status_str(t.PatientStatus)))
    else:
        print("║    (No target payload active)                        ║")

    print("╚" + "═" * W + "╝")

# ── Entry point ────────────────────────────────────────────────────────────────

def get_xbee_port():
    """Get XBee COM port from first CLI arg, or default to COM5."""
    return sys.argv[1] if len(sys.argv) > 1 else "COM5"


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║      Vehicle Telemetry Monitor  v1.9.2               ║")
    print("║      NGCP MRA — GCS Receive Endpoint (Diagnostic)    ║")
    print("╚══════════════════════════════════════════════════════╝")

    port = get_xbee_port()
    print(f"\n[*] Launching GCS XBee on {port} ...")

    # Register the MRA drone's XBee MAC so the library can route correctly
    PacketLibrary.SetVehicleMACAddress(Vehicle.MRA, "0013A20042981E9B")

    try:
        LaunchGCSXBee(port)
        print(f"[*] XBee up on {port}. Waiting for telemetry...\n")
    except Exception as e:
        print(f"[!] Failed to open {port}: {e}")
        print("    -> Make sure XCTU is closed (it locks the COM port).")
        sys.exit(1)

    packet_count = 0
    while True:
        try:
            telemetry = ReceiveTelemetry()   # blocks until a packet arrives

            if telemetry:
                packet_count += 1
                print_telemetry(telemetry, packet_count)

                # Dump full decoded state to %TEMP%/telemetry.json for local GUI
                try:
                    state_dump = {
                        "command_id":     telemetry.CommandID,
                        "packet_id":      telemetry.PacketID,
                        "lat":            telemetry.CurrentPositionX,
                        "lon":            telemetry.CurrentPositionY,
                        "alt":            telemetry.Altitude,
                        "speed":          telemetry.Speed,
                        "pitch":          telemetry.Pitch,
                        "roll":           telemetry.Roll,
                        "yaw":            telemetry.Yaw,
                        "battery":        telemetry.BatteryLife,
                        "vehicle_status": telemetry.VehicleStatus,
                        "message_flag":   telemetry.MessageFlag,
                        "target_lat":     telemetry.MessageLat,
                        "target_lon":     telemetry.MessageLon,
                        "patient_status": telemetry.PatientStatus,
                        "last_updated":   telemetry.LastUpdated,
                    }
                    temp_dir = os.environ.get('TEMP', 'C:\\Temp')
                    with open(os.path.join(temp_dir, 'telemetry.json'), 'w') as f:
                        json.dump(state_dump, f, indent=2)
                except Exception:
                    pass   # silently skip GUI file dump on error

        except KeyboardInterrupt:
            print(f"\n[*] Exiting after {packet_count} packets.")
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
