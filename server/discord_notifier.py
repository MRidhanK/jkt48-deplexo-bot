"""
JKT48 Ticket Radar - bot Discord + dashboard.

Sumber data HANYA dari Cloudflare Worker (atau klien lain) yang POST ke /notify.
Server ini juga bisa polling langsung ke jkt48.com kalau POLL_ENABLED=1.
"""
import asyncio
import concurrent.futures
import hmac
import json
import os
import threading
import time
import traceback
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import random
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
from datetime import datetime, timezone

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

EVENTS = {"EX5B99": "2 Shoot", "EX24AE": "MNG"}

# Alert jika worker melaporkan error berturut-turut sebanyak ini.
POLL_FAIL_ALERT = int(os.environ.get("POLL_FAIL_ALERT", "5"))

VIP_NAMES = [
    "Fiony Alveria", "Aurhel Alana", "Michelle Alexandra",
    "Hillary Abigail", "Adeline Wijaya", "Oline Manuel",
    "Abigail Rachel", "Catherina Vallencia", "Jacqueline Immanuela",
    "Nur Intan", "Putry Jazyta", "Astrella Virgiananda",
]

VIP_MEMBERS = {
    "EX5B99": VIP_NAMES,
    "EX24AE": VIP_NAMES,
}

SEED_FILE = Path(__file__).with_name("subscriptions.json")
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
    global quota_state, baselined, last_restock
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return

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


def buy_view(code):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="🛒 Beli sekarang",
        style=discord.ButtonStyle.link,
        url=buy_url(code),
    ))
    return view


# ------------------------------------------------------------------ bot
class RadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.main_loop = None
        self.save_task = None
        self.stale_task = None

    async def setup_hook(self):
        self.main_loop = asyncio.get_running_loop()
        self.save_task = asyncio.create_task(save_state_loop())
        self.stale_task = asyncio.create_task(stale_watch_loop())
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
    app_commands.Choice(name="2 Shoot", value="EX5B99"),
    app_commands.Choice(name="MNG", value="EX24AE"),
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


@bot.tree.command(name="2shoot", description="Lihat stok tiket member di event 2 Shoot")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_2shoot(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EX5B99", member)


@bot.tree.command(name="mng", description="Lihat stok tiket member di event MNG")
@app_commands.describe(member="Nama member (atau 'semua')")
@app_commands.autocomplete(member=member_autocomplete)
async def cmd_mng(interaction: discord.Interaction, member: str):
    await show_stock(interaction, "EX24AE", member)


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
                view=buy_view(code),
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
    restocks = []
    new_sessions = []
    sold_outs = []
    deltas = {}

    now = time.time()

    with lock:
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
                    >= RESTOCK_COOLDOWN
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

async def save_state_loop():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        save_state()


POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
POLL_BACKOFF_MIN = int(os.environ.get("POLL_BACKOFF_MIN", "60"))
POLL_BACKOFF_MAX = int(os.environ.get("POLL_BACKOFF_MAX", "300"))
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
        msg = "200 tapi 0 jalur (struktur JSON berubah atau event ditutup?)"
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
            backoff = min(max(backoff * 3, POLL_BACKOFF_MIN), POLL_BACKOFF_MAX)
        else:
            backoff = 0

        elapsed = time.time() - started
        jitter = random.uniform(0, POLL_JITTER_MAX)
        sleep_for = max(5.0, POLL_INTERVAL - elapsed + jitter + backoff)

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
            events[code] = {"name": name, "updated": last_report.get(code), "lanes": lanes}
    names = {l["member"] for e in events.values() for l in e["lanes"] if l.get("member")}
    return {"now": now, "stale_after": STALE_SECONDS, "events": events,
            "poller": poller_info(), "photos": member_photos.photos_for(names)}

def _same(a, b):
    """Bandingkan string secara aman dan tidak error untuk karakter non-ASCII."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))

# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if self.path.startswith(("/api/lanes", "/api/history", "/members/")):
            return
        print("[HTTP]", fmt % args)

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

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self.send_json(200, {
                "ok": True, "service": "jkt48-notifier",
                "poller": {**poller_info(), "events": list(EVENTS)},
            })

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

        if url.path == "/api/lanes":
            return self.send_json(200, snapshot())

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

    def do_POST(self):
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
    threading.Thread(target=run_http, daemon=True).start()
    if POLL_ENABLED:
        threading.Thread(target=poll_loop, daemon=True).start()
        print("[JKT48] Polling langsung ke jkt48.com aktif.")
        if POLL_PROXY:
            print("[JKT48] Polling lewat proxy (POLL_PROXY diset).")
    else:
        print("[JKT48] Polling langsung mati, menunggu laporan Worker.")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()