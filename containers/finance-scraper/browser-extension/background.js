const DEFAULT_ENDPOINT = "http://192.168.68.16:9107";

function getConfig() {
  return new Promise(resolve =>
    chrome.storage.local.get({ endpoint: DEFAULT_ENDPOINT, token: "" }, resolve)
  );
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "finance_push") return false;

  (async () => {
    const { endpoint, token } = await getConfig();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    try {
      const resp = await fetch(`${endpoint}/push`, {
        method: "POST",
        headers,
        body: JSON.stringify({ metrics: message.metrics }),
      });
      if (resp.ok) {
        console.log("[finance-sync] Pushed:", message.metrics);
        sendResponse({ ok: true });
      } else {
        console.error("[finance-sync] Server returned", resp.status);
        sendResponse({ ok: false, status: resp.status });
      }
    } catch (err) {
      console.error("[finance-sync] Push failed:", err.message);
      sendResponse({ ok: false, error: err.message });
    }
  })();

  return true; // keep channel open for async sendResponse
});
