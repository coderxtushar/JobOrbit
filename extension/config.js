/* Shared settings for the popup and the options page. Stored in chrome.storage.local only. */

// eslint-disable-next-line no-unused-vars
var JOBORBIT_DEFAULTS = {
  apiBase: "http://127.0.0.1:8000",
  apiToken: "",
  dashboardUrl: "http://localhost:8501"
};

// The extension's host permissions cover loopback only, so an API address anywhere else
// could never be reached (and must not be: the token would leave the machine).
// eslint-disable-next-line no-unused-vars
function joborbitIsLoopbackUrl(raw) {
  try {
    var url = new URL(raw);
    return url.protocol === "http:" && (url.hostname === "127.0.0.1" || url.hostname === "localhost");
  } catch (error) {
    return false;
  }
}

// eslint-disable-next-line no-unused-vars
function joborbitIsHttpUrl(raw) {
  try {
    var url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (error) {
    return false;
  }
}

// eslint-disable-next-line no-unused-vars
function joborbitLoadSettings() {
  return chrome.storage.local.get(JOBORBIT_DEFAULTS).then(function (stored) {
    return {
      apiBase: String(stored.apiBase || JOBORBIT_DEFAULTS.apiBase).replace(/\/+$/, ""),
      apiToken: String(stored.apiToken || ""),
      dashboardUrl: String(stored.dashboardUrl || JOBORBIT_DEFAULTS.dashboardUrl).replace(/\/+$/, "")
    };
  });
}
