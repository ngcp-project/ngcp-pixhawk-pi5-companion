#!/home/ngcp25/.local/share/pipx/venvs/mavproxy/bin/python
import sys
import time
import math
import logging

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
XBEE_PORT = '/dev/ttyUSB0'  # Fixed to USB port
XBEE_BAUD = 115200

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

    # 2. Setup XBee Connection (GCS Module)
    xb = None
    try:
        xb = XBee(port=XBEE_PORT, baudrate=XBEE_BAUD)
        xb.open()
        logger.info(f'XBee connected on {XBEE_PORT} at {XBEE_BAUD} baud.')
    except Exception as e:
        logger.warning(f'Could not connect XBee: {e}')
        logger.warning('Proceeding in TEST MODE (Printing payload to console).')

    # 3. Main Translation Loop
    telemetry = Telemetry()
    last_send_time = time.time()
    send_interval = 0.2  # 5 Hz

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
                
                if xb and xb.ser:
                    xb.transmit_data(payload_bytes, retrieveStatus=False)
                else:
                    # Debug print if no hardware
                    hex_str = ' '.join(f'{b:02x}' for b in payload_bytes)
                    logger.info(f'NO XBEE -> Tlm Packet: [{len(payload_bytes)}B] {hex_str}')
            except Exception as e:
                logger.error(f'Encoding or Transmit error: {e}')

            last_send_time = current_time

if __name__ == '__main__':
    main()
