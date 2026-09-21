"""Disposable, standard-library-only upstream for test_nginx.py; no app imports."""

import base64
import hashlib
import json
import os
import struct
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INSTANCE = os.environ["MOCK_INSTANCE"]
PROGRESS = {"bytes": 0}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def reply(self, status, payload, extra=()):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        # Deliberately unsafe upstream headers: the gateway must override them.
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Expires", "Wed, 01 Jan 2031 00:00:00 GMT")
        self.send_header("Content-Length", str(len(body)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            accept = base64.b64encode(
                hashlib.sha1(
                    (
                        self.headers["Sec-WebSocket-Key"]
                        + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    ).encode()
                ).digest()
            ).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            first, second = self.rfile.read(2)
            assert first == 0x81 and second & 0x80 and second & 0x7F < 126
            mask = self.rfile.read(4)
            data = self.rfile.read(second & 0x7F)
            message = bytes(value ^ mask[i % 4] for i, value in enumerate(data))
            body = json.dumps(
                {
                    "instance": INSTANCE,
                    "path": self.path,
                    "message": message.decode(),
                    "version": self.request_version,
                }
            ).encode()
            prefix = (
                bytes([0x81, len(body)])
                if len(body) < 126
                else (b"\x81\x7e" + struct.pack("!H", len(body)))
            )
            self.wfile.write(prefix + body)
            self.wfile.flush()
            self.close_connection = True
            return
        if self.path == "/v1/upload-progress":
            self.reply(200, PROGRESS)
            return
        if self.headers.get("Range") == "bytes=2-5":
            self.reply(
                206,
                b"2345",
                [("Content-Range", "bytes 2-5/10"), ("Accept-Ranges", "bytes")],
            )
            return
        status = 200
        extra = []
        if self.path.startswith("/v1/status/"):
            status = int(self.path.split("/")[-1])
        if status == 302:
            extra.append(("Location", "https://media.invalid/private?signature=mock"))
        if self.path == "/v1/auth/login":
            extra.append(("Set-Cookie", "session=mock; Secure; HttpOnly; SameSite=Lax"))
        self.reply(
            status,
            {"instance": INSTANCE, "path": self.path, "headers": dict(self.headers)},
            extra,
        )

    do_HEAD = do_GET

    def do_POST(self):
        remaining = int(self.headers["Content-Length"])
        digest = hashlib.sha256()
        PROGRESS["bytes"] = 0
        while remaining:
            chunk = self.rfile.read(min(4096, remaining))
            if not chunk:
                return
            digest.update(chunk)
            remaining -= len(chunk)
            PROGRESS["bytes"] += len(chunk)
        verify_seconds = 0
        if self.path == "/v1/evidence/assets?verify=slow":
            # No response bytes for longer than nginx's default 60s read timeout.
            started = time.monotonic()
            time.sleep(65)
            verify_seconds = time.monotonic() - started
        self.reply(
            200,
            {
                "instance": INSTANCE,
                "path": self.path,
                "bytes": PROGRESS["bytes"],
                "sha256": digest.hexdigest(),
                "version": self.request_version,
                "verify_seconds": verify_seconds,
                "headers": dict(self.headers),
            },
        )


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
