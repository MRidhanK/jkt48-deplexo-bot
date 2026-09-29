(() => {
  "use strict";

  if (window.__JKT48_HOOK__) return;
  window.__JKT48_HOOK__ = true;

  const TAG = "JKT48_HOOK";
  let lastRequest = null;

  function looksLikeTicketData(json) {
    return (
      json &&
      Array.isArray(json.data) &&
      json.data.some(item => item && Array.isArray(item.session_members))
    );
  }

  function publish(json, url) {
    window.postMessage({ source: TAG, type: "DATA", url, json }, location.origin);
  }

  function handleText(text, url, requestInfo) {
    try {
      const json = JSON.parse(text);
      if (!looksLikeTicketData(json)) return;
      if (requestInfo) lastRequest = requestInfo;
      publish(json, url);
    } catch {
      // Bukan JSON; abaikan.
    }
  }

  // ---- fetch ----
  const originalFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    const promise = originalFetch(input, init);

    promise.then(response => {
      try {
        const url = typeof input === "string" ? input : input?.url || String(input);
        const method = (init?.method || input?.method || "GET").toUpperCase();
        const headers = {};
        new Headers(init?.headers || input?.headers || {}).forEach((v, k) => {
          headers[k] = v;
        });
        const body = typeof init?.body === "string" ? init.body : undefined;

        response.clone().text().then(text =>
          handleText(text, url, { url, method, headers, body })
        ).catch(() => {});
      } catch {
        // Jangan pernah mengganggu request halaman.
      }
    }).catch(() => {});

    return promise;
  };

  // ---- XMLHttpRequest ----
  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  const xhrSetHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__jkt = { method: String(method || "GET").toUpperCase(), url: String(url), headers: {} };
    return xhrOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    if (this.__jkt) this.__jkt.headers[name] = value;
    return xhrSetHeader.call(this, name, value);
  };

  XMLHttpRequest.prototype.send = function (body) {
    this.addEventListener("load", () => {
      try {
        if (this.responseType && this.responseType !== "text") return;
        const info = this.__jkt || {};
        handleText(this.responseText, info.url, {
          ...info,
          body: typeof body === "string" ? body : undefined
        });
      } catch {
        // abaikan
      }
    });
    return xhrSend.call(this, body);
  };

  // ---- permintaan ulang dari content script ----
  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    if (event.data?.source !== "JKT48_CONTENT" || event.data.type !== "REFETCH") return;
    if (!lastRequest) return;

    const { url, method, headers, body } = lastRequest;

    originalFetch(url, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : body,
      credentials: "include"
    })
      .then(r => r.text())
      .then(text => handleText(text, url, null))
      .catch(() => {});
  });
})();