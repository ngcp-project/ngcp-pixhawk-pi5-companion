import json
import csv
import math
import os
import sys

def create_gaussian_spectrum(center_deg, width=5.0, peak=20.0):
    spectrum = []
    for i in range(360):
        # Handle wrap-around distance on a circle
        diff = min(abs(i - center_deg), 360 - abs(i - center_deg))
        val = peak * math.exp(-0.5 * (diff / width)**2)
        spectrum.append(round(val, 2))
    return spectrum

def convert_to_android_csv(json_path, csv_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    waypoints = data.get("waypoint_sequence", [])
    freq_hz = data.get("frequency_hz", 462637500)
    
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for obs in waypoints:
            # Android CSV Format requires exactly 377 columns
            row = []
            
            # 1. UNIX Epoch Time (13 digit long int - ms)
            row.append(int(obs.get("t_rx_ms", 0)))
            
            # 2. Max DOA Angle in degrees (Compass Convention)
            row.append(int(round(obs.get("bearing_deg", 0.0))))
            
            # 3. Confidence value (0 to 99)
            conf = int(round(obs.get("confidence", 0.0) * 100))
            row.append(min(99, conf)) # Cap at 99
            
            # 4. RSSI Power in dB (Mocked)
            row.append(-50)
            
            # 5. Channel Frequency in Hz
            row.append(freq_hz)
            
            # 6. Antenna Array arrangement
            row.append("UCA")
            
            # 7. Latency in ms
            row.append(0)
            
            # 8. Station ID
            row.append(obs.get("id", "Station"))
            
            # 9. Latitude
            row.append(obs.get("lat", 0.0))
            
            # 10. Longitude
            row.append(obs.get("lon", 0.0))
            
            # 11. GPS Heading
            row.append(obs.get("heading_used_deg", 0.0))
            
            # 12. Compass Heading
            row.append(0.0)
            
            # 13. Main Heading Sensor
            row.append("GPS")
            
            # 14-17. Reserved fields
            row.extend([0, 0, 0, 0])
            
            # 18-377. 360 degree DOA output (unit circle convention)
            # The raw DOA from KrakenSDR is in the unit circle convention natively.
            doa_raw = obs.get("doa_deg_raw", 0.0)
            spectrum = create_gaussian_spectrum(doa_raw)
            row.extend(spectrum)
            
            writer.writerow(row)
            
    print(f"Successfully exported {len(waypoints)} records to {csv_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python export_android.py <input.json> <output.csv>")
        sys.exit(1)
    convert_to_android_csv(sys.argv[1], sys.argv[2])
