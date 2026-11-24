/*
 * JobOrbit job-listing extractor.
 *
 * Injected into the active tab by popup.js only after the user clicks the toolbar button
 * (the `activeTab` grant). It reads the one page in front of the user and returns plain
 * data; it sends nothing anywhere itself.
 *
 * What it reads: schema.org JobPosting JSON-LD, a few visible elements of the listing
 * (title, company, location, description), <link rel=canonical>, and <meta> tags.
 * What it never reads: cookies, web storage, IndexedDB, form fields (the values of
 * inputs, textareas and selects), password fields, or any other tab.
 *
 * The file defines `joborbitExtract(doc, loc)` and ends with a call to it, so
 * `chrome.scripting.executeScript({files: ["extractor.js"]})` returns the result as the
 * script's completion value, and tests can evaluate the same function with Playwright.
 */

// eslint-disable-next-line no-unused-vars
function joborbitExtract(doc, loc) {
  "use strict";

  var MAX_DESCRIPTION = 20000;
  var LIMITS = { title: 400, company: 300, location: 300, posted_at: 100, employment_type: 100 };
  var FIELDS = ["title", "company", "location", "description", "posted_at", "employment_type"];
  var TRACKING_PARAMS = [
    "trk", "trkinfo", "trackingid", "refid", "ref", "ref_", "lipi", "midtoken", "midsig",
    "eboost", "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_ga", "_gl",
    "originalsubdomain", "alternatechannel", "src", "sid", "xid", "from", "fromjk",
    "tk", "advn", "adid", "searchid", "recommendedflavor", "si", "igshid", "source"
  ];
  // Elements whose text is never part of a listing, and form controls whose contents
  // belong to the user, not the page.
  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, SVG: 1, IFRAME: 1, OBJECT: 1, EMBED: 1,
    CANVAS: 1, INPUT: 1, TEXTAREA: 1, SELECT: 1, OPTION: 1, BUTTON: 1, FORM: 1, NAV: 1,
    HEAD: 1, LINK: 1, META: 1
  };
  var BLOCK_TAGS = {
    P: 1, DIV: 1, SECTION: 1, ARTICLE: 1, LI: 1, UL: 1, OL: 1, H1: 1, H2: 1, H3: 1, H4: 1,
    H5: 1, H6: 1, TR: 1, TABLE: 1, BR: 1, HR: 1, BLOCKQUOTE: 1, PRE: 1, DD: 1, DT: 1, DL: 1,
    HEADER: 1, FOOTER: 1, MAIN: 1, ASIDE: 1
  };

  var view = doc.defaultView || null;

  function clean(text, limit) {
    var value = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
    return limit ? value.slice(0, limit) : value;
  }

  function cleanBlock(text) {
    return String(text || "")
      .replace(/ /g, " ")
      .replace(/[ \t\f\v\r]+/g, " ")
      .replace(/ *\n */g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function isHidden(el) {
    if (!view || !view.getComputedStyle) return false;
    if (el.hidden || el.getAttribute("aria-hidden") === "true") return true;
    var style = view.getComputedStyle(el);
    return style.display === "none" || style.visibility === "hidden";
  }

  function isPasswordish(el) {
    var type = (el.getAttribute && el.getAttribute("type")) || "";
    return type.toLowerCase() === "password";
  }

  // Visible text of one element, with line breaks at block boundaries. Walks the tree
  // itself rather than using innerText so form controls and hidden nodes are excluded by
  // construction, not by whatever a browser's innerText happens to include.
  function visibleText(root, checkVisibility, limit) {
    var parts = [];
    var length = 0;
    var budget = limit || MAX_DESCRIPTION;
    function walk(node, depth) {
      if (length > budget || depth > 60) return;
      if (node.nodeType === 3) {
        var text = node.nodeValue;
        if (text) {
          parts.push(text);
          length += text.length;
        }
        return;
      }
      if (node.nodeType !== 1) return;
      var tag = node.tagName.toUpperCase();
      if (SKIP_TAGS[tag] || isPasswordish(node)) return;
      if (node.isContentEditable) return;
      if (checkVisibility && isHidden(node)) return;
      var block = BLOCK_TAGS[tag];
      if (block) parts.push("\n");
      if (tag === "LI") parts.push("- ");
      for (var child = node.firstChild; child; child = child.nextSibling) walk(child, depth + 1);
      if (block) parts.push("\n");
    }
    walk(root, 0);
    return cleanBlock(parts.join("")).slice(0, budget);
  }

  function htmlToText(html) {
    var source = String(html || "");
    if (!/[<&]/.test(source)) return cleanBlock(source).slice(0, MAX_DESCRIPTION);
    var Parser = view && view.DOMParser ? view.DOMParser : typeof DOMParser !== "undefined" ? DOMParser : null;
    if (!Parser) return cleanBlock(source.replace(/<[^>]+>/g, " ")).slice(0, MAX_DESCRIPTION);
    // DOMParser documents are inert: no script runs and no resource loads.
    var parsed = new Parser().parseFromString(source, "text/html");
    var text = visibleText(parsed.body || parsed.documentElement, false);
    // Some sites HTML-escape the description inside the JSON, so one parse yields markup.
    if (/<\/?(p|div|li|ul|br|strong|span|h\d)[\s>/]/i.test(text)) {
      parsed = new Parser().parseFromString(text, "text/html");
      text = visibleText(parsed.body || parsed.documentElement, false);
    }
    return text;
  }

  function first(selectors, root) {
    var scope = root || doc;
    for (var i = 0; i < selectors.length; i++) {
      var found;
      try {
        found = scope.querySelector(selectors[i]);
      } catch (error) {
        found = null; // an invalid selector must not abort the extraction
      }
      if (found && !isPasswordish(found)) {
        var text = clean(visibleText(found, true, 2000));
        if (text) return text;
      }
    }
    return "";
  }

  function firstBlock(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var found;
      try {
        found = doc.querySelector(selectors[i]);
      } catch (error) {
        found = null;
      }
      if (found) {
        var text = visibleText(found, true);
        if (text.length >= 40) return text;
      }
    }
    return "";
  }

  function meta(names) {
    for (var i = 0; i < names.length; i++) {
      var el =
        doc.querySelector('meta[property="' + names[i] + '"]') ||
        doc.querySelector('meta[name="' + names[i] + '"]');
      var value = el && clean(el.getAttribute("content"));
      if (value) return value;
    }
    return "";
  }

  function labelled(rootSelectors, labels) {
    // "Employment type: Full-time" laid out as label + value siblings or one line.
    var pattern = new RegExp("(?:" + labels.join("|") + ")\\s*:?\\s*(.+)", "i");
    for (var i = 0; i < rootSelectors.length; i++) {
      var nodes;
      try {
        nodes = doc.querySelectorAll(rootSelectors[i]);
      } catch (error) {
        continue;
      }
      for (var j = 0; j < nodes.length && j < 40; j++) {
        var text = clean(visibleText(nodes[j], true, 400));
        var match = pattern.exec(text);
        // Stop at the next "Label:" so a row of stats yields only this one's value.
        var value = match ? clean(match[1].split(/\s+[A-Z][A-Za-z ]{1,30}:\s/)[0]) : "";
        if (value) return clean(value, 100);
      }
    }
    return "";
  }

  var RELATIVE_DATE = /(\d+\+?\s*(?:minute|min|hour|hr|day|week|month)s?\s+ago|just now|today|yesterday)/i;
  var EMPLOYMENT = /(full[- ]?time|part[- ]?time|contract(?:or)?|internship|temporary|freelance)\b/i;

  function relativeDateIn(selectors) {
    return phraseIn(selectors, RELATIVE_DATE);
  }

  function employmentIn(selectors) {
    return phraseIn(selectors, EMPLOYMENT);
  }

  function phraseIn(selectors, pattern) {
    for (var i = 0; i < selectors.length; i++) {
      var nodes;
      try {
        nodes = doc.querySelectorAll(selectors[i]);
      } catch (error) {
        continue;
      }
      for (var j = 0; j < nodes.length && j < 40; j++) {
        var match = pattern.exec(clean(visibleText(nodes[j], true, 300)));
        if (match) return clean(match[1]);
      }
    }
    return "";
  }

  // ---------------------------------------------------------------- JSON-LD ---------

  function isJobPosting(node) {
    var type = node && node["@type"];
    var types = Array.isArray(type) ? type : [type];
    for (var i = 0; i < types.length; i++) {
      if (typeof types[i] === "string" && /(^|[/:#])JobPosting$/i.test(types[i])) return true;
    }
    return false;
  }

  function collectPostings(node, out, depth) {
    if (!node || depth > 8 || out.length > 10) return;
    if (Array.isArray(node)) {
      for (var i = 0; i < node.length; i++) collectPostings(node[i], out, depth + 1);
      return;
    }
    if (typeof node !== "object") return;
    if (isJobPosting(node)) out.push(node);
    if (node["@graph"]) collectPostings(node["@graph"], out, depth + 1);
    if (node.mainEntity) collectPostings(node.mainEntity, out, depth + 1);
    if (node.itemListElement) collectPostings(node.itemListElement, out, depth + 1);
    if (node.item) collectPostings(node.item, out, depth + 1);
  }

  function textOf(value) {
    if (value == null) return "";
    if (typeof value === "string" || typeof value === "number") return clean(value);
    if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join(", ");
    if (typeof value === "object") return clean(value.name || value["@value"] || "");
    return "";
  }

  function addressText(address) {
    if (!address) return "";
    if (typeof address === "string") return clean(address);
    if (Array.isArray(address)) return address.map(addressText).filter(Boolean).join("; ");
    var parts = [];
    ["addressLocality", "addressRegion", "addressCountry"].forEach(function (key) {
      var part = textOf(address[key]);
      if (part && parts.indexOf(part) === -1) parts.push(part);
    });
    if (!parts.length) parts.push(textOf(address.streetAddress) || textOf(address.name));
    return parts.filter(Boolean).join(", ");
  }

  function locationText(posting) {
    var places = posting.jobLocation;
    places = Array.isArray(places) ? places : places ? [places] : [];
    var names = [];
    places.forEach(function (place) {
      var text = typeof place === "string" ? clean(place) : addressText(place.address) || textOf(place.name);
      if (text && names.indexOf(text) === -1) names.push(text);
    });
    var remote = /TELECOMMUTE/i.test(textOf(posting.jobLocationType));
    if (remote) {
      var region = textOf(posting.applicantLocationRequirements);
      names.unshift(region ? "Remote (" + region + ")" : "Remote");
    }
    return names.join("; ");
  }

  function fromJsonLd() {
    var scripts = doc.querySelectorAll('script[type="application/ld+json"]');
    var postings = [];
    for (var i = 0; i < scripts.length && i < 30; i++) {
      var raw = scripts[i].textContent || "";
      if (raw.length > 2000000) continue;
      var parsed = null;
      try {
        parsed = JSON.parse(raw);
      } catch (error) {
        try {
          // Unescaped control characters inside strings are a common publishing bug.
          parsed = JSON.parse(raw.replace(/[\u0000-\u001f]+/g, " "));
        } catch (secondError) {
          parsed = null;
        }
      }
      collectPostings(parsed, postings, 0);
    }
    if (!postings.length) return null;
    // A careers page can list several; the one with a title and a description is the
    // listing itself rather than a "related jobs" teaser.
    postings.sort(function (a, b) {
      return String(b.description || "").length - String(a.description || "").length;
    });
    var posting = postings[0];
    return {
      title: clean(posting.title || posting.name, LIMITS.title),
      company: clean(textOf(posting.hiringOrganization), LIMITS.company),
      location: clean(locationText(posting), LIMITS.location),
      description: htmlToText(posting.description),
      posted_at: clean(posting.datePosted, LIMITS.posted_at),
      employment_type: clean(textOf(posting.employmentType), LIMITS.employment_type)
    };
  }

  // ---------------------------------------------------------- site heuristics -------

  var host = String((loc && loc.hostname) || "").toLowerCase().replace(/^www\./, "");

  function hostIs(suffix) {
    return host === suffix || host.slice(-(suffix.length + 1)) === "." + suffix;
  }

  function siteName() {
    if (hostIs("linkedin.com")) return "linkedin";
    if (hostIs("naukri.com")) return "naukri";
    if (/(^|\.)indeed\.[a-z.]+$/.test(host)) return "indeed";
    if (hostIs("wellfound.com") || hostIs("angel.co")) return "wellfound";
    return "";
  }

  var SITES = {
    linkedin: function () {
      return {
        title: first([
          ".job-details-jobs-unified-top-card__job-title h1",
          ".job-details-jobs-unified-top-card__job-title",
          ".jobs-unified-top-card__job-title",
          ".top-card-layout__title",
          ".topcard__title",
          "h1.t-24"
        ]),
        company: first([
          ".job-details-jobs-unified-top-card__company-name a",
          ".job-details-jobs-unified-top-card__company-name",
          ".jobs-unified-top-card__company-name a",
          ".jobs-unified-top-card__company-name",
          ".topcard__org-name-link",
          ".top-card-layout__second-subline a"
        ]),
        location: first([
          ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
          ".job-details-jobs-unified-top-card__bullet",
          ".jobs-unified-top-card__bullet",
          ".topcard__flavor--bullet"
        ]),
        description: firstBlock([
          "#job-details",
          ".jobs-description__content",
          ".jobs-box__html-content",
          ".show-more-less-html__markup",
          ".description__text"
        ]),
        posted_at: relativeDateIn([
          ".posted-time-ago__text",
          ".jobs-unified-top-card__posted-date",
          ".job-details-jobs-unified-top-card__primary-description-container span",
          ".job-details-jobs-unified-top-card__tertiary-description-container span",
          ".topcard__flavor--metadata"
        ]),
        employment_type:
          labelled([".description__job-criteria-item"], ["Employment type"]) ||
          employmentIn([
            ".job-details-preferences-and-skills",
            ".job-details-jobs-unified-top-card__job-insight",
            ".jobs-unified-top-card__job-insight"
          ])
      };
    },
    naukri: function () {
      return {
        title: first(['[class*="jd-header-title"]', ".jd-header-title", "h1"]),
        company: first([
          '[class*="jd-header-comp-name"] a',
          '[class*="jd-header-comp-name"]',
          ".jd-header-comp-name a"
        ]).replace(/\s*\d(\.\d)?\s*\d*\s*Reviews?$/i, ""),
        location: first(['[class*="jhc__location"]', ".location .loc", ".loc"]),
        description: firstBlock([
          '[class*="job-desc-container"]',
          '[class*="JDC__dang-inner-html"]',
          '[class*="dang-inner-html"]',
          ".job-desc",
          ".jd-desc"
        ]),
        posted_at:
          relativeDateIn(['[class*="jhc__stat"]', '[class*="jd-stats"]']) ||
          labelled(['[class*="jhc__stat"]'], ["Posted"]),
        employment_type: labelled(
          ['[class*="other-details"] [class*="details"]', '[class*="other-details"] div'],
          ["Employment Type"]
        )
      };
    },
    indeed: function () {
      return {
        title: first([
          '[data-testid="jobsearch-JobInfoHeader-title"]',
          "h1.jobsearch-JobInfoHeader-title",
          ".jobsearch-JobInfoHeader-title"
        ]).replace(/\s*-\s*job post$/i, ""),
        company: first([
          '[data-testid="inlineHeader-companyName"] a',
          '[data-testid="inlineHeader-companyName"]',
          '[data-company-name="true"]',
          ".jobsearch-CompanyInfoContainer a"
        ]),
        location: first([
          '[data-testid="inlineHeader-companyLocation"]',
          '[data-testid="job-location"]',
          '[data-testid="jobsearch-JobInfoHeader-companyLocation"]',
          "#jobLocationText"
        ]),
        description: firstBlock(["#jobDescriptionText", ".jobsearch-jobDescriptionText"]),
        posted_at: relativeDateIn([
          '[data-testid="myJobsStateDate"]',
          ".jobsearch-JobMetadataFooter span",
          ".jobsearch-JobMetadataFooter"
        ]),
        employment_type: employmentIn([
          "#salaryInfoAndJobType",
          '[data-testid="jobsearch-OtherJobDetailsContainer"]',
          "#jobDetailsSection"
        ])
      };
    },
    wellfound: function () {
      return {
        title: first(['[data-test="JobTitle"]', "h1"]),
        company: first([
          '[data-test="CompanyName"]',
          'a[href^="/company/"] h2',
          'a[href^="/company/"]'
        ]),
        location: first(['[data-test="JobLocation"]', '[class*="location"]']),
        description: firstBlock([
          '[data-test="JobDescription"]',
          '[class*="job-description"]',
          '[class*="description"]'
        ]),
        posted_at: relativeDateIn(['[class*="posted"]', "header", "main"]),
        employment_type:
          labelled(['[class*="job-type"]', "dl div"], ["Job type"]) ||
          employmentIn(['[class*="job-type"]', "header", "main ul"])
      };
    }
  };

  // ----------------------------------------------------------- generic fallback -----

  function splitTitle(raw) {
    // "Backend Engineer at Acme" / "Backend Engineer - Acme | Careers"
    var text = clean(raw).replace(/\s*[|–—-]\s*(careers?|jobs?|hiring)\b.*$/i, "");
    var at = /^(.{3,160}?)\s+(?:at|@)\s+(.{2,100}?)$/i.exec(text);
    if (at) return { title: at[1], company: at[2] };
    var dash = /^(.{3,160}?)\s+[|–—-]\s+(.{2,100}?)$/.exec(text);
    if (dash) return { title: dash[1], company: dash[2] };
    return { title: text, company: "" };
  }

  function generic() {
    var heading = first(["main h1", "article h1", "h1"]);
    var ogTitle = meta(["og:title", "twitter:title"]);
    var titleSource = heading || ogTitle || clean(doc.title);
    var split = splitTitle(titleSource);
    var fromOg = ogTitle ? splitTitle(ogTitle) : { title: "", company: "" };
    var body = firstBlock(["main article", "article", "main", '[role="main"]']);
    if (body.length < 200) body = "";
    return {
      title: clean(heading || split.title, LIMITS.title),
      // On a job board og:site_name is the board ("LinkedIn"), never the employer.
      company: clean(
        (site ? "" : meta(["og:site_name", "application-name"])) || split.company || fromOg.company,
        LIMITS.company
      ),
      location: "",
      description: body || meta(["og:description", "description", "twitter:description"]),
      posted_at: "",
      employment_type: employmentIn(["main header", "article header"])
    };
  }

  // ---------------------------------------------------------------- URL --------------

  function stripTracking(raw) {
    var url;
    try {
      url = new URL(raw, loc && loc.href);
    } catch (error) {
      return "";
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    var keys = [];
    url.searchParams.forEach(function (_, key) {
      keys.push(key);
    });
    keys.forEach(function (key) {
      var lower = key.toLowerCase();
      if (lower.indexOf("utm_") === 0 || TRACKING_PARAMS.indexOf(lower) !== -1) {
        url.searchParams.delete(key);
      }
    });
    url.hash = "";
    var text = url.toString();
    return text.slice(-1) === "?" ? text.slice(0, -1) : text;
  }

  function listingUrl(site) {
    var href = String((loc && loc.href) || "");
    var current;
    try {
      current = new URL(href);
    } catch (error) {
      current = null;
    }
    // A job opened from a search page is identified by a query parameter, and the page's
    // canonical link points at the search, not the job.
    if (current && site === "linkedin") {
      var jobId = current.searchParams.get("currentJobId");
      if (jobId && /^\d+$/.test(jobId)) return "https://www.linkedin.com/jobs/view/" + jobId + "/";
      var view = /\/jobs\/view\/(?:[^/]*?-)?(\d{6,})/.exec(current.pathname);
      if (view) return "https://www.linkedin.com/jobs/view/" + view[1] + "/";
    }
    if (current && site === "indeed") {
      var jk = current.searchParams.get("jk") || current.searchParams.get("vjk");
      if (jk && /^[0-9a-f]{8,32}$/i.test(jk)) return current.origin + "/viewjob?jk=" + jk;
    }
    var canonical = doc.querySelector('link[rel="canonical"]');
    var canonicalHref = canonical && canonical.getAttribute("href");
    if (canonicalHref) {
      var resolved = stripTracking(canonicalHref);
      if (resolved) return resolved;
    }
    return stripTracking(href);
  }

  // ---------------------------------------------------------------- assemble ---------

  var result = { title: "", company: "", location: "", description: "", posted_at: "", employment_type: "" };
  var sources = {};
  var method = "";

  function merge(found, label) {
    if (!found) return false;
    var used = false;
    FIELDS.forEach(function (field) {
      if (!result[field] && found[field]) {
        result[field] = found[field];
        sources[field] = label;
        used = true;
      }
    });
    if (used && !method) method = label;
    return used;
  }

  var site = siteName();
  var steps = [
    ["json-ld", fromJsonLd],
    site ? ["site:" + site, SITES[site]] : null,
    ["generic", generic]
  ];
  steps.forEach(function (step) {
    if (!step) return;
    var found = null;
    try {
      found = step[1]();
    } catch (error) {
      found = null; // a broken heuristic leaves the field for the next step
    }
    merge(found, step[0]);
  });

  result.title = clean(result.title, LIMITS.title);
  result.company = clean(result.company, LIMITS.company);
  result.location = clean(result.location, LIMITS.location);
  result.posted_at = clean(result.posted_at, LIMITS.posted_at);
  result.employment_type = clean(result.employment_type, LIMITS.employment_type);
  result.description = cleanBlock(result.description).slice(0, MAX_DESCRIPTION);

  var missing = FIELDS.filter(function (field) {
    return !result[field];
  });
  var base = { "json-ld": 0.9, generic: 0.4 }[method];
  if (base === undefined) base = method ? 0.7 : 0;
  ["title", "company", "description"].forEach(function (field) {
    if (!result[field]) base -= 0.2;
  });
  if (sources.title === "generic" || sources.company === "generic") base = Math.min(base, 0.5);

  var url = listingUrl(site);
  return {
    title: result.title,
    company: result.company,
    location: result.location,
    url: url,
    page_url: stripTracking(String((loc && loc.href) || "")),
    description: result.description,
    posted_at: result.posted_at,
    employment_type: result.employment_type,
    source_hint: site,
    extraction: {
      method: method || "none",
      confidence: Math.max(0, Math.round(base * 100) / 100),
      missing: missing,
      field_sources: sources
    }
  };
}

// Completion value of the injected script: what executeScript({files}) hands back.
joborbitExtract(document, location);
