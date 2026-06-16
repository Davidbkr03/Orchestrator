#!/bin/bash
# Fusion Orchestrator Self-Update Script
# Called by POST /api/update

set -e

echo "[restart.sh] Pulling latest code..."
git pull origin main 2>&1 || echo "[restart.sh] Warning: git pull failed (not a git repo?)"

echo "[restart.sh] Installing dependencies..."
pip install -r requirements.txt --quiet 2>&1 || echo "[restart.sh] Warning: pip install failed"

echo "[restart.sh] Restarting application..."
# Find the uvicorn process and send HUP signal
PID=$(pgrep -f "uvicorn orchestrator:app" | head -1)
if [ -n "$PID" ]; then
    kill -HUP "$PID"
    echo "[restart.sh] Sent HUP signal to PID $PID"
else
    echo "[restart.sh] No running uvicorn process found, starting new..."
    nohup uvicorn orchestrator:app --host 0.0.0.0 --port 8000 > orchestrator.log 2>&1 &
    echo "[restart.sh] Started new process"
fi

echo "[restart.sh] Update complete"