#!/usr/bin/env python3
import http.server
import socketserver
import os

PORT = 8082
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')

class TelemetryHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        if self.path == '/telemetry.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            try:
                with open('/tmp/telemetry.json', 'rb') as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                # Send empty state if translator hasn't written it yet
                self.wfile.write(b'{}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"error": "{str(e)}"}}'.encode('utf-8'))
        else:
            # Handle default static file serving for the web directory
            super().do_GET()

if __name__ == "__main__":
    os.makedirs(WEB_DIR, exist_ok=True)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), TelemetryHandler) as httpd:
        print(f"Starting lightweight GUI server on port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            httpd.server_close()
