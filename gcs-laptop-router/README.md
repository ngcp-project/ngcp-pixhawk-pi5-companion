# GCS Laptop MAVProxy Router

When the RFD-900x radio modem is physically plugged into a Windows machine, the operating system strictly limits access to its serial COM port. If QGroundControl grabs the port first, no other script or application (like the Kraken Triangulator backend) can read the live MAVLink telemetry stream. 

This directory contains utility scripts to solve this COM port locking issue by running a local UDP router *before* opening QGroundControl.

## Overview of Operation
The scripts automatically locate the RFD-900x's COM port, launch `MAVProxy`, and fan-out the MAVLink telemetry streams locally so all applications can listen simultaneously. 

### Pre-Allocated UDP Endpoints
The router splits the incoming MAVLink stream to the following localhost UDP ports:
- `udp:127.0.0.1:14550` : Reserved for **QGroundControl** (Listens here by default).
- `udp:127.0.0.1:14551` : Reserved for the **Kraken Triangulator** or custom GCS Python scripts.
- `udp:127.0.0.1:14601` : Reserved for the **Software Team Pipeline**.

## How to Use

### Method 1: The Automated Batch File (Recommended)
Simply navigate to this folder in Windows Explorer and double-click `launch.bat`. 
It will automatically verify your Python dependencies, scan the hardware registry for the RFD-900x COM port, and launch the router in a visible terminal window. 

> **Important:** Leave the terminal window running in the background for the duration of the flight. Closing it kills the telemetry stream to all apps!

### Method 2: Manual Terminal Launch
If the automatic COM port detection fails, or you prefer to use the command line directly, you can run MAVProxy manually using PowerShell or Command Prompt.

**Step 1:** Look up which COM port your RFD-900x is using via the Windows Device Manager (e.g. `COM4`).
**Step 2:** Run the following command from any terminal:
```powershell
mavproxy.py --master=COM4 --baudrate=57600 --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --out=udp:127.0.0.1:14601
```

## Dependencies
The automated scripts will attempt to install these automatically, but if they fail, ensure you have Python installed and run:
`pip install pyserial MAVProxy`
