const DEFAULT_ENDPOINT = "http://192.168.68.16:9107";

document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get({ endpoint: DEFAULT_ENDPOINT, token: "" }, ({ endpoint, token }) => {
    document.getElementById("endpoint").value = endpoint;
    document.getElementById("token").value = token;
  });

  document.getElementById("save").addEventListener("click", () => {
    const endpoint = document.getElementById("endpoint").value.trim();
    const token = document.getElementById("token").value.trim();
    const status = document.getElementById("status");

    chrome.storage.local.set({ endpoint, token }, () => {
      status.textContent = "Saved.";
      status.className = "ok";
      setTimeout(() => { status.textContent = ""; }, 2000);
    });
  });
});
