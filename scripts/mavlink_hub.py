#!/usr/bin/env python3
"""
mavlink_hub.py — MAVLink Publish-Subscribe Broker

Sits between MAVProxy and all consumer scripts. MAVProxy outputs to one
fixed UDP port (this hub's input). The hub fans MAVLink frames out to all
registered consumer ports at runtime — no launch script edits required.

Registration API (Unix domain socket / TCP fallback):
  {"action": "register",   "port": 14603, "name": "my_script.py"}
  {"action": "deregister", "port": 14603}
  {"action": "list"}

Usage:
  python3 mavlink_hub.py [--in-port 14550] [--reg-port 14555]
"""

import asyncio
import json
import logging
import socket
import sys
import time
import os
import argparse

# ── Configuration ──────────────────────────────────────────────────────────────
DEFAULT_IN_PORT   = 14550   # MAVProxy sends here (hub's single input)
DEFAULT_REG_PORT  = 14555   # TCP registration fallback (used on Windows too)
UNIX_SOCK_PATH    = '/tmp/mavlink_hub.sock'
DYNAMIC_PORT_MIN  = 14600
DYNAMIC_PORT_MAX  = 14699
DEAD_CLIENT_SECS  = 10.0   # seconds of silence before marking a client dead

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [HUB] %(levelname)s %(message)s'
)
logger = logging.getLogger('mavlink_hub')


class MAVLinkHub:
    """
    Core broker. Maintains a registry of {port → client_info} and
    fans out every UDP datagram from MAVProxy to all live clients.
    """

    def __init__(self, in_port: int):
        self.in_port = in_port
        # clients: { port (int) → {"name": str, "last_sent": float, "registered_at": float} }
        self.clients: dict = {}
        self._lock = asyncio.Lock()

    # ── Registration helpers ────────────────────────────────────────────────────

    async def register(self, port: int, name: str) -> dict:
        async with self._lock:
            self.clients[port] = {
                "name": name,
                "registered_at": time.time(),
                "last_sent": 0.0,
                "frames_sent": 0,
            }
        logger.info(f"Registered client: {name} on port {port}")
        return await self.list_clients()

    async def deregister(self, port: int) -> dict:
        async with self._lock:
            removed = self.clients.pop(port, None)
        if removed:
            logger.info(f"Deregistered client on port {port} ({removed['name']})")
        return await self.list_clients()

    async def list_clients(self) -> dict:
        now = time.time()
        async with self._lock:
            snapshot = {
                str(p): {
                    "name":  info["name"],
                    "alive": (now - info["last_sent"]) < DEAD_CLIENT_SECS
                              if info["last_sent"] > 0 else None,  # None = no data yet
                    "frames_sent": info["frames_sent"],
                    "registered_at": info["registered_at"],
                }
                for p, info in self.clients.items()
            }
        return {"status": "ok", "clients": snapshot}

    # ── Fan-out loop ────────────────────────────────────────────────────────────

    async def forward_loop(self):
        """Receives MAVLink UDP frames from MAVProxy and fans them out."""
        loop = asyncio.get_event_loop()

        in_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        in_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        in_sock.bind(('127.0.0.1', self.in_port))
        in_sock.setblocking(False)

        out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        logger.info(f"Hub listening for MAVProxy on UDP {self.in_port}")

        while True:
            try:
                data = await loop.sock_recv(in_sock, 512)
                async with self._lock:
                    ports = list(self.clients.keys())

                for port in ports:
                    try:
                        out_sock.sendto(data, ('127.0.0.1', port))
                        async with self._lock:
                            if port in self.clients:
                                self.clients[port]['last_sent'] = time.time()
                                self.clients[port]['frames_sent'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to forward to port {port}: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Forward loop error: {e}")
                await asyncio.sleep(0.01)

    # ── Registration request handler ────────────────────────────────────────────

    async def handle_registration(self, reader, writer):
        """Handles one registration socket connection (Unix or TCP)."""
        try:
            raw = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            msg = json.loads(raw.decode())
            action = msg.get('action')

            if action == 'register':
                port = int(msg['port'])
                name = msg.get('name', 'unknown')
                resp = await self.register(port, name)

            elif action == 'deregister':
                port = int(msg['port'])
                resp = await self.deregister(port)

            elif action == 'list':
                resp = await self.list_clients()

            else:
                resp = {"status": "error", "message": f"Unknown action: {action}"}

            writer.write(json.dumps(resp).encode())
            await writer.drain()

        except json.JSONDecodeError:
            writer.write(b'{"status":"error","message":"Invalid JSON"}')
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"Registration handler error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── Entry point ─────────────────────────────────────────────────────────────

    async def run(self, reg_port: int):
        servers = []

        # Try Unix domain socket first (Linux/Pi 5)
        if os.name != 'nt':
            try:
                if os.path.exists(UNIX_SOCK_PATH):
                    os.remove(UNIX_SOCK_PATH)
                unix_server = await asyncio.start_unix_server(
                    self.handle_registration, UNIX_SOCK_PATH
                )
                servers.append(unix_server)
                logger.info(f"Registration socket: {UNIX_SOCK_PATH} (Unix domain)")
            except Exception as e:
                logger.warning(f"Unix socket failed ({e}), falling back to TCP only")

        # Always also start TCP fallback (works on Windows + cross-platform tests)
        tcp_server = await asyncio.start_server(
            self.handle_registration, '127.0.0.1', reg_port
        )
        servers.append(tcp_server)
        logger.info(f"Registration socket: 127.0.0.1:{reg_port} (TCP fallback)")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.forward_loop())
            for s in servers:
                tg.create_task(s.serve_forever())


# ── Client helper (import this in any consumer script) ─────────────────────────

def register_with_hub(port: int, name: str, reg_port: int = DEFAULT_REG_PORT,
                      use_unix: bool = True) -> bool:
    """
    Two-line convenience function for consumer scripts to call at startup.

    Usage:
        from mavlink_hub import register_with_hub
        register_with_hub(14603, "krakensdr_listener.py")
        # then bind UDP socket on 14603 and recv MAVLink frames normally
    """
    msg = json.dumps({"action": "register", "port": port, "name": name}).encode()

    # Try Unix socket first
    if use_unix and os.name != 'nt' and os.path.exists(UNIX_SOCK_PATH):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(UNIX_SOCK_PATH)
            s.send(msg)
            s.close()
            return True
        except Exception:
            pass

    # TCP fallback
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('127.0.0.1', reg_port))
        s.send(msg)
        s.close()
        return True
    except Exception as e:
        print(f"[mavlink_hub] Could not register with hub: {e}")
        return False


def deregister_from_hub(port: int, reg_port: int = DEFAULT_REG_PORT) -> bool:
    msg = json.dumps({"action": "deregister", "port": port}).encode()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('127.0.0.1', reg_port))
        s.send(msg)
        s.close()
        return True
    except Exception:
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MAVLink Hub — publish-subscribe broker')
    parser.add_argument('--in-port',  type=int, default=DEFAULT_IN_PORT,
                        help=f'UDP port to receive MAVProxy output (default: {DEFAULT_IN_PORT})')
    parser.add_argument('--reg-port', type=int, default=DEFAULT_REG_PORT,
                        help=f'TCP port for client registration (default: {DEFAULT_REG_PORT})')
    args = parser.parse_args()

    hub = MAVLinkHub(in_port=args.in_port)

    try:
        asyncio.run(hub.run(reg_port=args.reg_port))
    except KeyboardInterrupt:
        logger.info("Hub shutting down.")
