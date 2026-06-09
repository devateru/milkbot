(async function () {
  "use strict";

  var APP_NAME = "maimai DX NET 컬렉션 목록";
  var MAX_PAGES = 120;
  var PAGE_DELAY_MS = 120;
  var CATEGORY_ORDER = ["icon", "nameplate", "frame", "trophy", "character", "eventCharacter", "partner", "unknown"];
  var CATEGORY_LABELS = {
    icon: "ICON",
    nameplate: "NAME PLATE",
    frame: "FRAME",
    trophy: "TITLE",
    character: "TOUR MEMBER",
    eventCharacter: "EVENT TOUR MEMBER",
    partner: "PARTNER",
    unknown: "UNKNOWN"
  };
  var COLLECTION_URLS = [
    "/maimai-mobile/collection/",
    "/maimai-mobile/collection/nameplate/",
    "/maimai-mobile/collection/frame/",
    "/maimai-mobile/collection/trophy/",
    "/maimai-mobile/collection/character/",
    "/maimai-mobile/collection/eventCharacter/",
    "/maimai-mobile/collection/partner/"
  ];
  var GRADE_ORDER = ["Rainbow", "Gold", "Silver", "Bronze", "Normal", "Rare5", "Rare4", "Rare3", "Rare2", "Rare1", "Rare0", "Unknown"];
  var TROPHY_RARE_VALUES = [0, 1, 2, 3, 4];
  var RARE_GRADE_HINTS = {
    "0": "Rare0",
    "1": "Rare1",
    "2": "Rare2",
    "3": "Rare3",
    "4": "Rare4"
  };
  var GRADE_LABELS = {
    Rainbow: "Rainbow",
    Gold: "Gold",
    Silver: "Silver",
    Bronze: "Bronze",
    Normal: "Normal",
    Rare5: "rare=5",
    Rare4: "rare=4",
    Rare3: "rare=3",
    Rare2: "rare=2",
    Rare1: "rare=1",
    Rare0: "rare=0",
    Unknown: "등급 미확인"
  };

  var BLOCK_INFO_GRADES = {
    RAINBOW: "Rainbow",
    GOLD: "Gold",
    SILVER: "Silver",
    BRONZE: "Bronze",
    NORMAL: "Normal"
  };

  var CATEGORY_IMAGE_PATTERNS = {
    icon: /\/img\/Icon\//i,
    nameplate: /\/img\/NamePlate\//i,
    frame: /\/img\/Frame\//i,
    character: /\/img\/(?:Chara|Character)\//i,
    eventCharacter: /\/img\/(?:Chara|Character)\//i,
    partner: /\/img\/Partner\//i
  };

  function cleanText(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t\r\f\v]+/g, " ")
      .replace(/\n\s+/g, "\n")
      .trim();
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[ch];
    });
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function normalizeUrl(rawUrl, baseUrl) {
    try {
      var url = new URL(rawUrl, baseUrl || location.href);
      url.hash = "";
      return url.href;
    } catch (error) {
      return "";
    }
  }

  function isMaimaiMobilePage() {
    return /(^|\.)maimaidx-eng\.com$/i.test(location.hostname) && location.pathname.indexOf("/maimai-mobile/") === 0;
  }

  function openReportWindow() {
    var win = window.open("", "_blank");
    if (!win) {
      alert("새 탭을 열 수 없습니다. 팝업 차단을 해제한 뒤 다시 실행해 주세요.");
      return null;
    }

    win.document.open();
    win.document.write([
      "<!doctype html>",
      "<html lang=\"ko\">",
      "<head>",
      "<meta charset=\"utf-8\">",
      "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
      "<title>" + escapeHtml(APP_NAME) + "</title>",
      "<style>",
      ":root{color-scheme:light;--bg:#f7f8fb;--panel:#fff;--ink:#1d2433;--muted:#667085;--line:#d8dde6;--accent:#0a7cff;--rainbow:#8658d7;--gold:#b07a13;--silver:#697386;--bronze:#a45f2b;--normal:#24795b;}",
      "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.55}",
      "header{position:sticky;top:0;z-index:2;border-bottom:1px solid var(--line);background:rgba(255,255,255,.96);backdrop-filter:blur(10px)}",
      ".wrap{width:min(1100px,calc(100% - 28px));margin:0 auto}.top{display:flex;gap:14px;align-items:center;justify-content:space-between;padding:16px 0}",
      "h1{margin:0;font-size:22px;letter-spacing:0}.sub{margin:4px 0 0;color:var(--muted);font-size:13px}.pill{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);font-size:13px;font-weight:650}",
      "main{padding:20px 0 48px}.panel{border:1px solid var(--line);border-radius:8px;background:var(--panel);box-shadow:0 1px 2px rgba(16,24,40,.05)}",
      ".status{padding:22px}.spinner{width:28px;height:28px;border:3px solid #dbe4f0;border-top-color:var(--accent);border-radius:50%;animation:spin .85s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}",
      ".status-grid{display:grid;grid-template-columns:36px 1fr;gap:14px;align-items:start}.status strong{display:block;margin-bottom:4px}.muted{color:var(--muted)}",
      ".toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 16px}.toolbar input{min-width:220px;flex:1;min-height:38px;padding:0 12px;border:1px solid var(--line);border-radius:8px;font:inherit}",
      "button{min-height:38px;padding:0 13px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);font:inherit;font-weight:650;cursor:pointer}button:hover{border-color:#aeb6c4}",
      ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}.summary div{padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff}.summary b{display:block;font-size:22px}.summary span{color:var(--muted);font-size:13px}",
      "section.grade{margin-top:16px}.grade-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--line)}.grade-head h2{margin:0;font-size:18px}.count{color:var(--muted);font-size:13px;font-weight:650}",
      "table{width:100%;border-collapse:collapse}th,td{padding:11px 14px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.02em}.thumb-cell{width:96px}.item-thumb{display:block;max-width:84px;max-height:84px;object-fit:contain;border:1px solid var(--line);border-radius:6px;background:#f8fafc}.name{font-weight:700}.meta{display:block;margin-top:4px;color:var(--muted);font-size:12px}.desc{white-space:pre-wrap;color:#344054}.source{display:block;margin-top:6px;color:var(--muted);font-size:12px;word-break:break-all}.image-link{display:block;margin-top:5px;color:var(--accent);font-size:12px;word-break:break-all}",
      ".empty{padding:28px;text-align:center;color:var(--muted)}.error{border-color:#f2b8b5;background:#fff7f7}.error strong{color:#b42318}",
      ".debug-actions{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}.debug-box{width:100%;min-height:420px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff;color:#202938;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,'Liberation Mono',monospace;white-space:pre;resize:vertical}",
      ".Rainbow{border-top:4px solid var(--rainbow)}.Gold{border-top:4px solid var(--gold)}.Silver{border-top:4px solid var(--silver)}.Bronze{border-top:4px solid var(--bronze)}.Normal{border-top:4px solid var(--normal)}.Rare5,.Rare4,.Rare3,.Rare2,.Rare1,.Rare0,.Unknown{border-top:4px solid #98a2b3}",
      "@media(max-width:720px){.top{display:block}.thumb-cell{width:72px}.item-thumb{max-width:60px;max-height:60px}th:nth-child(4),td:nth-child(4){display:none}.toolbar input{min-width:100%}}",
      "</style>",
      "</head>",
      "<body>",
      "<header><div class=\"wrap top\"><div><h1>" + escapeHtml(APP_NAME) + "</h1><p class=\"sub\" id=\"subtitle\">maimai DX NET에서 컬렉션 페이지를 읽는 중입니다.</p></div><span class=\"pill\" id=\"badge\">준비 중</span></div></header>",
      "<main class=\"wrap\" id=\"app\"></main>",
      "</body>",
      "</html>"
    ].join(""));
    win.document.close();
    return win;
  }

  function setReport(win, html, subtitle, badge) {
    if (!win || win.closed) return;
    var app = win.document.getElementById("app");
    var subtitleEl = win.document.getElementById("subtitle");
    var badgeEl = win.document.getElementById("badge");
    if (subtitleEl) subtitleEl.textContent = subtitle || "";
    if (badgeEl) badgeEl.textContent = badge || "";
    if (app) app.innerHTML = html;
  }

  function renderLoading(win, message, detail) {
    setReport(
      win,
      "<div class=\"panel status\"><div class=\"status-grid\"><div class=\"spinner\"></div><div><strong>" +
        escapeHtml(message) +
        "</strong><div class=\"muted\">" +
        escapeHtml(detail || "") +
        "</div></div></div></div>",
      "로그인 세션으로 collection 페이지를 읽고 있습니다.",
      "로딩 중"
    );
  }

  function renderError(win, title, detail, diagnostics) {
    var diag = diagnostics && diagnostics.length
      ? "<ul>" + diagnostics.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>"
      : "";
    setReport(
      win,
      "<div class=\"panel status error\"><strong>" +
        escapeHtml(title) +
        "</strong><p class=\"muted\">" +
        escapeHtml(detail || "") +
        "</p>" +
        diag +
        "</div>",
      "컬렉션 목록을 만들지 못했습니다.",
      "오류"
    );
  }

  function sanitizeDebugHtml(html) {
    try {
      var doc = new DOMParser().parseFromString(String(html || ""), "text/html");
      Array.prototype.forEach.call(doc.querySelectorAll("script"), function (script) {
        script.textContent = "[redacted script]";
      });
      Array.prototype.forEach.call(doc.querySelectorAll("input, textarea"), function (field) {
        var type = (field.getAttribute("type") || "").toLowerCase();
        var name = (field.getAttribute("name") || "").toLowerCase();
        var id = (field.getAttribute("id") || "").toLowerCase();
        var key = type + " " + name + " " + id;
        if (type === "hidden" || /token|csrf|auth|session|password|passwd|secret|key/.test(key)) {
          field.setAttribute("value", "[REDACTED]");
          if ("value" in field) field.value = "[REDACTED]";
          field.textContent = "[REDACTED]";
        }
      });
      return "<!doctype html>\n" + doc.documentElement.outerHTML;
    } catch (error) {
      return String(html || "")
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "<script>[redacted script]<\\/script>")
        .replace(/(<input\b[^>]*\btype=['\"]?hidden['\"]?[^>]*\bvalue=)(['\"]?)[^'\">\s]+/gi, "$1$2[REDACTED]");
    }
  }

  function makeDebugPayload(reason, detail, diagnostics, pages) {
    return {
      app: APP_NAME,
      generatedAt: new Date().toISOString(),
      location: location.href,
      reason: reason,
      detail: detail,
      diagnostics: diagnostics || [],
      pageCount: pages.length,
      pages: pages
    };
  }

  function downloadDebugJson(win, payloadText) {
    var blob = new Blob([payloadText], { type: "application/json;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = win.document.createElement("a");
    anchor.href = url;
    anchor.download = "maimai_collections_debug.json";
    win.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function renderDebugError(win, title, detail, diagnostics, pages) {
    var payloadText = JSON.stringify(makeDebugPayload(title, detail, diagnostics, pages), null, 2);
    setReport(
      win,
      "<div class=\"panel status error\"><strong>" +
        escapeHtml(title) +
        "</strong><p class=\"muted\">" +
        escapeHtml(detail || "") +
        "</p><p class=\"muted\">아래 JSON을 그대로 붙여넣으면 selector를 다시 맞출 수 있습니다. hidden input, token, password 계열 값은 마스킹했습니다.</p><div class=\"debug-actions\"><button id=\"copy-debug\" type=\"button\">디버그 JSON 복사</button><button id=\"download-debug\" type=\"button\">JSON 파일 저장</button></div><textarea id=\"debug-output\" class=\"debug-box\" readonly spellcheck=\"false\">" +
        escapeHtml(payloadText) +
        "</textarea></div>",
      "실패 원인 분석용 디버그 리포트를 만들었습니다.",
      "디버그"
    );

    var copyButton = win.document.getElementById("copy-debug");
    var downloadButton = win.document.getElementById("download-debug");
    var output = win.document.getElementById("debug-output");
    if (copyButton && output) {
      copyButton.addEventListener("click", async function () {
        try {
          await win.navigator.clipboard.writeText(payloadText);
          copyButton.textContent = "복사됨";
        } catch (error) {
          output.focus();
          output.select();
          win.document.execCommand("copy");
          copyButton.textContent = "선택 영역 복사됨";
        }
      });
    }
    if (downloadButton) {
      downloadButton.addEventListener("click", function () {
        downloadDebugJson(win, payloadText);
      });
    }
  }

  function isReadOnlyCollectionUrl(rawUrl, label, baseUrl) {
    var href = normalizeUrl(rawUrl, baseUrl);
    if (!href) return false;

    var url = new URL(href);
    if (url.origin !== location.origin) return false;
    if (url.pathname.indexOf("/maimai-mobile/") !== 0) return false;
    if (url.pathname.indexOf("/collection/") === -1) return false;

    var haystack = decodeURIComponent((url.pathname + " " + url.search + " " + (label || "")).toLowerCase());
    if (!/(collection|icon|nameplate|frame|trophy|title|character|eventcharacter|partner|称号|칭호)/i.test(haystack)) return false;
    if (/(update|setting|\/set\/|equip|delete|remove|change|favorite|decide|select)/i.test(haystack)) return false;
    return true;
  }

  function isAllowedCollectionListUrl(rawUrl, label, baseUrl) {
    var href = normalizeUrl(rawUrl, baseUrl);
    if (!href) return false;
    var url = new URL(href);
    var haystack = decodeURIComponent((url.pathname + " " + url.search + " " + (label || "")).toLowerCase());
    if (!/^\/maimai-mobile\/collection\/(?:$|nameplate\/|frame\/|trophy\/|character\/|eventcharacter\/|partner\/)/i.test(url.pathname)) return false;
    if (/(\/set\/|favorite|update|delete|remove|change)/i.test(haystack)) return false;
    return true;
  }

  async function fetchHtml(url) {
    var response = await fetch(url, {
      credentials: "include",
      cache: "no-store"
    });

    var text = await response.text();
    return {
      loader: "fetch",
      ok: response.ok,
      status: response.status,
      statusText: response.statusText,
      url: response.url || url,
      text: text,
      doc: new DOMParser().parseFromString(text, "text/html")
    };
  }

  function pageFromCurrentDocument() {
    var html = document.documentElement.outerHTML;
    return {
      loader: "current-document",
      ok: true,
      status: 200,
      statusText: "CURRENT_DOCUMENT",
      requestedUrl: location.href,
      url: location.href,
      text: html,
      doc: document
    };
  }

  function isMaimaiErrorPage(page) {
    if (!page) return true;
    var title = page.doc && page.doc.title ? page.doc.title : "";
    var text = page.text || "";
    return /\/maimai-mobile\/error\/?$/i.test(page.url || "") ||
      /error/i.test(title) ||
      /ERROR CODE|connection time has been expired/i.test(text);
  }

  function loadHtmlViaIframe(url) {
    return new Promise(function (resolve, reject) {
      var iframe = document.createElement("iframe");
      var finished = false;
      var timer = window.setTimeout(function () {
        cleanup();
        reject(new Error("iframe timeout - " + url));
      }, 15000);

      function cleanup() {
        if (finished) return;
        finished = true;
        window.clearTimeout(timer);
        iframe.onload = null;
        iframe.onerror = null;
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
      }

      iframe.style.position = "fixed";
      iframe.style.left = "-9999px";
      iframe.style.top = "-9999px";
      iframe.style.width = "1px";
      iframe.style.height = "1px";
      iframe.style.opacity = "0";

      iframe.onload = function () {
        try {
          var doc = iframe.contentDocument;
          var finalUrl = iframe.contentWindow.location.href;
          var html = doc && doc.documentElement ? doc.documentElement.outerHTML : "";
          cleanup();
          resolve({
            loader: "iframe",
            ok: true,
            status: 200,
            statusText: "IFRAME_LOAD",
            requestedUrl: url,
            url: finalUrl,
            text: html,
            doc: new DOMParser().parseFromString(html, "text/html")
          });
        } catch (error) {
          cleanup();
          reject(error);
        }
      };

      iframe.onerror = function () {
        cleanup();
        reject(new Error("iframe load failed - " + url));
      };

      document.body.appendChild(iframe);
      iframe.src = url;
    });
  }

  async function loadPage(url) {
    var page = await fetchHtml(url);
    page.requestedUrl = url;

    if (isMaimaiErrorPage(page)) {
      try {
        var iframePage = await loadHtmlViaIframe(url);
        iframePage.requestedUrl = url;
        if (!isMaimaiErrorPage(iframePage)) return iframePage;
        return iframePage;
      } catch (iframeError) {
        page.iframeError = iframeError.message || String(iframeError);
      }
    }

    return page;
  }

  function discoverLinks(doc, pageUrl, addUrl) {
    Array.prototype.forEach.call(doc.querySelectorAll("a[href]"), function (anchor) {
      var label = cleanText(anchor.textContent);
      var href = normalizeUrl(anchor.getAttribute("href"), pageUrl);
      if (!href) return;
      if (!isReadOnlyCollectionUrl(href, label)) return;
      if (!isAllowedCollectionListUrl(href, label)) return;
      addUrl(href);
    });

    Array.prototype.forEach.call(doc.querySelectorAll("form[action]"), function (form) {
      var method = (form.getAttribute("method") || "get").toLowerCase();
      if (method && method !== "get") return;
      var label = cleanText(form.textContent);
      var action = normalizeUrl(form.getAttribute("action"), pageUrl);
      if (!action) return;
      if (isReadOnlyCollectionUrl(action, label) && isAllowedCollectionListUrl(action, label)) addUrl(action);
    });
  }

  function classBlob(element) {
    var parts = [];
    var current = element;
    var depth = 0;
    while (current && current.nodeType === 1 && depth < 5) {
      parts.push(current.className || "");
      Array.prototype.forEach.call(current.querySelectorAll("img[src], img[alt]"), function (img) {
        parts.push(img.getAttribute("src") || "", img.getAttribute("alt") || "");
      });
      current = current.parentElement;
      depth += 1;
    }
    return parts.join(" ");
  }

  function detectGrade(element) {
    return normalizeGradeName(classBlob(element) + " " + cleanText(element.textContent));
  }

  function normalizeGradeName(text) {
    text = String(text || "");
    var checks = [
      ["Rainbow", /trophy[_-]?rainbow|rainbow|虹|무지개/i],
      ["Gold", /trophy[_-]?gold|gold|金|골드|금색?/i],
      ["Silver", /trophy[_-]?silver|silver|銀|실버|은색?/i],
      ["Bronze", /trophy[_-]?bronze|bronze|銅|브론즈|동색?/i],
      ["Normal", /trophy[_-]?normal|normal|通常|노멀|일반/i]
    ];
    for (var i = 0; i < checks.length; i += 1) {
      if (checks[i][1].test(text)) return checks[i][0];
    }
    return "Unknown";
  }

  function gradeHintFromPage(doc, pageUrl) {
    var rare = null;
    try {
      var url = new URL(pageUrl, location.href);
      rare = url.searchParams.get("rare");
    } catch (error) {
      rare = null;
    }

    var selectedNodes = Array.prototype.slice.call(doc.querySelectorAll("[class*='select'], [class*='active'], [class*='current'], [class*='on']"));
    for (var i = 0; i < selectedNodes.length; i += 1) {
      var selectedGrade = normalizeGradeName((selectedNodes[i].className || "") + " " + cleanText(selectedNodes[i].textContent));
      if (selectedGrade !== "Unknown") return selectedGrade;
    }

    if (rare != null) {
      var rarePattern = new RegExp("rare=" + String(rare) + "(?:\\D|$)");
      var linkedNodes = Array.prototype.slice.call(doc.querySelectorAll("a[href], form[action]"));
      for (var j = 0; j < linkedNodes.length; j += 1) {
        var href = linkedNodes[j].getAttribute("href") || linkedNodes[j].getAttribute("action") || "";
        if (!rarePattern.test(href)) continue;
        var linkedGrade = normalizeGradeName((linkedNodes[j].className || "") + " " + cleanText(linkedNodes[j].textContent));
        if (linkedGrade !== "Unknown") return linkedGrade;
      }

      return RARE_GRADE_HINTS[String(rare)] || "Unknown";
    }

      return "Unknown";
  }

  function hasLockedMarker(element) {
    var text = (classBlob(element) + " " + cleanText(element.textContent)).toLowerCase();
    return /(not[_-]?get|not[_-]?have|not[_-]?owned|unowned|locked|lock|disable|未取得|未獲得|未所持|미획득|미보유|잠김)/i.test(text);
  }

  function nearestTitleBlock(element) {
    var current = element;
    var best = element;
    var depth = 0;
    while (current && current.nodeType === 1 && depth < 6) {
      var cls = current.className || "";
      var text = cleanText(current.innerText || current.textContent || "");
      if (
        /trophy|title|basic_block|see_through_block|m_15|p_10|collection/i.test(cls) &&
        text.length > 0 &&
        text.length < 650
      ) {
        best = current;
      }
      current = current.parentElement;
      depth += 1;
    }
    return best;
  }

  function splitUsefulLines(text) {
    var noise = /^(set|setting|decide|select|back|prev|previous|next|page|collection|칭호|称号|title|trophy|normal|bronze|silver|gold|rainbow|\d+\/\d+|\d+|取得済み|획득|보유)$/i;
    return cleanText(text)
      .split(/\n+/)
      .map(cleanText)
      .filter(function (line) {
        return line && line.length <= 260 && !noise.test(line);
      });
  }

  function findDescription(block, name) {
    var selectors = [
      "[class*='description']",
      "[class*='explain']",
      "[class*='condition']",
      "[class*='detail']",
      "[class*='comment']",
      "[class*='text']"
    ];

    for (var i = 0; i < selectors.length; i += 1) {
      var matches = Array.prototype.slice.call(block.querySelectorAll(selectors[i]));
      for (var j = 0; j < matches.length; j += 1) {
        var candidate = cleanText(matches[j].innerText || matches[j].textContent || "");
        if (candidate && candidate !== name && candidate.length <= 320) return candidate;
      }
    }

    var lines = splitUsefulLines(block.innerText || block.textContent || "").filter(function (line) {
      return line !== name && line.indexOf(name + " ") !== 0;
    });
    if (!lines.length) return "";

    var descriptive = lines.filter(function (line) {
      return /[.!?。！？]|clear|play|achieve|rank|score|track|song|music|reward|complete|획득|클리어|플레이|달성|조건|스코어|칭호|보상|완료|プレイ|クリア|達成|獲得|楽曲|スコア/i.test(line);
    });
    return (descriptive[0] || lines[1] || lines[0] || "").slice(0, 320);
  }

  function gradeFromCollectionBlock(block, pageGradeHint) {
    var blockInfo = block.querySelector(".block_info");
    var blockInfoText = cleanText(blockInfo ? blockInfo.textContent : "").toUpperCase();
    if (blockInfoText === "RANDOM") return "Random";
    if (BLOCK_INFO_GRADES[blockInfoText]) return BLOCK_INFO_GRADES[blockInfoText];

    var classGrade = detectGrade(block);
    if (classGrade !== "Unknown") return classGrade;
    return pageGradeHint || "Unknown";
  }

  function descriptionFromCollectionBlock(block) {
    var candidates = Array.prototype.slice.call(block.children).filter(function (child) {
      var cls = child.className || "";
      return child.tagName === "DIV" &&
        !/block_info|collection_trophy_block|trophy_block|clearfix/i.test(cls) &&
        /break|f_12|gray|p_l_5/i.test(cls);
    });

    if (!candidates.length) {
      candidates = Array.prototype.slice.call(block.querySelectorAll("div")).filter(function (child) {
        var cls = child.className || "";
        return /break|f_12|gray|p_l_5/i.test(cls) && !child.querySelector(".trophy_inner_block");
      });
    }

    var source = candidates[0];
    if (!source) return "";

    var clone = source.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll("form, button, img, input, .f_r"), function (node) {
      node.remove();
    });
    Array.prototype.forEach.call(clone.querySelectorAll("br"), function (br) {
      br.replaceWith("\n");
    });

    return cleanText(clone.textContent || "").slice(0, 320);
  }

  function categoryFromUrl(pageUrl) {
    var path = "";
    try {
      path = new URL(pageUrl, location.href).pathname.toLowerCase();
    } catch (error) {
      path = String(pageUrl || "").toLowerCase();
    }

    if (/\/collection\/nameplate\/?/.test(path)) return "nameplate";
    if (/\/collection\/frame\/?/.test(path)) return "frame";
    if (/\/collection\/trophy\/?/.test(path)) return "trophy";
    if (/\/collection\/eventcharacter\/?/.test(path)) return "eventCharacter";
    if (/\/collection\/character\/?/.test(path)) return "character";
    if (/\/collection\/partner\/?/.test(path)) return "partner";
    if (/\/collection\/?$/.test(path)) return "icon";
    return "unknown";
  }

  function isUiImage(src) {
    return /\/img\/(?:line_|btn_|menu_|title_|logo|banner_|footer|icon_on|page_|tab_|bg_|chara_01|apple-touch-icon)/i.test(src || "");
  }

  function imageUrlFromElement(img, pageUrl) {
    var src = img ? (img.getAttribute("src") || "") : "";
    if (!src || isUiImage(src)) return "";
    return normalizeUrl(src, pageUrl);
  }

  function imageBasename(imageUrl) {
    try {
      var url = new URL(imageUrl, location.href);
      var file = url.pathname.split("/").filter(Boolean).pop() || "";
      return decodeURIComponent(file.replace(/\.[^.]+$/, ""));
    } catch (error) {
      return String(imageUrl || "").split("/").pop().replace(/\?.*$/, "").replace(/\.[^.]+$/, "");
    }
  }

  function collectionBlockFromImage(img) {
    return img.closest(".see_through_block") ||
      img.closest(".basic_block") ||
      img.closest("[class*='collection']") ||
      img.parentElement;
  }

  function textLinesFromBlock(block) {
    if (!block) return [];
    var clone = block.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll("script, style, form, button, input, noscript"), function (node) {
      node.remove();
    });
    Array.prototype.forEach.call(clone.querySelectorAll("img"), function (img) {
      if (isUiImage(img.getAttribute("src") || "")) {
        img.remove();
      }
    });
    Array.prototype.forEach.call(clone.querySelectorAll("br"), function (br) {
      br.replaceWith("\n");
    });

    return splitUsefulLines(clone.textContent || "").filter(function (line) {
      return !/^(icon|name plate|frame|title|tour member|event tour member|partner|random|normal|bronze|silver|gold|rainbow)$/i.test(line);
    });
  }

  function nameFromGenericCollectionBlock(block, img, imageUrl, category) {
    var alt = cleanText(img ? img.getAttribute("alt") : "");
    if (alt) return alt;

    var selectors = [".name_block", "[class*='name']", "[class*='title']", "[class*='item']"];
    for (var i = 0; i < selectors.length; i += 1) {
      var node = block ? block.querySelector(selectors[i]) : null;
      var text = cleanText(node ? node.textContent : "");
      if (text && text.length <= 120) return text;
    }

    var lines = textLinesFromBlock(block);
    if (lines.length && lines[0].length <= 120) return lines[0];

    return (CATEGORY_LABELS[category] || "ITEM") + " " + imageBasename(imageUrl);
  }

  function descriptionFromGenericCollectionBlock(block, name) {
    var lines = textLinesFromBlock(block).filter(function (line) {
      return line !== name;
    });
    return lines.slice(0, 3).join("\n").slice(0, 320);
  }

  function findCollectionImages(doc, pageUrl, category) {
    var pattern = CATEGORY_IMAGE_PATTERNS[category];
    var images = Array.prototype.slice.call(doc.querySelectorAll("img[src]")).map(function (img) {
      return {
        img: img,
        url: imageUrlFromElement(img, pageUrl)
      };
    }).filter(function (entry) {
      if (!entry.url) return false;
      if (pattern && pattern.test(entry.url)) return true;
      return !pattern && !isUiImage(entry.url);
    });

    if (!images.length && pattern) {
      images = Array.prototype.slice.call(doc.querySelectorAll("img[src]")).map(function (img) {
        return {
          img: img,
          url: imageUrlFromElement(img, pageUrl)
        };
      }).filter(function (entry) {
        return entry.url && !isUiImage(entry.url);
      });
    }

    return images;
  }

  function parseByGenericCollectionImages(doc, pageUrl) {
    var category = categoryFromUrl(pageUrl);
    if (category === "trophy" || category === "unknown") return [];

    var seen = new Set();
    var results = [];
    findCollectionImages(doc, pageUrl, category).forEach(function (entry) {
      if (seen.has(entry.url)) return;
      seen.add(entry.url);

      var block = collectionBlockFromImage(entry.img);
      var name = nameFromGenericCollectionBlock(block, entry.img, entry.url, category);
      var description = descriptionFromGenericCollectionBlock(block, name);

      results.push({
        category: category,
        name: name,
        description: description,
        grade: "",
        imageUrl: entry.url,
        imageAlt: cleanText(entry.img.getAttribute("alt") || ""),
        source: pageUrl
      });
    });

    return results;
  }

  function parseByCollectionTrophyBlocks(doc, pageUrl) {
    var blocks = Array.prototype.slice.call(doc.querySelectorAll(".see_through_block")).filter(function (block) {
      return block.querySelector(".collection_trophy_block .trophy_inner_block, .collection_trophy_block");
    });
    var pageGradeHint = gradeHintFromPage(doc, pageUrl);
    var results = [];

    blocks.forEach(function (block) {
      var grade = gradeFromCollectionBlock(block, pageGradeHint);
      if (grade === "Random") return;

      var titleNode = block.querySelector(".collection_trophy_block .trophy_inner_block, .trophy_inner_block");
      var name = cleanText(titleNode ? titleNode.textContent : "");
      name = name.replace(/^\[?(Rainbow|Gold|Silver|Bronze|Normal|rare=\d+)\]?\s*/i, "").trim();
      if (!name || name.length > 140) return;

      results.push({
        category: "trophy",
        name: name,
        description: descriptionFromCollectionBlock(block),
        grade: grade,
        imageUrl: "",
        imageAlt: "",
        source: pageUrl
      });
    });

    return results;
  }

  function itemFromNameNode(node, pageUrl, pageGradeHint) {
    var block = nearestTitleBlock(node);
    if (!block || hasLockedMarker(block)) return null;

    var name = cleanText(node.innerText || node.textContent || "");
    name = name.replace(/^\[?(Rainbow|Gold|Silver|Bronze|Normal|rare=\d+)\]?\s*/i, "").trim();
    if (!name || name.length > 120) return null;

    var description = findDescription(block, name);
    var grade = detectGrade(block);
    if (grade === "Unknown" && pageGradeHint) grade = pageGradeHint;
    return {
      category: "trophy",
      name: name,
      description: description,
      grade: grade,
      imageUrl: "",
      imageAlt: "",
      source: pageUrl
    };
  }

  function parseByKnownTrophyBlocks(doc, pageUrl) {
    var nodes = Array.prototype.slice.call(doc.querySelectorAll(".trophy_inner_block"));
    var results = [];
    var pageGradeHint = gradeHintFromPage(doc, pageUrl);
    nodes.forEach(function (node) {
      var item = itemFromNameNode(node, pageUrl, pageGradeHint);
      if (item) results.push(item);
    });
    return results;
  }

  function parseByGenericBlocks(doc, pageUrl) {
    var candidates = Array.prototype.slice.call(doc.querySelectorAll("[class*='trophy'], [class*='title']"));
    var results = [];
    var pageGradeHint = gradeHintFromPage(doc, pageUrl);
    candidates.forEach(function (node) {
      if (node.querySelector("[class*='trophy'], [class*='title']") && !/inner|name|text/i.test(node.className || "")) return;
      var item = itemFromNameNode(node, pageUrl, pageGradeHint);
      if (item) results.push(item);
    });
    return results;
  }

  function parseCollectionItems(doc, pageUrl) {
    var category = categoryFromUrl(pageUrl);
    var items = category === "trophy" ? parseByCollectionTrophyBlocks(doc, pageUrl) : parseByGenericCollectionImages(doc, pageUrl);
    if (items.length) return items;
    if (category !== "trophy") return [];
    items = parseByKnownTrophyBlocks(doc, pageUrl);
    if (!items.length) items = parseByGenericBlocks(doc, pageUrl);
    return items;
  }

  function dedupeItems(items) {
    var map = new Map();
    items.forEach(function (item) {
      var key = [item.category, item.grade, item.name, item.description, item.imageUrl].join("\u0001").toLowerCase();
      if (!map.has(key)) map.set(key, item);
    });
    return Array.from(map.values()).sort(function (a, b) {
      var categoryDiff = CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category);
      if (categoryDiff !== 0) return categoryDiff;
      var gradeA = GRADE_ORDER.indexOf(a.grade);
      var gradeB = GRADE_ORDER.indexOf(b.grade);
      if (gradeA < 0) gradeA = GRADE_ORDER.length;
      if (gradeB < 0) gradeB = GRADE_ORDER.length;
      var gradeDiff = gradeA - gradeB;
      if (gradeDiff !== 0) return gradeDiff;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });
  }

  function downloadJson(win, items) {
    var blob = new Blob([JSON.stringify(items, null, 2)], { type: "application/json;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = win.document.createElement("a");
    anchor.href = url;
    anchor.download = "maimai_collections.json";
    win.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function toCsv(items) {
    var rows = [["category", "grade", "name", "description", "imageUrl", "source"]].concat(items.map(function (item) {
      return [CATEGORY_LABELS[item.category] || item.category, item.grade, item.name, item.description, item.imageUrl, item.source];
    }));
    return rows.map(function (row) {
      return row.map(function (cell) {
        return '"' + String(cell == null ? "" : cell).replace(/"/g, '""') + '"';
      }).join(",");
    }).join("\n");
  }

  function downloadCsv(win, items) {
    var blob = new Blob(["\ufeff" + toCsv(items)], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = win.document.createElement("a");
    anchor.href = url;
    anchor.download = "maimai_collections.csv";
    win.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function renderResults(win, items, diagnostics) {
    var grouped = CATEGORY_ORDER.map(function (category) {
      return {
        category: category,
        items: items.filter(function (item) { return item.category === category; })
      };
    }).filter(function (group) {
      return group.items.length > 0;
    });

    var imageCount = items.filter(function (item) { return item.imageUrl; }).length;
    var summaryHtml = [
      "<div><b>" + escapeHtml(items.length) + "</b><span>컬렉션 항목</span></div>",
      "<div><b>" + escapeHtml(grouped.length) + "</b><span>카테고리</span></div>",
      "<div><b>" + escapeHtml(imageCount) + "</b><span>이미지 링크</span></div>",
      "<div><b>" + escapeHtml(diagnostics.fetchedPages) + "</b><span>읽은 페이지</span></div>"
    ].join("");

    var groupsHtml = grouped.map(function (group) {
      var rows = group.items.map(function (item) {
        var imageHtml = item.imageUrl
          ? "<a href=\"" + escapeHtml(item.imageUrl) + "\" target=\"_blank\" rel=\"noopener\"><img class=\"item-thumb\" src=\"" + escapeHtml(item.imageUrl) + "\" alt=\"" + escapeHtml(item.imageAlt || item.name) + "\"></a>"
          : "";
        var meta = item.grade ? "<span class=\"meta\">" + escapeHtml(GRADE_LABELS[item.grade] || item.grade) + "</span>" : "";
        var imageLink = item.imageUrl ? "<a class=\"image-link\" href=\"" + escapeHtml(item.imageUrl) + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(item.imageUrl) + "</a>" : "";
        var searchText = [
          CATEGORY_LABELS[item.category] || item.category,
          item.grade || "",
          item.name || "",
          item.description || "",
          item.imageUrl || ""
        ].join(" ").toLowerCase();

        return "<tr data-search=\"" + escapeHtml(searchText) + "\"><td class=\"thumb-cell\">" +
          imageHtml +
          "</td><td><span class=\"name\">" +
          escapeHtml(item.name) +
          "</span>" +
          meta +
          imageLink +
          "</td><td class=\"desc\">" +
          escapeHtml(item.description || "설명문을 찾지 못했습니다.") +
          "</td><td><span class=\"source\">" +
          escapeHtml(item.source) +
          "</span></td></tr>";
      }).join("");

      return "<section class=\"panel grade " + escapeHtml(group.category) + "\" data-category=\"" + escapeHtml(group.category) + "\"><div class=\"grade-head\"><h2>" +
        escapeHtml(CATEGORY_LABELS[group.category] || group.category) +
        "</h2><span class=\"count\">" +
        escapeHtml(group.items.length) +
        "개</span></div><table><thead><tr><th>이미지</th><th>항목</th><th>설명</th><th>출처</th></tr></thead><tbody>" +
        rows +
        "</tbody></table></section>";
    }).join("");

    if (!groupsHtml) {
      groupsHtml = "<div class=\"panel empty\">표시할 컬렉션 항목이 없습니다.</div>";
    }

    var html = "<div class=\"toolbar\"><input id=\"filter\" type=\"search\" placeholder=\"카테고리, 이름, 설명, 이미지 URL 검색\"><button id=\"json-download\" type=\"button\">JSON 저장</button><button id=\"csv-download\" type=\"button\">CSV 저장</button></div><div class=\"summary\">" +
      summaryHtml +
      "</div>" +
      groupsHtml;

    setReport(win, html, "보유 컬렉션 항목과 이미지 링크입니다.", "완료");

    var filterInput = win.document.getElementById("filter");
    if (filterInput) {
      filterInput.addEventListener("input", function () {
        var query = filterInput.value.trim().toLowerCase();
        Array.prototype.forEach.call(win.document.querySelectorAll("tbody tr"), function (row) {
          var text = row.getAttribute("data-search") || "";
          row.style.display = !query || text.indexOf(query) !== -1 ? "" : "none";
        });
        Array.prototype.forEach.call(win.document.querySelectorAll("section.grade"), function (section) {
          var visible = Array.prototype.some.call(section.querySelectorAll("tbody tr"), function (row) {
            return row.style.display !== "none";
          });
          section.style.display = visible ? "" : "none";
        });
      });
    }

    var jsonButton = win.document.getElementById("json-download");
    if (jsonButton) jsonButton.addEventListener("click", function () { downloadJson(win, items); });

    var csvButton = win.document.getElementById("csv-download");
    if (csvButton) csvButton.addEventListener("click", function () { downloadCsv(win, items); });
  }

  if (!isMaimaiMobilePage()) {
    alert("maimai DX NET 로그인 후 https://maimaidx-eng.com/maimai-mobile/ 안에서 실행해 주세요.");
    return;
  }

  var reportWindow = openReportWindow();
  if (!reportWindow) return;

  var queue = [];
  var queued = new Set();
  var visited = new Set();
  var allItems = [];
  var diagnostics = [];
  var debugPages = [];

  function addUrl(rawUrl) {
    var href = normalizeUrl(rawUrl);
    if (!href || queued.has(href) || visited.has(href)) return;
    if (!isReadOnlyCollectionUrl(href, "")) return;
    if (!isAllowedCollectionListUrl(href, "")) return;
    queued.add(href);
    queue.push(href);
  }

  function addBaseCollectionUrls() {
    COLLECTION_URLS.forEach(addUrl);
  }

  function addTrophyRareUrls() {
    TROPHY_RARE_VALUES.forEach(function (rare) {
      addUrl("/maimai-mobile/collection/trophy/?rare=" + rare);
    });
  }

  function rememberDebugPage(page, parsedCount, note) {
    debugPages.push({
      requestedUrl: page.requestedUrl || page.url,
      finalUrl: page.url,
      loader: page.loader || "",
      ok: page.ok,
      status: page.status,
      statusText: page.statusText,
      title: cleanText(page.doc && page.doc.title ? page.doc.title : ""),
      htmlLength: page.text ? page.text.length : 0,
      parsedItemCount: parsedCount || 0,
      note: note || "",
      iframeError: page.iframeError || "",
      html: sanitizeDebugHtml(page.text || "")
    });
  }

  addUrl(location.href);
  addBaseCollectionUrls();
  addTrophyRareUrls();

  try {
    var currentPage = pageFromCurrentDocument();
    var currentParsed = parseCollectionItems(currentPage.doc, currentPage.url);
    rememberDebugPage(currentPage, currentParsed.length, "북마클릿을 실행한 현재 페이지");
    discoverLinks(currentPage.doc, currentPage.url, addUrl);
    allItems = allItems.concat(currentParsed);
    visited.add(normalizeUrl(location.href));

    renderLoading(reportWindow, "컬렉션 페이지를 준비하는 중", "기본 컬렉션 후보 페이지 " + queue.length + "개를 준비했습니다.");

    while (queue.length && visited.size < MAX_PAGES) {
      var url = queue.shift();
      queued.delete(url);
      if (visited.has(url)) continue;
      visited.add(url);

      renderLoading(reportWindow, "컬렉션 페이지를 읽는 중", visited.size + "번째 페이지: " + url);
      await sleep(PAGE_DELAY_MS);

      var page;
      try {
        page = await loadPage(url);
      } catch (fetchError) {
        diagnostics.push(fetchError.message || String(fetchError));
        continue;
      }

      if (!page.ok) {
        diagnostics.push("HTTP " + page.status + " " + page.statusText + " - " + url);
      }

      var parsed = parseCollectionItems(page.doc, page.url);
      rememberDebugPage(page, parsed.length, isMaimaiErrorPage(page) ? "maimai error page" : (page.ok ? "" : "HTTP 오류 응답"));

      if (/login|sega|aime/i.test(page.doc.title || "") && page.text.indexOf("maimai-mobile") === -1) {
        diagnostics.push("로그인 페이지로 이동한 것 같습니다: " + url);
        continue;
      }

      if (!page.ok || isMaimaiErrorPage(page)) {
        continue;
      }

      discoverLinks(page.doc, page.url, addUrl);
      allItems = allItems.concat(parsed);
    }

    var uniqueItems = dedupeItems(allItems);
    if (!uniqueItems.length) {
      renderDebugError(
        reportWindow,
        "컬렉션 항목을 찾지 못했습니다.",
        "collection 페이지는 읽었지만, 보유 컬렉션 항목으로 보이는 내용을 파싱하지 못했습니다. 디버그 JSON을 붙여넣으면 selector를 다시 맞출 수 있습니다.",
        diagnostics.concat(["읽은 페이지 수: " + visited.size]),
        debugPages
      );
      return;
    }

    renderResults(reportWindow, uniqueItems, {
      fetchedPages: visited.size
    });
  } catch (error) {
    renderDebugError(reportWindow, "실행 중 오류가 발생했습니다.", error && error.stack ? error.stack : String(error), diagnostics, debugPages);
  }
}());
