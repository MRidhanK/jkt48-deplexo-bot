"""
JKT48 Ticket Radar - bot Discord + dashboard.

Sumber data HANYA dari Cloudflare Worker (atau klien lain) yang POST ke /notify.
Server ini juga bisa polling langsung ke jkt48.com kalau POLL_ENABLED=1.
"""
import asyncio
import concurrent.futures
import hmac
import csv
import io
import json
import os
import sys   
import threading
import time
import traceback
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote
try:
    from pywebpush import webpush, WebPushException
    PUSH_LIB = True
except ImportError:
    PUSH_LIB = False
import base64   # (jika belum ada, tidak wajib)
import struct
import zlib
import random
import re
import shutil
import urllib.request
from curl_cffi import requests as cffi_requests
# ------------------------------------------------------------
# Load member_photos dari:
# 1. folder yang sama dengan discord_notifier.py
# 2. folder server/ jika script dijalankan dari root container
# ------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent / "server"

if SERVER_DIR.is_dir():
    sys.path.insert(0, str(SERVER_DIR))

try:
    import member_photos

    print(
        f"[INIT] member_photos loaded from: "
        f"{getattr(member_photos, '__file__', '?')}"
    )

except ImportError as e:
    print(f"[WARN] member_photos.py tidak ditemukan: {e}")
    print("[WARN] Foto member dimatikan.")

    class member_photos:
        @staticmethod
        def photos_for(names):
            return {}

        @staticmethod
        def read_photo(filename):
            return None

        @staticmethod
        def check(names):
            return {
                "error": "member_photos.py tidak ditemukan"
            }
from urllib.parse import unquote
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

COLOR_AMBER = 0xF1C40F
LOW_QUOTA = 3
HARI = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
         "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

_send_alock = None

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
NOTIFY_SECRET = os.environ.get("NOTIFY_SECRET", "").strip()
MAX_BODY_SIZE = 500_000

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0") or 0)
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)
VIP_USER_ID = os.environ.get("VIP_USER_ID", "").strip()
VIP_FALLBACK_TEXT = os.environ.get("VIP_FALLBACK_TEXT", "")
SPAM_INTERVAL = float(os.environ.get("SPAM_INTERVAL", "4"))
SPAM_MAX = int(os.environ.get("SPAM_MAX", "20"))
# Worker lapor tiap ~1 menit (cron), jadi 150 detik masih aman.
STALE_SECONDS = int(os.environ.get("STALE_SECONDS", "150"))

MIN_SEND_GAP = float(os.environ.get("MIN_SEND_GAP", "1.2"))
MAX_CONCURRENT_SPAM = int(os.environ.get("MAX_CONCURRENT_SPAM", "5"))
RESTOCK_COOLDOWN = int(os.environ.get("RESTOCK_COOLDOWN", "300"))

# Riwayat kuota (untuk grafik & kecepatan terjual)
HIST_KEEP_SECONDS = int(os.environ.get("HIST_KEEP_SECONDS", "86400"))  # simpan 24 jam
HIST_MAXLEN = 1500

# Analytics harian ("hari ini" dihitung sejak 00:00 zona waktu ini, default WIB)
TZ_OFFSET_HOURS = float(os.environ.get("TZ_OFFSET_HOURS", "7"))
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))
ACTIVITY_KEEP_SECONDS = int(os.environ.get("ACTIVITY_KEEP_SECONDS", "172800"))  # 48 jam
ACTIVITY_MAXLEN = 20000

# Ringkasan harian ke Discord (jam lokal sesuai TZ_OFFSET_HOURS)
SUMMARY_HOUR = int(os.environ.get("SUMMARY_HOUR", "23"))

# Alert status
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "60"))
LATENCY_ALERT_MS = int(os.environ.get("LATENCY_ALERT_MS", "1500"))
LATENCY_ALERT_CHECKS = int(os.environ.get("LATENCY_ALERT_CHECKS", "3"))  # berturut-turut
API_ERR_WINDOW = int(os.environ.get("API_ERR_WINDOW", "300"))            # detik
API_ERR_ALERT = int(os.environ.get("API_ERR_ALERT", "5"))                # jumlah 5xx

# Web Push
VAPID_PUBLIC = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com").strip()
PUSH_TTL = int(os.environ.get("PUSH_TTL", "120"))              # detik; restock basi tidak perlu dikirim
PUSH_MAX_SUBS = int(os.environ.get("PUSH_MAX_SUBS", "200"))
PUSH_MAX_SINGLE = int(os.environ.get("PUSH_MAX_SINGLE", "3"))  # lebih dari ini digabung jadi 1 notifikasi
PUSH_ENABLED = bool(PUSH_LIB and VAPID_PUBLIC and VAPID_PRIVATE)

# Hanya endpoint dari layanan push resmi yang diterima (mencegah server dipakai menembak URL lain)
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
) + tuple(h.strip() for h in os.environ.get("PUSH_EXTRA_HOSTS", "").split(",") if h.strip())

# Pengelompokan event untuk halaman status
EVENT_GROUP = {"EX5B99": "JKT", "EX24AE": "JKT", "EXD1A1": "AKB", "EXA6F1": "AKB"}
GROUP_LABEL = {"JKT": "Poller JKT48", "AKB": "Poller AKB"}

EVENTS = {"EX5B99": "2 Shoot JKT", "EX24AE": "MNG JKT", "EXD1A1" : "2Shoot AKB", "EXA6F1": "MNG AKB"}

# Alert jika worker melaporkan error berturut-turut sebanyak ini.
POLL_FAIL_ALERT = int(os.environ.get("POLL_FAIL_ALERT", "5"))

# ------------------------------------------------------------------ War Mode, kanal cadangan, ketahanan
BASE_EVENTS = set(EVENTS)

def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")

RESTOCK_COOLDOWN_VIP = int(os.environ.get("RESTOCK_COOLDOWN_VIP", "30"))
WAR_COOLDOWN = int(os.environ.get("WAR_COOLDOWN", "20"))
POLL_INTERVAL_WAR = int(os.environ.get("POLL_INTERVAL_WAR", "10"))

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BACKUP_ENABLED = bool(NTFY_TOPIC or (TG_TOKEN and TG_CHAT))
BACKUP_IMMEDIATE = _flag("BACKUP_IMMEDIATE")          # kirim kanal cadangan langsung tiap restock VIP
ESCALATE_AFTER = int(os.environ.get("ESCALATE_AFTER", "20"))   # detik sebelum eskalasi

HEARTBEAT_URL = os.environ.get("HEARTBEAT_URL", "").strip()    # mis. healthchecks.io
EVENT_DISCOVERY = _flag("EVENT_DISCOVERY", "1")
EVENT_DISCOVERY_INTERVAL = int(os.environ.get("EVENT_DISCOVERY_INTERVAL", "120"))
EVENT_LIST_URLS = [u.strip() for u in os.environ.get(
    "EVENT_LIST_URLS", "https://jkt48.com/purchase/exclusive").split(",") if u.strip()]
EVENT_CODE_RE = re.compile(r"\bEX(?=[0-9A-Z]*[0-9])[0-9A-Z]{4}\b")

sale_state = {}            # code -> "waiting" | "open"
war_state = {"until": 0.0}
last_ack = [0.0]
seen_codes = set()


def war_active():
    return time.time() < war_state["until"]


def set_war(minutes):
    minutes = max(0.0, min(float(minutes), 360.0))
    war_state["until"] = (time.time() + minutes * 60) if minutes > 0 else 0.0
    print(f"[WAR] {'ON ' + str(int(minutes)) + ' menit' if minutes > 0 else 'OFF'}")


def war_info():
    return {"active": war_active(), "until": war_state["until"] or None}


def set_ack():
    last_ack[0] = time.time()


def cooldown_for(code, lane):
    if war_active():
        return WAR_COOLDOWN
    if is_vip(code, lane):
        return RESTOCK_COOLDOWN_VIP
    return RESTOCK_COOLDOWN


def current_poll_interval():
    return POLL_INTERVAL_WAR if war_active() else POLL_INTERVAL


def register_event(code, name=None):
    """Tambah event saat runtime. Dict diganti baru agar iterasi di thread lain tidak error."""
    global EVENTS
    if code in EVENTS:
        return False
    EVENTS = {**EVENTS, code: name or f"Event {code}"}
    return True

VIP_NAMES = [
    "Fiony Alveria", "Aurhel Alana", "Michelle Alexandra",
    "Hillary Abigail", "Adeline Wijaya", "Oline Manuel",
    "Abigail Rachel", "Catherina Vallencia", "Jacqueline Immanuela",
    "Nur Intan", "Putry Jazyta", "Astrella Virgiananda",
]
VIP_NAMES_AKB = [
    "Ayami Nagatomo",
    "Miyuu Mizushima",
    "Yui Oguri",
]

VIP_MEMBERS = {
    "EX5B99": VIP_NAMES,       # 2 Shoot JKT
    "EX24AE": VIP_NAMES,       # MNG JKT
    "EXD1A1": VIP_NAMES_AKB,   # 2 Shoot AKB
    "EXA6F1": VIP_NAMES_AKB,   # MNG AKB
}

SEED_FILE = Path(__file__).with_name("subscriptions.json")
DATA_DIR = os.environ.get("DATA_DIR", "").strip()
if DATA_DIR:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    SUBS_FILE = Path(os.environ.get("SUBS_FILE") or Path(DATA_DIR) / "subscriptions.json")
    if not SUBS_FILE.exists() and SEED_FILE.exists():
        shutil.copy(SEED_FILE, SUBS_FILE)
else:
    SUBS_FILE = Path(os.environ.get("SUBS_FILE") or SEED_FILE)
STATE_FILE = Path(os.environ.get("STATE_FILE") or SUBS_FILE.with_name("state.json"))

DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "").strip()


# ------------------------------------------------------------------ cari dashboard.html di beberapa lokasi
def _resolve_dashboard_file() -> Path:
    # 1. Env var eksplisit
    env_path = os.environ.get("DASHBOARD_FILE", "").strip()
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
        print(f"[WARN] DASHBOARD_FILE={env_path} tidak ditemukan, fallback ke pencarian otomatis.")

    here = Path(__file__).resolve().parent
    candidates = [
        here / "dashboard.html",                    # sebelah script
        here / "server" / "dashboard.html",         # script di root, dashboard di server/
        here.parent / "server" / "dashboard.html",  # script di subfolder, dashboard di ../server/
        here.parent / "dashboard.html",             # dashboard di parent
        Path.cwd() / "dashboard.html",              # current working dir
        Path.cwd() / "server" / "dashboard.html",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]  # default: sebelah script (untuk pesan error)


DASHBOARD_FILE = _resolve_dashboard_file()
print(f"[INIT] Dashboard file: {DASHBOARD_FILE} (exists={DASHBOARD_FILE.is_file()})")

COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C


def norm(text):
    return " ".join(str(text or "").split()).casefold()


VIP_SET = {code: {norm(n) for n in names} for code, names in VIP_MEMBERS.items()}


def parse_quota(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def format_rupiah(value):
    try:
        return "Rp" + f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError, OverflowError):
        return "-"


def hhmm(value):
    return str(value or "")[:5] or "-"


# ------------------------------------------------------------------ state
lock = threading.Lock()
quota_state = {}
baselined = set()
last_report = {}
known_members = {}
last_restock = {}
lane_state = {}
spam_tasks = {}

history = {}     # (code, sdc) -> deque[(ts, quota)]
so_after = {}    # (code, sdc) -> detik dari restock sampai sold out
last_so = {}     # (code, sdc) -> detik restock -> sold out TERAKHIR; tidak dihapus saat restock

activity = deque(maxlen=ACTIVITY_MAXLEN)   # [ts, jenis, code, sdc, jumlah, durasi]
activity_since = time.time()               # kapan pencatatan analytics dimulai

req_log = deque(maxlen=5000)          # (ts, status) tiap respons HTTP
summary_meta = {"day": ""}            # tanggal terakhir ringkasan terkirim
health_alerted = set()

stats_lock = threading.Lock()
request_total = 0
request_errors = 0

subs_lock = threading.Lock()
poll_status = {}  # code -> status laporan terakhir dari worker

_send_lock = threading.Lock()
_last_send_time = [0.0]


# ------------------------------------------------------------------ riwayat kuota & kecepatan terjual
def record_history(key, quota, now):
    dq = history.setdefault(key, deque(maxlen=HIST_MAXLEN))
    if not dq or dq[-1][1] != quota:
        dq.append((now, quota))
    # buang titik lama, sisakan satu titik sebelum batas sebagai baseline
    while len(dq) > 1 and dq[1][0] < now - HIST_KEEP_SECONDS:
        dq.popleft()


def sold_in(dq, since):
    sold, prev = 0, None
    for ts, q in dq:
        if prev is not None and ts >= since and q < prev:
            sold += prev - q
        prev = q
    return sold


def speed_stats(key, quota, now):
    dq = history.get(key)
    if not dq:
        return {"sold_10m": 0, "sold_1h": 0, "rate": 0, "eta": None,
                "peak": quota, "pct_sold": 0,
                "so_after": so_after.get(key), "last_so": last_so.get(key)}
    s10 = sold_in(dq, now - 600)
    s60 = sold_in(dq, now - 3600)
    rate = s10 / 10 if s10 else s60 / 60          # tiket per menit
    peak = max(q for _, q in dq)
    return {
        "sold_10m": s10,
        "sold_1h": s60,
        "rate": round(rate, 2),
        "eta": round(quota / rate, 1) if rate > 0 and quota > 0 else None,  # menit
        "peak": peak,
        "pct_sold": round((1 - quota / peak) * 100) if peak > 0 else 0,
        "so_after": so_after.get(key),
        "last_so": last_so.get(key),
    }

def log_activity(now, kind, code, sdc, n, dur=None):
    """Dipanggil di dalam `with lock:` (jangan ambil lock lagi di sini)."""
    activity.append([round(now, 1), kind, code, sdc, int(n),
                     None if dur is None else round(dur, 1)])
    cutoff = now - ACTIVITY_KEEP_SECONDS
    while activity and activity[0][0] < cutoff:
        activity.popleft()


def count_request(status):
    global request_total, request_errors
    now = time.time()
    with stats_lock:
        request_total += 1
        if status >= 400:
            request_errors += 1
        req_log.append((now, status))


def recent_5xx(window):
    cutoff = time.time() - window
    with stats_lock:
        return sum(1 for ts, st in req_log if ts >= cutoff and st >= 500)

def load_subs():
    try:
        return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_subs(data):
    tmp = SUBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SUBS_FILE)


def load_state():
    global quota_state, baselined, last_restock, activity_since
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for c, n in (raw.get("extra_events") or {}).items():
        if isinstance(c, str) and isinstance(n, str):
            register_event(c, n)
    seen_codes.update(x for x in (raw.get("seen_codes") or []) if isinstance(x, str))

    def split(k):
        code, _, sdc = k.partition("|")
        return (code, sdc)

    quota_state = {split(k): v for k, v in (raw.get("quota_state") or {}).items()}
    baselined = set(raw.get("baselined") or [])
    last_restock = {split(k): v for k, v in (raw.get("last_restock") or {}).items()}

    last_so.clear()
    last_so.update({split(k): v for k, v in (raw.get("last_so") or {}).items()})

    lane_state.clear()
    lane_state.update({
        split(k): v for k, v in (raw.get("lane_state") or {}).items()
        if isinstance(v, dict)
    })

    last_report.clear()
    for code, ts in (raw.get("last_report") or {}).items():
        if code in EVENTS:
            try:
                last_report[code] = float(ts)
            except (TypeError, ValueError):
                pass

    # daftar member untuk autocomplete Discord langsung tersedia setelah restart
    for (code, _), v in lane_state.items():
        name = str(v.get("member_name") or "").strip()
        if name and name != "Tidak diketahui":
            known_members.setdefault(code, set()).add(name)

    history.clear()
    for k, v in (raw.get("history") or {}).items():
        history[split(k)] = deque(
            ((float(t), int(q)) for t, q in v), maxlen=HIST_MAXLEN
        )
    activity.clear()
    for r in raw.get("activity") or []:
        try:
            activity.append([float(r[0]), str(r[1]), str(r[2]), str(r[3]),
                             int(r[4]), None if r[5] is None else float(r[5])])
        except (TypeError, ValueError, IndexError):
            pass
    try:
        activity_since = float(raw.get("activity_since") or activity_since)
    except (TypeError, ValueError):
        pass

    summary_meta["day"] = str(raw.get("summary_day") or "")

    print(f"[STATE] Dimuat: {len(quota_state)} lane, {len(lane_state)} data jalur, "
          f"{len(baselined)} event, {len(history)} riwayat")
    
def save_state():
    try:
        with lock:
            raw = {
                "quota_state": {f"{c}|{s}": q for (c, s), q in quota_state.items()},
                "baselined": list(baselined),
                "last_restock": {f"{c}|{s}": t for (c, s), t in last_restock.items()},
                "last_so": {f"{c}|{s}": t for (c, s), t in last_so.items()},
                "lane_state": {f"{c}|{s}": v for (c, s), v in lane_state.items()},
                "last_report": dict(last_report),
                "history": {
                    f"{c}|{s}": [[round(t), q] for t, q in dq]
                    for (c, s), dq in history.items()
                },
                "activity": list(activity),
                "activity_since": activity_since,
                "summary_day": summary_meta["day"],
                "extra_events": {c: n for c, n in EVENTS.items() if c not in BASE_EVENTS},
                "seen_codes": sorted(seen_codes),
            }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        traceback.print_exc()


def pretty_date(value):
    try:
        d = datetime.strptime(str(value), "%Y-%m-%d")
        return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month - 1]}"
    except ValueError:
        return str(value or "-")


def status_icon(q):
    if q <= 0:
        return "🔴"
    return "🟡" if q <= LOW_QUOTA else "🟢"


def quota_bar(q, peak, size=8):
    peak = peak if peak and peak > 0 else max(q, 1)
    filled = round(size * min(q, peak) / peak)
    if q > 0 and filled == 0:
        filled = 1
    return "▰" * filled + "▱" * (size - filled)


def peak_of(code, sdc, quota):
    with lock:
        dq = history.get((code, sdc))
        return max([quota] + [q for _, q in dq]) if dq else quota

def speed_of(code, sdc, quota):
    with lock:
        return speed_stats((code, sdc), quota, time.time())


def fmt_minutes(m):
    if m is None:
        return "-"
    if m < 1:
        return "<1 menit"
    if m < 60:
        return f"~{round(m)} menit"
    return f"~{m / 60:.1f} jam"


def speed_label(rate):
    if rate >= 2:
        return "🔥 Cepat"
    if rate >= 0.5:
        return "⚡ Sedang"
    if rate > 0:
        return "🐢 Lambat"
    return "💤 Belum ada penjualan"

# ------------------------------------------------------------------ embeds
def restock_embed(code, lane, delta=None):
    quota = parse_quota(lane.get("available_quota")) or 0
    sdc = str(lane.get("session_detail_code") or "")
    peak = peak_of(code, sdc, quota)

    desc = f"### {status_icon(quota)} {quota} tiket tersedia"
    if delta:
        desc += f"  ·  📈 +{delta}"
    desc += f"\n{quota_bar(quota, peak, 12)}"

    embed = discord.Embed(
        title=f"🟢 RESTOCK · {lane.get('member_name')}",
        url=buy_url(code),
        description=desc,
        color=COLOR_AMBER if quota <= LOW_QUOTA else COLOR_GREEN,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"{EVENTS.get(code, code)} · {lane.get('label')}")
    embed.add_field(name="🗓️ Sesi", value=str(lane.get("session_label") or "-"), inline=True)
    embed.add_field(name="📅 Tanggal", value=pretty_date(lane.get("session_date")), inline=True)
    embed.add_field(
        name="🕒 Waktu",
        value=f"{hhmm(lane.get('session_start_time'))}–{hhmm(lane.get('session_end_time'))}",
        inline=True,
    )
    embed.add_field(name="💰 Harga", value=format_rupiah(lane.get("price")), inline=True)

    # ---- kecepatan terjual ----
    sp = speed_of(code, sdc, quota)
    if sp["sold_1h"] > 0:
        lines = [
            f"{speed_label(sp['rate'])} · **{sp['rate']}** tiket/menit",
            f"Terjual **{sp['sold_10m']}** (10 mnt) · **{sp['sold_1h']}** (1 jam)",
        ]
        if sp["eta"] is not None:
            lines.append(f"Perkiraan habis dalam **{fmt_minutes(sp['eta'])}**")
        embed.add_field(name="⚡ Kecepatan", value="\n".join(lines), inline=False)
    else:
        embed.add_field(
            name="⚡ Kecepatan",
            value="💤 Belum ada data penjualan (baru terpantau)",
            inline=False,
        )

    so = sp.get("last_so")

    if sp.get("eta") is not None:
        embed.add_field(
            name="⏳ Estimasi Sold Out",
            value=fmt_minutes(sp["eta"]),
            inline=True,
        )

    if so:
        if so < 60:
            so_text = f"{int(so)} detik"
        elif so < 3600:
            so_text = f"{round(so / 60)} menit"
        else:
            so_text = f"{so / 3600:.1f} jam"

        embed.add_field(
            name="📈 Riwayat Sold Out",
            value=f"Terakhir habis dalam **{so_text}**",
            inline=True,
        )
    return embed


def new_session_embed(code, lane):
    quota = parse_quota(lane.get("available_quota"))
    return discord.Embed(
        title=f"🆕 SESI BARU · {lane.get('member_name')}",
        color=COLOR_GREEN,
        description=f"**{EVENTS.get(code, code)}** · {lane.get('label')}",
    ).add_field(name="🗓️ Sesi", value=str(lane.get("session_label") or "-"), inline=True
    ).add_field(name="📅 Tanggal", value=str(lane.get("session_date") or "-"), inline=True
    ).add_field(
        name="🕒 Waktu",
        value=f"{hhmm(lane.get('session_start_time'))} - {hhmm(lane.get('session_end_time'))}",
        inline=True,
    ).add_field(name="📊 Kuota", value=f"`{quota}`", inline=True
    ).add_field(name="💰 Harga", value=format_rupiah(lane.get("price")), inline=True
    ).add_field(name="🧩 Kode sesi", value=f"`{lane.get('session_detail_code')}`", inline=False)


def buy_url(code):
    return f"https://jkt48.com/purchase/exclusive?code={code}"


def buy_view(code, ack=False):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="🛒 Beli sekarang",
        style=discord.ButtonStyle.link,
        url=buy_url(code),
    ))
    if ack:
        btn = discord.ui.Button(label="✅ Saya urus", style=discord.ButtonStyle.success)

        async def cb(interaction: discord.Interaction):
            set_ack()
            await interaction.response.send_message("Oke, eskalasi dijeda.", ephemeral=True)

        btn.callback = cb
        view.add_item(btn)
    return view


# ------------------------------------------------------------------ bot
class RadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.main_loop = None
        self.save_task = None
        self.stale_task = None
        self.summary_task = None
        self.health_task = None

    async def setup_hook(self):
        self.main_loop = asyncio.get_running_loop()
        self.save_task = asyncio.create_task(save_state_loop())
        self.stale_task = asyncio.create_task(stale_watch_loop())
        self.summary_task = asyncio.create_task(daily_summary_loop())
        self.health_task = asyncio.create_task(health_watch_loop())
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"[JKT48] Bot aktif sebagai {self.user}")


bot = RadarBot()

EVENT_CHOICES = [
    app_commands.Choice(name="2 Shoot JKT", value="EX5B99"),
    app_commands.Choice(name="MNG JKT", value="EX24AE"),
    app_commands.Choice(name="2 Shoot AKB", value="EXD1A1"),
    app_commands.Choice(name="MNG AKB", value="EXA6F1"),
    app_commands.Choice(name="Semua event", value="*"),
]


async def member_autocomplete(interaction: discord.Interaction, current: str):
    with lock:
        names = {n for group in known_members.values() for n in group}
    query = norm(current)
    matches = sorted(n for n in names if query in norm(n))[:25]
    return [app_commands.Choice(name=n, value=n) for n in matches]


async def add_subscription(interaction: discord.Interaction, member: str, ev: str):
    key = "*" if norm(member) in ("semua", "*", "all") else norm(member)
    uid = str(interaction.user.id)

    with subs_lock:
        data = load_subs()
        items = data.setdefault(uid, [])
        entry = {"member": key, "event": ev}
        already = entry in items
        if not already:
            items.append(entry)
        save_subs(data)

    ev_name = "semua event" if ev == "*" else EVENTS[ev]
    who = "semua member" if key == "*" else member
    prefix = "ℹ️ Sudah terdaftar sebelumnya. " if already else "✅ "
    await interaction.response.send_message(
        f"{prefix}Kamu akan di-mention saat **{who}** restock di **{ev_name}**.",
        ephemeral=True,
    )


@bot.tree.command(name="pantau", description="Notifikasi saat tiket member restock")
@app_commands.describe(member="Nama member (atau 'semua')", event="Event yang dipantau")
@app_commands.choices(event=EVENT_CHOICES)
@app_commands.autocomplete(member=member_autocomplete)
async def pantau(interaction: discord.Interaction, member: str,
                 event: app_commands.Choice[str] = None):
    await add_subscription(interaction, member, event.value if event else "*")


STOCK_CHUNK = 3800
STOCK_MAX_EMBEDS = 5


def stock_pages(lanes):
    lanes = sorted(
        lanes,
        key=lambda l: (
            norm(l.get("member_name")), str(l.get("session_date") or ""),
            str(l.get("session_start_time") or ""), str(l.get("label") or ""),
        ),
    )
    lines, last_member = [], None
    for lane in lanes:
        name = str(lane.get("member_name") or "-")
        if name != last_member:
            lines.append(f"\n👤 **{name}**")
            last_member = name
        quota = parse_quota(lane.get("available_quota")) or 0
        head = (
            f"{status_icon(quota)} **{lane.get('session_label') or '-'}** · "
            f"{pretty_date(lane.get('session_date'))} · "
            f"`{hhmm(lane.get('session_start_time'))}–{hhmm(lane.get('session_end_time'))}`"
        )
        if quota > 0:
            bar = quota_bar(quota, lane.get("_peak"))
            tail = f"{lane.get('label') or '-'} · {format_rupiah(lane.get('price'))} · {bar} **{quota}**"
        else:
            tail = f"{lane.get('label') or '-'} · {format_rupiah(lane.get('price'))} · habis"
        lines.append(f"{head}\n-# └ {tail}")

    pages, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > STOCK_CHUNK:
            pages.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        pages.append(current)
    return pages


async def show_stock(interaction: discord.Interaction, code: str, member: str):
    ev_name = EVENTS[code]
    show_all = norm(member) in ("semua", "*", "all")
    query = "" if show_all else norm(member)

    with lock:
        lanes = []
        for (c, sdc), v in lane_state.items():
            if c == code and (show_all or query in norm(v.get("member_name"))):
                q = parse_quota(v.get("available_quota")) or 0
                dq = history.get((c, sdc))
                peak = max([q] + [x for _, x in dq]) if dq else q
                lanes.append({**v, "_peak": peak})
        reported = last_report.get(code)

    await interaction.response.defer(ephemeral=True)

    if reported is None:
        await interaction.followup.send(
            f"Belum ada data **{ev_name}**. Tunggu laporan pertama dari worker "
            f"(sekitar 1 menit), lalu coba lagi.",
            ephemeral=True,
        )
        return
    if not lanes:
        await interaction.followup.send(
            f"Tidak ada jalur **{ev_name}** untuk \"{member}\". "
            f"Cek ejaan nama, atau pakai `semua`.",
            ephemeral=True,
        )
        return

    age = time.time() - reported
    quotas = [parse_quota(l.get("available_quota")) or 0 for l in lanes]
    low = sum(1 for q in quotas if 0 < q <= LOW_QUOTA)
    ready = sum(1 for q in quotas if q > LOW_QUOTA)
    sold = sum(1 for q in quotas if q <= 0)

    header = (
        f"🟢 **{ready}** tersedia · 🟡 **{low}** menipis · 🔴 **{sold}** habis\n"
        f"🔄 Diperbarui <t:{int(reported)}:R>"
    )
    if age > STALE_SECONDS:
        header += "\n⚠️ Data sudah lama, worker mungkin berhenti melapor."

    color = COLOR_GREEN if ready else (COLOR_AMBER if low else COLOR_RED)
    pages = stock_pages(lanes)
    shown = pages[:STOCK_MAX_EMBEDS]
    who = "Semua member" if show_all else member

    for i, page in enumerate(shown):
        embed = discord.Embed(
            title=f"📊 Stok {ev_name} · {who}",
            url=buy_url(code),
            description=(header + "\n" if i == 0 else "") + page,
            color=color,
            timestamp=datetime.fromtimestamp(reported, tz=timezone.utc),
        )
        footer = "JKT48 Ticket Radar"
        if len(pages) > 1:
            footer += f" · Halaman {i + 1}/{len(shown)}"
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed, view=buy_view(code), ephemeral=True)

    if len(pages) > STOCK_MAX_EMBEDS:
        await interaction.followup.send(
            "Hasil terlalu panjang, sebutkan nama member yang lebih spesifik.",
            ephemeral=True,
        )


@bot.tree.command(name="2shoot", description="Lihat stok tiket member di event 2 Shoot JKT")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_2shoot(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EX5B99", member)


@bot.tree.command(name="mng", description="Lihat stok tiket member di event MNG JKT")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_mng(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EX24AE", member)


@bot.tree.command(name="2shootakb", description="Lihat stok tiket member di event 2 Shoot AKB")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_2shoot_akb(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EXD1A1", member)


@bot.tree.command(name="mngakb", description="Lihat stok tiket member di event MNG AKB")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_mng_akb(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EXA6F1", member)

@bot.tree.command(name="analytics", description="Ringkasan restock hari ini")
async def cmd_analytics(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    a = analytics_snapshot()
    top = top_members(5)
    await interaction.followup.send(
        embed=analytics_embed("📊 Analytics Hari Ini", a, top), ephemeral=True
    )


@bot.tree.command(name="top", description="Top 5 member dengan restock terbanyak hari ini")
@app_commands.describe(event="Filter event (kosongkan untuk semua event)")
@app_commands.choices(event=EVENT_CHOICES)
async def cmd_top(interaction: discord.Interaction,
                  event: app_commands.Choice[str] = None):
    code = event.value if event else "*"
    rows = top_members(5, code)
    if not rows:
        await interaction.response.send_message(
            "Belum ada restock tercatat hari ini.", ephemeral=True
        )
        return
    where = "semua event" if code == "*" else EVENTS.get(code, code)
    embed = discord.Embed(
        title="🏆 Top Member Hari Ini",
        description=f"{where}\n\n{top_lines(rows)}",
        color=COLOR_GREEN,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="JKT48 Ticket Radar")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="berhenti", description="Berhenti memantau member")
@app_commands.describe(member="Nama member (atau 'semua' untuk menghapus semua)")
@app_commands.autocomplete(member=member_autocomplete)
async def berhenti(interaction: discord.Interaction, member: str):
    uid = str(interaction.user.id)
    clear_all = norm(member) in ("semua", "*", "all")

    with subs_lock:
        data = load_subs()
        items = data.get(uid, [])
        before = len(items)
        if clear_all:
            items = []
        else:
            items = [i for i in items if i["member"] != norm(member)]
        data[uid] = items
        save_subs(data)

    removed = before - len(items)
    await interaction.response.send_message(
        f"🗑️ {removed} pantauan dihapus." if removed else "Tidak ada pantauan yang cocok.",
        ephemeral=True,
    )


@bot.tree.command(name="daftar", description="Lihat daftar pantauanmu")
async def daftar(interaction: discord.Interaction):
    with subs_lock:
        items = load_subs().get(str(interaction.user.id), [])

    if not items:
        await interaction.response.send_message("Belum ada pantauan.", ephemeral=True)
        return

    lines = [
        f"• {'Semua member' if i['member'] == '*' else i['member']} — "
        f"{'Semua event' if i['event'] == '*' else EVENTS.get(i['event'], i['event'])}"
        for i in items
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="status", description="Cek kondisi laporan worker")
async def status_cmd(interaction: discord.Interaction):
    lines = []
    for code, name in EVENTS.items():
        s = poll_status.get(code)
        if not s:
            lines.append(f"⚪ **{name}** — belum ada laporan dari worker")
            continue
        txt = f"{'🟢' if s['ok'] else '🔴'} **{name}** — <t:{int(s['at'])}:R>"
        if not s["ok"]:
            txt += f"\n   ↳ gagal {s['fails']}x: {s['error']}"
        lines.append(txt)
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="war", description="Aktifkan/matikan War Mode (cooldown pendek, polling lebih cepat)")
@app_commands.describe(menit="Durasi dalam menit (0 = matikan)")
async def cmd_war(interaction: discord.Interaction, menit: int = 60):
    if VIP_USER_ID and str(interaction.user.id) != VIP_USER_ID:
        await interaction.response.send_message("Hanya pemilik bot.", ephemeral=True)
        return
    set_war(menit)
    await interaction.response.send_message(
        f"⚔️ War Mode aktif {menit} menit." if menit > 0 else "War Mode dimatikan.", ephemeral=True)

# ------------------------------------------------------------------ rate-limited send
async def safe_send(channel, **kwargs):
    global _send_alock
    if _send_alock is None:
        _send_alock = asyncio.Lock()
    async with _send_alock:
        wait = _last_send_time[0] + MIN_SEND_GAP - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await channel.send(**kwargs)
        except discord.HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", None) or 5.0
                print(f"[RATE] 429, tunggu {retry:.1f}s")
                await asyncio.sleep(retry)
                try:
                    await channel.send(**kwargs)
                except discord.HTTPException as e2:
                    print(f"[RATE] Gagal setelah retry: {e2}")
                    raise
            else:
                raise
        finally:
            _last_send_time[0] = time.time()


# ------------------------------------------------------------------ notifikasi
async def get_channel():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(CHANNEL_ID)
    return channel


def vip_mention():
    return f"<@{VIP_USER_ID}>" if VIP_USER_ID else VIP_FALLBACK_TEXT


def vip_allowed():
    if VIP_USER_ID:
        return discord.AllowedMentions(users=[discord.Object(id=int(VIP_USER_ID))])
    return discord.AllowedMentions.none()


def is_vip(code, lane):
    return norm(lane.get("member_name")) in VIP_SET.get(code, set())


async def notify_subscribers(code, lanes, deltas=None):
    if not lanes:
        return
    channel = await get_channel()
    subs = load_subs()
    deltas = deltas or {}

    per_user = {}
    for lane in lanes:
        name = norm(lane.get("member_name"))
        for uid, items in subs.items():
            if uid == VIP_USER_ID and is_vip(code, lane):
                continue
            for item in items:
                if item["event"] not in ("*", code):
                    continue
                if item["member"] in ("*", name) or (
                    item["member"] != "*" and item["member"] in name
                ):
                    per_user.setdefault(uid, []).append(lane)
                    break

    def delta_of(lane):
        return deltas.get((code, str(lane.get("session_detail_code") or "")))

    for uid, user_lanes in per_user.items():
        for start in range(0, len(user_lanes), 10):
            chunk = user_lanes[start:start + 10]
            await safe_send(
                channel,
                content=f"<@{uid}> 🔔 **Restock!**",
                embeds=[restock_embed(code, lane, delta_of(lane)) for lane in chunk],
                view=buy_view(code),
                allowed_mentions=discord.AllowedMentions(
                    users=[discord.Object(id=int(uid))]
                ),
            )

async def notify_new_sessions(code, lanes):
    if not lanes:
        return
    channel = await get_channel()
    for lane in lanes[:10]:
        await safe_send(
            channel,
            content=f"🆕 **Sesi/Jalur baru terdeteksi di {EVENTS.get(code, code)}!**",
            embed=new_session_embed(code, lane),
            view=buy_view(code),
        )
    if len(lanes) > 10:
        await safe_send(
            channel,
            content=f"…dan {len(lanes) - 10} sesi baru lainnya.",
        )

async def notify_sold_out(code, lane, duration=None):
    """
    Mengirim notifikasi ketika satu lane berubah menjadi sold out.

    duration:
        waktu dari restock terakhir sampai sold out,
        dalam detik.
    """

    try:
        channel = await get_channel()

        event_name = EVENTS.get(code, code)

        embed = discord.Embed(
            title=(
                f"🔴 SOLD OUT · "
                f"{lane.get('member_name', '-')}"
            ),
            description=(
                f"**{event_name}**\n"
                f"{lane.get('label', '-')}"
            ),
            color=COLOR_RED,
            timestamp=datetime.now(timezone.utc),
        )

        # ==========================================
        # INFO EVENT
        # ==========================================
        embed.add_field(
            name="🎫 Jalur",
            value=str(
                lane.get("label") or "-"
            ),
            inline=True,
        )

        embed.add_field(
            name="🗓️ Sesi",
            value=str(
                lane.get("session_label") or "-"
            ),
            inline=True,
        )

        embed.add_field(
            name="📅 Event",
            value=str(event_name),
            inline=True,
        )

        # ==========================================
        # MEMBER
        # ==========================================
        embed.add_field(
            name="👤 Member",
            value=str(
                lane.get("member_name") or "-"
            ),
            inline=True,
        )

        # ==========================================
        # DURASI SAMPAI SOLD OUT
        # ==========================================
        if duration is not None and duration >= 0:

            if duration < 60:
                duration_text = (
                    f"{int(duration)} detik"
                )

            elif duration < 3600:
                duration_text = (
                    f"{duration / 60:.1f} menit"
                )

            else:
                duration_text = (
                    f"{duration / 3600:.2f} jam"
                )

            embed.add_field(
                name="⏱️ Bertahan",
                value=(
                    f"**{duration_text}**"
                ),
                inline=False,
            )

        # ==========================================
        # FOOTER
        # ==========================================
        embed.set_footer(
            text="JKT48 Ticket Radar · Sold Out Tracker"
        )

        await safe_send(
            channel,
            embed=embed,
        )

        print(
            f"[SOLD OUT] "
            f"{event_name} | "
            f"{lane.get('member_name', '-')} | "
            f"{lane.get('label', '-')} | "
            f"duration={duration}"
        )

    except Exception:
        traceback.print_exc()

async def spam_loop(code, lane, delta):
    key = (code, lane["session_detail_code"])
    sent = 0
    reason = "cap"

    t0 = time.time()
    escalated = False

    try:
        channel = await get_channel()

        while sent < SPAM_MAX:
            with lock:
                quota_now = quota_state.get(key, 0)
                age = time.time() - last_report.get(code, 0)

            # ==========================================
            # SOLD OUT
            # ==========================================
            if quota_now <= 0:
                reason = "so"
                break

            # ==========================================
            # WORKER / DATA STALE
            # ==========================================
            if age > STALE_SECONDS:
                reason = "stale"
                break

            if (not escalated and BACKUP_ENABLED and is_vip(code, lane)
                    and time.time() - t0 >= ESCALATE_AFTER and last_ack[0] < t0):
                escalated = True
                backup_notify(
                    f"🚨 BELUM DITINDAKLANJUTI · {lane.get('member_name', '-')}",
                    f"{EVENTS.get(code, code)} · {lane.get('label', '-')} · "
                    f"{quota_now} tiket masih ada",
                    buy_url(code), priority=5)

            # ==========================================
            # UPDATE QUOTA TERBARU
            # ==========================================
            lane_now = {
                **lane,
                "available_quota": quota_now,
            }

            event_name = EVENTS.get(code, code)

            await safe_send(
                channel,
                content=(
                    f"{vip_mention()} 🚨 **RESTOCK {event_name}**\n"
                    f"👤 {lane.get('member_name', '-')}\n"
                    f"🎫 {lane.get('label', '-')}"
                    f" ({lane.get('session_label', '-')})\n"
                    f"📈 +{delta} tiket"
                ),
                embed=restock_embed(
                    code,
                    lane_now,
                    delta,
                ),
                view=buy_view(code, ack=True),
                allowed_mentions=vip_allowed(),
            )

            sent += 1

            # Jangan langsung spam tanpa jeda
            await asyncio.sleep(SPAM_INTERVAL)

        # ==========================================
        # PESAN AKHIR SPAM
        # ==========================================
        if reason == "so":
            text = (
                f"🔴 **{lane.get('member_name', '-')}** · "
                f"{lane.get('label', '-')} sold out kembali.\n"
                f"Spam dihentikan ({sent}x)."
            )

        elif reason == "stale":
            text = (
                f"⚠️ Spam **{lane.get('member_name', '-')}** · "
                f"{lane.get('label', '-')} dihentikan "
                f"karena worker berhenti melaporkan data."
            )

        else:
            text = (
                f"⚠️ Spam **{lane.get('member_name', '-')}** · "
                f"{lane.get('label', '-')} dihentikan karena "
                f"mencapai batas **{SPAM_MAX}x**.\n"
                f"🎫 Tiket masih tersedia."
            )

        await safe_send(
            channel,
            content=f"{vip_mention()} {text}",
            allowed_mentions=vip_allowed(),
        )

    except asyncio.CancelledError:
        # Task dibatalkan secara normal
        raise

    except Exception:
        traceback.print_exc()

    finally:
        # Pastikan task dibersihkan
        spam_tasks.pop(key, None)

def ensure_spam(code, lane, delta):
    """
    Memulai spam untuk semua event:
    - EX5B99 = 2 Shoot
    - EX24AE = MNG

    Hanya satu spam task aktif untuk satu session_detail_code.
    """

    session_code = lane.get("session_detail_code")

    if not session_code:
        print(
            f"[SPAM] Skip {code}: "
            f"session_detail_code tidak tersedia"
        )
        return

    key = (code, session_code)

    # ==========================================
    # CEK TASK YANG SUDAH AKTIF
    # ==========================================
    existing = spam_tasks.get(key)

    if existing is not None and not existing.done():
        print(
            f"[SPAM] Already running: "
            f"{EVENTS.get(code, code)} / {session_code}"
        )
        return

    # ==========================================
    # BATAS JUMLAH SPAM CONCURRENT
    # ==========================================
    active = sum(
        1
        for task in spam_tasks.values()
        if not task.done()
    )

    if active >= MAX_CONCURRENT_SPAM:
        print(
            f"[SPAM] Skip {key}: "
            f"sudah {active} task aktif "
            f"(limit={MAX_CONCURRENT_SPAM})"
        )
        return

    # ==========================================
    # BUAT TASK BARU
    # ==========================================
    try:
        task = asyncio.create_task(
            spam_loop(
                code,
                lane,
                delta,
            )
        )

        spam_tasks[key] = task

        print(
            f"[SPAM] START "
            f"{EVENTS.get(code, code)} | "
            f"{lane.get('member_name', '-')} | "
            f"{lane.get('label', '-')} | "
            f"+{delta}"
        )

    except Exception:
        traceback.print_exc()

async def poll_alert(text):
    backup_notify("⚠️ JKT48 Radar", text.replace("**", ""), priority=4)
    try:
        channel = await get_channel()
        await safe_send(
            channel,
            content=f"{vip_mention()} {text}",
            allowed_mentions=vip_allowed(),
        )
    except Exception:
        traceback.print_exc()


# ------------------------------------------------------------------ proses laporan
def process_report(code, lanes):
    if not lanes:                       # API hidup tapi 0 jalur = menunggu penjualan dibuka
        mark_waiting(code)
        return (0, 0, 0)
    restocks = []
    new_sessions = []
    sold_outs = []
    deltas = {}
    sold_total = 0

    now = time.time()

    with lock:
        opened = sale_state.get(code) == "waiting"
        if opened:
            baselined.discard(code)
        sale_state[code] = "open"
        first_scan = code not in baselined

        baselined.add(code)
        last_report[code] = now

        members = known_members.setdefault(code, set())

        for lane in lanes:
            sdc = str(
                lane.get("session_detail_code") or ""
            ).strip()

            quota = parse_quota(
                lane.get("available_quota")
            )

            name = str(
                lane.get("member_name") or ""
            ).strip()

            # --------------------------------------------------
            # Validasi lane
            # --------------------------------------------------
            if (
                not sdc
                or sdc == "Tidak diketahui"
                or quota is None
            ):
                continue

            # --------------------------------------------------
            # Simpan nama member
            # --------------------------------------------------
            if name and name != "Tidak diketahui":
                members.add(name)

            key = (code, sdc)

            # --------------------------------------------------
            # Kuota sebelumnya
            # --------------------------------------------------
            prev = quota_state.get(key)

            quota_state[key] = quota

            lane_state[key] = {
                **lane,
                "available_quota": quota,
            }

            # --------------------------------------------------
            # History kuota
            # --------------------------------------------------
            record_history(
                key,
                quota,
                now,
            )
            if prev is not None and quota < prev:
                sold_total += prev - quota

            # --------------------------------------------------
            # SOLD OUT
            #
            # Contoh:
            # 5 -> 0
            # 10 -> 0
            #
            # Catat berapa lama sejak restock terakhir.
            # --------------------------------------------------
            if (
                prev is not None
                and prev > 0
                and quota == 0
            ):
                started = last_restock.get(key)

                duration = None

                if started:
                    elapsed = now - started

                    # Maksimal 6 jam supaya timestamp lama
                    # dari state sebelumnya tidak dianggap
                    # sebagai durasi restock sekarang.
                    if elapsed < 21600:
                        duration = elapsed
                        so_after[key] = elapsed
                        last_so[key] = elapsed
                log_activity(now, "so", code, sdc, 0, duration)
                sold_outs.append(
                    (
                        {
                            **lane,
                            "available_quota": 0,
                        },
                        duration,
                    )
                )

            # --------------------------------------------------
            # Kalau masih tersedia, hapus status
            # sold-out sementara.
            # --------------------------------------------------
            elif quota > 0:
                so_after.pop(key, None)

            # --------------------------------------------------
            # SESSION BARU
            # --------------------------------------------------
            is_new_session = (
                prev is None
                and not first_scan
            )

            # --------------------------------------------------
            # RESTOCK DETECTION
            #
            # prev=None + bukan first scan
            #       -> lane baru muncul
            #
            # quota > prev
            #       -> kuota bertambah
            # --------------------------------------------------
            delta = 0
            is_restock = False

            if quota > 0:

                if prev is None:

                    if not first_scan:
                        is_restock = True
                        delta = quota

                elif quota > prev:

                    is_restock = True
                    delta = quota - prev
            if is_restock and delta > 0:
                log_activity(now, "in", code, sdc, delta)
            # --------------------------------------------------
            # Simpan RESTOCK
            # --------------------------------------------------
            if is_restock:

                last = last_restock.get(
                    key,
                    0,
                )

                # Hindari spam restock berulang
                # dalam cooldown.
                if (
                    now - last
                    >= cooldown_for(code, lane)
                ):
                    restocks.append(
                        {
                            **lane,
                            "available_quota": quota,
                        }
                    )

                    deltas[key] = delta

                    # Mulai timer restock -> sold out
                    last_restock[key] = now

            # --------------------------------------------------
            # SESSION BARU DENGAN KUOTA
            # --------------------------------------------------
            if (
                is_new_session
                and quota > 0
            ):
                new_sessions.append(
                    {
                        **lane,
                        "available_quota": quota,
                    }
                )
        if sold_total:
            log_activity(now, "sold", code, "", sold_total)
    # Web Push: tidak bergantung pada kesiapan Discord
    if opened:
        sale_open_dispatch(code, lanes)
    if restocks:
        push_dispatch(code, restocks, deltas)
        discord_up = bot.main_loop is not None and bot.is_ready()
        if war_active() or BACKUP_IMMEDIATE or not discord_up:
            backup_restocks(code, restocks, deltas)
    # ==========================================================
    # Jangan kirim Discord kalau bot belum siap
    # ==========================================================
    if (
        bot.main_loop is None
        or not bot.is_ready()
    ):
        return (
            len(restocks),
            len(new_sessions),
            len(sold_outs),
        )

    # ==========================================================
    # RESTOCK
    #
    # Berlaku untuk:
    # EX5B99 = 2 Shoot
    # EX24AE = MNG
    # ==========================================================
    if restocks:

        asyncio.run_coroutine_threadsafe(
            notify_subscribers(
                code,
                restocks,
                deltas,
            ),
            bot.main_loop,
        )

        # Blast untuk semua event
        for lane in restocks:

            sdc = str(
                lane.get(
                    "session_detail_code"
                ) or ""
            )

            delta = deltas.get(
                (code, sdc),
                0,
            )

            bot.main_loop.call_soon_threadsafe(
                ensure_spam,
                code,
                dict(lane),
                delta,
            )

    # ==========================================================
    # SESSION BARU
    # ==========================================================
    if new_sessions:

        asyncio.run_coroutine_threadsafe(
            notify_new_sessions(
                code,
                new_sessions,
            ),
            bot.main_loop,
        )

    # ==========================================================
    # SOLD OUT
    # ==========================================================
    if sold_outs:

        for lane, duration in sold_outs:

            asyncio.run_coroutine_threadsafe(
                notify_sold_out(
                    code,
                    lane,
                    duration,
                ),
                bot.main_loop,
            )

    # ==========================================================
    # LOG
    # ==========================================================
    print(
        f"[PROCESS] "
        f"{EVENTS.get(code, code)} "
        f"lanes={len(lanes)} "
        f"restock={len(restocks)} "
        f"new={len(new_sessions)} "
        f"soldout={len(sold_outs)}"
    )

    return (
        len(restocks),
        len(new_sessions),
        len(sold_outs),
    )

def record_remote_poll(code, error=""):
    prev = poll_status.get(code) or {}
    fails = prev.get("fails", 0) + 1 if error else 0
    poll_status[code] = {"ok": not error, "at": time.time(), "error": error, "fails": fails}

    if bot.main_loop is None or not bot.is_ready():
        return
    if error and fails == POLL_FAIL_ALERT:
        text = f"⚠️ Worker gagal mengambil **{EVENTS[code]}** {fails}x berturut-turut: {error}"
    elif not error and prev.get("fails", 0) >= POLL_FAIL_ALERT:
        text = f"✅ Pemantauan **{EVENTS[code]}** pulih kembali."
    else:
        return
    asyncio.run_coroutine_threadsafe(poll_alert(text), bot.main_loop)

START_TIME = time.time()
STALE_ALERT_AFTER = int(os.environ.get("STALE_ALERT_AFTER", "300"))
stale_alerted = set()


async def stale_watch_loop():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for code, name in EVENTS.items():
            with lock:
                ts = last_report.get(code, START_TIME)  # belum pernah sukses -> hitung dari start
            age = now - ts
            if age > STALE_ALERT_AFTER and code not in stale_alerted:
                stale_alerted.add(code)
                await poll_alert(
                    f"⏰ Data **{name}** basi {int(age // 60)} menit. "
                    f"Restock tidak akan terdeteksi sampai pulih."
                )
            elif age <= STALE_SECONDS and code in stale_alerted:
                stale_alerted.discard(code)
                await poll_alert(f"✅ Data **{name}** segar lagi.")

async def daily_summary_loop():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(30)
        try:
            local = datetime.now(LOCAL_TZ)
            today = local.strftime("%Y-%m-%d")
            if local.hour < SUMMARY_HOUR or summary_meta["day"] == today:
                continue
            a = analytics_snapshot()
            top = top_members(5)
            channel = await get_channel()
            await safe_send(channel, embed=analytics_embed("📊 Ringkasan Harian", a, top))
            summary_meta["day"] = today
            save_state()
        except Exception:
            traceback.print_exc()


async def health_watch_loop():
    await bot.wait_until_ready()
    high = low = 0
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        try:
            # ---- latensi Discord
            lat = bot.latency
            if lat == lat and lat != float("inf"):
                ms = lat * 1000
                if ms >= LATENCY_ALERT_MS:
                    high, low = high + 1, 0
                else:
                    high, low = 0, low + 1
                if high >= LATENCY_ALERT_CHECKS and "latency" not in health_alerted:
                    health_alerted.add("latency")
                    await poll_alert(
                        f"🐌 Latensi Discord tinggi: **{ms:.0f} ms** "
                        f"(batas {LATENCY_ALERT_MS} ms, {high}x pengecekan berturut-turut). "
                        f"Notifikasi bisa terlambat."
                    )
                elif low >= 2 and "latency" in health_alerted:
                    health_alerted.discard("latency")
                    await poll_alert(f"✅ Latensi Discord normal lagi (**{ms:.0f} ms**).")

            # ---- lonjakan error server (5xx)
            errs = recent_5xx(API_ERR_WINDOW)
            if errs >= API_ERR_ALERT and "api5xx" not in health_alerted:
                health_alerted.add("api5xx")
                await poll_alert(
                    f"🔥 API mengembalikan **{errs}** error 5xx dalam "
                    f"{API_ERR_WINDOW // 60} menit terakhir. Cek log server."
                )
            elif errs == 0 and "api5xx" in health_alerted:
                health_alerted.discard("api5xx")
                await poll_alert("✅ Error API sudah berhenti.")
        except Exception:
            traceback.print_exc()

async def save_state_loop():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        save_state()


POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
POLL_BACKOFF_MIN = int(os.environ.get("POLL_BACKOFF_MIN", "15"))
POLL_BACKOFF_MAX = int(os.environ.get("POLL_BACKOFF_MAX", "90"))
JKT48_COOKIE = os.environ.get("JKT48_COOKIE", "").strip()
IMPERSONATE = os.environ.get("IMPERSONATE", "chrome")
# Proxy opsional untuk polling langsung (mis. proxy residensial Indonesia).
# Format: http://user:pass@host:port  atau  socks5://user:pass@host:port
POLL_PROXY = os.environ.get("POLL_PROXY", "").strip()
# Profil impersonasi cadangan (pisahkan koma). Dipakai bergantian saat terdeteksi blokir.
# Contoh: IMPERSONATE_FALLBACKS=chrome131,chrome124,safari17_0,edge101
IMPERSONATE_FALLBACKS = [
    p.strip() for p in os.environ.get("IMPERSONATE_FALLBACKS", "").split(",") if p.strip()
]

POLL_ENABLED = os.environ.get("POLL_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")

# Jitter kecil supaya tidak terlalu "kaku", tapi tidak bikin interval molor.
POLL_JITTER_MAX = float(os.environ.get("POLL_JITTER_MAX", "2"))
# Jeda antar-event DIHAPUS karena polling paralel (thread pool).
EVENT_GAP_MIN = float(os.environ.get("EVENT_GAP_MIN", "0"))
EVENT_GAP_MAX = float(os.environ.get("EVENT_GAP_MAX", "0"))


def api_url(code):
    return f"https://jkt48.com/api/v1/exclusives/{code}/bonus?lang=id"


def flatten(payload):
    lanes = []
    data = payload.get("data") if isinstance(payload, dict) else None
    for sess in data if isinstance(data, list) else []:
        sess = sess or {}
        for m in sess.get("session_members") or []:
            if not m or not m.get("session_detail_code"):
                continue
            lanes.append({
                "label": str(m.get("label") or "-"),
                "price": m.get("price"),
                "member_name": " ".join(str(m.get("member_name") or "").split()),
                "session_detail_code": str(m["session_detail_code"]).strip(),
                "available_quota": m.get("available_quota"),
                "session_label": str(sess.get("label") or "-"),
                "session_date": str(sess.get("date") or "-"),
                "session_start_time": str(sess.get("start_time") or ""),
                "session_end_time": str(sess.get("end_time") or ""),
            })
    return lanes

def poll_once(session, code):
    """
    Return True jika terdeteksi blokir (403/429/bukan JSON/timeout).
    Return False jika polling berhasil.
    """
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Referer": buy_url(code),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if JKT48_COOKIE:
        headers["Cookie"] = JKT48_COOKIE

    name = EVENTS.get(code, code)

    try:
        r = session.get(api_url(code), headers=headers, timeout=15)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:120]}"
        record_remote_poll(code, msg)
        print(f"[POLL] {name} ERROR -> {msg}")
        return True

    cf = r.headers.get("cf-mitigated", "")
    ray = r.headers.get("cf-ray", "")
    server = r.headers.get("server", "")

    if r.status_code != 200:
        msg = f"HTTP {r.status_code}"
        if server:
            msg += f" server={server}"
        if cf:
            msg += f" cf={cf}"
        if ray:
            msg += f" ray={ray}"
        record_remote_poll(code, msg)
        print(f"[POLL] {name} -> {msg} body={r.text[:150]!r}")
        return r.status_code in (403, 429)

    try:
        payload = r.json()
    except ValueError:
        snippet = " ".join(r.text.split())[:120]
        msg = "200 tapi bukan JSON"
        if cf:
            msg += f" cf={cf}"
        if ray:
            msg += f" ray={ray}"
        msg += f" body={snippet}"
        record_remote_poll(code, msg)
        print(f"[POLL] {name} -> {msg}")
        return True

    try:
        lanes = flatten(payload)
    except Exception as e:
        msg = f"flatten error: {type(e).__name__}: {e}"
        record_remote_poll(code, msg)
        print(f"[POLL] {name} -> {msg}")
        return False

    if not lanes:
        data_field = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data_field, list):          # struktur normal, hanya kosong = belum dibuka
            process_report(code, [])
            record_remote_poll(code)
            print(f"[POLL] {name} menunggu penjualan dibuka ray={ray}")
            return False
        msg = "200 tapi struktur JSON tidak dikenali"
        if ray:
            msg += f" ray={ray}"
        record_remote_poll(code, msg)
        print(f"[POLL] {name} -> {msg}")
        return False

    process_report(code, lanes)
    record_remote_poll(code)
    print(f"[POLL] {name} OK lanes={len(lanes)} ray={ray}")
    return False

def build_session(profile):
    kwargs = {"impersonate": profile}
    if POLL_PROXY:
        kwargs["proxies"] = {"http": POLL_PROXY, "https": POLL_PROXY}
    return cffi_requests.Session(**kwargs)
poll_reset_event = threading.Event()


def request_poll_reset():
    """Dipanggil dari endpoint HTTP: kosongkan status & bangunkan poller sekarang."""
    poll_status.clear()
    poll_reset_event.set()

def poll_loop():
    """
    Polling paralel untuk semua event, siklus start-to-start ~POLL_INTERVAL detik.

    - Diblokir (403/challenge): backoff naik bertahap POLL_BACKOFF_MIN -> x3 -> POLL_BACKOFF_MAX.
    - Backoff dihitung SEBELUM tidur, jadi siklus sukses langsung kembali normal.
    - Tidur bisa dibangunkan lewat request_poll_reset() (endpoint /api/poll/reset).
    """
    profiles = list(dict.fromkeys([IMPERSONATE] + IMPERSONATE_FALLBACKS))
    profile_idx = 0
    session = build_session(profiles[profile_idx])
    backoff = 0

    while True:
        started = time.time()
        blocked = False

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(EVENTS)) as ex:
                futures = {ex.submit(poll_once, session, code): code for code in EVENTS}
                for fut in concurrent.futures.as_completed(futures):
                    code = futures[fut]
                    try:
                        blocked = fut.result() or blocked
                    except Exception as e:
                        record_remote_poll(code, f"{type(e).__name__}: {e}"[:200])
        except Exception as e:
            print(f"[POLL] Error di siklus polling: {type(e).__name__}: {e}")
            blocked = True

        if blocked:
            backoff = min(max(backoff * 1.5, POLL_BACKOFF_MIN), POLL_BACKOFF_MAX)
        else:
            backoff = 0

        elapsed = time.time() - started
        jitter = random.uniform(0, POLL_JITTER_MAX)
        sleep_for = max(5.0, current_poll_interval() - elapsed + jitter + backoff)

        if blocked:
            print(f"[POLL] Terblokir, tidur {sleep_for:.0f}s (backoff {backoff}s)")

        # Tidur, tapi langsung bangun kalau ada permintaan reset.
        if poll_reset_event.wait(sleep_for):
            poll_reset_event.clear()
            backoff = 0
            profile_idx = 0
            try:
                session = build_session(profiles[profile_idx])
            except Exception as e:
                print(f"[POLL] Gagal membuat sesi baru saat reset: {e}")
            print("[POLL] Reset manual: backoff dikosongkan, polling ulang sekarang.")
            continue

        if blocked and len(profiles) > 1:
            profile_idx = (profile_idx + 1) % len(profiles)
            try:
                session = build_session(profiles[profile_idx])
                print(f"[POLL] Ganti profil impersonasi ke {profiles[profile_idx]}")
            except Exception as e:
                print(f"[POLL] Gagal memakai profil {profiles[profile_idx]}: {e}")
                
# ------------------------------------------------------------------ dashboard API
def poller_info():
    return {
        "enabled": POLL_ENABLED,
        "mode": "direct" if POLL_ENABLED else "worker",
        "status": poll_status,
    }

def snapshot():
    now = time.time()
    with lock:
        events = {}
        for code, name in EVENTS.items():
            lanes = []
            for (c, sdc), v in lane_state.items():
                if c != code:
                    continue
                quota = parse_quota(v.get("available_quota")) or 0
                lanes.append({
                    "member": v.get("member_name"), "lane": v.get("label"),
                    "quota": quota,
                    "price": v.get("price"), "sdc": sdc,
                    "session": v.get("session_label"), "date": v.get("session_date"),
                    "start": hhmm(v.get("session_start_time")),
                    "end": hhmm(v.get("session_end_time")),
                    "restock_at": last_restock.get((c, sdc)),
                    "vip": is_vip(code, v),
                    **speed_stats((c, sdc), quota, now),
                })
            events[code] = {"name": name, "updated": last_report.get(code),
                            "sale": sale_state.get(code, "open"), "lanes": lanes}
    names = {l["member"] for e in events.values() for l in e["lanes"] if l.get("member")}
    return {"now": now, "stale_after": STALE_SECONDS, "events": events, "war": war_info(),
            "poller": poller_info(), "photos": member_photos.photos_for(names)}

def analytics_snapshot():
    now = time.time()
    local_now = datetime.fromtimestamp(now, LOCAL_TZ)
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight.timestamp()

    hours = [0] * 24
    hours_in = [0] * 24
    per_event = {
        code: {"name": name, "restock": 0, "tickets_in": 0,
               "tickets_sold": 0, "sold_out": 0}
        for code, name in EVENTS.items()
    }
    restock = tin = sold = so = 0
    durs, in_by, fast = [], {}, {}

    with lock:
        rows = [r for r in activity if r[0] >= start]
        for ts, kind, code, sdc, n, dur in rows:
            pe = per_event.get(code)
            if pe is None:
                continue
            if kind == "in":
                restock += 1
                tin += n
                pe["restock"] += 1
                pe["tickets_in"] += n
                h = datetime.fromtimestamp(ts, LOCAL_TZ).hour
                hours[h] += 1
                hours_in[h] += n
                in_by[(code, sdc)] = in_by.get((code, sdc), 0) + n
            elif kind == "sold":
                sold += n
                pe["tickets_sold"] += n
            elif kind == "so":
                so += 1
                pe["sold_out"] += 1
                if dur is not None:
                    durs.append(dur)
                    k = (code, sdc)
                    if k not in fast or dur < fast[k]:
                        fast[k] = dur

        fastest = []
        for (code, sdc), dur in sorted(fast.items(), key=lambda kv: kv[1])[:5]:
            v = lane_state.get((code, sdc)) or {}
            fastest.append({
                "event": EVENTS.get(code, code),
                "member": v.get("member_name") or "-",
                "lane": v.get("label") or "-",
                "session": v.get("session_label") or "-",
                "date": v.get("session_date") or "",
                "start": hhmm(v.get("session_start_time")),
                "duration": dur,
                "tickets_in": in_by.get((code, sdc), 0),
            })
        tracked_since = activity_since

    active = [c for c, e in per_event.items() if e["restock"] > 0]
    most_active = max(
        active, key=lambda c: (per_event[c]["restock"], per_event[c]["tickets_in"])
    ) if active else None
    peak_hour = max(range(24), key=lambda h: (hours[h], hours_in[h])) if any(hours) else None

    return {
        "now": now,
        "day_start": start,
        "day_label": pretty_date(midnight.strftime("%Y-%m-%d")),
        "hour_now": local_now.hour,
        "tracked_since": tracked_since,
        "today": {"restock": restock, "tickets_in": tin,
                  "tickets_sold": sold, "sold_out": so},
        "avg_so": (sum(durs) / len(durs)) if durs else None,
        "so_samples": len(durs),
        "most_active": most_active,
        "peak_hour": peak_hour,
        "hours": hours,
        "hours_in": hours_in,
        "events": per_event,
        "fastest": fastest,
    }


def health_snapshot():
    now = time.time()
    uptime = now - START_TIME
    labels = {"ok": "ONLINE", "warn": "BERMASALAH", "bad": "OFFLINE", "idle": "MENUNGGU"}
    comps = []

    # Discord bot
    ready = bot.is_ready() and not bot.is_closed()
    lat = bot.latency
    lat_ms = round(lat * 1000) if lat == lat and lat != float("inf") else None
    st = "ok" if ready else "bad"
    comps.append({
        "id": "discord", "name": "Discord Bot", "status": st, "label": labels[st],
        "latency_ms": lat_ms if ready else None,
        "detail": "" if ready else "belum terhubung ke Discord",
    })

    # Dashboard
    dash_ok = DASHBOARD_FILE.is_file()
    st = "ok" if dash_ok else "bad"
    comps.append({
        "id": "dashboard", "name": "Dashboard", "status": st, "label": labels[st],
        "detail": "" if dash_ok else "dashboard.html tidak ditemukan",
    })

    # API (kalau endpoint ini menjawab, berarti API hidup)
    comps.append({"id": "api", "name": "API", "status": "ok",
                  "label": labels["ok"], "detail": ""})

    # Poller per grup (JKT / AKB)
    groups = {}
    for code in EVENTS:
        groups.setdefault(EVENT_GROUP.get(code, code), []).append(code)

    for g, codes in groups.items():
        evs, lasts = [], []
        for code in codes:
            with lock:
                last = last_report.get(code)
            ps = poll_status.get(code) or {}
            failing = bool(ps) and not ps.get("ok", True)
            if last is None and uptime < STALE_SECONDS:
                est = "idle"
            elif last is None or now - last > STALE_SECONDS:
                est = "bad"
            elif failing:
                est = "warn"
            else:
                est = "ok"
            if last:
                lasts.append(last)
            evs.append({
                "code": code, "name": EVENTS[code], "status": est, "last": last,
                "error": ps.get("error", "") if failing else "",
                "fails": ps.get("fails", 0) if failing else 0,
            })
        sts = [e["status"] for e in evs]
        worst = ("bad" if "bad" in sts else "warn" if "warn" in sts
                 else "idle" if all(s == "idle" for s in sts) else "ok")
        comps.append({
            "id": f"poller-{g}", "group": g, "name": GROUP_LABEL.get(g, f"Poller {g}"),
            "status": worst, "label": labels[worst],
            "last": min(lasts) if lasts else None, "events": evs,
        })

    with stats_lock:
        total, errors = request_total, request_errors

    return {
        "now": now, "started": START_TIME, "uptime": uptime,
        "components": comps,
        "requests": {"total": total, "errors": errors},
        "poller": {"enabled": POLL_ENABLED, "interval": POLL_INTERVAL},
        "stale_after": STALE_SECONDS,
    }

def day_start_ts(now=None):
    local = datetime.fromtimestamp(now or time.time(), LOCAL_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def fmt_ms(sec):
    if sec is None:
        return "-"
    s = max(0, int(round(sec)))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}j {s % 3600 // 60}m"


def hour_range(h):
    return "-" if h is None else f"{h:02d}:00–{(h + 1) % 24:02d}:00"


def top_members(limit=5, code=None):
    """Member dengan restock terbanyak hari ini (opsional per event)."""
    since = day_start_ts()
    agg = {}
    with lock:
        for ts, kind, c, sdc, n, dur in activity:
            if ts < since or kind == "sold":
                continue
            if code and code != "*" and c != code:
                continue
            v = lane_state.get((c, sdc)) or {}
            name = str(v.get("member_name") or "").strip()
            if not name:
                continue
            e = agg.setdefault(norm(name), {
                "member": name, "restock": 0, "tickets_in": 0, "sold_out": 0,
            })
            if kind == "in":
                e["restock"] += 1
                e["tickets_in"] += n
            elif kind == "so":
                e["sold_out"] += 1
    rows = [e for e in agg.values() if e["restock"] > 0]
    rows.sort(key=lambda e: (-e["restock"], -e["tickets_in"], e["member"]))
    return rows[:limit]


def top_lines(rows):
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    return "\n".join(
        f"{medals[i] if i < len(medals) else str(i + 1) + '.'} **{r['member']}** · "
        f"{r['restock']}x restock · +{r['tickets_in']} tiket"
        for i, r in enumerate(rows)
    )


def analytics_embed(title, a, top):
    t = a["today"]
    embed = discord.Embed(
        title=title,
        description=f"📅 {a['day_label']}",
        color=COLOR_GREEN if t["restock"] else COLOR_AMBER,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="📈 Restock", value=f"**{t['restock']}**", inline=True)
    embed.add_field(name="🎟️ Tiket masuk", value=f"**{t['tickets_in']}**", inline=True)
    embed.add_field(name="🛒 Tiket terjual", value=f"**{t['tickets_sold']}**", inline=True)
    embed.add_field(name="🔴 Sold out", value=f"**{t['sold_out']}**", inline=True)
    embed.add_field(
        name="⏱️ Rata-rata sampai SO",
        value=f"**{fmt_ms(a['avg_so'])}**" + (f"\n-# {a['so_samples']} sampel" if a["so_samples"] else ""),
        inline=True,
    )
    embed.add_field(name="🕒 Jam restock terbanyak", value=f"**{hour_range(a['peak_hour'])}**", inline=True)

    mc = a.get("most_active")
    if mc and mc in a["events"]:
        e = a["events"][mc]
        embed.add_field(
            name="🔥 Event paling aktif",
            value=f"**{e['name']}** · {e['restock']}x restock · +{e['tickets_in']} tiket",
            inline=False,
        )
    if top:
        embed.add_field(name="🏆 Top member", value=top_lines(top), inline=False)
    if a["fastest"]:
        lines = [
            f"{i}. **{f['member']}** · {f['event']} {f['lane']} → {fmt_ms(f['duration'])}"
            for i, f in enumerate(a["fastest"][:3], 1)
        ]
        embed.add_field(name="⚡ Turnover tercepat", value="\n".join(lines), inline=False)

    if a.get("tracked_since") and a["tracked_since"] > a["day_start"] + 60:
        since = datetime.fromtimestamp(a["tracked_since"], LOCAL_TZ).strftime("%H:%M")
        embed.set_footer(text=f"JKT48 Ticket Radar · pencatatan mulai {since}")
    else:
        embed.set_footer(text="JKT48 Ticket Radar")
    return embed


CSV_KIND = {"in": "restock", "sold": "terjual", "so": "sold_out"}


def export_csv(only_today=False):
    since = day_start_ts() if only_today else 0
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["waktu_lokal", "epoch", "jenis", "kode_event", "event", "member",
                "jalur", "sesi", "tanggal_sesi", "jam_mulai", "jumlah", "durasi_detik"])
    with lock:
        for ts, kind, code, sdc, n, dur in activity:
            if ts < since:
                continue
            v = lane_state.get((code, sdc)) or {}
            w.writerow([
                datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                int(ts), CSV_KIND.get(kind, kind), code, EVENTS.get(code, code),
                v.get("member_name") or "", v.get("label") or "",
                v.get("session_label") or "", v.get("session_date") or "",
                hhmm(v.get("session_start_time")) if v else "",
                n, "" if dur is None else dur,
            ])
    return buf.getvalue()

def _same(a, b):
    """Bandingkan string secara aman dan tidak error untuk karakter non-ASCII."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))

# ------------------------------------------------------------------ Web Push
PUSH_FILE = Path(os.environ.get("PUSH_FILE") or SUBS_FILE.with_name("push_subs.json"))
push_lock = threading.Lock()
_push_file_lock = threading.Lock()
push_subs = {}      # endpoint -> {"subscription": {...}, "prefs": {...}, "created": ts, "updated": ts}
push_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="push")

SW_JS = r"""
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : "" }; }
  const opts = {
    body: d.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: d.url || "/" },
    vibrate: [200, 100, 200]
  };
  if (d.tag) { opts.tag = d.tag; opts.renotify = true; }
  e.waitUntil(self.registration.showNotification(d.title || "JKT48 Ticket Radar", opts));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.openWindow(url));
});
"""

_icon_cache = {}


def icon_png(size):
    """Ikon PNG polos (merah + titik putih) tanpa library gambar."""
    if size in _icon_cache:
        return _icon_cache[size]
    red, white = bytes((0xE1, 0x1D, 0x48)), bytes((255, 255, 255))
    c = size / 2
    r = size * 0.28
    solid = b"\x00" + red * size
    rows = []
    for y in range(size):
        dy = y + 0.5 - c
        if abs(dy) >= r:
            rows.append(solid)
            continue
        dx = int((r * r - dy * dy) ** 0.5)
        x0, x1 = max(0, int(c - dx)), min(size, int(c + dx))
        rows.append(b"\x00" + red * x0 + white * (x1 - x0) + red * (size - x1))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
           + chunk(b"IEND", b""))
    _icon_cache[size] = png
    return png


def manifest_json(key=""):
    start = "/" + ("?key=" + quote(key, safe="") if key else "")
    return {
        "name": "JKT48 Ticket Radar", "short_name": "Ticket Radar",
        "id": "/", "start_url": start, "scope": "/",
        "display": "standalone",
        "background_color": "#0f1117", "theme_color": "#e11d48",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }


def load_push():
    try:
        raw = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        with push_lock:
            push_subs.clear()
            for ep, rec in raw.items():
                if isinstance(rec, dict) and isinstance(rec.get("subscription"), dict):
                    push_subs[ep] = rec
    print(f"[PUSH] Dimuat {len(push_subs)} langganan")


def save_push():
    with push_lock:
        snap = dict(push_subs)
    with _push_file_lock:
        try:
            tmp = PUSH_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PUSH_FILE)
        except Exception:
            traceback.print_exc()


def push_remove(endpoint):
    with push_lock:
        existed = push_subs.pop(endpoint, None) is not None
    if existed:
        save_push()
    return existed


def valid_subscription(sub):
    if not isinstance(sub, dict):
        return False
    ep, keys = sub.get("endpoint"), sub.get("keys")
    if not isinstance(ep, str) or len(ep) > 600 or not isinstance(keys, dict):
        return False
    if not (isinstance(keys.get("p256dh"), str) and isinstance(keys.get("auth"), str)):
        return False
    u = urlparse(ep)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def _send_one(rec, payload):
    """Return 'ok' | 'dead' (langganan sudah mati, hapus) | 'error' (sementara)."""
    try:
        webpush(
            subscription_info=rec["subscription"],
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE,
            vapid_claims={"sub": VAPID_SUBJECT},   # dict baru tiap panggilan (library mengubahnya)
            ttl=PUSH_TTL,
            headers={"Urgency": "high"},
            timeout=10,
        )
        return "ok"
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            return "dead"
        print(f"[PUSH] gagal ({status}): {str(e)[:150]}")
        return "error"
    except Exception as e:
        print(f"[PUSH] error: {type(e).__name__}: {str(e)[:150]}")
        return "error"


def _push_wants(prefs, code, lane):
    mode = prefs.get("mode", "all")
    if mode == "vip":
        return is_vip(code, lane)
    if mode == "favs":
        return norm(lane.get("member_name")) in set(prefs.get("favs") or [])
    return True


def _push_payloads(code, lanes, deltas):
    ev = EVENTS.get(code, code)
    if len(lanes) <= PUSH_MAX_SINGLE:
        out = []
        for l in lanes:
            sdc = str(l.get("session_detail_code") or "")
            q = parse_quota(l.get("available_quota")) or 0
            d = deltas.get((code, sdc))
            out.append({
                "title": f"🟢 RESTOCK · {l.get('member_name') or '-'}",
                "body": f"{ev} · {l.get('label') or '-'} · {l.get('session_label') or '-'}\n"
                        f"{q} tiket" + (f" (+{d})" if d else ""),
                "url": buy_url(code),
                "tag": f"{code}|{sdc}",
            })
        return out
    names = []
    for l in lanes:
        n = l.get("member_name")
        if n and n not in names:
            names.append(n)
    shown = ", ".join(names[:4]) + (f" +{len(names) - 4} lainnya" if len(names) > 4 else "")
    return [{
        "title": f"🟢 {len(lanes)} restock · {ev}",
        "body": shown, "url": buy_url(code), "tag": f"{code}|multi",
    }]


def _push_to_sub(endpoint, rec, code, lanes, deltas):
    try:
        matched = [l for l in lanes if _push_wants(rec.get("prefs") or {}, code, l)]
        if not matched:
            return
        for payload in _push_payloads(code, matched, deltas):
            if _send_one(rec, payload) == "dead":
                push_remove(endpoint)
                print("[PUSH] langganan mati dihapus")
                return
    except Exception:
        traceback.print_exc()


def push_dispatch(code, restocks, deltas):
    """Non-blocking: dipanggil dari process_report."""
    if not PUSH_ENABLED:
        return
    with push_lock:
        subs = list(push_subs.items())
    if not subs:
        return
    lanes = [dict(l) for l in restocks]
    d = dict(deltas)
    for endpoint, rec in subs:
        push_pool.submit(_push_to_sub, endpoint, rec, code, lanes, d)

# ------------------------------------------------------------------ push broadcast
def _push_raw(endpoint, rec, payload):
    try:
        if _send_one(rec, payload) == "dead":
            push_remove(endpoint)
    except Exception:
        traceback.print_exc()


def push_broadcast(payload):
    if not PUSH_ENABLED:
        return
    with push_lock:
        subs = list(push_subs.items())
    for endpoint, rec in subs:
        push_pool.submit(_push_raw, endpoint, rec, dict(payload))


# ------------------------------------------------------------------ kanal cadangan (ntfy / Telegram)
backup_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="backup")


def _post_json(url, payload, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        r.read()


def _backup_send(title, body, url, priority):
    if NTFY_TOPIC:
        try:
            p = {"topic": NTFY_TOPIC, "title": title, "message": body,
                 "priority": priority, "tags": ["rotating_light"]}
            if url:
                p["click"] = url
                p["actions"] = [{"action": "view", "label": "Beli", "url": url}]
            _post_json(NTFY_SERVER, p,
                       {"Authorization": "Bearer " + NTFY_TOKEN} if NTFY_TOKEN else None)
        except Exception as e:
            print(f"[BACKUP] ntfy gagal: {type(e).__name__}")
    if TG_TOKEN and TG_CHAT:
        try:
            text = f"{title}\n{body}" + (f"\n{url}" if url else "")
            _post_json(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                       {"chat_id": TG_CHAT, "text": text})
        except Exception as e:
            print(f"[BACKUP] telegram gagal: {type(e).__name__}")


def backup_notify(title, body, url="", priority=4):
    """Non-blocking. priority 1-5 (ntfy); 5 = paling tinggi."""
    if BACKUP_ENABLED:
        backup_pool.submit(_backup_send, title, body, url, priority)


def backup_restocks(code, restocks, deltas):
    vip = [l for l in restocks if is_vip(code, l)]
    if not vip:
        return
    lines = []
    for l in vip[:5]:
        d = deltas.get((code, str(l.get("session_detail_code") or "")))
        lines.append(
            f"{l.get('member_name')} · {l.get('label')} · {l.get('session_label')} · "
            f"{parse_quota(l.get('available_quota')) or 0} tiket" + (f" (+{d})" if d else ""))
    backup_notify(f"🟢 RESTOCK VIP · {EVENTS.get(code, code)}", "\n".join(lines),
                  buy_url(code), priority=5)


# ------------------------------------------------------------------ deteksi penjualan dibuka
def mark_waiting(code):
    """API hidup tapi belum ada jalur: bukan error, cuma menunggu penjualan dibuka."""
    with lock:
        last_report[code] = time.time()
        baselined.discard(code)      # begitu dibuka, jadi scan awal (tanpa banjir notifikasi restock)
    if sale_state.get(code) != "waiting":
        sale_state[code] = "waiting"
        print(f"[SALE] {EVENTS.get(code, code)} menunggu penjualan dibuka")


async def notify_sale_open(code, name, body):
    try:
        channel = await get_channel()
        embed = discord.Embed(
            title=f"🚀 PENJUALAN DIBUKA · {name}", url=buy_url(code),
            description=body, color=COLOR_GREEN, timestamp=datetime.now(timezone.utc))
        await safe_send(
            channel, content=f"{vip_mention()} 🚀 **PENJUALAN {name} DIBUKA!**",
            embed=embed, view=buy_view(code, ack=True), allowed_mentions=vip_allowed())
    except Exception:
        traceback.print_exc()


def sale_open_dispatch(code, lanes):
    name = EVENTS.get(code, code)
    avail = [l for l in lanes if (parse_quota(l.get("available_quota")) or 0) > 0]
    total = sum(parse_quota(l.get("available_quota")) or 0 for l in lanes)
    vips = sorted({l.get("member_name") for l in avail if is_vip(code, l) and l.get("member_name")})
    body = f"{len(avail)}/{len(lanes)} jalur tersedia · {total} tiket"
    if vips:
        body += " · VIP: " + ", ".join(vips[:6])
    print(f"[SALE] DIBUKA {name}: {body}")
    push_broadcast({"title": f"🚀 PENJUALAN DIBUKA · {name}", "body": body,
                    "url": buy_url(code), "tag": f"{code}|open"})
    backup_notify(f"🚀 PENJUALAN DIBUKA · {name}", body, buy_url(code), priority=5)
    if bot.main_loop is not None and bot.is_ready():
        asyncio.run_coroutine_threadsafe(notify_sale_open(code, name, body), bot.main_loop)


# ------------------------------------------------------------------ penemuan event baru
def discovery_loop():
    time.sleep(20)
    session = None
    warned = False
    while True:
        try:
            if session is None:
                session = build_session(IMPERSONATE)
            found = set()
            for u in EVENT_LIST_URLS:
                try:
                    r = session.get(u, headers={"Accept-Language": "id-ID,id;q=0.9"}, timeout=15)
                    if r.status_code == 200:
                        found.update(EVENT_CODE_RE.findall(r.text))
                except Exception as e:
                    print(f"[DISCOVER] {u} gagal: {type(e).__name__}")
                    session = None
            if not found and not warned:
                warned = True
                print("[DISCOVER] tidak ada kode event di halaman (mungkin dirender JS).")
            baseline = not seen_codes        # scan pertama hanya mencatat, tidak mendaftar
            for code in sorted(found):
                if code in EVENTS or code in seen_codes:
                    seen_codes.add(code)
                    continue
                seen_codes.add(code)
                if baseline:
                    continue
                if register_event(code):
                    save_state()
                    print(f"[DISCOVER] event baru: {code}")
                    if bot.main_loop is not None and bot.is_ready():
                        asyncio.run_coroutine_threadsafe(poll_alert(
                            f"🆕 Event baru terdeteksi: **{code}** ({buy_url(code)}). "
                            f"Otomatis dipantau dengan nama sementara 'Event {code}'."),
                            bot.main_loop)
        except Exception:
            traceback.print_exc()
        time.sleep(EVENT_DISCOVERY_INTERVAL)


# ------------------------------------------------------------------ heartbeat (dead-man switch)
def heartbeat_loop():
    """Ping hanya jika semua event segar dan bot terhubung; berhenti ping = layanan eksternal membunyikan alarm."""
    while True:
        time.sleep(60)
        now = time.time()
        fresh = all(last_report.get(c) and now - last_report[c] <= STALE_SECONDS for c in list(EVENTS))
        if fresh and bot.is_ready():
            try:
                urllib.request.urlopen(HEARTBEAT_URL, timeout=8).read()
            except Exception as e:
                print(f"[HEARTBEAT] gagal: {type(e).__name__}")

# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def send_response(self, code, message=None):
        count_request(code)
        super().send_response(code, message)

    def log_message(self, fmt, *args):
        if self.path.startswith(("/api/lanes", "/api/history", "/api/analytics",
                                 "/api/status", "/members/")):
            return

    def send_json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_csv(self, filename, text):
        raw = ("\ufeff" + text).encode("utf-8")   # BOM supaya Excel membaca UTF-8
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(self, ctype, raw, cache="no-store", extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _dash_ok(self, url):
        if not DASHBOARD_KEY:
            return True
        given = (parse_qs(url.query).get("key") or [self.headers.get("X-Dashboard-Key", "")])[0]
        return _same(given, DASHBOARD_KEY)

    def handle_push_post(self, url):
        if not self._dash_ok(url):
            return self.send_json(401, {"ok": False, "error": "Key dashboard salah."})
        if not PUSH_ENABLED:
            return self.send_json(503, {"ok": False, "error": "Push belum aktif di server (VAPID key / pywebpush)."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20000:
                return self.send_json(413, {"ok": False, "error": "Ukuran payload tidak valid."})
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("payload")
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"ok": False, "error": "Payload harus JSON object."})

        path = url.path

        if path == "/api/push/subscribe":
            sub = data.get("subscription")
            if not valid_subscription(sub):
                return self.send_json(400, {"ok": False, "error": "Langganan tidak valid."})
            pin = data.get("prefs") if isinstance(data.get("prefs"), dict) else {}
            mode = pin.get("mode") if pin.get("mode") in ("all", "vip", "favs") else "all"
            fav_in = pin.get("favs") if isinstance(pin.get("favs"), list) else []
            favs = [norm(x) for x in fav_in if isinstance(x, str)][:300]
            ep = sub["endpoint"]
            now = int(time.time())
            rec = {
                "subscription": {"endpoint": ep, "keys": {
                    "p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}},
                "prefs": {"mode": mode, "favs": favs},
                "updated": now,
            }
            with push_lock:
                if ep not in push_subs and len(push_subs) >= PUSH_MAX_SUBS:
                    full = True
                else:
                    full = False
                    rec["created"] = (push_subs.get(ep) or {}).get("created", now)
                    push_subs[ep] = rec
                count = len(push_subs)
            if full:
                return self.send_json(429, {"ok": False, "error": "Batas jumlah perangkat tercapai."})
            save_push()
            return self.send_json(200, {"ok": True, "count": count})

        if path == "/api/push/unsubscribe":
            ep = data.get("endpoint")
            if isinstance(ep, str):
                push_remove(ep)
            return self.send_json(200, {"ok": True})

        if path == "/api/push/test":
            ep = data.get("endpoint")
            with push_lock:
                rec = push_subs.get(ep) if isinstance(ep, str) else None
            if not rec:
                return self.send_json(404, {"ok": False, "error": "Perangkat belum terdaftar di server."})
            result = _send_one(rec, {
                "title": "✅ Tes notifikasi",
                "body": "Push dari JKT48 Ticket Radar berfungsi.",
                "url": "/", "tag": "test",
            })
            if result == "ok":
                return self.send_json(200, {"ok": True})
            if result == "dead":
                push_remove(ep)
                return self.send_json(410, {"ok": False, "error": "Langganan sudah tidak valid, aktifkan ulang."})
            return self.send_json(502, {"ok": False, "error": "Layanan push menolak. Lihat log server."})

        return self.send_json(404, {"ok": False, "error": "Endpoint tidak ditemukan."})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            now = time.time()
            stale = [c for c in list(EVENTS)
                     if not last_report.get(c) or now - last_report[c] > STALE_SECONDS]
            strict = (parse_qs(url.query).get("strict") or [""])[0] == "1"
            warm = now - START_TIME < STALE_SECONDS
            ok = True if (not strict or warm) else (not stale and bot.is_ready())
            return self.send_json(200, {
                "ok": ok, "service": "jkt48-notifier",
                "stale": [EVENTS.get(c, c) for c in stale],
                "poller": {**poller_info(), "events": list(EVENTS)},
            })

        if url.path == "/sw.js":
            return self.send_bytes(
                "application/javascript; charset=utf-8", SW_JS.encode("utf-8"),
                "no-cache", {"Service-Worker-Allowed": "/"})

        if url.path == "/manifest.webmanifest":
            key = (parse_qs(url.query).get("key") or [""])[0][:200]
            raw = json.dumps(manifest_json(key), ensure_ascii=False).encode("utf-8")
            return self.send_bytes("application/manifest+json; charset=utf-8", raw)

        icon_size = {"/icon-192.png": 192, "/icon-512.png": 512,
                     "/apple-touch-icon.png": 180}.get(url.path)
        if icon_size:
            return self.send_bytes("image/png", icon_png(icon_size), "public, max-age=86400")

        if url.path.startswith("/members/"):
            found = member_photos.read_photo(unquote(url.path[len("/members/"):]))
            if not found:
                return self.send_json(404, {"ok": False, "error": "Foto tidak ditemukan."})
            body, ctype = found
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if DASHBOARD_KEY:
            given = (parse_qs(url.query).get("key") or [self.headers.get("X-Dashboard-Key", "")])[0]
            if not _same(given, DASHBOARD_KEY):
                return self.send_json(401, {"ok": False, "error": "Key dashboard salah."})

        if url.path == "/api/war":
            return self.send_json(200, war_info())

        if url.path == "/api/lanes":
            return self.send_json(200, snapshot())

        if url.path == "/api/analytics":
            return self.send_json(200, analytics_snapshot())

        if url.path == "/api/status":
            return self.send_json(200, health_snapshot())

        if url.path == "/api/push/key":
            return self.send_json(200, {"enabled": PUSH_ENABLED,
                                        "key": VAPID_PUBLIC if PUSH_ENABLED else ""})

        if url.path == "/api/export.csv":
            only_today = (parse_qs(url.query).get("range") or [""])[0] == "today"
            stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
            name = f"jkt48-radar-{stamp}.csv" if only_today else f"jkt48-radar-{stamp}-48jam.csv"
            return self.send_csv(name, export_csv(only_today))

        if url.path == "/api/members":
            with lock:
                names = [n for group in known_members.values() for n in group]
            return self.send_json(200, member_photos.check(names))

        if url.path == "/api/history":
            qs = parse_qs(url.query)
            code = (qs.get("code") or [""])[0]
            sdc = (qs.get("sdc") or [""])[0]
            with lock:
                pts = [[round(t), q] for t, q in history.get((code, sdc), [])]
            return self.send_json(200, {"now": time.time(), "points": pts})

        if url.path in ("/", "/index.html"):
            try:
                return self.send_html(200, DASHBOARD_FILE.read_bytes())
            except FileNotFoundError:
                msg = (
                    f"dashboard.html tidak ditemukan.\n"
                    f"Lokasi yang dicari: {DASHBOARD_FILE}\n"
                    f"Set env DASHBOARD_FILE ke path lengkap dashboard.html,\n"
                    f"atau taruh dashboard.html di folder yang sama dengan script ini."
                )
                return self.send_html(500, msg.encode("utf-8"))
        self.send_json(404, {"ok": False, "error": "Tidak ditemukan."})

    def handle_ctl_post(self, url):
        if not self._dash_ok(url):
            return self.send_json(401, {"ok": False, "error": "Key dashboard salah."})
        data = {}
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if 0 < length <= 2000:
                parsed = json.loads(self.rfile.read(length).decode("utf-8"))
                data = parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        if url.path == "/api/ack":
            set_ack()
            return self.send_json(200, {"ok": True})
        try:
            minutes = float(data.get("minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        set_war(minutes)
        return self.send_json(200, {"ok": True, **war_info()})

    def do_POST(self):
        url0 = urlparse(self.path)
        if url0.path.startswith("/api/push/"):
            return self.handle_push_post(url0)       
        secret = self.headers.get("X-Notify-Secret", "")
        if not NOTIFY_SECRET or not _same(secret, NOTIFY_SECRET):
            return self.send_json(401, {"ok": False, "error": "Unauthorized."})

        path = urlparse(self.path).path

        if path == "/api/poll/reset":
            if not POLL_ENABLED:
                return self.send_json(400, {"ok": False, "error": "Poller direct tidak aktif."})
            request_poll_reset()
            return self.send_json(200, {"ok": True, "message": "Poller direset, polling ulang sekarang."})

        if path != "/notify":
            return self.send_json(404, {"ok": False, "error": "Endpoint tidak ditemukan."})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_SIZE:
                return self.send_json(413, {"ok": False, "error": "Ukuran payload tidak valid."})

            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                return self.send_json(400, {"ok": False, "error": "Payload harus JSON object."})

            code = str(data.get("code") or "").strip().upper()
            page_url = str(data.get("pageUrl") or "")
            lanes = data.get("lanes")

            if code not in EVENTS:
                return self.send_json(400, {"ok": False, "error": f"Kode event tidak diizinkan: {code}"})
            if not page_url.startswith("https://jkt48.com/purchase/exclusive"):
                return self.send_json(400, {"ok": False, "error": "URL halaman tidak diizinkan."})
            if data.get("error"):
                record_remote_poll(code, " ".join(str(data["error"]).split())[:200])
                return self.send_json(200, {"ok": True, "code": code, "recorded": "error"})
            if not isinstance(lanes, list) or len(lanes) > 1000:
                return self.send_json(400, {"ok": False, "error": "Daftar jalur tidak valid."})

            lanes = [l for l in lanes if isinstance(l, dict)]
            restocks, new_sessions, sold_outs = process_report(code, lanes)
            record_remote_poll(code)

            print(f"[JKT48] {EVENTS[code]}: jalur={len(lanes)} restock={restocks} baru={new_sessions} soldout={sold_outs}")
            self.send_json(200, {
                "ok": True, "code": code, "laneCount": len(lanes),
                "restocks": restocks, "newSessions": new_sessions, "soldOuts": sold_outs,
            })
        except Exception as error:
            traceback.print_exc()
            self.send_json(500, {"ok": False, "error": f"{type(error).__name__}: {str(error)[:300]}"})

def run_http():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[JKT48] Notifier aktif di http://{HOST}:{PORT}/notify (menunggu laporan worker)")
    print(f"[JKT48] Dashboard di http://{HOST}:{PORT}/")
    server.serve_forever()


def main():
    if not TOKEN or not CHANNEL_ID:
        raise SystemExit("Set DISCORD_BOT_TOKEN dan DISCORD_CHANNEL_ID terlebih dahulu.")
    if not NOTIFY_SECRET:
        print("[INFO] NOTIFY_SECRET kosong: endpoint /notify dinonaktifkan (hanya polling langsung).")
    load_state()
    load_push()
    if not DATA_DIR:
        print("[WARN] DATA_DIR belum diset: state, langganan, dan push hilang saat redeploy.")
    if BACKUP_ENABLED:
        print(f"[BACKUP] Aktif (ntfy={'ya' if NTFY_TOPIC else 'tidak'}, telegram={'ya' if TG_TOKEN and TG_CHAT else 'tidak'})")
    if HEARTBEAT_URL:
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    if PUSH_ENABLED:
        print(f"[PUSH] Aktif ({len(push_subs)} perangkat)")
    else:
        print("[PUSH] Nonaktif: pasang pywebpush dan set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.")
    threading.Thread(target=run_http, daemon=True).start()
    if POLL_ENABLED:
        threading.Thread(target=poll_loop, daemon=True).start()
        print("[JKT48] Polling langsung ke jkt48.com aktif.")
        if POLL_PROXY:
            print("[JKT48] Polling lewat proxy (POLL_PROXY diset).")
        if EVENT_DISCOVERY:
            threading.Thread(target=discovery_loop, daemon=True).start()
    else:
        print("[JKT48] Polling langsung mati, menunggu laporan Worker.")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()