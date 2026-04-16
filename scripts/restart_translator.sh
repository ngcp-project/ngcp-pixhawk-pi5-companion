#!/bin/bash
pkill -f gcs_translator 2>/dev/null
sleep 1
cd /home/ngcp25/work/ngcp-pixhawk-pi5-companion/scripts
nohup python3 gcs_translator.py > /tmp/gcs_translator.log 2>&1 &
sleep 8
echo "=== Translator Log ==="
cat /tmp/gcs_translator.log
echo "=== Process Check ==="
ps aux | grep gcs_translator | grep -v grep
echo "=== telemetry.json ==="
cat /tmp/telemetry.json 2>/dev/null || echo "NOT FOUND"
