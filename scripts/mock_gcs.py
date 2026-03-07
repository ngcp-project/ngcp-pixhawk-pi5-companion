import socket
import struct
import time
import argparse

def send_emergency_stop(port=14551, enable=True):
    # Command Format: PAYLOAD_ID (1), COMMAND_ID (3), param (0=Enable, 1=Disable)
    # format = 'BBB'
    payload_id = 1
    command_id = 3
    status = 0 if enable else 1

    payload = struct.pack('BBB', payload_id, command_id, status)

    print(f"Sending Emergency Stop {'ENABLE' if enable else 'DISABLE'} to 127.0.0.1:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(payload, ('127.0.0.1', port))
    
    print("Payload sent! payload bytes:", payload.hex())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock GCS - Sends XBee UDP Packets locally.")
    parser.add_argument("--disable", action="store_true", help="Send a Disable Emergency Stop command instead of Enable.")
    args = parser.parse_args()

    send_emergency_stop(enable=not args.disable)
