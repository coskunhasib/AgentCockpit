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
home = os.path.expanduser("~")

# App processes are matched by their script path (these never relocate).
patterns = [
    f"{root}/main.py",
    f"{root}/phone_bridge_server.py",
]

# The tunnel binaries are trickier: the bundled runtime bin dir moves with
# $AGENTCOCKPIT_HOME / $XDG_STATE_HOME / $AGENTCOCKPIT_RUNTIME_DIR (and a temp
# fallback), and the binary may instead come from $CLOUDFLARED_EXE/$BORE_EXE or
# straight off $PATH (e.g. a Homebrew cloudflared). Hard-coding one path (the
# old behavior) missed all of those and left the public tunnel running after a
# stop. Collect every bin dir we can derive from the environment...
runtime_roots = []
if os.environ.get("AGENTCOCKPIT_RUNTIME_DIR"):
    runtime_roots.append(os.environ["AGENTCOCKPIT_RUNTIME_DIR"])
if os.environ.get("AGENTCOCKPIT_HOME"):
    runtime_roots.append(os.path.join(os.environ["AGENTCOCKPIT_HOME"], "runtime"))
if os.environ.get("XDG_STATE_HOME"):
    runtime_roots.append(os.path.join(os.environ["XDG_STATE_HOME"], "agentcockpit", "runtime"))
runtime_roots.append(os.path.join(root, ".agentcockpit", "runtime"))
runtime_roots.append(os.path.join(home, ".agentcockpit", "runtime"))
for rt in runtime_roots:
    patterns.append(os.path.join(rt, "bin", "cloudflared"))
    patterns.append(os.path.join(rt, "bin", "bore"))
for env_name in ("CLOUDFLARED_EXE", "BORE_EXE"):
    if os.environ.get(env_name):
        patterns.append(os.environ[env_name])


def is_our_tunnel(command):
    # ...and as a location-independent backstop (covers a $PATH/Homebrew binary
    # with no env override), match our exact tunnel invocation shape regardless
    # of where the binary lives on disk.
    if "cloudflared" in command and "tunnel --url" in command and "--no-autoupdate" in command:
        return True
    if "bore" in command and "local --local-host" in command and "--to" in command:
        return True
    return False


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
        if any(pattern in command for pattern in patterns) or is_our_tunnel(command):
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
