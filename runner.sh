#!/bin/bash
set -u

export PYTHONIOENCODING=utf-8
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

stop_stack() {
  PROJECT_ROOT_ENV="$PROJECT_ROOT" python3 - <<'PY'
import os
import signal
import subprocess
import time

root = os.environ["PROJECT_ROOT_ENV"]
patterns = [
    f"{root}/main.py",
    f"{root}/phone_bridge_server.py",
    f"{root}/.agentcockpit/runtime/bin/cloudflared",
    f"{root}/.agentcockpit/runtime/bin/bore",
]


def matching_pids():
    output = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    pids = []
    current_pid = os.getpid()
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        pid_text, _, command = text.partition(" ")
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == current_pid:
            continue
        if any(pattern in command for pattern in patterns):
            pids.append(pid)
    return pids


for sig in (signal.SIGTERM, signal.SIGKILL):
    pids = matching_pids()
    if not pids:
        break
    for pid in sorted(pids, reverse=True):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
    time.sleep(1)
PY
}

if [[ "${1:-}" == "stop" ]]; then
  stop_stack
  echo "[STOP] AgentCockpit süreçleri kapatildi."
  exit 0
fi

python3 "$PROJECT_ROOT/main.py"
