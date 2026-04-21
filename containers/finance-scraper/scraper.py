#!/usr/bin/env python3
"""Scrape Aegon Retiready pension total and write to Prometheus textfile."""

import os
import re
import time
import random
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://retiready.co.uk/public/sign-in.html"
TEXTFILE = Path("/opt/textfiles/finance.prom")
STATE_DIR = Path("/state")
SESSION_FILE = STATE_DIR / "session.json"
SCREENSHOT_DIR = STATE_DIR / "screenshots"


def delay(lo=0.8, hi=2.5):
    time.sleep(random.uniform(lo, hi))


def dismiss_cookie_banner(page):
    for selector in [
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('Continue')",
        "button:has-text('I agree')",
        "[id*='cookie'] button",
        "[class*='cookie'] button",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1_500):
                btn.click()
                delay(0.5, 1.0)
                print(f"[{datetime.now():%H:%M:%S}] Dismissed cookie banner")
                return
        except Exception:
            continue


def type_humanlike(field, text):
    field.click()
    delay(0.2, 0.5)
    for char in text:
        field.type(char, delay=random.randint(40, 130))


def do_login(page, email, password):
    print(f"[{datetime.now():%H:%M:%S}] Navigating to login page...")
    page.goto(LOGIN_URL, wait_until="networkidle")
    delay(2.0, 4.0)

    dismiss_cookie_banner(page)
    delay(1.0, 2.0)

    type_humanlike(page.get_by_label("Email"), email)
    delay(0.5, 1.2)
    type_humanlike(page.get_by_label("Password"), password)
    delay(1.0, 2.5)

    page.screenshot(path=str(SCREENSHOT_DIR / "01_pre_login.png"))

    page.get_by_role("button", name=re.compile(r"sign.?in", re.I)).click()

    try:
        page.wait_for_url(lambda url: "sign-in" not in url, timeout=30_000)
    except Exception:
        page.screenshot(path=str(SCREENSHOT_DIR / "02_login_failed.png"))
        raise RuntimeError("Login failed or timed out — check screenshots/02_login_failed.png")

    delay(2.0, 3.5)
    print(f"[{datetime.now():%H:%M:%S}] Logged in, now at: {page.url}")


SAVINGS_URL = "https://retiready.co.uk/secure/savings.html"


def extract_total(page):
    """Navigate to savings page and extract the Total savings figure."""
    if page.url != SAVINGS_URL:
        page.goto(SAVINGS_URL, wait_until="networkidle")
        delay(2.0, 3.5)

    page.screenshot(path=str(SCREENSHOT_DIR / "03_savings.png"))
    (SCREENSHOT_DIR / "savings.html").write_text(page.content(), encoding="utf-8")

    # "Total savings" sidebar item: heading followed immediately by the value
    # e.g. <p>Total savings</p><p>£200,981.42</p>
    total_el = page.locator("text=Total savings").locator("xpath=following-sibling::*[1] | ../following-sibling::*[1]").first
    raw = None
    try:
        raw = total_el.inner_text(timeout=5_000).strip()
    except Exception:
        pass

    if raw:
        match = re.search(r"([\d,]+(?:\.\d{2})?)", raw)
        if match:
            total = float(match.group(1).replace(",", ""))
            print(f"[{datetime.now():%H:%M:%S}] Total savings (targeted): £{total:,.2f}")
            return total

    # Fallback: largest £ amount on page
    print(f"[{datetime.now():%H:%M:%S}] Targeted selector missed — falling back to largest amount")
    amounts = re.findall(r"£\s*([\d,]+(?:\.\d{2})?)", page.inner_text("body"))
    if not amounts:
        raise RuntimeError("No £ amounts found — inspect savings.html and 03_savings.png")
    values = [float(a.replace(",", "")) for a in amounts]
    total = max(values)
    print(f"[{datetime.now():%H:%M:%S}] Total savings (fallback): £{total:,.2f}")
    return total


def write_textfile(total):
    TEXTFILE.parent.mkdir(parents=True, exist_ok=True)
    TEXTFILE.write_text(
        "# HELP finance_pension_value_gbp Aegon Retiready pension pot total value in GBP\n"
        "# TYPE finance_pension_value_gbp gauge\n"
        f'finance_pension_value_gbp{{provider="aegon",account="retiready"}} {total}\n',
        encoding="utf-8",
    )
    print(f"[{datetime.now():%H:%M:%S}] Written {TEXTFILE}")


def main():
    email = os.environ["AEGON_EMAIL"]
    password = os.environ["AEGON_PASSWORD"]

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        ctx_kwargs = dict(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )

        if SESSION_FILE.exists():
            ctx_kwargs["storage_state"] = str(SESSION_FILE)

        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        if SESSION_FILE.exists():
            page.goto("https://retiready.co.uk/secure/savings", wait_until="networkidle")
            delay(1.5, 2.5)
            if "sign-in" in page.url:
                print(f"[{datetime.now():%H:%M:%S}] Session expired — logging in again")
                SESSION_FILE.unlink()
                ctx.close()
                ctx = browser.new_context(**{k: v for k, v in ctx_kwargs.items() if k != "storage_state"})
                page = ctx.new_page()
                do_login(page, email, password)
            else:
                print(f"[{datetime.now():%H:%M:%S}] Reusing saved session")
        else:
            do_login(page, email, password)

        ctx.storage_state(path=str(SESSION_FILE))

        total = extract_total(page)
        write_textfile(total)

        browser.close()


if __name__ == "__main__":
    main()
