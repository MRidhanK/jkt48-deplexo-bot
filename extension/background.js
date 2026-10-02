"use strict";

// ====== KONFIGURASI ======
const NOTIFIER_URL = "https://jkt-bot-2shoot.de.deplexo.com/notify";
// Isi dengan secret BARU (yang lama sudah bocor di chat). Harus sama dengan env NOTIFY_SECRET di server.
const NOTIFY_SECRET = "GANTI_DENGAN_SECRET_BARU";
const EVENT_CODES = ["EX5B99", "EX24AE"];

const ALARM_NAME = "jkt48-poll";
const POLL_PERIOD_MIN = 0.5;          // 30 detik (minimum Chrome >= 120)
const BACKOFF_BASE_MS = 2 * 60_000;   // kena 403/429 -> tunggu 2 menit, lalu 4, 8, ... maks 30 menit
const BACKOFF_MAX_MS = 30 * 60_000;
const STATE_KEY = "pollState";
// =========================

const apiUrl = code =>
  `https://jkt48.com/api/v1/exclusives/${code}/bonus?lang=id`;

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function loadState() {
  const raw = await chrome.storage.local.get(STATE_KEY);
  return raw[STATE_KEY] || {};
}

async function saveState(state) {
  await chrome.storage.local.set({ [STATE_KEY]: state });
}

async function postNotify(body) {
  try {
    const res = await fetch(NOTIFIER_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Notify-Secret": NOTIFY_SECRET
      },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      console.warn("[JKT48] Notifier membalas", res.status);
    }
  } catch (err) {
    console.warn("[JKT48] Tidak bisa menghubungi notifier:", err.message);
  }
}

function markFailure(entry, blocked) {
  entry.fails = (entry.fails || 0) + 1;
  if (blocked) {
    const wait = Math.min(BACKOFF_BASE_MS * 2 ** (entry.fails - 1), BACKOFF_MAX_MS);
    entry.until = Date.now() + wait;
  }
}

async function pollCode(code, state) {
  const entry = (state[code] = state[code] || { fails: 0, until: 0 });

  if (Date.now() < entry.until) {
    console.log(`[JKT48] ${code} masih cooldown ${Math.ceil((entry.until - Date.now()) / 1000)}s`);
    return;
  }

  let res;
  try {
    res = await fetch(`${apiUrl(code)}&_=${Date.now()}`, {
      method: "GET",
      credentials: "include", // bawa cookie browser (termasuk cf_clearance)
      cache: "no-store",
      headers: { Accept: "application/json, text/plain, */*" }
    });
  } catch (err) {
    markFailure(entry, false);
    await postNotify({ code, error: `fetch gagal: ${err.message}` });
    return;
  }

  if (!res.ok) {
    const blocked = res.status === 403 || res.status === 429;
    markFailure(entry, blocked);
    console.warn(`[JKT48] ${code} HTTP ${res.status}`);
    await postNotify({ code, error: `HTTP ${res.status}` });
    return;
  }

  let json;
  try {
    json = JSON.parse(await res.text());
  } catch {
    markFailure(entry, true);
    await postNotify({ code, error: "bukan JSON (kemungkinan halaman verifikasi Cloudflare)" });
    return;
  }

  entry.fails = 0;
  entry.until = 0;

  // Server menerima {"code": ..., "data": [...respons mentah...]} dan meratakannya sendiri.
  const data = Array.isArray(json?.data) ? json.data : [];
  await postNotify({ code, data });

  const lanes = data.reduce((n, s) => n + (s?.session_members?.length || 0), 0);
  console.log(`[JKT48] ${code}: ${data.length} sesi, ${lanes} jalur terkirim`);
}

let running = false;

async function pollAll() {
  if (running) return;
  running = true;
  try {
    const state = await loadState();
    for (let i = 0; i < EVENT_CODES.length; i++) {
      try {
        await pollCode(EVENT_CODES[i], state);
      } catch (err) {
        console.error(`[JKT48] ${EVENT_CODES[i]} error:`, err);
      }
      if (i < EVENT_CODES.length - 1) {
        await sleep(1000 + Math.random() * 2000);
      }
    }
    await saveState(state);
  } finally {
    running = false;
  }
}

async function ensureAlarm() {
  const existing = await chrome.alarms.get(ALARM_NAME);
  if (!existing) {
    chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_PERIOD_MIN, delayInMinutes: 0.1 });
  }
}

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM_NAME) pollAll();
});

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
  pollAll();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
  pollAll();
});

// Jaga-jaga jika service worker dibangunkan tanpa event install/startup.
ensureAlarm();