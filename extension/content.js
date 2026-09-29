(() => {
  "use strict";

  if (window.__JKT48_TICKET_RADAR_V64__) return;
  window.__JKT48_TICKET_RADAR_V64__ = true;

  const ALLOWED_CODES = new Set(["EX5B99", "EX24AE"]);
  const EXPECTED_LANES_PER_SESSION = 25;
  const SCAN_INTERVAL_MS = 30_000;
  const INITIAL_SCAN_DELAYS = [3000, 8000];
  const STORAGE_PREFIX = "jkt48-ticket-radar-v64:";

  const currentUrl = new URL(location.href);
  const code = currentUrl.searchParams.get("code")?.toUpperCase();

  if (
    currentUrl.origin !== "https://jkt48.com" ||
    currentUrl.pathname !== "/purchase/exclusive" ||
    !ALLOWED_CODES.has(code)
  ) {
    return;
  }

  let scanning = false;
  let stopped = false;
  let intervalId = null;
  const initialTimeouts = [];

  // Data JSON hasil intercept fetch/XHR dari page_hook.js (world MAIN).
  let interceptedJson = null;
  let pendingFresh = null;

  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin) return;
    if (event.data?.source !== "JKT48_HOOK" || event.data.type !== "DATA") return;

    interceptedJson = event.data.json;

    if (pendingFresh) {
      pendingFresh();
      pendingFresh = null;
    }
  });

  function requestFreshData(timeoutMs = 5000) {
    return new Promise(resolve => {
      const timer = setTimeout(() => {
        pendingFresh = null;
        resolve(false);
      }, timeoutMs);

      pendingFresh = () => {
        clearTimeout(timer);
        resolve(true);
      };

      window.postMessage(
        { source: "JKT48_CONTENT", type: "REFETCH" },
        location.origin
      );
    });
  }

  const clean = value =>
    String(value ?? "").replace(/\s+/g, " ").trim();

  function verificationDetected() {
    const text = clean(document.body?.innerText).toLowerCase();

    return [
      "checking your browser",
      "verify you are human",
      "access denied",
      "403 forbidden",
      "just a moment"
    ].some(phrase => text.includes(phrase));
  }

  function isValidTicketRecord(value) {
    return (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      typeof value.label === "string" &&
      Object.prototype.hasOwnProperty.call(value, "price") &&
      typeof value.member_name === "string" &&
      typeof value.session_detail_code === "string" &&
      Object.prototype.hasOwnProperty.call(value, "available_quota")
    );
  }

  function normalizeRecord(value, context = {}) {
    return {
      label: clean(value.label),
      price: value.price,
      member_name: clean(value.member_name),
      session_detail_code: clean(value.session_detail_code),
      available_quota: value.available_quota,
      session_label: clean(context.session_label) || "Tidak diketahui",
      session_date: clean(context.session_date) || "Tidak diketahui",
      session_start_time:
        clean(context.session_start_time) || "Tidak diketahui",
      session_end_time:
        clean(context.session_end_time) || "Tidak diketahui",
      source: "json"
    };
  }

  function isSessionObject(value) {
    return (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Array.isArray(value.session_members)
    );
  }

  function collectRecords(value, output, context = {}, depth = 0) {
    if (depth > 30 || value === null || value === undefined) {
      return;
    }

    if (Array.isArray(value)) {
      for (const item of value) {
        collectRecords(item, output, context, depth + 1);
      }
      return;
    }

    if (typeof value !== "object") {
      return;
    }

    if (isValidTicketRecord(value)) {
      output.push(normalizeRecord(value, context));
      return;
    }

    let nextContext = context;

    if (isSessionObject(value)) {
      nextContext = {
        session_label: clean(value.label) || context.session_label,
        session_date: clean(value.date) || context.session_date,
        session_start_time:
          clean(value.start_time) || context.session_start_time,
        session_end_time:
          clean(value.end_time) || context.session_end_time
      };
    }

    for (const [key, child] of Object.entries(value)) {
      // Data sesi diwariskan hanya ke session_members.
      // Properti lain tetap dipindai untuk mendukung variasi struktur JSON.
      const childContext =
        key === "session_members" ? nextContext : context;

      collectRecords(child, output, childContext, depth + 1);
    }
  }

  /*
   * Mengambil kandidat object JSON dari teks script.
   * Kandidat hanya diparse sebagai JSON; JavaScript tidak dieksekusi.
   */
  function extractBalancedJson(text, output) {
    const source = String(text || "");
    let depth = 0;
    let start = -1;
    let inString = false;
    let escaped = false;

    for (let index = 0; index < source.length; index++) {
      const char = source[index];

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === '"') {
          inString = false;
        }
        continue;
      }

      if (char === '"') {
        inString = true;
        continue;
      }

      if (char === "{") {
        if (depth === 0) start = index;
        depth++;
        continue;
      }

      if (char === "}") {
        if (depth === 0) continue;

        depth--;

        if (depth === 0 && start >= 0) {
          const candidate = source.slice(start, index + 1);

          try {
            collectRecords(JSON.parse(candidate), output);
          } catch {
            // Abaikan potongan JavaScript yang bukan JSON valid.
          }

          start = -1;
        }
      }
    }
  }

  function scanJsonScripts(output) {
    const scripts = [...document.querySelectorAll("script")];

    for (const script of scripts) {
      const type = clean(script.getAttribute("type")).toLowerCase();
      const text = script.textContent || "";

      if (!text.trim()) continue;

      if (type.includes("json")) {
        try {
          collectRecords(JSON.parse(text), output);
          continue;
        } catch {
          // Coba ekstraksi object JSON jika ada pembungkus.
        }
      }

      extractBalancedJson(text, output);
    }
  }

  function parseLaneLabel(text) {
    const match = clean(text).match(/^jalur\s*(\d+)$/i);
    if (!match) return null;

    const number = Number(match[1]);

    if (!Number.isInteger(number) || number < 1 || number > 100) {
      return null;
    }

    return number;
  }

  function inferQuotaFromText(text) {
    const value = clean(text);

    const patterns = [
      /(?:sisa|tersisa|kuota tersedia|available quota)\s*[:：]?\s*(\d+)/i,
      /(\d+)\s*(?:slot|tiket|kuota)\s*(?:tersisa|tersedia|left)/i
    ];

    for (const pattern of patterns) {
      const match = value.match(pattern);
      if (match) return Number(match[1]);
    }

    return null;
  }

  function inferPriceFromText(text) {
    const value = clean(text);
    const match = value.match(/Rp\s*([\d.]+)/i);

    if (!match) return null;

    const number = Number(match[1].replace(/\./g, ""));
    return Number.isFinite(number) ? number : null;
  }

  function findNearestLaneCard(labelElement) {
    let node = labelElement;
    let best = labelElement;

    for (let depth = 0; node && depth < 6; depth++) {
      const text = clean(node.innerText || node.textContent);

      if (!text || text.length > 1200) break;

      best = node;

      if (
        /sold\s*out|tersedia|available|habis|kuota|sisa\s*\d+/i.test(text) &&
        text.length < 900
      ) {
        return node;
      }

      node = node.parentElement;
    }

    return best;
  }

  /*
   * Fallback DOM: membaca label jalur yang terlihat.
   * Tidak mengarang nama member, kode sesi, atau kuota.
   */
  function scanVisibleLaneCards(output) {
    const elements = [
      ...document.querySelectorAll("p, span, div, label, button")
    ];

    const labels = elements.filter(element => {
      const text = clean(element.innerText || element.textContent);
      return parseLaneLabel(text) !== null;
    });

    const seenCards = new WeakSet();

    for (const labelElement of labels) {
      const laneNumber = parseLaneLabel(
        labelElement.innerText || labelElement.textContent
      );

      if (laneNumber === null) continue;

      const card = findNearestLaneCard(labelElement);

      if (seenCards.has(card)) continue;
      seenCards.add(card);

      const cardText = clean(card.innerText || card.textContent);

      output.push({
        label: `Jalur ${laneNumber}`,
        price: inferPriceFromText(cardText),
        member_name: "Tidak diketahui",
        session_detail_code: "Tidak diketahui",
        available_quota: inferQuotaFromText(cardText),
        session_label: "Tidak diketahui",
        session_date: "Tidak diketahui",
        session_start_time: "Tidak diketahui",
        session_end_time: "Tidak diketahui",
        source: "dom-fallback"
      });
    }
  }

  function recordKey(record) {
    return [
      clean(record.session_detail_code).toLowerCase(),
      clean(record.member_name).toLowerCase(),
      clean(record.label).toLowerCase()
    ].join("|");
  }

  function recordCompleteness(record) {
    return (
      Number(record.price !== null && record.price !== undefined) +
      Number(record.available_quota !== null &&
        record.available_quota !== undefined) +
      Number(record.member_name !== "Tidak diketahui") +
      Number(record.session_detail_code !== "Tidak diketahui") +
      Number(record.session_label !== "Tidak diketahui") +
      Number(record.session_date !== "Tidak diketahui")
    );
  }

  function deduplicateRecords(records) {
    const map = new Map();

    for (const record of records) {
      const key = recordKey(record);
      const existing = map.get(key);

      if (!existing) {
        map.set(key, record);
        continue;
      }

      if (recordCompleteness(record) >= recordCompleteness(existing)) {
        map.set(key, record);
      }
    }

    return [...map.values()].sort((a, b) =>
      clean(a.session_date).localeCompare(clean(b.session_date), "id") ||
      clean(a.session_start_time).localeCompare(
        clean(b.session_start_time),
        "id"
      ) ||
      clean(a.session_detail_code).localeCompare(
        clean(b.session_detail_code),
        "id"
      ) ||
      clean(a.member_name).localeCompare(clean(b.member_name), "id") ||
      clean(a.label).localeCompare(clean(b.label), "id")
    );
  }

  async function readAllTickets() {
    await requestFreshData();

    const records = [];

    if (interceptedJson) {
      collectRecords(interceptedJson, records);
    }

    if (records.length === 0) {
      scanJsonScripts(records);
    }

    if (records.length === 0) {
      // Fallback DOM tidak memuat member/kuota/kode sesi, jadi tidak dilaporkan
      // agar Discord tidak dibanjiri data "Tidak diketahui".
      const partial = [];
      scanVisibleLaneCards(partial);
      console.warn(
        `[JKT48] Data API belum tertangkap (DOM hanya melihat ${partial.length} label). ` +
        "Reload tab agar hook bisa menangkap request."
      );
      return [];
    }

    return deduplicateRecords(records);
  }

  function quotaValue(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  }

  function statusOf(record) {
    const quota = quotaValue(record.available_quota);

    if (quota === null) return "Tidak diketahui";
    return quota > 0 ? "Tersedia" : "Sold Out";
  }

  function compareRecords(previous, current) {
    const oldMap = new Map(
      (Array.isArray(previous) ? previous : []).map(record => [
        recordKey(record),
        record
      ])
    );

    const newMap = new Map(
      current.map(record => [recordKey(record), record])
    );

    const changes = [];

    for (const [key, now] of newMap) {
      const old = oldMap.get(key);

      if (!old) {
        changes.push(
          `🆕 ${now.member_name} · ${now.label} · ` +
          `${now.session_label} (${now.session_detail_code}) — ` +
          `terdeteksi; kuota ${quotaValue(now.available_quota) ?? "?"}`
        );
        continue;
      }

      const oldQuota = quotaValue(old.available_quota);
      const newQuota = quotaValue(now.available_quota);

      if (oldQuota !== newQuota) {
        const delta =
          oldQuota !== null && newQuota !== null
            ? newQuota - oldQuota
            : null;

        const changeText =
          delta === null
            ? "kuota berubah"
            : `kuota ${oldQuota} → ${newQuota} ` +
              `(${delta > 0 ? "+" : ""}${delta})`;

        changes.push(
          `🔄 ${now.member_name} · ${now.label} · ` +
          `${now.session_label} — ${changeText}`
        );
      }

      if (statusOf(old) !== statusOf(now) && oldQuota === newQuota) {
        changes.push(
          `🚦 ${now.member_name} · ${now.label} · ` +
          `${now.session_label} — ${statusOf(old)} → ${statusOf(now)}`
        );
      }
    }

    for (const [key, old] of oldMap) {
      if (!newMap.has(key)) {
        changes.push(
          `⚠️ Tidak lagi terdeteksi: ${old.member_name} · ` +
          `${old.label} · ${old.session_label} · ` +
          `${old.session_detail_code}`
        );
      }
    }

    return changes;
  }

  function sendReport(payload) {
    try {
      chrome.runtime.sendMessage(
        {
          type: "JKT48_FULL_REPORT",
          payload
        },
        response => {
          if (chrome.runtime.lastError) {
            console.error(
              "[JKT48] Background error:",
              chrome.runtime.lastError.message
            );
            return;
          }

          if (!response?.ok) {
            console.error("[JKT48] Gagal mengirim laporan:", {
              status: response?.status,
              error: response?.error,
              serverError: response?.result?.error,
              response
            });
            return;
          }

          console.log(
            `[JKT48] Laporan terkirim: ${payload.lanes.length} record; ` +
            `${payload.changes.length} perubahan.`
          );
        }
      );
    } catch (error) {
      console.error("[JKT48] Gagal mengirim pesan:", error);
    }
  }

  function summarizeRecords(lanes) {
    return lanes.reduce((result, lane) => {
      const status = statusOf(lane);
      result[status] = (result[status] || 0) + 1;
      return result;
    }, {});
  }

  async function scanPage() {
    if (scanning || stopped) return;

    scanning = true;

    try {
      if (verificationDetected()) {
        stopped = true;

        if (intervalId !== null) {
          clearInterval(intervalId);
          intervalId = null;
        }

        for (const timeoutId of initialTimeouts) {
          clearTimeout(timeoutId);
        }

        console.warn(
          "[JKT48] Halaman verifikasi atau akses ditolak terdeteksi. " +
          "Pemantauan dihentikan. Periksa halaman secara manual."
        );
        return;
      }

      const lanes = await readAllTickets();
      const storageKey = STORAGE_PREFIX + code;

      const stored = await chrome.storage.local.get(storageKey);
      const previousLanes = stored[storageKey]?.lanes || [];
      const changes = compareRecords(previousLanes, lanes);

      const scannedAt = new Date().toLocaleString("id-ID", {
        timeZone: "Asia/Jakarta"
      });

      const payload = {
        code,
        title: "JKT48 Ticket Radar",
        scannedAt,
        pageUrl: location.href,
        expectedLanesPerSession: EXPECTED_LANES_PER_SESSION,
        laneCount: lanes.length,
        lanes,
        changes
      };

      // Laporan lengkap dikirim pada setiap pemindaian.
      sendReport(payload);

      /*
       * Simpan snapshot hanya jika data ditemukan.
       * Hasil kosong sesaat tidak akan menghapus snapshot lama.
       */
      if (lanes.length > 0) {
        await chrome.storage.local.set({
          [storageKey]: {
            lanes,
            scannedAt: Date.now()
          }
        });
      }

      console.log("[JKT48] Pemindaian selesai:", {
        event: code,
        records: lanes.length,
        expectedLanesPerSession: EXPECTED_LANES_PER_SESSION,
        statuses: summarizeRecords(lanes),
        changes: changes.length
      });

      if (lanes.length === 0) {
        console.warn(
          "[JKT48] Data tiket tidak ditemukan. Ini bukan bukti tiket habis. " +
          "Periksa apakah data tersedia pada dokumen halaman."
        );
      }
    } catch (error) {
      const message = String(error?.message || error);

      console.error("[JKT48] Scan gagal:", message);

      if (/extension context invalidated|context invalidated/i.test(message)) {
        stopped = true;

        if (intervalId !== null) {
          clearInterval(intervalId);
          intervalId = null;
        }

        for (const timeoutId of initialTimeouts) {
          clearTimeout(timeoutId);
        }

        console.warn(
          "[JKT48] Context extension tidak aktif. " +
          "Reload extension dan tab event."
        );
      }
    } finally {
      scanning = false;
    }
  }

  console.log(`[JKT48] Ticket Radar aktif untuk ${code}.`);

  for (const delay of INITIAL_SCAN_DELAYS) {
    const timeoutId = setTimeout(scanPage, delay);
    initialTimeouts.push(timeoutId);
  }

  intervalId = setInterval(scanPage, SCAN_INTERVAL_MS);
})();