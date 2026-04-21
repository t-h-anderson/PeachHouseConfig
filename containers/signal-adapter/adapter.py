"""
Thin adapter: translates OpenClaw's /api/v1/ Signal HTTP protocol
to/from the bbernhard signal-cli-rest-api at SIGNAL_API.

Polling runs in a background thread and pushes messages into a queue.
SSE handler reads from the queue and sends keepalive comments so the
connection stays alive during slow /v1/receive calls (can take 80s+).
"""

import json
import queue
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
import urllib.request

SIGNAL_API = os.environ.get("SIGNAL_API", "http://192.168.68.16:8080")
ACCOUNT = os.environ.get("SIGNAL_ACCOUNT", "+447873395430")
PORT = int(os.environ.get("PORT", "8082"))
KEEPALIVE_INTERVAL = 15  # seconds between SSE keepalive comments


def signal_get(path):
    with urllib.request.urlopen(f"{SIGNAL_API}{path}", timeout=120) as r:
        return json.loads(r.read())


def signal_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{SIGNAL_API}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read()
        return json.loads(text) if text else {}


# Per-account: background poller + set of subscriber queues
_pollers = {}   # account -> PollerState
_pollers_lock = threading.Lock()


class PollerState:
    def __init__(self, account):
        self.account = account
        self.subscribers = set()  # set of queue.Queue
        self.lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def subscribe(self):
        q = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subscribers.discard(q)

    def _broadcast(self, item):
        with self.lock:
            for q in self.subscribers:
                try:
                    q.put_nowait(item)
                except queue.Full:
                    pass  # slow consumer; drop rather than block

    def _run(self):
        print(f"poller started for {self.account}", flush=True)
        while True:
            try:
                messages = signal_get(f"/v1/receive/{self.account}")
                for msg in (messages or []):
                    envelope = msg.get("envelope", {})
                    if envelope.get("dataMessage") or envelope.get("syncMessage"):
                        self._broadcast(json.dumps(msg))
            except Exception as e:
                print(f"poller error ({self.account}): {e}", flush=True)
                time.sleep(2)


def get_poller(account):
    with _pollers_lock:
        if account not in _pollers:
            _pollers[account] = PollerState(account)
        return _pollers[account]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/check":
            self.send_json(200, {"ok": True})

        elif parsed.path == "/api/v1/events":
            account = parse_qs(parsed.query).get("account", [ACCOUNT])[0]
            poller = get_poller(account)
            q = poller.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    try:
                        data = q.get(timeout=KEEPALIVE_INTERVAL)
                        self.wfile.write(
                            f"event: receive\ndata: {data}\n\n".encode()
                        )
                        self.wfile.flush()
                    except queue.Empty:
                        # Send keepalive comment so the connection doesn't time out
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                poller.unsubscribe(q)
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/v1/rpc":
            self.send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        method = req.get("method", "")
        params = req.get("params") or {}
        req_id = req.get("id")
        account = params.get("account", ACCOUNT) if isinstance(params, dict) else ACCOUNT

        try:
            if method == "version":
                about = signal_get("/v1/about")
                self.send_json(200, {"jsonrpc": "2.0", "result": {"version": about.get("version", "0.98")}, "id": req_id})

            elif method == "send":
                recipients = params.get("recipient", [])
                body = {
                    "message": params.get("message", ""),
                    "number": account,
                    "recipients": recipients,
                }
                result = signal_post("/v2/send", body)
                self.send_json(200, {"jsonrpc": "2.0", "result": result, "id": req_id})

            elif method in ("sendTyping", "sendReceipt"):
                self.send_response(201)
                self.end_headers()

            else:
                self.send_json(200, {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"unknown method: {method}"}, "id": req_id})

        except Exception as e:
            self.send_json(200, {"jsonrpc": "2.0", "error": {"code": -1, "message": str(e)}, "id": req_id})


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"signal-adapter listening on :{PORT} → {SIGNAL_API}", flush=True)
    server.serve_forever()
