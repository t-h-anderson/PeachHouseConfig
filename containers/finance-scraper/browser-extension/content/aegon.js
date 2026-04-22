// Runs on https://retiready.co.uk/secure/*
// Finds the Total savings figure and pushes it to the home server.

function extractTotal() {
  // Primary: find the "Total savings" label and grab the adjacent value
  const els = document.querySelectorAll("p, span, div, td, dt, li, h1, h2, h3, h4");
  for (const el of els) {
    if (el.childElementCount > 0) continue; // leaf nodes only
    if (el.innerText?.trim().toLowerCase() !== "total savings") continue;

    const candidates = [
      el.nextElementSibling,
      el.parentElement?.nextElementSibling,
      el.closest("li, tr, dt, dd")?.nextElementSibling,
    ].filter(Boolean);

    for (const c of candidates) {
      const m = c.innerText?.match(/([\d,]+(?:\.\d{2})?)/);
      if (m) {
        const val = parseFloat(m[1].replace(/,/g, ""));
        if (val > 1000) return val; // pension pot sanity check
      }
    }
  }

  // Fallback: largest £ amount on the page
  const amounts = [...document.body.innerText.matchAll(/£\s*([\d,]+(?:\.\d{2})?)/g)]
    .map(m => parseFloat(m[1].replace(/,/g, "")))
    .filter(v => v > 1000);

  return amounts.length > 0 ? Math.max(...amounts) : null;
}

function tryPush() {
  if (!location.pathname.toLowerCase().includes("saving")) return false;

  const value = extractTotal();
  if (value === null) {
    console.log("[finance-sync] Aegon: no value found yet");
    return false;
  }

  console.log(`[finance-sync] Aegon pension: £${value.toLocaleString()}`);
  chrome.runtime.sendMessage(
    { type: "finance_push", metrics: [{ source: "aegon_pension", value }] },
    resp => {
      if (chrome.runtime.lastError) return;
      if (resp?.ok) console.log("[finance-sync] Aegon pushed OK");
      else console.warn("[finance-sync] Aegon push failed:", resp);
    }
  );
  return true;
}

let attempts = 0;
const timer = setInterval(() => {
  if (tryPush() || ++attempts >= 20) clearInterval(timer);
}, 1000);
