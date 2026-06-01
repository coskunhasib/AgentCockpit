#!/bin/bash
set -u

export PYTHONIOENCODING=utf-8
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

stop_stack() {
  local patterns=(
    "$PROJECT_ROOT/main.py"
    "$PROJECT_ROOT/phone_bridge_server.py"
    "$PROJECT_ROOT/.agentcockpit/runtime/bin/cloudflared tunnel --url http://127.0.0.1:8765"
  )

  for pattern in "${patterns[@]}"; do
    pkill -f "$pattern" >/dev/null 2>&1 || true
  done
}

if [[ "${1:-}" == "stop" ]]; then
  stop_stack
  echo "[STOP] AgentCockpit süreçleri kapatildi."
  exit 0
fi

python3 "$PROJECT_ROOT/main.py"
