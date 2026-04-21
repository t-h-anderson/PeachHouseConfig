#!/usr/bin/env python3
"""Fetch Monzo account balances and write to Prometheus textfile."""

import os
import sys
import urllib.request
import urllib.error
import json
from pathlib import Path
from datetime import datetime

TEXTFILE = Path("/opt/textfiles/finance_monzo.prom")
API = "https://api.monzo.com"


def load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def api_get(path, token):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"[{datetime.now():%H:%M:%S}] Token expired or unauthorised — skipping update")
            sys.exit(0)
        raise


def main():
    load_env()
    token = os.environ["MONZO_ACCESS_TOKEN"]
    personal_id = os.environ["MONZO_PERSONAL_ACCOUNT_ID"]
    joint_id = os.environ["MONZO_JOINT_ACCOUNT_ID"]

    personal = api_get(f"/balance?account_id={personal_id}", token)
    joint = api_get(f"/balance?account_id={joint_id}", token)

    personal_gbp = personal["total_balance"] / 100
    joint_gbp = joint["balance"] / 100

    print(f"[{datetime.now():%H:%M:%S}] Personal (total inc. pots): £{personal_gbp:,.2f}")
    print(f"[{datetime.now():%H:%M:%S}] Joint: £{joint_gbp:,.2f}")

    TEXTFILE.parent.mkdir(parents=True, exist_ok=True)
    TEXTFILE.write_text(
        "# HELP finance_account_balance_gbp Account balance in GBP\n"
        "# TYPE finance_account_balance_gbp gauge\n"
        f'finance_account_balance_gbp{{provider="monzo",account="personal"}} {personal_gbp}\n'
        f'finance_account_balance_gbp{{provider="monzo",account="joint"}} {joint_gbp}\n',
        encoding="utf-8",
    )
    print(f"[{datetime.now():%H:%M:%S}] Written {TEXTFILE}")


if __name__ == "__main__":
    main()
