"""
auth.py - OAuth 2.0 login to the Conta Azul API (authorization code flow).

Run once per company:

    python -m pipeline.auth NWA

It opens the browser on the Conta Azul login page. After you approve, the
browser is sent back to a small local server (127.0.0.1 only, never the
network) that captures the one-time code and exchanges it for tokens. If the
redirect cannot reach your machine, paste the final URL into the terminal.

Tokens are saved in tokens/<CODE>.json (not versioned). Every run of the
pipeline refreshes the access token automatically, so you log in only once.
"""

import base64
import json
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import config

AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
SCOPE = "openid profile aws.cognito.signin.user.admin"
REFRESH_MARGIN = 120          # seconds: refresh a little before the token expires


def _basic_auth(company: config.Company) -> str:
    return "Basic " + base64.b64encode(f"{company.client_id}:{company.client_secret}".encode()).decode()


def _token_request(company: config.Company, data: dict) -> dict:
    resp = requests.post(TOKEN_URL, data=data, timeout=15,
                         headers={"Authorization": _basic_auth(company),
                                  "Content-Type": "application/x-www-form-urlencoded"})
    resp.raise_for_status()
    tokens = resp.json()
    tokens["saved_at"] = int(time.time())
    return tokens


def _save(company: config.Company, tokens: dict) -> None:
    company.token_file.parent.mkdir(parents=True, exist_ok=True)
    company.token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def access_token(company: config.Company) -> str:
    """A valid access token, refreshed with the saved refresh token when needed."""
    if not company.token_file.exists():
        raise SystemExit(f"[{company.code}] Not logged in. Run: python -m pipeline.auth {company.code}")
    tokens = json.loads(company.token_file.read_text(encoding="utf-8"))
    expires_at = tokens.get("saved_at", 0) + int(tokens.get("expires_in", 3600)) - REFRESH_MARGIN
    if time.time() < expires_at:
        return tokens["access_token"]
    new = _token_request(company, {"grant_type": "refresh_token",
                                   "refresh_token": tokens["refresh_token"]})
    new.setdefault("refresh_token", tokens["refresh_token"])   # some servers do not resend it
    _save(company, new)
    return new["access_token"]


def code_from_url(text: str) -> str | None:
    """Accepts the full redirect URL or just the code."""
    text = text.strip()
    if text.startswith("http"):
        return parse_qs(urlparse(text).query).get("code", [None])[0]
    return text or None


def login(company: config.Company, timeout: int = 300) -> None:
    state = secrets.token_urlsafe(32)
    received = threading.Event()
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                body, status = "Invalid state. Start the login again.", 400
            elif "code" not in query:
                body, status = "No authorization code in the URL.", 400
            else:
                result["code"] = query["code"][0]
                received.set()
                body, status = "Login complete. You can close this tab.", 200
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):        # keep codes out of the terminal
            pass

    redirect = urlparse(config.REDIRECT_URI)
    server = None
    if redirect.hostname in ("127.0.0.1", "localhost"):
        server = HTTPServer(("127.0.0.1", redirect.port or 80), Callback)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def manual():
        while not received.is_set():
            try:
                code = code_from_url(input("If the browser did not come back, paste the final URL here: "))
            except EOFError:
                return
            if code:
                result["code"] = code
                received.set()
    threading.Thread(target=manual, daemon=True).start()

    url = AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": company.client_id,
                                      "redirect_uri": config.REDIRECT_URI, "state": state,
                                      "scope": SCOPE})
    print(f"[{company.code}] Opening the Conta Azul login in your browser...")
    webbrowser.open(url)
    ok = received.wait(timeout)
    if server:
        server.shutdown()
    if not ok:
        raise SystemExit("Timed out after 5 minutes. Run the login again.")

    tokens = _token_request(company, {"grant_type": "authorization_code", "code": result["code"],
                                      "redirect_uri": config.REDIRECT_URI})
    _save(company, tokens)
    print(f"[{company.code}] Logged in. Tokens saved to {company.token_file}")


if __name__ == "__main__":
    codes = sys.argv[1:]
    companies = [c for c in config.load_companies() if not codes or c.code in codes]
    if not companies:
        raise SystemExit("No company found. Copy companies/EXAMPLE.json.example to companies/<CODE>.json first.")
    for c in companies:
        login(c)
