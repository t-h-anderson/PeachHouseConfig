# Finance Scraper

Prometheus textfile metrics for personal finance accounts, scraped automatically
or pushed from a browser extension.

## Scrapers

| Scraper | Method | Schedule | Output |
|---|---|---|---|
| Aegon Retiready | Playwright/Chromium (headless) | Twice daily via cron | `finance.prom` |
| Monzo | REST API | Every 6h via cron | `finance_monzo.prom` |
| Co-op bank | Browser extension push | On login | `finance_manual.prom` |

All `.prom` files are written to `/opt/textfiles/` and picked up by the
node-exporter textfile collector.

## Components

```
scraper.py          Aegon Playwright scraper
monzo.py            Monzo API scraper
import-session.py   Imports Cookie-Editor cookies into Playwright session state
receiver/           HTTP receiver for browser-pushed metrics (port 9107)
browser-extension/  Chrome/Firefox/Kiwi extension — see browser-extension/README.md
```

## Setup

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Start persistent services:

```bash
docker-compose up -d finance-receiver
```

Run scrapers on demand (or let cron handle it):

```bash
docker-compose run --rm finance-scraper   # Aegon
python3 monzo.py                          # Monzo
```

## Browser extension

See [`browser-extension/README.md`](browser-extension/README.md) for install
instructions on Windows, Mac, and Android.
