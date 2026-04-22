#!/usr/bin/env python3
"""HTTP receiver for browser-pushed finance metrics.

Accepts POST /push from the Finance Sync browser extension and updates
the Prometheus textfiles in /opt/textfiles/ in-place.

Aegon  → updates finance.prom       (same file as server scraper; last write wins)
Co-op  → updates finance_manual.prom (regex-replaces the existing balance lines)
"""

import os
import re
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

TEXTFILE_DIR = Path(os.environ.get("TEXTFILE_DIR", "/opt/textfiles"))
PORT = int(os.environ.get("RECEIVER_PORT", "9107"))
TOKEN = os.environ.get("BROWSER_PUSH_TOKEN", "")

COOP_ACCOUNTS = {"joint", "personal", "saving_366"}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def atomic_write(path: Path, content: str):
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def update_aegon(value: float):
    path = TEXTFILE_DIR / "finance.prom"
    atomic_write(
        path,
        "# HELP finance_pension_value_gbp Aegon Retiready pension pot total value in GBP\n"
        "# TYPE finance_pension_value_gbp gauge\n"
        f'finance_pension_value_gbp{{provider="aegon",account="retiready"}} {value}\n',
    )
    log(f"finance.prom updated: aegon/retiready = {value}")


def update_coop(account: str, value: float):
    path = TEXTFILE_DIR / "finance_manual.prom"
    content = path.read_text(encoding="utf-8") if path.exists() else ""

    metric = f'finance_account_balance_gbp{{provider="coop",account="{account}"}}'
    pattern = rf'finance_account_balance_gbp\{{[^}}]*provider="coop"[^}}]*account="{re.escape(account)}"[^}}]*\}} [\d.]+'
    replacement = f'{metric} {value}'

    if re.search(pattern, content):
        content = re.sub(pattern, replacement, content)
    else:
        # Line doesn't exist yet — insert after the TYPE line for this metric family
        type_line = re.search(r'# TYPE finance_account_balance_gbp gauge\n', content)
        if type_line:
            pos = type_line.end()
            content = content[:pos] + replacement + "\n" + content[pos:]
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += (
                "# HELP finance_account_balance_gbp Account balance in GBP\n"
                "# TYPE finance_account_balance_gbp gauge\n"
                f"{replacement}\n"
            )

    atomic_write(path, content)
    log(f"finance_manual.prom updated: coop/{account} = {value}")


def handle_push(metrics: list):
    for entry in metrics:
        source = entry.get("source", "")
        value = entry.get("value")

        if not isinstance(value, (int, float)):
            log(f"Skipping {source}: invalid value {value!r}")
            continue

        if source == "aegon_pension":
            update_aegon(float(value))
        elif source.startswith("coop_"):
            account = source[len("coop_"):]
            if account in COOP_ACCOUNTS:
                update_coop(account, float(value))
            else:
                log(f"Unknown Co-op account: {account}")
        else:
            log(f"Unknown source: {source}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/push":
            self.send_response(404)
            self.end_headers()
            return

        auth = self.headers.get("Authorization", "")
        if TOKEN and auth != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            log(f"Rejected unauthorised push from {self.address_string()}")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        handle_push(data.get("metrics", []))

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")


if __name__ == "__main__":
    TEXTFILE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Receiver listening on :{PORT}")
    if not TOKEN:
        log("WARNING: BROWSER_PUSH_TOKEN not set — endpoint is unprotected")
    HTTPServer(("", PORT), Handler).serve_forever()
