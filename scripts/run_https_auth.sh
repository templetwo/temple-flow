#!/bin/bash
cd /Users/tony_studio/spiral-broker || exit 1
exec /Users/tony_studio/spiral-broker-prod/dashboard/api/venv_new/bin/python3 https_auth.py
