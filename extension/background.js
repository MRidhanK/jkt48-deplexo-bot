"use strict";

const NOTIFIER_URL = "https://jkt-bot-2shoot.de.deplexo.com/notify";
const INGEST_URL = "https://jkt-bot-2shoot.de.deplexo.com/ingest"; // FITUR BARU
const NOTIFY_SECRET = "mzPgq6wNe6ZwzXT8IiS1JuoYAhLJlKaTEb1dd-QUuMI";
const INGEST_TOKEN = "isi-token-ingest-jika-ada"; // FITUR BARU, kosongkan jika tidak dipakai
const ALLOWED_CODES = new Set(["EX5B99", "EX24AE"]);
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 2000;

async function sendWithRetry(url, body, headers, attempt = 1) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body)
    });
    const result = await response.json().catch(() => ({
      error: "Server mengembalikan respons yang bukan JSON."
    }));
    return { ok: response.ok && result.ok === true, status: response.status, result };
  } catch (error) {
    if (attempt < MAX_RETRIES) {
      await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
      return sendWithRetry(url, body, headers, attempt + 1);
    }
    return { ok: false, error: `Retry habis: ${error.message}` };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "JKT48_FULL_REPORT") return false;

  const senderUrl = sender.tab?.url || "";
  const payload = message.payload || {};
  const code = String(payload.code || "").toUpperCase();

  if (
    !senderUrl.startsWith("https://jkt48.com/purchase/exclusive") ||
    !ALLOWED_CODES.has(code)
  ) {
    sendResponse({ ok: false, error: "Halaman atau kode event tidak diizinkan." });
    return false;
  }

  const body = { ...payload, code, pageUrl: senderUrl };

  // FITUR BARU: gunakan /ingest jika INGEST_TOKEN diisi, else /notify
  const useIngest = INGEST_TOKEN && INGEST_TOKEN !== "isi-token-ingest-jika-ada";
  const url = useIngest ? INGEST_URL : NOTIFIER_URL;
  const headers = useIngest
    ? { "X-Ingest-Token": INGEST_TOKEN }
    : { "X-Notify-Secret": NOTIFY_SECRET };

  sendWithRetry(url, body, headers).then(sendResponse);
  return true;
});