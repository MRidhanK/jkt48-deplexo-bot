// ==UserScript==
// @name         JKT48 Account Bridge — Ticket Radar
// @namespace    voltvoltre.jkt48.radar
// @version      1.0.0
// @description  Membaca My Tickets dari sesi browser JKT48 lalu mengirim hasilnya ke Ticket Radar.
// @match        https://jkt48.com/*
// @grant        GM_xmlhttpRequest
// @connect      jkt48.com
// @connect      *
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  const qs = new URLSearchParams(location.search);

  // Hanya berjalan ketika dibuka oleh fitur Fetch Akun
  if (qs.get("radar_fetch") !== "1") return;

  const from =
    qs.get("from") ||
    new Date().toISOString().slice(0, 10);

  const to =
    qs.get("to") ||
    new Date(Date.now() + 32 * 86400000)
      .toISOString()
      .slice(0, 10);

  const token = qs.get("token") || "";
  const callback = qs.get("callback") || "";

  // =========================================================
  // UI OVERLAY
  // =========================================================

  function overlay(title, message, ok = false) {
    let box = document.getElementById("radar-account-bridge");

    if (!box) {
      box = document.createElement("div");
      box.id = "radar-account-bridge";

      box.style.cssText = [
        "position:fixed",
        "inset:16px",
        "z-index:2147483647",
        "display:flex",
        "align-items:center",
        "justify-content:center",
        "pointer-events:none"
      ].join(";");

      document.documentElement.appendChild(box);
    }

    box.innerHTML = "";

    const card = document.createElement("div");

    card.style.cssText = [
      "pointer-events:auto",
      "width:min(480px,calc(100vw - 32px))",
      "padding:20px",
      "border-radius:16px",
      "background:#181b25",
      "color:#fff",
      "font:14px/1.55 system-ui,sans-serif",
      "box-shadow:0 20px 60px rgba(0,0,0,.4)",
      "border:1px solid rgba(255,255,255,.14)"
    ].join(";");

    const h = document.createElement("div");

    h.textContent = title;

    h.style.cssText =
      "font-size:18px;font-weight:700;margin-bottom:8px";

    const p = document.createElement("div");

    p.textContent = message;

    p.style.cssText = "opacity:.8;white-space:pre-line";

    card.append(h, p);
    box.appendChild(card);
  }

  // =========================================================
  // HELPER
  // =========================================================

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // =========================================================
  // BACA SESSION AKUN JKT48
  // =========================================================

  async function getSession() {
    const r = await fetch("/api/auth/session", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: {
        "Accept": "application/json"
      }
    });

    if (!r.ok) {
      throw new Error(
        "/api/auth/session HTTP " + r.status
      );
    }

    const j = await r.json();

    if (!j?.user) {
      throw new Error(
        "Sesi JKT48 tidak ditemukan. Login dulu di jkt48.com."
      );
    }

    return j;
  }

  // =========================================================
  // FETCH SATU HALAMAN MY TICKETS
  // =========================================================

  async function fetchMyTicketsPage(page, accessToken) {
    const params = new URLSearchParams({
      lang: "id",
      limit: "10",
      page: String(page),
      from,
      to
    });

    const headers = {
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
      "Cache-Control": "no-cache",
      "Pragma": "no-cache"
    };

    // Access token hanya digunakan di browser.
    // Tidak dikirim ke backend Ticket Radar.
    if (accessToken) {
      headers.Authorization = "Bearer " + accessToken;
    }

    let r = await fetch(
      "/api/v1/accounts/my-tickets?" +
        params.toString(),
      {
        method: "GET",
        credentials: "include",
        cache: "no-store",
        headers
      }
    );

    // Fallback:
    // Coba tanpa Authorization apabila API cukup dengan
    // session/cookie browser.
    if (r.status === 401) {
      r = await fetch(
        "/api/v1/accounts/my-tickets?" +
          params.toString(),
        {
          method: "GET",
          credentials: "include",
          cache: "no-store",
          headers: {
            "Accept":
              "application/json, text/plain, */*",

            "Accept-Language":
              "id-ID,id;q=0.9,en;q=0.8"
          }
        }
      );
    }

    const text = await r.text();

    let j = null;

    try {
      j = JSON.parse(text);
    } catch (_) {
      // Bukan JSON
    }

    if (!r.ok) {
      const cf =
        r.headers.get("cf-mitigated") || "";

      const server =
        r.headers.get("server") || "";

      const detail = [
        "HTTP " + r.status,
        server && ("server=" + server),
        cf && ("cf=" + cf)
      ]
        .filter(Boolean)
        .join(" ");

      throw new Error(
        "My Tickets gagal: " + detail
      );
    }

    if (!j || typeof j !== "object") {
      throw new Error(
        "My Tickets bukan JSON valid."
      );
    }

    if (j.status === false) {
      throw new Error(
        String(
          j.message ||
          "My Tickets ditolak oleh JKT48."
        )
      );
    }

    return j;
  }

  // =========================================================
  // KIRIM HASIL KE BACKEND TICKET RADAR
  // =========================================================

  function gmPostJSON(url, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "POST",

        url,

        // Tidak mengirim cookie browser ke backend.
        anonymous: true,

        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },

        data: JSON.stringify(body),

        timeout: 20000,

        onload(resp) {
          let j = null;

          try {
            j = JSON.parse(
              resp.responseText || "{}"
            );
          } catch (_) {
            // Backend bukan JSON
          }

          if (
            resp.status >= 200 &&
            resp.status < 300
          ) {
            return resolve(j || {});
          }

          reject(
            new Error(
              (j &&
                (j.error || j.message)) ||
              ("Backend HTTP " + resp.status)
            )
          );
        },

        ontimeout() {
          reject(
            new Error(
              "Koneksi ke Ticket Radar timeout."
            )
          );
        },

        onerror() {
          reject(
            new Error(
              "Tidak bisa mengirim hasil ke Ticket Radar."
            )
          );
        }
      });
    });
  }

  // =========================================================
  // MAIN
  // =========================================================

  async function run() {
    if (!token || !callback) {
      throw new Error(
        "Parameter Browser Bridge tidak lengkap."
      );
    }

    // -------------------------------------------------------
    // STEP 1 — SESSION
    // -------------------------------------------------------

    overlay(
      "🔐 JKT48 Account Bridge",
      "Membaca session akun dari browser…"
    );

    const session = await getSession();

    const accessToken =
      session?.user?.access_token || "";

    if (!accessToken) {
      throw new Error(
        "Access token akun JKT48 tidak ditemukan."
      );
    }

    // -------------------------------------------------------
    // STEP 2 — MY TICKETS
    // -------------------------------------------------------

    overlay(
      "🎟️ Membaca My Tickets",
      `${from} → ${to}\nMengambil semua halaman dari akun JKT48…`
    );

    const all = [];

    let page = 1;
    let totalPage = 1;
    let guard = 0;

    // -------------------------------------------------------
    // PAGINATION
    // -------------------------------------------------------

    while (
      page <= totalPage &&
      guard < 100
    ) {
      const payload =
        await fetchMyTicketsPage(
          page,
          accessToken
        );

      const rows =
        Array.isArray(payload.data)
          ? payload.data
          : [];

      all.push(...rows);

      const meta =
        payload._meta || {};

      totalPage =
        Math.max(
          1,
          Number(
            meta.total_page || 1
          )
        );

      overlay(
        "🎟️ Membaca My Tickets",
        `Halaman ${page}/${totalPage} · ${all.length} record`
      );

      page += 1;
      guard += 1;

      if (page <= totalPage) {
        await sleep(180);
      }
    }

    // -------------------------------------------------------
    // STEP 3 — KIRIM RESULT KE BACKEND
    // -------------------------------------------------------

    overlay(
      "📡 Mengirim Data",
      `${all.length} record berhasil dibaca.\nMengirim hasil ke Ticket Radar…`
    );

    const imported =
      await gmPostJSON(
        callback,
        {
          token,

          from,
          to,

          pages_fetched:
            Math.max(
              1,
              page - 1
            ),

          fetched_at:
            Date.now() / 1000,

          tickets: all
        }
      );

    if (!imported?.ok) {
      throw new Error(
        imported?.error ||
        "Backend menolak hasil My Tickets."
      );
    }

    // -------------------------------------------------------
    // SUCCESS
    // -------------------------------------------------------

    overlay(
      "✅ Fetch Akun Berhasil",
      `${all.length} record berhasil dikirim ke Ticket Radar.\nTab ini bisa ditutup.`,
      true
    );

    setTimeout(() => {
      try {
        window.close();
      } catch (_) {}
    }, 1400);
  }

  // =========================================================
  // ERROR HANDLER
  // =========================================================

  run().catch(err => {
    console.error(
      "JKT48 Account Bridge:",
      err
    );

    overlay(
      "❌ Fetch Akun Gagal",
      err?.message ||
        String(err)
    );
  });

})();