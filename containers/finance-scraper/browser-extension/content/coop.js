// Runs on co-operativebank.co.uk pages.
// Finds account name + balance pairs and pushes matched accounts to the home server.
//
// If accounts aren't detected on first run, open DevTools → Console and look for
// "[finance-sync]" lines — they show what text was found and why matching failed.
// Adjust ACCOUNT_PATTERNS or add selectors to CARD_SELECTORS as needed.

const ACCOUNT_PATTERNS = [
  // More specific patterns first to avoid mismatches
  { source: "coop_saving_366", keywords: ["366", "notice sav"] },
  { source: "coop_joint",      keywords: ["joint"] },
  { source: "coop_personal",   keywords: ["everyday extra", "current", "personal"] },
];

// Selectors that typically wrap a single account card in banking UIs.
// Co-op Bank uses React; these cover common patterns without knowing the exact class names.
const CARD_SELECTORS = [
  "[data-testid*='account']",
  "[class*='AccountCard']",
  "[class*='account-card']",
  "[class*='account-tile']",
  "[class*='AccountTile']",
  "[class*='ProductCard']",
  "article",
  "[role='listitem']",
  "[role='article']",
];

function matchSource(text) {
  const lower = text.toLowerCase();
  for (const { source, keywords } of ACCOUNT_PATTERNS) {
    if (keywords.some(k => lower.includes(k))) return source;
  }
  return null;
}

function extractAmount(text) {
  const m = text.match(/£\s*([\d,]+(?:\.\d{2})?)/);
  return m ? parseFloat(m[1].replace(/,/g, "")) : null;
}

function scrapeCards() {
  const metrics = [];
  const seen = new Set();

  for (const sel of CARD_SELECTORS) {
    const cards = document.querySelectorAll(sel);
    if (!cards.length) continue;

    for (const card of cards) {
      const text = card.innerText || "";
      const source = matchSource(text);
      if (!source || seen.has(source)) continue;

      const value = extractAmount(text);
      if (value === null) continue;

      console.log(`[finance-sync] Card match: ${source} = £${value} (via "${sel}")`);
      metrics.push({ source, value });
      seen.add(source);
    }

    if (metrics.length > 0) return metrics;
  }

  return metrics;
}

function scrapeFullPage() {
  // Fallback: scan the full page text for account name + nearby £ amount.
  const metrics = [];
  const seen = new Set();
  const body = document.body.innerText;

  for (const { source, keywords } of ACCOUNT_PATTERNS) {
    if (seen.has(source)) continue;
    for (const kw of keywords) {
      const idx = body.toLowerCase().indexOf(kw);
      if (idx === -1) continue;

      // Look for a £ amount within 200 chars after the keyword
      const window = body.slice(idx, idx + 200);
      const value = extractAmount(window);
      if (value !== null) {
        console.log(`[finance-sync] Fullpage match: ${source} = £${value} (keyword "${kw}")`);
        metrics.push({ source, value });
        seen.add(source);
        break;
      }
    }
  }

  return metrics;
}

function tryPush() {
  let metrics = scrapeCards();
  if (metrics.length === 0) metrics = scrapeFullPage();
  if (metrics.length === 0) return false;

  chrome.runtime.sendMessage({ type: "finance_push", metrics }, resp => {
    if (chrome.runtime.lastError) return;
    if (resp?.ok) console.log(`[finance-sync] Co-op: pushed ${metrics.length} account(s)`);
    else console.warn("[finance-sync] Co-op push failed:", resp);
  });
  return true;
}

// Poll until balances appear (SPAs render asynchronously)
let attempts = 0;
const timer = setInterval(() => {
  if (tryPush() || ++attempts >= 20) clearInterval(timer);
}, 1500);
