import sys
import os
import time
import json
import serial.tools.list_ports

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

def get_xbee_port():
    """Get the XBee COM port from args, or default to COM5."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return "COM5"

def main():
    print("==================================================")
    print("    GCS XBee Telemetry Receiver (Console)         ")
    print("==================================================")

    port = get_xbee_port()
    print(f"[*] Attempting to launch GCS XBee on {port}...")

    # Set the MAC address of the drone's XBee (Transmitter) so we can theoretically send commands back
    PacketLibrary.SetVehicleMACAddress(Vehicle.MRA, "0013A20042981E9B")
    
    try:
        LaunchGCSXBee(port)
        print("[*] XBee launched successfully! Listening for telemetry...\n")
    except Exception as e:
        print(f"[!] Failed to launch XBee on {port}: {e}")
        print("    -> Make sure XCTU is closed so it doesn't lock the COM port!")
        sys.exit(1)

    while True:
        try:
            # Blocks until telemetry is popped from the queue
            telemetry = ReceiveTelemetry()
            
            if telemetry:
                print(f"[{time.strftime('%H:%M:%S')}] TELEMETRY DECODED:")
                print(f"  Drone Pos:   Lat {telemetry.CurrentPositionX:.6f} | Lon {telemetry.CurrentPositionY:.6f} | Alt {telemetry.Altitude:.1f}ft")
                print(f"  Target Pos:  Lat {telemetry.MessageLat:.6f} | Lon {telemetry.MessageLon:.6f} | Flag {telemetry.MessageFlag}")
                print("-" * 50)
                
                # Write to the local temp file so the local gui_server.py can visualize it!
                try:
                    state_dump = {
                        "pitch": telemetry.Pitch,
                        "roll": telemetry.Roll,
                        "yaw": telemetry.Yaw,
                        "lat": telemetry.CurrentPositionX,
                        "lon": telemetry.CurrentPositionY,
                        "alt": telemetry.Altitude,
                        "speed": telemetry.Speed,
                        "battery": getattr(telemetry, 'BatteryLife', 0.0),
                        "message_flag": telemetry.MessageFlag,
                        "target_lat": telemetry.MessageLat,
                        "target_lon": telemetry.MessageLon,
                        "last_updated": time.time() * 1000
                    }
                    temp_dir = os.environ.get('TEMP', 'C:\\Temp')
                    target_file = os.path.join(temp_dir, 'telemetry.json')
                    with open(target_file, 'w') as f:
                        json.dump(state_dump, f)
                except Exception as e:
                    pass # Silently fail the UI file dump if it occurs

        except KeyboardInterrupt:
            print("\n[*] Exiting gracefully...")
            break
        except Exception as e:
            print(f"[!] Error receiving telemetry: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
