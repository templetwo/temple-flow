#!/usr/bin/env python3
"""HTTPS Schwab OAuth. Ignore empty hits; wait until a real ?code= arrives."""
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from dotenv import load_dotenv
import requests

BROKER = Path("/Users/tony_studio/spiral-broker")
os.chdir(BROKER)
load_dotenv(BROKER / ".env")

APP_KEY = os.getenv("SCHWAB_APP_KEY")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
CALLBACK = "https://127.0.0.1:8080"
TOKEN_PATH = BROKER / ".schwab_tokens.json"
STATE = {"code": None, "done": False}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        code = (qs.get("code") or [None])[0]
        print("HIT", parsed.path, "code", bool(code), flush=True)

        if not code:
            self.send_response(204)
            self.end_headers()
            return

        STATE["code"] = code
        creds = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode()).decode()
        r = requests.post(
            "https://api.schwabapi.com/v1/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALLBACK,
            },
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
        )
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if r.status_code == 200:
            tokens = r.json()
            tokens["expires_at"] = time.time() + tokens.get("expires_in", 0)
            TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
            os.chmod(TOKEN_PATH, 0o600)
            print("SAVED", TOKEN_PATH, "expires_in", tokens.get("expires_in"), flush=True)
            self.wfile.write(b"<html><body style='font-family:sans-serif;text-align:center;padding:40px'><h1 style='color:green'>Authentication Successful</h1><p>Tokens saved. You can close this.</p></body></html>")
            STATE["done"] = True
        else:
            print("EXCHANGE_FAIL", r.status_code, r.text[:300], flush=True)
            self.wfile.write(b"<html><body><h1>Token exchange failed</h1></body></html>")
            STATE["done"] = True

    def log_message(self, fmt, *args):
        return


def main() -> int:
    if not APP_KEY or not APP_SECRET:
        print("missing SCHWAB_APP_KEY/SECRET")
        return 2
    params = {"client_id": APP_KEY, "redirect_uri": CALLBACK, "response_type": "code"}
    url = "https://api.schwabapi.com/v1/oauth/authorize?" + urlencode(params)
    print("AUTH_URL", url, flush=True)
    server = HTTPServer(("127.0.0.1", 8080), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(BROKER / "cert.pem"), str(BROKER / "key.pem"))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print("LISTEN https://127.0.0.1:8080 waiting for code", flush=True)
    deadline = time.time() + 600
    while not STATE["done"] and time.time() < deadline:
        server.timeout = 2
        server.handle_request()
    if not STATE["done"]:
        print("TIMEOUT no code")
        return 1
    return 0 if TOKEN_PATH.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
