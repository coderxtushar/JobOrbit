/*
 * Popup: runs only while the user has the popup open, which only happens on a click.
 *
 * 1. Injects extractor.js into the active tab (allowed by the activeTab grant that the
 *    click itself creates) and fills the form with what it found.
 * 2. The user checks or edits the fields and presses "Send to JobOrbit".
 * 3. The listing is posted to the local JobOrbit API, and the result is shown.
 *
 * Everything rendered from the page or the API goes through textContent, never innerHTML.
 */
/* global JOBORBIT_DEFAULTS, joborbitLoadSettings, joborbitIsHttpUrl, joborbitIsLoopbackUrl */

(function () {
  "use strict";

  var FIELDS = ["title", "company", "location", "url", "posted_at", "employment_type", "description"];
  var REQUIRED = ["title", "company", "url"];
  var FIELD_LABELS = {
    title: "title",
    company: "company",
    location: "location",
    description: "description",
    posted_at: "posted date",
    employment_type: "employment type",
    url: "URL"
  };
  var METHOD_LABELS = {
    "json-ld": "the page's structured job data (JSON-LD)",
    "site:linkedin": "LinkedIn's job view",
    "site:naukri": "Naukri's job page",
    "site:indeed": "Indeed's job page",
    "site:wellfound": "Wellfound's job page",
    generic: "the page heading and meta tags",
    none: "nothing on this page"
  };
  var BAND_LABELS = { high: "strong match", review: "worth a review", low: "weak match" };
  var START_COMMAND = ".venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000";

  var settings = Object.assign({}, JOBORBIT_DEFAULTS);
  var extracted = null;
  var pageUrl = "";
  var sourceHint = "";

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function setConnection(kind, text) {
    var pill = $("connection");
    pill.className = "pill pill-" + kind;
    pill.textContent = text;
  }

  function showResult(kind, nodes) {
    var box = $("result");
    box.className = "result " + kind;
    box.replaceChildren.apply(box, nodes);
    box.hidden = false;
    box.scrollIntoView({ block: "nearest" });
  }

  function unreachableNodes() {
    return [
      el("h2", "Can't reach JobOrbit"),
      el("p", "Nothing answered at " + settings.apiBase + ". Start JobOrbit's API (see the README):"),
      el("p", null).appendChild(el("code", START_COMMAND)).parentNode,
      el("p", "If it runs on a different port, change the API address in Options.")
    ];
  }

  function tokenNodes() {
    return [
      el("h2", "A token is needed"),
      el(
        "p",
        "JobOrbit is running with an API token (JA_API_TOKEN). Paste the same value into " +
          "Options, then try again."
      )
    ];
  }

  function headers(json) {
    var result = { Accept: "application/json" };
    if (json) result["Content-Type"] = "application/json";
    if (settings.apiToken) result.Authorization = "Bearer " + settings.apiToken;
    return result;
  }

  function request(path, options, timeoutMs) {
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, timeoutMs);
    return fetch(settings.apiBase + path, Object.assign({ signal: controller.signal }, options)).finally(
      function () {
        clearTimeout(timer);
      }
    );
  }

  function readJson(response) {
    return response.json().catch(function () {
      return {};
    });
  }

  // ------------------------------------------------------------ connection ---------

  function checkStatus() {
    if (!joborbitIsLoopbackUrl(settings.apiBase)) {
      setConnection("err", "Bad API address");
      return Promise.resolve();
    }
    return request("/api/capture/status", { headers: headers(false) }, 3000)
      .then(function (response) {
        if (response.status === 401) {
          setConnection("warn", "Token needed");
          return;
        }
        if (!response.ok) {
          setConnection("warn", "HTTP " + response.status);
          return;
        }
        return readJson(response).then(function (body) {
          if (body.demo_mode) setConnection("warn", "Demo mode: capture off");
          else setConnection("ok", "Connected" + (body.version ? " · v" + body.version : ""));
        });
      })
      .catch(function () {
        setConnection("err", "Not running");
      });
  }

  // ------------------------------------------------------------ extraction ---------

  function extract() {
    return chrome.tabs.query({ active: true, currentWindow: true }).then(function (tabs) {
      var tab = tabs && tabs[0];
      if (!tab || tab.id == null) throw new Error("no active tab");
      var target = { tabId: tab.id };
      return chrome.scripting.executeScript({ target: target, files: ["extractor.js"] }).then(function (results) {
        var data = results && results[0] && results[0].result;
        if (data && typeof data === "object") return data;
        // Fallback for a browser that does not return a file's completion value: the file
        // has defined joborbitExtract in this extension's isolated world, so call it.
        return chrome.scripting
          .executeScript({
            target: target,
            func: function () {
              /* global joborbitExtract */
              return joborbitExtract(document, location);
            }
          })
          .then(function (again) {
            return again && again[0] && again[0].result;
          });
      });
    });
  }

  function fill(data) {
    extracted = data;
    pageUrl = joborbitIsHttpUrl(data.page_url || "") ? data.page_url : "";
    sourceHint = data.source_hint || "";
    FIELDS.forEach(function (field) {
      $(field).value = data[field] || "";
    });
    markMissing();
    updateCounter();

    var info = data.extraction || {};
    var how = METHOD_LABELS[info.method] || info.method || "the page";
    var missing = (info.missing || []).map(function (name) {
      return FIELD_LABELS[name] || name;
    });
    var text = "Read from " + how;
    if (typeof info.confidence === "number" && info.method !== "none") {
      text += ", confidence " + Math.round(info.confidence * 100) + "%";
    }
    text += ".";
    if (missing.length) text += " Not found: " + missing.join(", ") + ".";
    text += " Check the fields before sending.";
    $("extraction").textContent = text;
  }

  function markMissing() {
    FIELDS.forEach(function (field) {
      var input = $(field);
      var empty = !input.value.trim();
      input.classList.toggle("missing", empty && REQUIRED.indexOf(field) !== -1);
    });
  }

  function updateCounter() {
    var length = $("description").value.length;
    $("counter").textContent = length ? length.toLocaleString() + " / 20,000 characters" : "";
  }

  // ------------------------------------------------------------ sending ------------

  function payload() {
    var body = {};
    FIELDS.forEach(function (field) {
      body[field] = $(field).value.trim();
    });
    var info = (extracted && extracted.extraction) || {};
    var fieldSources = Object.assign({}, info.field_sources || {});
    FIELDS.forEach(function (field) {
      var before = extracted ? String(extracted[field] || "").trim() : "";
      if (body[field] && body[field] !== before) fieldSources[field] = "user";
    });
    body.source_hint = sourceHint;
    body.page_url = pageUrl;
    body.extension_version = chrome.runtime.getManifest().version;
    body.captured_at = new Date().toISOString();
    body.extraction = {
      method: info.method || "manual",
      confidence: typeof info.confidence === "number" ? info.confidence : 0,
      missing: (info.missing || []).slice(0, 20),
      field_sources: fieldSources
    };
    return body;
  }

  function renderSuccess(body) {
    var nodes = [];
    if (body.created) {
      nodes.push(el("h2", "Added to JobOrbit"));
      nodes.push(el("p", "Saved as job #" + body.job_id + " (" + body.source + ")."));
    } else {
      nodes.push(el("h2", "Already in JobOrbit"));
      nodes.push(
        el(
          "p",
          "This listing matched job #" + (body.duplicate_of || body.job_id) +
            ", so no second copy was made. Any new details were merged into it."
        )
      );
    }

    if (typeof body.score === "number") {
      var line = el("p");
      line.appendChild(el("span", "Score " + Math.round(body.score), "score"));
      var parts = [];
      if (body.band) parts.push(BAND_LABELS[body.band] || body.band);
      if (body.confidence) parts.push(body.confidence + " confidence");
      if (parts.length) line.appendChild(document.createTextNode(" · " + parts.join(" · ")));
      nodes.push(line);
    } else {
      nodes.push(el("p", "Not scored yet."));
    }
    if (body.filtered_out && body.filter_reasons && body.filter_reasons.length) {
      nodes.push(el("p", "Filtered out: " + body.filter_reasons.join("; ")));
    }
    if (body.explanation && body.explanation.length) {
      var list = el("ul");
      body.explanation.slice(0, 5).forEach(function (item) {
        list.appendChild(el("li", item));
      });
      nodes.push(list);
    }
    if (body.dashboard_path && joborbitIsHttpUrl(settings.dashboardUrl)) {
      var link = el("a", "Open in the JobOrbit dashboard");
      link.href = settings.dashboardUrl + body.dashboard_path;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      var holder = el("p");
      holder.appendChild(link);
      nodes.push(holder);
    }
    showResult("ok", nodes);
  }

  function renderError(response, body) {
    var error = (body && body.error) || {};
    if (response.status === 401) {
      showResult("warn", tokenNodes());
      return;
    }
    var nodes = [el("h2", response.status === 403 ? "JobOrbit refused the capture" : "Not saved")];
    nodes.push(el("p", error.message || "JobOrbit answered HTTP " + response.status + "."));
    var fieldErrors = error.field_errors || {};
    var keys = Object.keys(fieldErrors);
    if (keys.length) {
      var list = el("ul");
      keys.forEach(function (key) {
        list.appendChild(el("li", key + ": " + [].concat(fieldErrors[key]).join("; ")));
      });
      nodes.push(list);
    }
    showResult("err", nodes);
  }

  function send(event) {
    event.preventDefault();
    markMissing();
    var body = payload();
    var absent = REQUIRED.filter(function (field) {
      return !body[field];
    });
    if (absent.length) {
      showResult("warn", [
        el("h2", "A few fields are needed"),
        el("p", "Fill in: " + absent.map(function (name) { return FIELD_LABELS[name]; }).join(", ") + ".")
      ]);
      $(absent[0]).focus();
      return;
    }
    if (!joborbitIsHttpUrl(body.url)) {
      showResult("warn", [el("h2", "Check the URL"), el("p", "The listing URL must start with http:// or https://.")]);
      $("url").focus();
      return;
    }
    if (!joborbitIsLoopbackUrl(settings.apiBase)) {
      showResult("err", [
        el("h2", "Check the API address"),
        el("p", "The API address must be on this computer (http://127.0.0.1 or http://localhost). Fix it in Options.")
      ]);
      return;
    }

    var button = $("send");
    button.disabled = true;
    button.textContent = "Sending...";
    request("/api/capture/job", { method: "POST", headers: headers(true), body: JSON.stringify(body) }, 30000)
      .then(function (response) {
        return readJson(response).then(function (json) {
          if (response.ok) {
            renderSuccess(json);
            setConnection("ok", "Connected");
          } else {
            renderError(response, json);
            if (response.status === 401) setConnection("warn", "Token needed");
          }
        });
      })
      .catch(function () {
        setConnection("err", "Not running");
        showResult("err", unreachableNodes());
      })
      .finally(function () {
        button.disabled = false;
        button.textContent = "Send to JobOrbit";
      });
  }

  // ------------------------------------------------------------ start ---------------

  $("capture").addEventListener("submit", send);
  $("description").addEventListener("input", updateCounter);
  FIELDS.forEach(function (field) {
    $(field).addEventListener("input", markMissing);
  });
  $("open-options").addEventListener("click", function (event) {
    event.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  joborbitLoadSettings()
    .then(function (loaded) {
      settings = loaded;
    })
    .catch(function () {
      /* defaults stay in place */
    })
    .then(function () {
      checkStatus();
      return extract();
    })
    .then(function (data) {
      if (!data || typeof data !== "object") throw new Error("no result");
      fill(data);
    })
    .catch(function () {
      $("extraction").textContent =
        "This page can't be read by extensions (browser pages, the Chrome Web Store and " +
        "some viewers are off-limits). You can still type the details in by hand.";
      markMissing();
    });
})();
