#!/bin/bash

set -u

# macOS Finder executes .command files in the home directory by default.
# We change the working directory to the folder containing this file.
cd "$(dirname "$0")" || exit 1

PHONE_PORT="${PHONE_PORT:-8765}"
HEALTH_URL="${AGENTCOCKPIT_HEALTH_URL:-http://127.0.0.1:${PHONE_PORT}/health}"
FORCE_RESTART="${AGENTCOCKPIT_FORCE_RESTART:-0}"

show_header() {
  echo -ne "\033]0;AgentCockpit Control Panel\007"
  clear
  echo "=================================================================="
  echo "                 AGENTCOCKPIT CONTROL PANEL"
  echo "=================================================================="
  echo "  * Phone bridge, Telegram UX and backend flows are starting."
  echo "  * Close this Terminal window or press [Ctrl + C] to stop."
  echo "  * Forced restart: AGENTCOCKPIT_FORCE_RESTART=1"
  echo "=================================================================="
  echo ""
}

print_health_summary() {
  python3 - "$HEALTH_URL" <<'PY' 2>/dev/null || true
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=2) as response:
    data = json.load(response)

print("Status:              " + str(data.get("status", "")))
print("Screen:              " + str(data.get("screen", "")))
print("Capture available:   " + str(data.get("capture_available", "")))
print("WAN URL:             " + str(data.get("public_url") or "not ready"))
print("WAN provider:        " + str(data.get("public_tunnel_provider") or "not ready"))
print("WAN status:          " + str(data.get("public_tunnel_status") or "not ready"))
error = data.get("public_tunnel_error") or data.get("capture_error") or ""
if error:
    print("Current error:       " + str(error))
PY
}

show_header

if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "AgentCockpit is already running."
  echo ""
  print_health_summary
  echo ""

  if [ "$FORCE_RESTART" != "1" ]; then
    echo "No restart was performed. This launcher does not stop an existing stack by default."
    echo "To force restart, run: AGENTCOCKPIT_FORCE_RESTART=1 ./AgentCockpit.command"
    echo ""
    read -r -p "Press [Enter] to close this window..."
    exit 0
  fi

  echo "Forced restart requested. Stopping existing stack first..."
  ./runner.sh stop
fi

echo "Starting AgentCockpit..."
./runner.sh
status=$?

echo ""
echo "=================================================================="
echo "  AgentCockpit exited with status: ${status}"
echo "=================================================================="
read -r -p "Press [Enter] to close this window..."
exit "$status"
