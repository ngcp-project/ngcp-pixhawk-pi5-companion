#!/home/ngcp25/.local/share/pipx/venvs/mavproxy/bin/python
import sys
import time
import math
import logging
import json
import struct
import socket

try:
    from pymavlink import mavutil
except ImportError:
    print('pymavlink not installed. Run: pip install pymavlink')
    sys.exit(1)

# Import GCS Modules directly from the other repository
sys.path.append('/home/ngcp25/gcs-infrastructure')
try:
    from Packet.Telemetry.Telemetry import Telemetry
    from Communication.XBee.XBee import XBee
except ImportError as e:
    print(f'Failed to import GCS modules: {e}')
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
    """Parses custom GCS frame bytes and converts back to MAVLink."""
    if not data or not isinstance(data, bytes) or len(data) == 0:
        return None
        
    PAYLOAD_ID = data[0]
    if PAYLOAD_ID != 0x01: # 0x01 is the GCS TAG_COMMAND
        return None

    if len(data) >= 2:
        COMMAND_ID = data[1]
        
        # Emergency Stop Command (ID: 2, Format: BBB) — per gcs-infrastructure README
        if COMMAND_ID == 2 and len(data) >= 3:
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
            
    return None

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('MAV_GCS_Translator')

def main():
    logger.info(f'Starting MAVLink to GCS Translator...')

    # Register with the MAVLink Hub so this script appears in the Port Monitor GUI.
    # Hub fans MAVProxy output on port 14550 down to all registered clients.
    # Falls back silently if hub isn't running (direct MAVProxy connection still works).
    HUB_UDP_PORT = 14600   # the port this script binds to receive MAVLink frames
    try:
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from mavlink_hub import register_with_hub
        registered = register_with_hub(HUB_UDP_PORT, 'gcs_translator.py')
        if registered:
            logger.info(f'Registered with MAVLink Hub on port {HUB_UDP_PORT}')
            HUB_URI = f'udp:127.0.0.1:{HUB_UDP_PORT}'
        else:
            logger.warning('Hub registration failed — falling back to direct MAVProxy port 14550')
            HUB_URI = MAVLINK_URI
    except ImportError:
        logger.warning('mavlink_hub not found — falling back to direct MAVProxy port 14550')
        HUB_URI = MAVLINK_URI
    
    # 1. Connect to MAVProxy (via hub if registered, direct fallback otherwise)
    logger.info(f'Connecting to MAVLink stream on {HUB_URI}')
    mav_connection = mavutil.mavlink_connection(HUB_URI)
    mav_connection.wait_heartbeat()
    logger.info(f'Heartbeat from system (system {mav_connection.target_system} component {mav_connection.target_component})')

    # 2. Setup XBee Connection (GCS Module)
    xb = None
    try:
        xb = XBee(port=XBEE_PORT, baudrate=XBEE_BAUD)
        xb.open()
        logger.info(f'XBee connected on {XBEE_PORT} at {XBEE_BAUD} baud.')
    except Exception as e:
        logger.warning(f'Could not connect XBee: {e}')
        logger.warning('Proceeding in TEST MODE (Starting UDP Mock on port 14551).')
        xb = MockXBee(port=14551)

    # 3. Main Translation Loop
    telemetry = Telemetry()
    last_send_time = time.time()
    send_interval = 0.2  # 5 Hz
    latest_command = None

    logger.info('Starting telemetry translation loop (5 Hz Target)...')

    while True:
        # Grab next MAVLink message
        msg = mav_connection.recv_match(blocking=False)
        
        if msg:
            msg_type = msg.get_type()
            
            # Map MAVLink data to GCS Telemetry struct
            if msg_type == 'GLOBAL_POSITION_INT':
                telemetry.current_latitude = msg.lat / 1e7
                telemetry.current_longitude = msg.lon / 1e7
                telemetry.altitude = msg.alt / 1000.0 * 3.28084 # mm to feet
            elif msg_type == 'VFR_HUD':
                telemetry.speed = msg.groundspeed * 3.28084 # m/s to ft/s
            elif msg_type == 'ATTITUDE':
                telemetry.pitch = math.degrees(msg.pitch)
                telemetry.roll = math.degrees(msg.roll)
                telemetry.yaw = math.degrees(msg.yaw)
            elif msg_type == 'SYS_STATUS':
                # Convert mV to Battery Voltage (Assuming Battery 0)
                if hasattr(msg, 'voltage_battery'):
                     telemetry.battery_life = msg.voltage_battery / 1000.0

        current_time = time.time()
        
        # Poll for Incoming XBee RX Frames
        if xb:
            frame = xb.retrieve_data()
            if frame and hasattr(frame, 'received_data'):  # matches real XBee lib & MockXBee
                cmd_event = process_xbee_command(frame.received_data, mav_connection, logger)
                if cmd_event:
                    latest_command = cmd_event
        
        # Transmit at set frequency
        if current_time - last_send_time >= send_interval:
            telemetry.last_updated = int(current_time * 1000) # milliseconds
            
            # --- DEFAULT GCS FIELDS ---
            # TODO (Future Implementation): These fields lack native MAVLink equivalents.
            # - patient_status: Needs to be ingested from the external patient monitoring system
            # - message_flag: Represents GCS operational intent (0=No Message, 1=Package Location, 2=Patient Location)
            #                 Currently hardcoded to 0. MAVLink does not natively track Package/Patient status.
            telemetry.vehicle_status = 1  
            telemetry.message_flag = 0    
            telemetry.patient_status = 0
            
            # Pack payload using GCS repo code!
            try:
                payload_bytes = telemetry.encode()
                hex_str = ' '.join(f'{b:02x}' for b in payload_bytes)
                
                if xb and xb.ser:
                    xb.transmit_data(payload_bytes, retrieveStatus=False)
                else:
                    # Debug print if no hardware
                    logger.info(f'NO XBEE -> Tlm Packet: [{len(payload_bytes)}B] {hex_str}')
                
                # Dump state for GUI
                try:
                    state_dump = {
                        "lat": telemetry.current_latitude,
                        "lon": telemetry.current_longitude,
                        "alt": telemetry.altitude,
                        "speed": telemetry.speed,
                        "pitch": telemetry.pitch,
                        "roll": telemetry.roll,
                        "yaw": telemetry.yaw,
                        "battery": telemetry.battery_life,
                        "hex_payload": hex_str,
                        "last_updated": telemetry.last_updated,
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
