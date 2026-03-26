import json
import time
import os

TELEMETRY_PATH = (
    '/tmp/telemetry.json' if os.name != 'nt'
    else os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'telemetry.json')
)

def run():
    print("Starting mock telemetry harness...")
    for i in range(25):
        data = {
            "lat": 34.0522, "lon": -118.2437, "alt": 400.0, "speed": 45.2,
            "pitch": i * 2, "roll": -5.0, "yaw": 180.0, "battery": 22.4,
            "hex_payload": "7E 00 12 01 02 03 04 05 0A 0B 0C 0D...", "last_updated": int(time.time() * 1000)
        }
        
        # Inject the mock command at 5 seconds
        if i >= 5: 
            data["latest_command"] = {
                "command": "EmergencyStop",
                "action": "ENABLE",
                "timestamp": time.time() - (i - 5) * 0.5 # keep timestamp static to simulate a single command
            }
            if i == 5:
                print("Injected Mock Emergency Stop Command!")
        
        with open(TELEMETRY_PATH, 'w') as f:
            json.dump(data, f)
            
        time.sleep(0.5)
    print("Test harness finished.")

if __name__ == "__main__":
    os.makedirs(os.path.dirname(TELEMETRY_PATH), exist_ok=True)
    run()
