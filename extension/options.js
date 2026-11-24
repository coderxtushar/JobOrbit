/* Options page: API address, optional bearer token and dashboard address. */
/* global JOBORBIT_DEFAULTS, joborbitLoadSettings, joborbitIsHttpUrl, joborbitIsLoopbackUrl */

(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function say(text, kind) {
    var message = $("message");
    message.textContent = text;
    message.dataset.kind = kind || "";
  }

  function setConnection(kind, text) {
    var pill = $("connection");
    pill.className = "pill pill-" + kind;
    pill.textContent = text;
  }

  function read() {
    return {
      apiBase: ($("apiBase").value.trim() || JOBORBIT_DEFAULTS.apiBase).replace(/\/+$/, ""),
      apiToken: $("apiToken").value.trim(),
      dashboardUrl: ($("dashboardUrl").value.trim() || JOBORBIT_DEFAULTS.dashboardUrl).replace(/\/+$/, "")
    };
  }

  function validate(values) {
    if (!joborbitIsLoopbackUrl(values.apiBase)) {
      return "The API address must be http://127.0.0.1:<port> or http://localhost:<port>. The extension is only allowed to talk to this computer.";
    }
    if (!joborbitIsHttpUrl(values.dashboardUrl)) {
      return "The dashboard address must start with http:// or https://.";
    }
    return "";
  }

  function test(values) {
    setConnection("muted", "Checking...");
    var headers = { Accept: "application/json" };
    if (values.apiToken) headers.Authorization = "Bearer " + values.apiToken;
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, 3000);
    return fetch(values.apiBase + "/api/capture/status", { headers: headers, signal: controller.signal })
      .then(function (response) {
        if (response.status === 401) {
          setConnection("warn", "Token needed");
          say("JobOrbit is running and requires a token. Enter the value of JA_API_TOKEN.", "warn");
          return;
        }
        if (!response.ok) {
          setConnection("warn", "HTTP " + response.status);
          say("JobOrbit answered HTTP " + response.status + ".", "warn");
          return;
        }
        return response.json().then(function (body) {
          setConnection("ok", "Connected · v" + body.version);
          say(body.demo_mode ? "Connected, but this JobOrbit is in demo mode, so capture is disabled." : "Connected to JobOrbit " + body.version + ".", "ok");
        });
      })
      .catch(function () {
        setConnection("err", "Not running");
        say("Nothing answered at " + values.apiBase + ". Start the API with: .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000", "err");
      })
      .finally(function () {
        clearTimeout(timer);
      });
  }

  $("options").addEventListener("submit", function (event) {
    event.preventDefault();
    var values = read();
    var problem = validate(values);
    if (problem) {
      say(problem, "err");
      return;
    }
    chrome.storage.local.set(values).then(function () {
      say("Saved.", "ok");
    });
  });

  $("test").addEventListener("click", function () {
    var values = read();
    var problem = validate(values);
    if (problem) {
      say(problem, "err");
      return;
    }
    test(values);
  });

  joborbitLoadSettings().then(function (values) {
    $("apiBase").value = values.apiBase;
    $("apiToken").value = values.apiToken;
    $("dashboardUrl").value = values.dashboardUrl;
  });
})();
