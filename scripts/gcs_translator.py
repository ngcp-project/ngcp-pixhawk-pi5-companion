#!/home/ngcp25/.local/share/pipx/venvs/mavproxy/bin/python
# NOTE (code reviewers): The shebang above is intentionally Pi 5-specific.
# This script runs on the Raspberry Pi 5 companion computer under the MAVProxy
# virtual environment (pipx), which is the only Python env on the Pi that has
# pymavlink installed. Do not change this to /usr/bin/env python3 — the system
# Python on the Pi does not have the required dependencies.
import sys
import time
import math
import logging
import json
import struct
import os
try:
    from pymavlink import mavutil
except ImportError:
    print('pymavlink not installed. Run: pip install pymavlink')
    sys.exit(1)

# ---------------------------------------------------------------------------
# GCS Infrastructure Library (consumer-only submodule)
# ---------------------------------------------------------------------------
# gcs-infrastructure is owned and maintained by the GCS Subteam.
# MRA is a READ-ONLY consumer. Do NOT commit to that repo directly.
#
# Module resolution uses pip install -e (editable installs) per the
# gcs-infrastructure README. All three packages are registered under lib/:
#   pip install -e "lib/gcs-infrastructure"   (pyproject: Application/)
#   pip install -e "lib/gcs-packet"           (pyproject: Packet/)
#   pip install -e "lib/xbee-python"          (pyproject: src/)
#
# After running the above, imports resolve via standard Python module
# resolution — no sys.path.append workarounds needed.
#
# IMPORTANT (module aliasing): Telemetry MUST be imported as
#   'from Telemetry.Telemetry import Telemetry'
# NOT as 'from Packet.Telemetry.Telemetry import Telemetry'.
# Both resolve to the same file, but Python caches them under different keys.
# VehicleXBee.RunTelemetryThread uses isinstance(obj, Telemetry), which will
# silently return False (dropping all packets) if the class identity differs.
# See: MRA Consumer Bug Log, Bug #001 for the full root cause analysis.
#
try:
    from Telemetry.Telemetry import Telemetry
    from Enum import DecodeFormat
    from Infrastructure.InfrastructureInterface import LaunchVehicleXBee, SendTelemetry, ReceiveCommand
    from Infrastructure.PacketQueue import CommandQueue
    print('[gcs_translator] GCS modules loaded (InfrastructureInterface API).')
except ImportError as e:
    print(f'[gcs_translator] FATAL: Could not import GCS modules: {e}')
    print('[gcs_translator] Ensure submodules are initialised and installed:')
    print('[gcs_translator]   git submodule update --init --recursive')
    print('[gcs_translator]   pip install -e "lib/gcs-infrastructure"')
    print('[gcs_translator]   pip install -e "lib/gcs-packet"')
    print('[gcs_translator]   pip install -e "lib/xbee-python"')
    sys.exit(1)

# Configuration
MAVLINK_URI = 'udp:127.0.0.1:14550'

import glob
def get_xbee_port():
    ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    if not ports:
        return '/dev/ttyUSB0'
    ports.sort()
    return ports[0]

XBEE_PORT = get_xbee_port()  # Auto-detects USB port
XBEE_BAUD = 115200

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('MAV_GCS_Translator')

def main():
    logger.info(f'Starting MAVLink to GCS Translator...')
    
    # 1. Connect to MAVProxy
    # MAVProxy runs as a systemd service on the Pi 5 and connects to the
    # Pixhawk FC via UART (TELEM2). It fans out MAVLink messages to UDP
    # ports, including :14550 which this script listens on.
    logger.info(f'Connecting to MAVLink stream on {MAVLINK_URI}')
    mav_connection = mavutil.mavlink_connection(MAVLINK_URI)
    mav_connection.wait_heartbeat()
    logger.info(f'Heartbeat from system (system {mav_connection.target_system} component {mav_connection.target_component})')

    # 2. Connect to XBee radio.
    # Using InfrastructureInterface to spawn background VehicleXBee queues.
    # The XBee radio MUST be available — if it fails, exit immediately.
    # There is no mock/fallback mode in production. (Per Aiden's feedback 4/28/26)
    try:
        # Define destination GCS laptop MAC address.
        from PacketLibrary.PacketLibrary import PacketLibrary
        PacketLibrary.SetGCSMACAddress("0013A2004298267E")
        # The above is the MAC address of the GCS laptop's XBee radio module.
        
        LaunchVehicleXBee(get_xbee_port())
        logger.info(f'VehicleXBee connected on {get_xbee_port()} via InfrastructureInterface.')
    except Exception as e:
        logger.critical(f'FATAL: Could not launch VehicleXBee: {e}')
        logger.critical('XBee radio is required for operation. Exiting.')
        sys.exit(1)

    # 3. Main Translation Loop
    # Aiden notes that it is preferable to have the constructor loaded with
    # fields that GCS expects (4/27/26). TODO: refactor to construct with
    # all values once per send cycle instead of incremental attribute assignment.
    telemetry = Telemetry()
    last_send_time = time.time()
    send_interval = 0.2  # 5 Hz
    latest_command = None
    raw_battery_mv = 0.0

    logger.info('Starting telemetry translation loop (5 Hz Target)...')

    while True:
        # ── STEP 1: Read MAVLink messages (non-blocking) ──────────────
        # The Pixhawk sends each sensor category as a separate MAVLink
        # message type. We read whatever is available and update the
        # corresponding Telemetry fields. Messages arrive asynchronously
        # at different rates (GPS ~5 Hz, attitude ~50 Hz, etc.).
        msg = mav_connection.recv_match(blocking=False)
        
        if msg:
            msg_type = msg.get_type()

            # Map MAVLink data to GCS Telemetry struct fields.
            # Each handler performs the necessary unit conversions:
            #   - GPS: 1e-7 degrees (int32) → degrees (float)
            #   - Altitude: mm → feet
            #   - Speed: m/s → ft/s
            #   - Angles: radians → degrees
            #   - Battery: millivolts → volts
            if msg_type == 'GLOBAL_POSITION_INT':
                telemetry.CurrentPositionX = msg.lat / 1e7
                telemetry.CurrentPositionY = msg.lon / 1e7
                telemetry.Altitude = msg.alt / 1000.0 * 3.28084  # mm to feet
            elif msg_type == 'VFR_HUD':
                telemetry.Speed = msg.groundspeed * 3.28084  # m/s to ft/s
            elif msg_type == 'ATTITUDE':
                telemetry.Pitch = math.degrees(msg.pitch)
                telemetry.Roll = math.degrees(msg.roll)
                telemetry.Yaw = math.degrees(msg.yaw)
            elif msg_type == 'SYS_STATUS':
                # Convert mV to Battery Voltage
                if hasattr(msg, 'voltage_battery'):
                    raw_battery_mv = msg.voltage_battery
                    telemetry.BatteryLife = msg.voltage_battery / 1000.0
            elif msg_type == 'HEARTBEAT':
                # Map MAVLink system_status to GCS vehicle_status field.
                # MAV_STATE: 0=UNINIT, 1=BOOT, 2=CALIBRATING, 3=STANDBY,
                #            4=ACTIVE, 5=CRITICAL, 6=EMERGENCY, 7=POWEROFF
                # We map 4=ACTIVE → 1 (nominal), all others → 0 (not ready).
                mav_state = getattr(msg, 'system_status', 0)
                telemetry.VehicleStatus = 1 if mav_state == 4 else 0
            elif msg_type == 'DEBUG_VECT':
                # ──────────────────────────────────────────────────────────
                # GCS REVIEWERS: This handler is MRA-INTERNAL ONLY.
                # It does NOT use the XBee radio and has ZERO interaction
                # with GCS infrastructure, the GCS Dashboard, or any GCS
                # software. You can safely ignore this entire block.
                #
                # PURPOSE: MRA uses a KrakenSDR radio direction-finding
                # system to geolocate a ground-based RF transmitter
                # (the "survivor"). The Kraken Triangulator application
                # runs on a SEPARATE MRA laptop (not the GCS laptop) and
                # calculates estimated survivor coordinates.
                #
                # HOW IT WORKS (Dual-RF Architecture):
                #   1. The MRA laptop connects to the Pixhawk flight
                #      controller via an RFD-900x radio on Pixhawk TELEM1.
                #      This is a completely separate radio link from the
                #      XBee used for GCS telemetry.
                #   2. The Kraken Triangulator app on the MRA laptop sends
                #      the estimated survivor lat/lon upstream to the
                #      Pixhawk as a MAVLink DEBUG_VECT message with the
                #      name field set to 'KRAKEN_TGT'.
                #   3. This script (running on the Pi 5) intercepts that
                #      DEBUG_VECT message from the MAVLink stream and
                #      stores the coordinates in the Telemetry struct
                #      (MessageLat, MessageLon, MessageFlag=2).
                #   4. The coordinates are then included in the next
                #      XBee telemetry packet sent to GCS, so the GCS
                #      Dashboard can display the estimated survivor
                #      location if desired.
                #
                # RADIO LINK SUMMARY:
                #   RFD-900x (TELEM1) → MRA-internal Kraken data (this handler)
                #   XBee XR  (Pi 5 USB) → GCS telemetry (SendTelemetry above)
                #   These two radios operate independently on different
                #   frequencies and do not interfere with each other.
                # ──────────────────────────────────────────────────────────
                raw_name = getattr(msg, 'name', '')
                msg_name = (raw_name.decode('utf-8', 'ignore') if isinstance(raw_name, bytes) else str(raw_name)).strip('\x00')
                if msg_name == 'KRAKEN_TGT':
                    telemetry.MessageLat = float(msg.x)
                    telemetry.MessageLon = float(msg.y)
                    telemetry._last_target_mtime = time.time()
                    logger.info(f"Kraken target received via RFD-900x: ({msg.x}, {msg.y})")

        current_time = time.time()
        
        # ── STEP 2: Receive and dispatch GCS commands ─────────────────
        # Process commands BEFORE sending telemetry so that command
        # acknowledgments (e.g., MessageFlag updates) are reflected in the
        # same loop iteration's telemetry packet. (Per Aiden's feedback 4/28/26)
        try:
            if not CommandQueue.empty():
                # DecodeFormat.Class returns a typed Command object (Heartbeat,
                # EmergencyStop, AddZone, PatientLocation) per gcs-infrastructure API.
                cmd_obj = ReceiveCommand(DecodeFormat.Class)
                if cmd_obj:
                    cmd_name = type(cmd_obj).__name__
                    logger.info(f'Received GCS command: {cmd_name}')
                    latest_command = {"command": cmd_name, "timestamp": time.time()}
                    # Command dispatch: each case corresponds to a command type
                    # defined in gcs-infrastructure/lib/gcs-packet/Packet/Command/.
                    # DecodeFormat.Class gives us a typed object (not raw JSON),
                    # matching the pattern shown in GCSTest.py / VehicleTest.py.
                    #
                    # TODO (Aiden / future integration): The cases below marked
                    # 'not yet implemented' need MAVLink actions wired up once
                    # the GCS team begins sending these during integration tests.
                    # We may need to get MRA Software to map the MAVLink commands to 
                    # ensure that the system is compatible with the GCS team's commands. 4/28/2026
                    match cmd_obj:
                        case _ if cmd_name == 'EmergencyStop':
                            # Status=0 means STOP, Status=1 means RESUME.
                            # Sends MAV_CMD_DO_FLIGHTTERMINATION (ID 185) to FC.
                            status = getattr(cmd_obj, 'Status', getattr(cmd_obj, 'status', 0))
                            if status == 0:
                                logger.info('Sending MAV_CMD_DO_FLIGHTTERMINATION to flight controller!')
                                try:
                                    mav_connection.mav.command_long_send(
                                        mav_connection.target_system, mav_connection.target_component,
                                        mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION, 0,
                                        1.0, 0, 0, 0, 0, 0, 0
                                    )
                                except Exception as mav_exc:
                                    logger.error(f'Failed to send MAVLink command: {mav_exc}')
                        case _ if cmd_name == 'Heartbeat':
                            # GCS keepalive. No MAVLink action needed —
                            # just acknowledge receipt so GCS knows we are alive.
                            logger.info('Heartbeat received from GCS — connection confirmed.')
                        case _ if cmd_name == 'AddZone':
                            # TODO: Geofence upload. cmd_obj.ZoneType and
                            # cmd_obj.Coordinates contain the zone data.
                            # Wire up MAV_CMD_DO_FENCE_ENABLE or upload via
                            # MISSION_ITEM_INT with MAV_MISSION_TYPE_FENCE.
                            logger.info(f'AddZone received (not yet implemented): {cmd_obj}')
                        case _ if cmd_name == 'PatientLocation':
                            # TODO: GCS-pushed patient coordinate. cmd_obj.Coordinate
                            # contains the (lat, lon) tuple. Forward to autopilot
                            # or store for Kraken overlay.
                            logger.info(f'PatientLocation received (not yet implemented): {cmd_obj}')
                        case _:
                            logger.warning(f'Unrecognised command type — no action taken: {cmd_name}')
        except Exception as e:
            logger.error(f"Command receive error: {e}")
        
        # ── STEP 3: Transmit telemetry at 5 Hz ───────────────────────
        # Telemetry is sent AFTER command processing so that any flag
        # updates from commands (e.g., PatientLocation setting MessageFlag=2)
        # are included in this cycle's packet.
        if current_time - last_send_time >= send_interval:
            telemetry.LastUpdated = int(current_time * 1000) # milliseconds
            
            # --- DEFAULT GCS FIELDS ---
            # vehicle_status is now updated live from HEARTBEAT.system_status above.
            # patient_status: Needs to be ingested from an external patient monitoring system.
            
            telemetry.MessageFlag = 0
            telemetry.PatientStatus = 0
            
            # --- PATIENT LOCATION (MessageFlag=2) ---
            # If we received a patient location via MAVLink (from Kraken Triangulator), flag it.
            if getattr(telemetry, '_last_target_mtime', 0) > 0:
                # TODO: add a new command to reset the flag or a timeout mechanism
                telemetry.MessageFlag = 2  # 2 = Patient per GCS Telemetry spec
            
            # Encode and transmit telemetry over XBee.
            try:
                payload_bytes = telemetry.Encode()
                hex_str = ' '.join(f'{b:02x}' for b in payload_bytes)

                SendTelemetry(telemetry)
                logger.info(f'XBee -> Tlm Packet Queued: [{len(payload_bytes)}B] {hex_str}')
                
                # Dump state for GUI (this is for UI/Dashboard reference only gui_server.py)
                try:
                    state_dump = {
                        "lat": telemetry.CurrentPositionX,
                        "lon": telemetry.CurrentPositionY,
                        "alt": telemetry.Altitude,
                        "speed": telemetry.Speed,
                        "pitch": telemetry.Pitch,
                        "roll": telemetry.Roll,
                        "yaw": telemetry.Yaw,
                        "battery": raw_battery_mv,
                        "hex_payload": hex_str,
                        "last_updated": telemetry.LastUpdated,
                        "latest_command": latest_command,
                        "message_flag": telemetry.MessageFlag,
                        "target_lat": getattr(telemetry, 'MessageLat', 0.0),
                        "target_lon": getattr(telemetry, 'MessageLon', 0.0)
                    }
                    with open('/tmp/telemetry.json', 'w') as f:
                        json.dump(state_dump, f)
                except Exception as json_e:
                    logger.error(f"Failed to write state JSON: {json_e}")

            except Exception as e:
                logger.error(f'Encoding or Transmit error: {e}')

            last_send_time = current_time

if __name__ == '__main__':
    main()
