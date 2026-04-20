#!/home/ngcp25/.local/share/pipx/venvs/mavproxy/bin/python
import sys
import time
import math
import logging
import json
import struct
import socket
import threading
import queue

from pathlib import Path
import uuid

from enum import IntEnum
try:
    from pymavlink import mavutil
except ImportError:
    print('pymavlink not installed. Run: pip install pymavlink')
    sys.exit(1)

# Import GCS Modules from gcs-infrastructure repo.
# The repo must be cloned to: /home/ngcp25/gcs-infrastructure
#   git clone https://github.com/ngcp-project/gcs-infrastructure.git /home/ngcp25/gcs-infrastructure
#

#Fix the location of this
MISSION_STATE_FILE = Path(__file__).resolve().parent / "mission_state.json" 

BASE_DIR = Path(__file__).resolve().parents[2]  # go up to ~/Projects
GCS_DIR = BASE_DIR / "gcs-infrastructure"

sys.path.append(str(GCS_DIR))
sys.path.append(str(GCS_DIR / "Application"))
sys.path.append(str(GCS_DIR / "lib" / "gcs-packet"))
sys.path.append(str(GCS_DIR / "lib" / "gcs-packet" / "Packet"))
sys.path.append(str(GCS_DIR / "lib" / "xbee-python"))

try:
    from Packet.Telemetry.Telemetry import Telemetry
    from Infrastructure.InfrastructureInterface import LaunchVehicleXBee, SendTelemetry, ReceiveCommand
    from Infrastructure.PacketQueue import CommandQueue
    print('[gcs_translator] GCS modules loaded (InfrastructureInterface API).')
except ImportError as e:
    print(f'[gcs_translator] FATAL: Could not import GCS modules: {e}')
    print('[gcs_translator] Run `git pull && git submodule update --init --recursive` in /home/ngcp25/gcs-infrastructure')
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

class MockXBee:
    """Mock XBee interface using UDP for local bidirectional testing."""
    def __init__(self, port=14551):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.setblocking(False)
        self.ser = True # Bypass none check

    def retrieve_data(self):
        try:
            data, _ = self.sock.recvfrom(1024)
            class MockFrame: pass
            frame = MockFrame()
            frame.received_data = data  # Match real XBee library field name
            return frame
        except BlockingIOError:
            return None

    def transmit_data(self, payload, retrieveStatus=False):
        pass

#Functions that load and write to the mission_state.json

def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def _write_state(updates: dict) -> None:
    """Atomically merge updates into mission_state.json."""
    import fcntl
    try:
        if not MISSION_STATE_FILE.exists():
            MISSION_STATE_FILE.write_text(json.dumps({}, indent=2))

        with open(MISSION_STATE_FILE, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            state = json.load(f)
            state = _deep_merge(state, updates)
            f.seek(0)
            json.dump(state, f, indent=2)
            f.truncate()
            fcntl.flock(f, fcntl.LOCK_UN)

    except FileNotFoundError:
        MISSION_STATE_FILE.write_text(json.dumps(updates, indent=2))

    except Exception as e:
        logger.error(f"[bridge] Failed to write mission_state.json: {e}")


def process_xbee_command(data, mav_connection, logger):
    """
    Parse raw XBee bytes and return a command dict.
    EmergencyStop triggers MAVLink immediately.
    All other commands are written to mission_state.json via _write_state().
    
    Command IDs (from gcs-infrastructure VehicleXBee.py):
      1  = Heartbeat
      2  = EmergencyStop
      3  = KeepIn
      4  = KeepOut
      5  = PatientLocation
      6  = SearchArea
      7  = StartLog
      8  = StopLog
      9  = StartAutonomy
      10 = StopAutonomy
      11 = RTL
      12 = Reboot
      13 = Shutdown
      14 = NewSearchSession
      15 = StartSearch
      16 = StopSearch
      17 = SetTarget
    """
    class Command(IntEnum):
        Heartbeat        = 1
        EmergencyStop    = 2
        KeepIn           = 3
        KeepOut          = 4
        PatientLocation  = 5
        SearchArea       = 6
        StartLog         = 7
        StopLog          = 8
        StartAutonomy    = 9
        StopAutonomy     = 10
        RTL              = 11
        Reboot           = 12
        Shutdown         = 13
        NewSearchSession = 14
        StartSearch      = 15
        StopSearch       = 16
        SetTarget        = 17

    if not data or not isinstance(data, bytes) or len(data) == 0:
        return None

    PAYLOAD_ID = data[0]
    if PAYLOAD_ID != 0x01:
        return None
    if len(data) < 2:
        return None

    COMMAND_ID = data[1]
    now = time.time()

    # --- Heartbeat ---
    if COMMAND_ID == Command.Heartbeat:
        logger.info("[cmd] HEARTBEAT from GCS")
        return {"command": "Heartbeat", "timestamp": now}

    # --- EmergencyStop (BYPASS: direct MAVLink, no state dependency) ---
    if COMMAND_ID == Command.EmergencyStop and len(data) >= 3:
        status = data[2]
        action = "ENABLE" if status == 0 else "DISABLE"
        logger.warning(f"[cmd] EMERGENCY STOP — {action}")

        if status == 0:
            logger.warning("[cmd] Sending MAV_CMD_DO_FLIGHTTERMINATION!")
            try:
                mav_connection.mav.command_long_send(
                    mav_connection.target_system, mav_connection.target_component,
                    mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION, 0,
                    1.0, 0, 0, 0, 0, 0, 0
                )
            except Exception as e:
                logger.error(f"[cmd] MAVLink termination failed: {e}")

        # Write to state for audit only — AFTER MAVLink call
        _write_state({
            "pending_action": "emergency_stop" if status == 0 else None,
            "last_command": "EmergencyStop",
            "timestamp": now,
        })
        return {"command": "EmergencyStop", "action": action, "timestamp": now}

    # --- RTL (Return to Launch — MAVLink + state) ---
    if COMMAND_ID == Command.RTL:
        logger.warning("[cmd] RTL requested")
        try:
            mav_connection.mav.command_long_send(
                mav_connection.target_system, mav_connection.target_component,
                mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, 0,
                0, 0, 0, 0, 0, 0, 0
            )
        except Exception as e:
            logger.error(f"[cmd] MAVLink RTL failed: {e}")
        _write_state({"rtl_requested": True, "last_command": "RTL", "timestamp": now})
        return {"command": "RTL", "timestamp": now}

    # --- Logging Control ---
    if COMMAND_ID == Command.StartLog:
        logger.info("[cmd] StartLog")
        _write_state({"logging_enabled": True, "last_command": "StartLog", "timestamp": now})
        return {"command": "StartLog", "timestamp": now}

    if COMMAND_ID == Command.StopLog:
        logger.info("[cmd] StopLog")
        _write_state({"logging_enabled": False, "last_command": "StopLog", "timestamp": now})
        return {"command": "StopLog", "timestamp": now}

    # --- Autonomy Control ---
    if COMMAND_ID == Command.StartAutonomy:
        logger.info("[cmd] StartAutonomy")
        _write_state({"autonomy_active": True, "last_command": "StartAutonomy", "timestamp": now})
        return {"command": "StartAutonomy", "timestamp": now}

    if COMMAND_ID == Command.StopAutonomy:
        logger.info("[cmd] StopAutonomy")
        _write_state({"autonomy_active": False, "last_command": "StopAutonomy", "timestamp": now})
        return {"command": "StopAutonomy", "timestamp": now}

    # --- System Control ---
    if COMMAND_ID == Command.Reboot:
        logger.warning("[cmd] Reboot requested — writing to pending_action")
        _write_state({"pending_action": "reboot", "last_command": "Reboot", "timestamp": now})
        return {"command": "Reboot", "timestamp": now}

    if COMMAND_ID == Command.Shutdown:
        logger.warning("[cmd] Shutdown requested — writing to pending_action")
        _write_state({"pending_action": "shutdown", "last_command": "Shutdown", "timestamp": now})
        return {"command": "Shutdown", "timestamp": now}

    # --- Search Session Control ---
    if COMMAND_ID == Command.NewSearchSession:
        session_id = str(uuid.uuid4())[:8]
        logger.info(f"[cmd] NewSearchSession — id={session_id}")
        _write_state({
            "search_phase": {"start_time": now, "time_limit_s": 480, "session_id": session_id},
            "last_command": "NewSearchSession",
            "timestamp": now,
        })
        return {"command": "NewSearchSession", "session_id": session_id, "timestamp": now}

    if COMMAND_ID == Command.StartSearch:
        logger.info("[cmd] StartSearch")
        _write_state({"last_command": "StartSearch", "timestamp": now})
        return {"command": "StartSearch", "timestamp": now}

    if COMMAND_ID == Command.StopSearch:
        logger.info("[cmd] StopSearch")
        _write_state({"last_command": "StopSearch", "timestamp": now})
        return {"command": "StopSearch", "timestamp": now}

    # --- Target / RF ---
    if COMMAND_ID == Command.PatientLocation and len(data) >= 10:
        # Expect: [PAYLOAD_ID, CMD_ID, lat(4B float), lon(4B float)]
        lat, lon = struct.unpack('>ff', data[2:10])
        logger.info(f"[cmd] PatientLocation lat={lat:.6f} lon={lon:.6f}")
        _write_state({
            "target_fix": {"fix_id": str(uuid.uuid4())[:8], "lat": lat, "lon": lon,
                           "confidence": None, "timestamp": now},
            "last_command": "PatientLocation",
            "timestamp": now,
        })
        return {"command": "PatientLocation", "lat": lat, "lon": lon, "timestamp": now}

    if COMMAND_ID == Command.SetTarget and len(data) >= 11:
        lat, lon = struct.unpack('>ff', data[2:10])
        confidence = data[10] / 100.0 if len(data) >= 11 else None
        logger.info(f"[cmd] SetTarget lat={lat:.6f} lon={lon:.6f} conf={confidence}")
        _write_state({
            "target_fix": {"fix_id": str(uuid.uuid4())[:8], "lat": lat, "lon": lon,
                           "confidence": confidence, "timestamp": now},
            "last_command": "SetTarget",
            "timestamp": now,
        })
        return {"command": "SetTarget", "lat": lat, "lon": lon, "timestamp": now}

    if COMMAND_ID == Command.SearchArea and len(data) >= 3:
        # Placeholder — parse polygon bytes when gcs-infrastructure spec is finalized
        logger.info("[cmd] SearchArea received (payload parsing pending)")
        _write_state({"last_command": "SearchArea", "timestamp": now})
        return {"command": "SearchArea", "timestamp": now}

    # --- Geofencing (stub — parse when spec is ready) ---
    if COMMAND_ID == Command.KeepIn:
        logger.info("[cmd] KeepIn received (not yet implemented)")
        return None

    if COMMAND_ID == Command.KeepOut:
        logger.info("[cmd] KeepOut received (not yet implemented)")
        return None

    logger.warning(f"[cmd] Unknown or malformed command ID={COMMAND_ID} len={len(data)}")
    return None

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('MAV_GCS_Translator')

def main():
    logger.info(f'Starting MAVLink to GCS Translator...')
    
    # 1. Connect to MAVProxy
    logger.info(f'Connecting to MAVLink stream on {MAVLINK_URI}')
    mav_connection = mavutil.mavlink_connection(MAVLINK_URI)
    hb = mav_connection.wait_heartbeat(timeout=30)
    if not hb:
        logger.error("No heartbeat received")
        return
    logger.info(f'Heartbeat from system (system {mav_connection.target_system} component {mav_connection.target_component})')

    # 2. Connect to XBee radio (real hardware or MockXBee UDP fallback).
    # Using InfrastructureInterface to spawn background VehicleXBee queues.
    xb_mode = 'none'
    xb = None
    _cmd_queue: queue.Queue = queue.Queue()

    try:
        # Define destination GCS laptop MAC address.
        from PacketLibrary.PacketLibrary import PacketLibrary
        PacketLibrary.SetGCSMACAddress("000000000000FFFF")
        
        LaunchVehicleXBee(get_xbee_port())
        xb_mode = 'real'
        logger.info(f'VehicleXBee connected on {get_xbee_port()} via InfrastructureInterface.')
    except Exception as e:
        logger.warning(f'Could not launch VehicleXBee: {e}')
        logger.warning('Proceeding in TEST MODE (UDP MockXBee on port 14551).')
        xb = MockXBee(port=14551)
        xb_mode = 'mock'

    # 3. Main Translation Loop
    telemetry = Telemetry()
    last_send_time = time.time()
    send_interval = 0.2  # 5 Hz
    latest_command = None
    raw_battery_mv = 0.0

    logger.info('Starting telemetry translation loop (5 Hz Target)...')

    while True:
        # Grab next MAVLink message
        msg = mav_connection.recv_match(blocking=False)
        
        if msg:
            msg_type = msg.get_type()

            # Map MAVLink data to GCS Telemetry struct
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

        current_time = time.time()
        
        # Receive incoming commands from GCS.
        # Real mode: poll CommandQueue from InfrastructureInterface
        # Mock mode: poll the UDP MockXBee socket.
        if xb_mode == 'real':
            try:
                if not CommandQueue.empty():
                    cmd_raw = ReceiveCommand()
                    if not cmd_raw:
                        continue

                    try:
                        cmd_data = json.loads(cmd_raw) if isinstance(cmd_raw, str) else cmd_raw
                    except Exception as e:
                        logger.error(f"[real] Failed to parse command JSON: {e} | raw={cmd_raw}")
                        continue

                    cmd_id = cmd_data.get("Command ID")
                    packet_id = cmd_data.get("Packet ID")
                    now = time.time()

                    logger.info(f"[real] Received GCS command id={cmd_id} packet_id={packet_id}")

                    if cmd_id == 1:
                        _write_state({
                            "last_command": "Heartbeat",
                            "timestamp": now,
                        })
                        latest_command = {
                            "command": "Heartbeat",
                            "packet_id": packet_id,
                            "timestamp": now,
                        }

                    elif cmd_id == 2:
                        status = cmd_data.get("Stop Status", 0)
                        
                        action = "ENABLE" if status == 0 else "DISABLE"

                        if status == 0:
                            logger.warning("[real] Sending MAV_CMD_DO_FLIGHTTERMINATION!")
                            try:
                                mav_connection.mav.command_long_send(
                                    mav_connection.target_system,
                                    mav_connection.target_component,
                                    mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION,
                                    0,
                                    1.0, 0, 0, 0, 0, 0, 0
                                )
                            except Exception as e:
                                logger.error(f"[real] MAVLink termination failed: {e}")

                        _write_state({
                            "pending_action": "emergency_stop" if status == 0 else None,
                            "last_command": "EmergencyStop",
                            "timestamp": now,
                        })

                        latest_command = {
                            "command": "EmergencyStop",
                            "packet_id": packet_id,
                            "action": action,
                            "timestamp": now,
                        }

                    elif cmd_id == 3:
                        coords = cmd_data.get("Coordinates", [])
                        _write_state({
                            "keep_in": coords,
                            "last_command": "KeepIn",
                            "timestamp": now,
                        })
                        latest_command = {
                            "command": "KeepIn",
                            "packet_id": packet_id,
                            "timestamp": now,
                        }

                    elif cmd_id == 4:
                        coords = cmd_data.get("Coordinates", [])
                        _write_state({
                            "keep_out": coords,
                            "last_command": "KeepOut",
                            "timestamp": now,
                        })
                        latest_command = {
                            "command": "KeepOut",
                            "packet_id": packet_id,
                            "timestamp": now,
                        }

                    elif cmd_id == 5:
                        coords = cmd_data.get("Coordinates", [])

                        if len(coords) >= 2:
                            lat, lon = coords[0], coords[1]
                        else:
                            lat, lon = None, None

                        _write_state({
                            #I think this is patient location given to us from ERU so this would be where to go for mission 3
                            "target_fix": {
                                "fix_id": str(uuid.uuid4())[:8],
                                "lat": lat,
                                "lon": lon,
                                "confidence": None,
                                "timestamp": now,
                            },
                            "last_command": "PatientLocation",
                            "timestamp": now,
                        })

                        latest_command = {
                            "command": "PatientLocation",
                            "packet_id": packet_id,
                            "lat": lat,
                            "lon": lon,
                            "timestamp": now,
                        }

                    elif cmd_id == 6:
                        coords = cmd_data.get("Coordinates", [])
                        _write_state({
                            "search_area": coords,
                            "last_command": "KeepIn",
                            "timestamp": now,
                        })

                        latest_command = {
                            "command": "SearchArea",
                            "packet_id": packet_id,
                            "timestamp": now,
                        }

                    else:
                        logger.warning(f"[real] Unsupported command id={cmd_id}")
                        latest_command = {
                            "command": f"Unknown({cmd_id})",
                            "packet_id": packet_id,
                            "timestamp": now,
                        }

            except Exception as e:
                logger.error(f"[real] Command receive error: {e}")
                
        elif xb_mode == 'mock' and xb:
            frame = xb.retrieve_data()
            if frame and hasattr(frame, 'received_data'):
                cmd_event = process_xbee_command(frame.received_data, mav_connection, logger)
                if cmd_event:
                    latest_command = cmd_event
        
        # Transmit at set frequency
        if current_time - last_send_time >= send_interval:
            telemetry.LastUpdated = int(current_time * 1000) # milliseconds
            
            # --- DEFAULT GCS FIELDS ---
            # vehicle_status is now updated live from HEARTBEAT.system_status above.
            # patient_status: Needs to be ingested from an external patient monitoring system.
            # message_flag: GCS operational intent (0=No Message, 1=Package Location, 2=Patient Location).
            #               Hardcoded to 0 — MAVLink has no native equivalent.
            telemetry.MessageFlag = 0
            telemetry.PatientStatus = 0
            
            # Encode and transmit telemetry over XBee (real or mock).
            try:
                payload_bytes = telemetry.Encode()
                hex_str = ' '.join(f'{b:02x}' for b in payload_bytes)

                if xb_mode == 'real':
                    SendTelemetry(telemetry)
                    logger.info(f'XBee -> Tlm Packet Queued: [{len(payload_bytes)}B] {hex_str}')
                elif xb_mode == 'mock' and xb:
                    xb.transmit_data(payload_bytes, retrieveStatus=False)
                    logger.info(f'MOCK -> Tlm Packet: [{len(payload_bytes)}B] {hex_str}')
                else:
                    logger.info(f'NO XBEE -> Tlm Packet: [{len(payload_bytes)}B] {hex_str}')
                
                # Dump state for GUI
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
                        "latest_command": latest_command
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
