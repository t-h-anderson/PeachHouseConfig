#!/usr/bin/env python3
"""Convert a Cookie-Editor JSON export to Playwright storage_state format.

Usage:
    python import-session.py cookies.json

Get cookies.json by:
1. Install Cookie-Editor extension (Chrome/Firefox)
2. Log into retiready.co.uk in your real browser
3. Click Cookie-Editor icon → Export → Export as JSON
4. Save the file and copy it to this directory
5. Run this script
"""

import json
import sys
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"
SESSION_FILE = STATE_DIR / "session.json"

SAMSITE_MAP = {"strict": "Strict", "lax": "Lax", "no_restriction": "None", "unspecified": "None"}


def convert(cookie_editor_cookies):
    converted = []
    for c in cookie_editor_cookies:
        converted.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", "retiready.co.uk"),
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate", c.get("expires", -1)),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", True),
            "sameSite": SAMSITE_MAP.get((c.get("sameSite") or "lax").lower(), "Lax"),
        })
    return {"cookies": converted, "origins": []}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} cookies.json")
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    raw = json.loads(src.read_text())
    state = convert(raw)

    STATE_DIR.mkdir(exist_ok=True)
    SESSION_FILE.write_text(json.dumps(state, indent=2))
    print(f"Written {len(state['cookies'])} cookies to {SESSION_FILE}")
    print("Run the scraper now — it will skip login and use this session.")
