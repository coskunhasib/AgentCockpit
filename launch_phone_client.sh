#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
./venv/bin/python ./phone_bridge_server.py
