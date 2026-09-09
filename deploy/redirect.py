#!/usr/bin/env python3
"""HTTP -> HTTPS 301 redirector.

Sits behind `tailscale serve --http=80 http://127.0.0.1:8081` so that a plain
http:// hit on the resume-tailor MagicDNS name bounces to https://. Stdlib only.
"""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

LISTEN = ("127.0.0.1", 8081)
# Only used if a request arrives with no Host header. Set REDIRECT_HOST to your
# own MagicDNS name (e.g. resume-tailor.<your-tailnet>.ts.net) in the unit file.
FALLBACK_HOST = os.environ.get("REDIRECT_HOST", "resume-tailor.example.ts.net")


class Redirect(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "rt-redirect"

    def _go(self, body: bool) -> None:
        host = (self.headers.get("Host") or FALLBACK_HOST).split(":")[0]
        # 308 keeps the method/body; browsers typing the URL send GET anyway.
        code = 301 if self.command in ("GET", "HEAD") else 308
        self.send_response(code)
        self.send_header("Location", f"https://{host}{self.path}")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        self._go(True)

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

    def log_message(self, *_a):  # keep the journal quiet
        pass


if __name__ == "__main__":
    HTTPServer(LISTEN, Redirect).serve_forever()
