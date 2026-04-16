#!/usr/bin/env python3
"""
gui_server.py — Lightweight HTTP server for the GCS Telemetry Monitor web GUI.

Endpoints:
  GET /             → serves web/index.html
  GET /telemetry.json → reads /tmp/telemetry.json written by gcs_translator.py
  GET /ports        → queries mavlink_hub for active registered clients
"""
import http.server
import socketserver
import os
import json
import socket
import time

PORT    = 8082
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')

# Hub registration endpoint (TCP fallback — works on Windows + Linux)
HUB_REG_HOST = '127.0.0.1'
HUB_REG_PORT = 14555

# Path for /tmp/telemetry.json (cross-platform: Windows uses TEMP)
TELEMETRY_PATH = (
    '/tmp/telemetry.json' if os.name != 'nt'
    else os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'telemetry.json')
)

# ── Mock data for local Windows development / demo ────────────────────────────
MOCK_PORTS = {
    "14600": {"name": "gcs_translator.py",    "alive": True,  "frames_sent": 1420},
    "14601": {"name": "command_listener.py",  "alive": True,  "frames_sent": 892},
    "14602": {"name": "autonomy_engine.py",   "alive": False, "frames_sent": 245},
}


def query_hub_ports() -> dict:
    """Ask the hub for the active client list via TCP. Falls back to mock data."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect((HUB_REG_HOST, HUB_REG_PORT))
        s.send(json.dumps({"action": "list"}).encode())
        resp = s.recv(4096)
        s.close()
        data = json.loads(resp.decode())
        return data.get('clients', {})
    except Exception:
        # Hub not running — return mock data so GUI still renders
        return MOCK_PORTS


class TelemetryHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):

        # ── /telemetry.json ───────────────────────────────────────────────────
        if self.path == '/telemetry.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            try:
                with open(TELEMETRY_PATH, 'rb') as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.wfile.write(b'{}')
            except Exception as e:
                self.wfile.write(f'{{"error": "{str(e)}"}}'.encode())

        # ── /ports ────────────────────────────────────────────────────────────
        elif self.path == '/ports':
            clients = query_hub_ports()
            payload = json.dumps({
                "timestamp": time.time(),
                "clients": clients
            }).encode()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(payload)

        # ── Static files (index.html, app.js, style.css …) ───────────────────
        else:
            super().do_GET()

    def log_message(self, format, *args):
        # Suppress noisy per-request logs; keep startup message clean
        pass


if __name__ == "__main__":
    os.makedirs(WEB_DIR, exist_ok=True)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), TelemetryHandler) as httpd:
        print(f"GCS Telemetry Monitor  ->  http://localhost:{PORT}")
        print(f"Telemetry endpoint     ->  http://localhost:{PORT}/telemetry.json")
        print(f"Port monitor endpoint  ->  http://localhost:{PORT}/ports")
        print("Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            httpd.server_close()
