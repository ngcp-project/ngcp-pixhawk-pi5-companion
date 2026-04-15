import os
import sys
import time
import subprocess
try:
    import serial.tools.list_ports
except ImportError:
    print("FATAL: 'pyserial' is not installed.")
    print("Please run: pip install pyserial")
    sys.exit(1)

# Default routing configurations
BAUD_RATE = 57600
# Target endpoints
# 14550: QGroundControl (Default)
# 14551: Kraken Triangulator / Custom Python scripts
# 14601: Software Team Pipeline (telemetry_logger, command_listener)
# 14602: (reserved)
# 14603: (reserved)
# 14604: (reserved)
# 14605: Fusion Sender (Pi 5 side — outbound chunked STATUSTEXT)
# 14606: Fusion Receiver (GCS side — reassembles fusion frames)
# 14607–14610: (reserved for future scripts)
UDP_OUT_PORTS = [14550, 14551] + list(range(14601, 14611))

def find_rfd900_com_port():
    print("Scanning for connected USB Serial Devices (RFD-900x)...")
    ports = list(serial.tools.list_ports.comports())
    
    if not ports:
        print("[ERROR] No COM ports found! Is the RFD-900x plugged into the laptop?")
        return None

    # The RFD-900x typically uses an FTDI FT230X chip
    candidates = []
    for p in ports:
        print(f"  -> Found: {p.device} | Desc: {p.description} | HWID: {p.hwid}")
        if 'FTDI' in p.hwid or 'USB Serial Port' in p.description:
            candidates.append(p)

    if len(candidates) == 1:
        print(f"\n[SUCCESS] Auto-detected likely RFD-900x on {candidates[0].device}")
        return candidates[0].device
    elif len(candidates) > 1:
        print("\n[WARNING] Multiple potential radios detected:")
        for idx, c in enumerate(candidates):
            print(f"  [{idx}] {c.device} - {c.description}")
        choice = input("Enter the number of the correct COM port: ")
        try:
            return candidates[int(choice)].device
        except:
            print("Invalid selection.")
            return None
    else:
        print("\n[WARNING] No FTDI devices identified automatically.")
        print("Available ports:")
        for idx, p in enumerate(ports):
            print(f"  [{idx}] {p.device} - {p.description}")
        choice = input("Enter the number of your RFD-900x COM port (or press Enter to abort): ")
        try:
            val = int(choice)
            return ports[val].device
        except:
            print("Aborted.")
            return None

def launch_mavproxy(com_port):
    print("\n=======================================================")
    print(f"Starting MAVProxy Router on {com_port} ({BAUD_RATE} baud)")
    print("Routing telemetry to:")
    for port in UDP_OUT_PORTS:
        print(f"  -> udp:127.0.0.1:{port}")
    print("=======================================================\n")
    
    # Construct out arguments
    out_args = []
    for port in UDP_OUT_PORTS:
        out_args.extend(["--out", f"udp:127.0.0.1:{port}"])
        
    cmd = [
        sys.executable, "-m", "MAVProxy.mavproxy",
        "--master", com_port,
        "--baudrate", str(BAUD_RATE)
    ] + out_args
    
    print(f"Executing: {' '.join(cmd)}")
    print("Press CTRL+C to safely exit the router.\n")
    
    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"\n[FATAL ERROR] Could not launch MAVProxy: {e}")
        print("Make sure MAVProxy is installed: pip install MAVProxy prompt_toolkit")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down GCS Router gracefully.")

if __name__ == "__main__":
    target_port = find_rfd900_com_port()
    if target_port:
        launch_mavproxy(target_port)
    else:
        print("\nLaunch failed. Ensure the drone is powered and the radio is plugged in.")
        time.sleep(3)
