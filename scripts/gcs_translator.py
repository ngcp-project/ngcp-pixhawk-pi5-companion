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
import os
from pathlib import Path
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
sys.path.append('/home/ngcp25/gcs-infrastructure')
sys.path.append('/home/ngcp25/gcs-infrastructure/Application')
sys.path.append('/home/ngcp25/gcs-infrastructure/lib/gcs-packet')
sys.path.append('/home/ngcp25/gcs-infrastructure/lib/gcs-packet/Packet')
sys.path.append('/home/ngcp25/gcs-infrastructure/lib/xbee-python')
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

def process_xbee_command(data, mav_connection, logger):
    """Parses custom GCS frame bytes and converts back to MAVLink.
    Command IDs match VehicleXBee.py in gcs-infrastructure:
      1 = Heartbeat
      2 = EmergencyStop  (Format: BBB — PAYLOAD_ID, COMMAND_ID, status)
      3 = KeepIn         (not yet implemented)
      4 = KeepOut        (not yet implemented)
      5 = PatientLocation (not yet implemented)
      6 = SearchArea      (not yet implemented)
    """
    #Command ID
    class Command(IntEnum):
        Heartbeat = 1
        EmergencyStop = 2
        KeepIn = 3
        KeepOut = 4
        PatientLocation = 5
        SearchArea = 6

    if not data or not isinstance(data, bytes) or len(data) == 0:
        return None

    PAYLOAD_ID = data[0]
    if PAYLOAD_ID != 0x01:  # 0x01 is the GCS TAG_COMMAND
        return None

    if len(data) >= 2:
        COMMAND_ID = data[1]
        
        # Heartbeat Command (ID: 1) — GCS keepalive
        if COMMAND_ID == Command.Heartbeat:
            logger.info("Received HEARTBEAT command from GCS")
            return {"command": "Heartbeat", "timestamp": time.time()}

        # Emergency Stop Command (ID: 2, Format: BBB) — per gcs-infrastructure spec
        if COMMAND_ID == Command.EmergencyStop and len(data) >= 3:
            status = data[2]
            action = "ENABLE" if status == 0 else "DISABLE"
            logger.info(f"Received EMERGENCY STOP command: {action}")

            # Send MAV_CMD_DO_FLIGHTTERMINATION (ID: 185) if Enabled
            if status == 0:
                logger.info("Sending Flight Termination to MAVLink!")
                try:
                    mav_connection.mav.command_long_send(
                        mav_connection.target_system, mav_connection.target_component,
                        mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION, 0,
                        1.0, 0, 0, 0, 0, 0, 0
                    )
                except Exception as e:
                    logger.error(f"Failed to send MAVLink command: {e}")

            return {"command": "EmergencyStop", "action": action, "timestamp": time.time()}
        
        #KeepIn (not yet implemented)
        if COMMAND_ID == Command.KeepIn and len(data) >= 3:
            return None

        #KeepOut (not yet implemented)
        if COMMAND_ID == Command.KeepOut and len(data) >= 3:
            return None
        
        #PaitentLocation (not yet implemented)
        if COMMAND_ID == Command.PatientLocation and len(data) >= 3:
            return None
        
        #Search Area (not yet implemented)
        if COMMAND_ID == Command.SearchArea and len(data) >= 3:
            return None

    return None #return None if invalid IDs 

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('MAV_GCS_Translator')

def main():
    logger.info(f'Starting MAVLink to GCS Translator...')
    
    # 1. Connect to MAVProxy
    logger.info(f'Connecting to MAVLink stream on {MAVLINK_URI}')
    mav_connection = mavutil.mavlink_connection(MAVLINK_URI)
    mav_connection.wait_heartbeat()
    logger.info(f'Heartbeat from system (system {mav_connection.target_system} component {mav_connection.target_component})')

    # 2. Connect to XBee radio (real hardware or MockXBee UDP fallback).
    # Using InfrastructureInterface to spawn background VehicleXBee queues.
    xb_mode = 'none'
    xb = None
    _cmd_queue: queue.Queue = queue.Queue()

    try:
        # Define destination GCS laptop MAC address.
        from PacketLibrary.PacketLibrary import PacketLibrary
        PacketLibrary.SetGCSMACAddress("0013A2004298267E")
        
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
            elif msg_type == 'DEBUG_VECT':
                # Intercept upstream target coordinates from Kraken Server
                raw_name = getattr(msg, 'name', '')
                msg_name = (raw_name.decode('utf-8', 'ignore') if isinstance(raw_name, bytes) else str(raw_name)).strip('\x00')
                if msg_name == 'KRAKEN_TGT':
                    telemetry.MessageLat = float(msg.x)
                    telemetry.MessageLon = float(msg.y)
                    telemetry._last_target_mtime = time.time()
                    logger.info(f"Intercepted Target from upstream MAVLink: {msg.x}, {msg.y}")

        current_time = time.time()
        
        # Receive incoming commands from GCS.
        # Real mode: poll CommandQueue from InfrastructureInterface
        # Mock mode: poll the UDP MockXBee socket.
        if xb_mode == 'real':
            try:
                if not CommandQueue.empty():
                    cmd_obj = ReceiveCommand()
                    if cmd_obj:
                        cmd_name = type(cmd_obj).__name__
                        logger.info(f'Received GCS command: {cmd_name}')
                        latest_command = {"command": cmd_name, "timestamp": time.time()}
                        # Forward EmergencyStop to MAVLink flight controller
                        if cmd_name == 'EmergencyStop':
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
            except Exception as e:
                logger.error(f"Command receive error: {e}")
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
            
            telemetry.MessageFlag = 0
            telemetry.PatientStatus = 0
            
            # --- KRAKEN GCS BRIDGE ---
            # If we received a target via MAVLink recently (e.g. within this session), flag it
            if getattr(telemetry, '_last_target_mtime', 0) > 0:
                telemetry.MessageFlag = 2
            
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
