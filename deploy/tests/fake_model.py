"""Synthetic model for isolated Docker tests. No external network or billing."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from uuid import uuid4

counts = {"success": 0, "disconnect": 0}
lock = Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        data = json.dumps(counts).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        failed = payload["messages"][-1]["content"] == "simulate-disconnect"
        with lock:
            counts["disconnect" if failed else "success"] += 1
        if failed:
            self.close_connection = True
            return
        result = {
            "id": str(uuid4()),
            "choices": [{"message": {"content": '{"synthetic":true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8766), Handler).serve_forever()
