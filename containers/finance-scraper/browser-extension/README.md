# Finance Sync — Browser Extension

Automatically pushes Aegon pension and Co-op bank balances to the home server
whenever you visit those sites. No credentials stored; it reads values from the
already-authenticated page.

## How it works

| Site | Trigger | Metric updated |
|---|---|---|
| `retiready.co.uk/secure/*` | Savings page loads | `finance.prom` → `finance_pension_value_gbp` |
| `co-operativebank.co.uk/*` | Accounts overview loads | `finance_manual.prom` → `finance_account_balance_gbp` |

Content scripts run inside your already-logged-in browser session, extract the
displayed values, and POST them to the `finance-receiver` service running on the
home server. The receiver updates the Prometheus textfiles in-place so Grafana
picks up the new values on its next scrape.

---

## Prerequisites — start the receiver on the server

1. Add a token to `/opt/containers/finance-scraper/.env`:
   ```
   BROWSER_PUSH_TOKEN=some-long-random-secret
   ```
   Generate one with: `python3 -c "import secrets; print(secrets.token_hex(20))"`

2. Start the receiver:
   ```bash
   cd /opt/containers/finance-scraper
   docker-compose up -d finance-receiver
   ```
   It listens on port **9107**.

---

## Installing the extension

### Windows & Mac — Chrome or Edge

1. Download or clone this repo to your machine
2. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge)
3. Enable **Developer mode** (toggle, top-right)
4. Click **Load unpacked**
5. Select the `browser-extension/` folder
6. The Finance Sync icon appears in the toolbar

> The extension persists across browser restarts. To update it after pulling new
> changes, go back to `chrome://extensions` and click the refresh icon on the card.

### Windows & Mac — Firefox

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on…**
3. Select `browser-extension/manifest.json`

> **Limitation:** Firefox removes temporary add-ons on browser restart. For a
> permanent install on desktop Firefox, you would need to sign the extension via
> AMO (out of scope for personal use). Reloading it takes ~10 seconds and is
> only needed when you reboot.

### Android — Kiwi Browser (recommended)

Kiwi Browser is a Chromium-based Android browser that supports loading unpacked
Chrome extensions — the same extension files work without modification.

1. Install **Kiwi Browser** from the Play Store
2. On your computer, zip the `browser-extension/` folder:
   ```bash
   cd Finance-Scraper
   zip -r finance-sync.zip browser-extension/
   ```
3. Transfer `finance-sync.zip` to your Android device (AirDrop, Google Drive,
   USB, etc.)
4. In Kiwi Browser, open the menu (⋮) → **Extensions**
5. Enable **Developer mode**
6. Tap **Load unpacked (zip)** and select `finance-sync.zip`
7. The extension appears in the extensions list

> If Kiwi shows an error about the manifest version, the extension may need
> to be converted to MV2 — open an issue and we can provide a Kiwi-compatible
> build.

### Android — Firefox Nightly (alternative)

Firefox Nightly supports loading extensions from a custom AMO collection without
publishing publicly.

1. Install **Firefox Nightly** from the Play Store
2. Go to Settings → About Firefox Nightly → tap the Firefox logo **5 times**
3. A "Debug menu enabled" toast appears; go back to Settings
4. Tap **Custom Add-on collection** and enter your AMO user ID and a collection
   name containing this extension
5. Firefox restarts and shows the extension in your collection

> This requires publishing the extension to an AMO collection (even a private
> one). For most users, Kiwi Browser above is simpler.

---

## Configuring the endpoint

After installing, click the **Finance Sync icon** in the toolbar:

- **Server endpoint:** `http://192.168.68.16:9107`
  (use your Tailscale IP `http://100.119.249.10:9107` when off the home network)
- **Auth token:** the value of `BROWSER_PUSH_TOKEN` from the server `.env`

Click **Save**.

---

## Testing

1. Log into [retiready.co.uk](https://retiready.co.uk) and navigate to the
   Savings page
2. Open DevTools → Console (F12) and look for `[finance-sync]` lines:
   ```
   [finance-sync] Aegon pension: £201,231
   [finance-sync] Aegon pushed OK
   ```
3. Verify on the server: `cat /opt/textfiles/finance.prom`

Repeat for Co-op — log in and navigate to the accounts overview page.

---

## Troubleshooting Co-op selectors

Co-op's banking UI is a React SPA. If accounts aren't detected, the console will
show what was (or wasn't) found:

```
[finance-sync] Card match: coop_joint = £144.04 (via "[class*='AccountCard']")
```

If nothing matches:

1. Open DevTools → Elements on the Co-op accounts overview page
2. Find the element wrapping a single account card
3. Note its tag, class, or `data-` attribute
4. Add it to `CARD_SELECTORS` near the top of `content/coop.js`
5. Reload the extension and refresh the page

The keyword matching in `ACCOUNT_PATTERNS` handles the three known accounts by
text in the account name:

| Source key | Matched keywords |
|---|---|
| `coop_saving_366` | `366`, `notice sav` |
| `coop_joint` | `joint` |
| `coop_personal` | `everyday extra`, `current`, `personal` |

If your account names differ from these, update the `keywords` arrays accordingly.

---

## Cleanup — removing manual Co-op entries

Once the extension is reliably pushing Co-op balances, the manually-entered lines
in `finance_manual.prom` are overwritten automatically on each push. No cleanup is
strictly required, but to stop using `finance-manual` for Co-op:

```bash
finance-manual remove balance coop joint
finance-manual remove balance coop personal
finance-manual remove balance coop saving_366
```
