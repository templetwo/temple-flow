#!/bin/bash
cd /Users/tony_studio/spiral-broker || exit 1
exec /Users/tony_studio/spiral-broker-prod/dashboard/api/venv_new/bin/python3 /Users/tony_studio/temple-flow/scripts/send_tf_20260830.py
