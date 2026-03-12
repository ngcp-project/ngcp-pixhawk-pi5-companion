#!/usr/bin/env python3
"""
test_mavlink_hub.py — Unit tests for the MAVLink Hub broker

Tests:
  1. Hub starts and accepts TCP registration connections
  2. A client can register and appears in list()
  3. A registered client receives forwarded MAVLink UDP frames
  4. A client can deregister and disappears from list()
  5. Dead-client detection (alive=False after DEAD_CLIENT_SECS)
  6. Multiple simultaneous clients all receive frames

Run: python3 test_mavlink_hub.py
"""

import asyncio
import json
import socket
import sys
import time
import threading
import unittest

# Use non-default ports so tests don't clash with a running hub
TEST_IN_PORT  = 19550   # simulate MAVProxy sending here
TEST_REG_PORT = 19555   # registration TCP port
TEST_CLIENT_A = 19600
TEST_CLIENT_B = 19601

# Import the hub (same directory)
import os
sys.path.insert(0, os.path.dirname(__file__))
from mavlink_hub import MAVLinkHub, register_with_hub, deregister_from_hub


# ── Helpers ────────────────────────────────────────────────────────────────────

def tcp_request(payload: dict, port: int = TEST_REG_PORT) -> dict:
    """Send a JSON registration request over TCP and return parsed response."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(('127.0.0.1', port))
    s.send(json.dumps(payload).encode())
    resp = s.recv(4096)
    s.close()
    return json.loads(resp.decode())


def udp_send(data: bytes, port: int = TEST_IN_PORT):
    """Simulate MAVProxy sending a frame into the hub."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(data, ('127.0.0.1', port))
    s.close()


def udp_recv(port: int, timeout: float = 2.0) -> bytes | None:
    """Try to receive one UDP datagram on a port, return None on timeout."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', port))
    s.settimeout(timeout)
    try:
        data, _ = s.recvfrom(512)
        return data
    except socket.timeout:
        return None
    finally:
        s.close()


# ── Test Fixture ───────────────────────────────────────────────────────────────

class HubTestCase(unittest.TestCase):
    """Spins up a real MAVLinkHub in a background thread for each test class."""

    hub_thread: threading.Thread = None
    loop: asyncio.AbstractEventLoop = None

    @classmethod
    def setUpClass(cls):
        """Start hub in background event loop thread."""
        cls.hub = MAVLinkHub(in_port=TEST_IN_PORT)
        cls.loop = asyncio.new_event_loop()

        def run_hub():
            cls.loop.run_until_complete(cls.hub.run(reg_port=TEST_REG_PORT))

        cls.hub_thread = threading.Thread(target=run_hub, daemon=True)
        cls.hub_thread.start()
        time.sleep(0.4)  # give the hub a moment to start

    @classmethod
    def tearDownClass(cls):
        """Cancel all hub tasks and close the loop."""
        for task in asyncio.all_tasks(cls.loop):
            task.cancel()
        cls.loop.stop()


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestHubRegistration(HubTestCase):

    def test_1_hub_accepts_list_request(self):
        """Hub should respond to a 'list' action immediately after start."""
        resp = tcp_request({"action": "list"})
        self.assertEqual(resp["status"], "ok")
        self.assertIn("clients", resp)
        print("\n  ✅ test_1: Hub responds to list request")

    def test_2_register_client(self):
        """Client registers and appears in list."""
        resp = tcp_request({
            "action": "register",
            "port": TEST_CLIENT_A,
            "name": "mock_consumer_A.py"
        })
        self.assertEqual(resp["status"], "ok")
        self.assertIn(str(TEST_CLIENT_A), resp["clients"])
        self.assertEqual(resp["clients"][str(TEST_CLIENT_A)]["name"], "mock_consumer_A.py")
        print("  ✅ test_2: Client registered successfully")

    def test_3_registered_client_receives_frames(self):
        """A registered client should receive all forwarded MAVLink frames."""
        # Register client B
        tcp_request({"action": "register", "port": TEST_CLIENT_B, "name": "mock_consumer_B.py"})
        time.sleep(0.1)

        MOCK_MAVLINK_FRAME = b'\xfe\x09\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x28\x04'

        # Start a UDP receiver in parallel, then send the frame
        received = []

        def recv_thread():
            data = udp_recv(TEST_CLIENT_B, timeout=2.0)
            if data:
                received.append(data)

        t = threading.Thread(target=recv_thread)
        t.start()
        time.sleep(0.05)          # let receiver bind first
        udp_send(MOCK_MAVLINK_FRAME)
        t.join(timeout=3.0)

        self.assertEqual(len(received), 1, "Client B should have received exactly 1 frame")
        self.assertEqual(received[0], MOCK_MAVLINK_FRAME, "Frame contents should be identical")
        print("  ✅ test_3: Forwarded frame received by client")

    def test_4_deregister_client(self):
        """Deregistered client disappears from list."""
        # Register then immediately deregister client B
        tcp_request({"action": "register", "port": TEST_CLIENT_B, "name": "mock_consumer_B.py"})
        resp = tcp_request({"action": "deregister", "port": TEST_CLIENT_B})
        self.assertEqual(resp["status"], "ok")
        self.assertNotIn(str(TEST_CLIENT_B), resp["clients"])
        print("  ✅ test_4: Client deregistered successfully")

    def test_5_alive_status_no_data(self):
        """A client that has never received data should have alive=None (pending)."""
        # Register a fresh port that has never had data sent to it
        fresh_port = 19605
        tcp_request({"action": "register", "port": fresh_port, "name": "fresh_client.py"})
        resp = tcp_request({"action": "list"})
        info = resp["clients"].get(str(fresh_port))
        self.assertIsNotNone(info)
        self.assertIsNone(info["alive"], "Client with no data should report alive=null")
        tcp_request({"action": "deregister", "port": fresh_port})
        print("  ✅ test_5: alive=null for client with no data received yet")

    def test_6_invalid_action_returns_error(self):
        """Unknown actions should return an error status, not crash the hub."""
        resp = tcp_request({"action": "explode"})
        self.assertEqual(resp["status"], "error")
        print("  ✅ test_6: Invalid action handled gracefully")

    def test_7_multiple_clients_all_receive(self):
        """All registered clients receive the same frame."""
        PORT_C = 19602
        PORT_D = 19603

        tcp_request({"action": "register", "port": PORT_C, "name": "client_C.py"})
        tcp_request({"action": "register", "port": PORT_D, "name": "client_D.py"})
        time.sleep(0.1)

        FRAME = b'\xfe\x01\x02\x03\x04\x05'
        received = {PORT_C: [], PORT_D: []}

        def recv(p):
            data = udp_recv(p, timeout=2.0)
            if data:
                received[p].append(data)

        threads = [threading.Thread(target=recv, args=(p,)) for p in [PORT_C, PORT_D]]
        for t in threads:
            t.start()
        time.sleep(0.05)
        udp_send(FRAME)
        for t in threads:
            t.join(timeout=3.0)

        self.assertEqual(len(received[PORT_C]), 1, "Client C missed the frame")
        self.assertEqual(len(received[PORT_D]), 1, "Client D missed the frame")
        print("  ✅ test_7: All clients received the same frame")

        # Cleanup
        tcp_request({"action": "deregister", "port": PORT_C})
        tcp_request({"action": "deregister", "port": PORT_D})


if __name__ == '__main__':
    print("=" * 60)
    print("  MAVLink Hub — Mock Unit Tests")
    print("=" * 60)
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # preserve definition order
    suite = loader.loadTestsFromTestCase(TestHubRegistration)
    runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    result = runner.run(suite)
    print("=" * 60)
    if result.wasSuccessful():
        print("  ALL TESTS PASSED ✅")
    else:
        print(f"  {len(result.failures)} FAILED, {len(result.errors)} ERRORS ❌")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
