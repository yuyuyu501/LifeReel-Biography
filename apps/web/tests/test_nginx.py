"""Run explicitly with Python 3.10+ and Docker, independently of app test suites.

Uses only a dedicated disposable network, mock upstreams and random loopback ports.
Does not run Compose, load .env, or access databases, production or paid providers.
"""

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOCK = Path(__file__).with_name("nginx_mock.py")


def docker(*args, timeout=60):
    result = subprocess.run(
        ["docker", *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"docker {' '.join(map(str, args))}: {result.stderr}")
    return result.stdout.strip()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Regression:
    def __init__(self, args):
        self.args = args
        self.prefix = "lifereel-d02-" + uuid.uuid4().hex[:12]
        self.network = self.prefix + "-net"
        self.containers = []
        self.network_created = False
        self.report = {"checks": [], "network": self.network}
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls.check_hostname = False
        self.tls.verify_mode = (
            ssl.CERT_NONE
        )  # Disposable, locally generated certificate.

    def passed(self, name):
        self.report["checks"].append(name)
        print("PASS:", name, flush=True)

    def launch(self, name, image, *options, command=()):
        self.containers.append(name)
        return docker(
            "run",
            "-d",
            "--pull=never",
            "--name",
            name,
            "--label",
            "lifereel.test=d02",
            "--network",
            self.network,
            *options,
            image,
            *command,
        )

    def mock(self, suffix, alias=True):
        name = self.prefix + "-" + suffix
        self.launch(
            name,
            self.args.mock_image,
            *(["--network-alias", "api"] if alias else []),
            "-e",
            "MOCK_INSTANCE=" + suffix,
            "--mount",
            f"type=bind,src={MOCK},dst=/mock.py,readonly",
            command=("python", "-u", "/mock.py"),
        )
        # Readiness only queries this mock directly, never the application API.
        for _ in range(30):
            try:
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')",
                )
                return name
            except RuntimeError:
                time.sleep(0.1)
        raise AssertionError("mock failed to start")

    def request(
        self, path, *, https=False, method="GET", body=None, headers=None, timeout=4
    ):
        conn = (
            http.client.HTTPSConnection(
                "127.0.0.1", self.https_port, context=self.tls, timeout=timeout
            )
            if https
            else http.client.HTTPConnection(
                "127.0.0.1", self.http_port, timeout=timeout
            )
        )
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            conn.close()

    def private(self, headers):
        cache = [v for k, v in headers if k.lower() == "cache-control"]
        require(cache == ["private, no-store"], f"unexpected cache policy: {cache}")
        require(not any(k.lower() == "expires" for k, _ in headers), "Expires leaked")

    @staticmethod
    def client_headers():
        # The trusted host proxy appends the real client last; earlier entries
        # and the caller's X-Real-IP / internal credentials are untrusted.
        return {
            "X-API-Key": "untrusted",
            "X-Tenant-ID": "untrusted",
            "X-Worker-Key": "untrusted",
            "X-Real-IP": "198.51.100.99",
            "X-Forwarded-For": "198.51.100.99, 203.0.113.17",
            "Cookie": "session=mock",
        }

    def upstream_headers(self, headers):
        require(headers.get("X-API-Key") == "d02-mock-key", "API key not overridden")
        for name in ("X-Tenant-ID", "X-Worker-Key", "X-Forwarded-For"):
            require(name not in headers, f"untrusted {name} reached API")
        require(
            headers.get("X-Real-IP") == "203.0.113.17",
            "trusted client IP lost or spoofed",
        )
        require(headers.get("Cookie") == "session=mock", "session lost")
        require(headers.get("Host") == "127.0.0.1", "Host lost")
        require(headers.get("X-Forwarded-Proto") == "http", "proxy scheme changed")
        require(headers.get("Connection") == "close", "HTTP connection header changed")

    def process_state(self):
        details = json.loads(docker("inspect", self.web))[0]
        # PID + process start ticks catch a reload (new workers), even without restart.
        processes = docker(
            "exec",
            self.web,
            "sh",
            "-c",
            "for p in /proc/[0-9]*; do "
            '[ "$(cat "$p/comm" 2>/dev/null)" = nginx ] && '
            "awk '{print $1, $22}' \"$p/stat\"; done; true",
        )
        return {
            "id": details["Id"],
            "started_at": details["State"]["StartedAt"],
            "restarts": details["RestartCount"],
            "nginx_processes": sorted(processes.splitlines()),
        }

    def ip(self, container):
        info = json.loads(docker("inspect", container))[0]
        return info["NetworkSettings"]["Networks"][self.network]["IPAddress"]

    def setup(self, directory):
        image = re.findall(
            r"^FROM\s+(\S+)", (ROOT / "apps/web/Dockerfile").read_text(), re.MULTILINE
        )[-1]
        self.image = image
        self.report["nginx_image"] = json.loads(docker("image", "inspect", image))[0][
            "Id"
        ]
        docker("image", "inspect", self.args.mock_image)
        filters = [
            re.search(r"NGINX_ENVSUBST_FILTER:\s*(.+)", (ROOT / name).read_text())
            .group(1)
            .strip()
            for name in ("compose.yaml", "compose.production.yaml")
        ]
        require(filters[0] == filters[1], "Compose envsubst filters differ")
        self.report["envsubst_filter"] = filters[0]
        self.report["template_sha256"] = hashlib.sha256(
            self.args.template.read_bytes()
        ).hexdigest()
        docker("network", "create", "--label", "lifereel.test=d02", self.network)
        self.network_created = True
        # Ask Docker for a free subnet, then explicitly configure only our new
        # network so reconnecting the old mock at its original IP is supported.
        subnet = json.loads(docker("network", "inspect", self.network))[0]["IPAM"][
            "Config"
        ][0]["Subnet"]
        docker("network", "rm", self.network)
        self.network_created = False
        docker(
            "network",
            "create",
            "--subnet",
            subnet,
            "--label",
            "lifereel.test=d02",
            self.network,
        )
        self.network_created = True
        self.report["subnet"] = subnet
        self.old = self.mock("old")
        # Generate a fresh test key without touching host or production credentials.
        docker(
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "none",
            "--mount",
            f"type=bind,src={directory},dst=/test",
            self.args.mock_image,
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            "/test/key.pem",
            "-out",
            "/test/cert.pem",
        )
        (directory / "tls.conf").write_text(
            """server {
  listen 443 ssl;
  ssl_certificate /test/cert.pem;
  ssl_certificate_key /test/key.pem;
  location / {
    proxy_pass http://127.0.0.1:80;
    proxy_http_version 1.1;
    proxy_connect_timeout 30s;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Host $host;
  }
}
""",
            encoding="utf-8",
        )
        self.web = self.prefix + "-web"
        self.launch(
            self.web,
            image,
            "-p",
            "127.0.0.1::80",
            "-p",
            "127.0.0.1::443",
            "-e",
            "API_ACCESS_KEY=d02-mock-key",
            "-e",
            "NGINX_CLIENT_MAX_BODY_SIZE=2m",
            "-e",
            "NGINX_ENVSUBST_FILTER=" + filters[0],
            "--mount",
            f"type=bind,src={self.args.template},dst=/etc/nginx/templates/default.conf.template,readonly",
            "--mount",
            f"type=bind,src={directory},dst=/test,readonly",
            "--mount",
            f"type=bind,src={directory / 'tls.conf'},dst=/etc/nginx/conf.d/tls-test.conf,readonly",
        )
        info = json.loads(docker("inspect", self.web))[0]
        self.http_port = int(info["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"])
        self.https_port = int(
            info["NetworkSettings"]["Ports"]["443/tcp"][0]["HostPort"]
        )
        for _ in range(50):
            try:
                if self.request("/health")[0] == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("Nginx did not become healthy")
        version = subprocess.run(
            ["docker", "exec", self.web, "nginx", "-v"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.report["nginx_version"] = (version.stdout + version.stderr).strip()
        docker("exec", self.web, "nginx", "-t")
        rendered = docker("exec", self.web, "cat", "/etc/nginx/conf.d/default.conf")
        if not self.args.dns_only:
            for token in (
                "$api_upstream",
                "$request_uri",
                "$http_upgrade",
                "$connection_upgrade",
                "$host",
                "$scheme",
                "$remote_addr",
                "$uri",
            ):
                require(token in rendered, f"envsubst removed {token}")
            require(
                "${API_ACCESS_KEY}" not in rendered and "d02-mock-key" in rendered,
                "API key substitution failed",
            )
            require(
                "client_max_body_size 2m;" in rendered,
                "upload size substitution failed",
            )
            for location in ("location = /v1/evidence/assets {", "location /v1/ {"):
                block = rendered.split(location, 1)[1].split("\n  }", 1)[0]
                for directive in (
                    "proxy_connect_timeout 30s;",
                    "proxy_read_timeout 900s;",
                    "proxy_send_timeout 900s;",
                    "proxy_http_version 1.1;",
                ):
                    require(directive in block, f"{location} missing {directive}")
            self.passed("real image entrypoint/envsubst and nginx -t")
        self.before = self.process_state()

    def routes(self, instance):
        for path in (
            "/v1/echo/a%2Fb/%E4%B8%AD?x=a%2Bb&x=%2F&empty=",
            "/v1/echo//double?value=%252F",
            "/health?probe=a%2Bb",
        ):
            status, headers, body = self.request(
                path,
                headers=self.client_headers(),
            )
            data = json.loads(body)
            require(
                status == 200 and data["path"] == path and data["instance"] == instance,
                f"path/instance changed: {data}",
            )
            if path.startswith("/v1/"):
                self.private(headers)
                self.upstream_headers(data["headers"])
        for path in (
            "/v1/internal/worker",
            "/v1/internal/worker/jobs?x=1",
            "/v1/internal%2Fworker/jobs",
            "/v1/internal/worker-suffix",
        ):
            require(self.request(path)[0] == 404, f"worker route exposed: {path}")
        status, headers, body = self.request("/interviews/spa-deep-link")
        require(status == 200 and b"<html" in body, "SPA fallback broken")
        require(
            not any(k.lower() == "cache-control" for k, _ in headers),
            "SPA caching scope changed",
        )
        self.passed(
            f"URI/query, health, auth headers, worker blocking and SPA ({instance})"
        )

    def caching(self):
        for path, expected in [("/v1/auth/login", 200)] + [
            (f"/v1/status/{status}", status) for status in (302, 401, 403, 404, 500)
        ]:
            status, headers, _ = self.request(path, https=True)
            require(status == expected, f"wrong HTTPS status for {path}: {status}")
            self.private(headers)
            if path == "/v1/auth/login":
                require("Secure" in dict(headers)["Set-Cookie"], "Set-Cookie lost")
            if expected == 302:
                require(
                    "signature=mock" in dict(headers)["Location"],
                    "signed redirect lost",
                )
        status, headers, body = self.request(
            "/v1/media/file", https=True, headers={"Range": "bytes=2-5"}
        )
        require(
            status == 206
            and body == b"2345"
            and dict(headers)["Content-Range"] == "bytes 2-5/10",
            "Range streaming broken",
        )
        self.private(headers)
        self.passed(
            "HTTPS private cache policy on 200/206/302/401/403/404/500, cookies and Range"
        )

    def upload(self, instance):
        body = b"d02-upload-data-" * 80000  # Above nginx's default 1 MiB limit.
        path = "/v1/evidence/assets?name=a%2Bb&name=%E4%B8%AD"
        conn = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=5)
        try:
            conn.putrequest("POST", path)
            conn.putheader("Content-Length", str(len(body)))
            conn.putheader("Content-Type", "application/octet-stream")
            for name, value in self.client_headers().items():
                conn.putheader(name, value)
            conn.endheaders()
            conn.send(body[:4096])
            for _ in range(30):
                if json.loads(self.request("/v1/upload-progress")[2])["bytes"] == 4096:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("upload buffered before reaching mock")
            conn.send(body[4096:])
            response = conn.getresponse()
            self.private(response.getheaders())
            data = json.loads(response.read())
            self.upstream_headers(data["headers"])
            require(data["version"] == "HTTP/1.1", "upload upstream HTTP/1.1 lost")
            require(
                response.status == 200
                and data["instance"] == instance
                and data["path"] == path,
                "upload routing failed",
            )
            require(
                data["bytes"] == len(body)
                and data["sha256"] == hashlib.sha256(body).hexdigest(),
                "upload body corrupted",
            )
        finally:
            conn.close()
        status, headers, _ = self.request(
            "/v1/evidence/assets",
            method="POST",
            headers={"Content-Length": str(2 * 1024 * 1024 + 1)},
        )
        require(status == 413, f"configured upload limit ignored: {status}")
        self.private(headers)
        self.passed(
            f"streaming upload >1 MiB, SHA256, query and 413 limit ({instance})"
        )

    def slow_upload(self):
        print(
            "Checking upload verification with 65s of upstream silence...", flush=True
        )
        started = time.monotonic()
        status, headers, body = self.request(
            "/v1/evidence/assets?verify=slow",
            https=True,
            method="POST",
            body=b"synthetic verification payload",
            headers=self.client_headers(),
            timeout=80,
        )
        elapsed = time.monotonic() - started
        require(status == 200, f"slow upload failed: {status}, {elapsed}s")
        data = json.loads(body)
        # Measure silence on the mock's clock, independently of the host clock.
        require(data["verify_seconds"] >= 65, "mock did not wait beyond 60s")
        self.private(headers)
        self.upstream_headers(data["headers"])
        self.report["slow_upload"] = {
            "status": status,
            "host_seconds": round(elapsed, 3),
            "upstream_silence_seconds": round(data["verify_seconds"], 3),
        }
        self.passed(
            "HTTPS upload verification survives 65s silence; trusted IP and internal headers"
        )

    def websocket(self, instance):
        path = "/v1/interviews/mock/live?value=a%2Bb"
        with (
            socket.create_connection(("127.0.0.1", self.https_port), timeout=5) as raw,
            self.tls.wrap_socket(raw, server_hostname="localhost") as sock,
        ):
            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall(
                (
                    f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            with sock.makefile("rb") as stream:
                require(b" 101 " in stream.readline(), "WSS upgrade failed")
                headers = {}
                while True:
                    line = stream.readline()
                    if line == b"\r\n":
                        break
                    require(bool(line), "truncated handshake")
                    name, value = line.decode().split(":", 1)
                    headers[name.lower()] = value.strip()
                accept = base64.b64encode(
                    hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                    ).digest()
                ).decode()
                require(
                    headers["sec-websocket-accept"] == accept,
                    "invalid WS handshake",
                )
                payload, mask = b"d02-echo", os.urandom(4)
                sock.sendall(
                    bytes([0x81, 0x80 | len(payload)])
                    + mask
                    + bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
                )
                opcode, size = stream.read(2)
                require(opcode == 0x81, "not a text frame")
                if size == 126:
                    size = struct.unpack("!H", stream.read(2))[0]
                data = json.loads(stream.read(size))
                require(
                    data
                    == {
                        "instance": instance,
                        "path": path,
                        "message": "d02-echo",
                        "version": "HTTP/1.1",
                    },
                    "WSS echo changed",
                )
        self.passed(f"WSS 101 handshake and bidirectional frame ({instance})")

    def rollover(self):
        # Prime the old address immediately before replacement. Leave its HTTP
        # server reachable at that IP, but remove its api DNS alias. This detects
        # stale routing without a 30s connect timeout masking the DNS TTL.
        require(
            json.loads(self.request("/health")[2])["instance"] == "old",
            "old upstream not primed",
        )
        old_ip = self.ip(self.old)
        new = self.mock("new")
        new_ip = self.ip(new)
        require(old_ip != new_ip, "test did not change API IP")
        docker("network", "disconnect", self.network, self.old)
        docker("network", "connect", "--ip", old_ip, self.network, self.old)
        dns = docker(
            "exec",
            new,
            "python",
            "-c",
            "import socket,json; print(json.dumps(socket.gethostbyname_ex('api')[2]))",
        )
        require(set(json.loads(dns)) == {new_ip}, f"unexpected Docker DNS: {dns}")
        started = time.monotonic()
        samples = []
        while time.monotonic() - started < 15:
            try:
                status, _, body = self.request("/health")
                instance = (
                    json.loads(body)["instance"] if status == 200 else str(status)
                )
            except (OSError, ValueError, http.client.HTTPException) as exc:
                instance = type(exc).__name__
            samples.append(
                {"seconds": round(time.monotonic() - started, 3), "instance": instance}
            )
            if instance == "new":
                break
            time.sleep(0.25)
        self.report["rollover"] = {
            "old_ip": old_ip,
            "new_ip": new_ip,
            "dns": json.loads(dns),
            "seconds": round(time.monotonic() - started, 3),
            "samples": samples,
        }
        require(
            samples[-1]["instance"] == "new",
            "D02: still routing to old API after 15s without reload",
        )
        # Every request must use the new address, not intermittently fall back.
        for _ in range(20):
            require(
                json.loads(self.request("/v1/echo")[2])["instance"] == "new",
                "stale address reused",
            )
        after = self.process_state()
        self.report["nginx_before"] = self.before
        self.report["nginx_after"] = after
        require(
            after == self.before, "Nginx container/master/workers restarted or reloaded"
        )
        self.passed(
            "API IP rollover and 20 new-upstream reads without Nginx reload/restart"
        )
        return new

    def outage(self, new):
        docker("network", "disconnect", self.network, new)
        time.sleep(6)
        for path in ("/v1/echo", "/v1/evidence/assets", "/health"):
            status, headers, _ = self.request(path, https=True)
            require(status == 502, f"missing API did not return 502: {path}: {status}")
            if path.startswith("/v1/"):
                self.private(headers)
        docker("exec", self.web, "nginx", "-t")
        # Start another Nginx with API DNS absent; dynamic resolution must not
        # require a resolvable API at config load. No published ports needed.
        probe = self.prefix + "-startup"
        self.launch(
            probe,
            self.image,
            "-e",
            "API_ACCESS_KEY=d02-mock-key",
            "-e",
            "NGINX_CLIENT_MAX_BODY_SIZE=2m",
            "-e",
            "NGINX_ENVSUBST_FILTER=" + self.report["envsubst_filter"],
            "--mount",
            f"type=bind,src={self.args.template},dst=/etc/nginx/templates/default.conf.template,readonly",
        )
        for _ in range(30):
            if docker("exec", probe, "cat", "/proc/1/comm") == "nginx":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Nginx did not start with API DNS absent")
        docker("exec", probe, "nginx", "-t")
        docker("network", "connect", "--alias", "api", self.network, new)
        started = time.monotonic()
        for _ in range(60):
            if self.request("/health")[0] == 200:
                break
            time.sleep(0.25)
        else:
            raise AssertionError("API did not recover after NXDOMAIN")
        require(
            self.process_state() == self.before, "Nginx changed during outage recovery"
        )
        self.report["nxdomain_recovery_seconds"] = round(time.monotonic() - started, 3)
        self.passed(
            "DNS absence: HTTPS 502 no-store, cold startup and automatic recovery"
        )

    def cleanup(self):
        errors = []
        for name in reversed(self.containers):
            try:
                docker("rm", "-f", name)
            except RuntimeError as exc:
                errors.append(str(exc))
        if self.network_created:
            try:
                docker("network", "rm", self.network)
            except RuntimeError as exc:
                errors.append(str(exc))
        self.report["cleanup_errors"] = errors
        if errors:
            raise RuntimeError("; ".join(errors))

    def run(self):
        with tempfile.TemporaryDirectory(prefix=self.prefix) as directory:
            try:
                self.setup(Path(directory))
                if not self.args.dns_only:
                    self.routes("old")
                    self.caching()
                    self.upload("old")
                    self.websocket("old")
                new = self.rollover()
                if not self.args.dns_only:
                    self.routes("new")
                    self.upload("new")
                    self.websocket("new")
                    self.slow_upload()
                    self.outage(new)
                self.report["result"] = "passed"
            except Exception as exc:
                self.report["result"] = "failed"
                self.report["error"] = str(exc)
                if hasattr(self, "web"):
                    self.report["nginx_logs"] = docker("logs", self.web)
                raise
            finally:
                try:
                    self.cleanup()
                finally:
                    if self.args.output:
                        self.args.output.parent.mkdir(parents=True, exist_ok=True)
                        self.args.output.write_text(
                            json.dumps(self.report, indent=2) + "\n", encoding="utf-8"
                        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template", type=Path, default=ROOT / "apps/web/nginx.conf.template"
    )
    parser.add_argument("--mock-image", default="python:3.10-slim")
    parser.add_argument(
        "--output", type=Path, help="write sanitized JSON evidence (use tmp/)"
    )
    parser.add_argument(
        "--dns-only",
        action="store_true",
        help="also supports testing the old static template",
    )
    args = parser.parse_args()
    args.template = args.template.resolve()
    Regression(args).run()
