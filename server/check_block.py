"""
Uji cepat: apakah host ini diblokir Cloudflare saat mengakses API JKT48?

Tidak butuh bot Discord. Jalankan di mesin/server mana pun yang ingin diuji
(Deplexo, VPS gratis lain, dll.).

Contoh:
    python check_block.py
    python check_block.py --proxy http://user:pass@host:port
    python check_block.py --profiles chrome131 chrome124 safari17_0
    python check_block.py --events EX5B99

Env opsional: POLL_PROXY, JKT48_COOKIE (sama seperti discord_notifier.py)
"""
import argparse
import os
import time

from curl_cffi import requests as cffi_requests

EVENTS = {"EX5B99": "2 Shoot", "EX24AE": "MNG"}
DEFAULT_PROFILES = [
    "chrome", "chrome131", "chrome124", "chrome120",
    "edge101", "safari17_0", "safari18_0", "firefox133",
]


def api_url(code):
    return f"https://jkt48.com/api/v1/exclusives/{code}/bonus?lang=id"


def has_ticket_data(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    return isinstance(data, list) and any(
        isinstance(x, dict) and isinstance(x.get("session_members"), list) for x in data
    )


def try_once(profile, code, proxy, cookie):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Referer": f"https://jkt48.com/purchase/exclusive?code={code}",
    }
    if cookie:
        headers["Cookie"] = cookie
    kwargs = {"impersonate": profile}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    try:
        session = cffi_requests.Session(**kwargs)
        r = session.get(api_url(code), headers=headers, timeout=15)
    except Exception as e:
        return False, f"error: {type(e).__name__}: {str(e)[:80]}"

    cf = r.headers.get("cf-mitigated", "")
    ray = r.headers.get("cf-ray", "")
    if r.status_code != 200:
        extra = f" cf-mitigated={cf}" if cf else ""
        return False, f"HTTP {r.status_code}{extra} ray={ray}"
    try:
        payload = r.json()
    except ValueError:
        snippet = " ".join(r.text.split())[:60]
        return False, f"200 tapi bukan JSON: {snippet}"
    if not has_ticket_data(payload):
        return False, "200 JSON, tapi tidak ada data session_members"
    return True, "OK, data tiket diterima"


def main():
    ap = argparse.ArgumentParser(description="Uji blokir Cloudflare ke API JKT48")
    ap.add_argument("--proxy", default=os.environ.get("POLL_PROXY", "").strip())
    ap.add_argument("--cookie", default=os.environ.get("JKT48_COOKIE", "").strip())
    ap.add_argument("--profiles", nargs="*", default=DEFAULT_PROFILES)
    ap.add_argument("--events", nargs="*", default=list(EVENTS))
    ap.add_argument("--delay", type=float, default=2.0, help="jeda antar percobaan (detik)")
    args = ap.parse_args()

    print(f"Proxy : {'ya' if args.proxy else 'tidak'}")
    print(f"Cookie: {'ya' if args.cookie else 'tidak'}\n")

    working = []
    for profile in args.profiles:
        for code in args.events:
            ok, msg = try_once(profile, code, args.proxy, args.cookie)
            print(f"{'OK  ' if ok else 'GAGAL'} {profile:<12} {EVENTS.get(code, code):<8} {msg}")
            if ok and profile not in working:
                working.append(profile)
            time.sleep(args.delay)

    print()
    if working:
        print("Profil yang berhasil:", ", ".join(working))
        print(f"Set di env:  IMPERSONATE={working[0]}")
        if len(working) > 1:
            print(f"             IMPERSONATE_FALLBACKS={','.join(working[1:])}")
    else:
        print("Semua percobaan gagal: IP/host ini kemungkinan diblokir.")
        print("Coba host lain, atau tambahkan proxy residensial (--proxy / POLL_PROXY).")


if __name__ == "__main__":
    main()