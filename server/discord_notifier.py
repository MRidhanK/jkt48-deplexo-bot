import asyncio
import hmac
import json
import os
import random
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import discord
from discord import app_commands

# ------------------------------------------------------------------ FITUR BARU: load .env
def _load_dotenv():
    env_path = Path(__file__).with_name(".env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        traceback.print_exc()

_load_dotenv()

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
NOTIFY_SECRET = os.environ.get("NOTIFY_SECRET", "").strip()
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()  # FITUR BARU
MAX_BODY_SIZE = 500_000

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0") or 0)
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)
VIP_USER_ID = os.environ.get("VIP_USER_ID", "").strip()
VIP_FALLBACK_TEXT = os.environ.get("VIP_FALLBACK_TEXT", "")
SPAM_INTERVAL = float(os.environ.get("SPAM_INTERVAL", "4"))
SPAM_MAX = int(os.environ.get("SPAM_MAX", "20"))
STALE_SECONDS = int(os.environ.get("STALE_SECONDS", "150"))

MIN_SEND_GAP = float(os.environ.get("MIN_SEND_GAP", "1.2"))
MAX_CONCURRENT_SPAM = int(os.environ.get("MAX_CONCURRENT_SPAM", "5"))
RESTOCK_COOLDOWN = int(os.environ.get("RESTOCK_COOLDOWN", "300"))
USER_NOTIFY_COOLDOWN = int(os.environ.get("USER_NOTIFY_COOLDOWN", "60"))  # FITUR BARU

LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))  # FITUR BARU

EVENTS = {"EX5B99": "2 Shoot", "EX24AE": "MNG"}

POLL_ENABLED = os.environ.get("POLL_ENABLED", "1") != "0"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "20"))
POLL_FAIL_ALERT = int(os.environ.get("POLL_FAIL_ALERT", "5"))
POLL_EVENTS = [
    c.strip().upper()
    for c in os.environ.get("POLL_EVENTS", ",".join(EVENTS)).split(",")
    if c.strip().upper() in EVENTS
]
API_URL = os.environ.get(
    "JKT48_API_URL", "https://jkt48.com/api/v1/exclusives/{code}/bonus?lang=id"
)
JKT48_COOKIE = os.environ.get("JKT48_COOKIE", "").strip()
JKT48_USER_AGENT = os.environ.get(
    "JKT48_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
JKT48_PROXY = os.environ.get("JKT48_PROXY", "").strip() or None
try:
    JKT48_EXTRA_HEADERS = json.loads(os.environ.get("JKT48_EXTRA_HEADERS", "") or "{}")
except json.JSONDecodeError:
    JKT48_EXTRA_HEADERS = {}

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


# ------------------------------------------------------------------ FITUR BARU: logging
def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"jkt48-{datetime.now():%Y-%m-%d}.log"

    def _log(msg):
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        print(line)
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    return _log

log = setup_logging()


def _resolve_dashboard_file() -> Path:
    env_path = os.environ.get("DASHBOARD_FILE", "").strip()
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
        log(f"[WARN] DASHBOARD_FILE={env_path} tidak ditemukan, fallback.")

    here = Path(__file__).resolve().parent
    candidates = [
        here / "dashboard.html",
        here / "server" / "dashboard.html",
        here.parent / "server" / "dashboard.html",
        here.parent / "dashboard.html",
        Path.cwd() / "dashboard.html",
        Path.cwd() / "server" / "dashboard.html",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


DASHBOARD_FILE = _resolve_dashboard_file()
log(f"[INIT] Dashboard file: {DASHBOARD_FILE} (exists={DASHBOARD_FILE.is_file()})")

COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C
COLOR_GOLD = 0xF1C40F  # FITUR BARU: warna VIP


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
restock_history = defaultdict(list)  # FITUR BARU: riwayat restock per event

subs_lock = threading.Lock()
poll_status = {}

_send_lock = threading.Lock()
_last_send_time = [0.0]

# FITUR BARU: cooldown notifikasi per user
_user_last_notify = {}
_user_last_command = {}  # FITUR BARU: rate limit command per user


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
    global quota_state, baselined, last_restock, restock_history
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        quota_state = {}
        for k, v in (raw.get("quota_state") or {}).items():
            code, _, sdc = k.partition("|")
            quota_state[(code, sdc)] = v
        baselined = set(raw.get("baselined") or [])
        last_restock = {}
        for k, v in (raw.get("last_restock") or {}).items():
            code, _, sdc = k.partition("|")
            last_restock[(code, sdc)] = v
        # FITUR BARU: restore history
        restock_history = defaultdict(list)
        for code, items in (raw.get("restock_history") or {}).items():
            restock_history[code] = items[-200:]
        log(f"[STATE] Dimuat: {len(quota_state)} lane, {len(baselined)} event")
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_state():
    try:
        with lock:
            raw = {
                "quota_state": {f"{c}|{s}": q for (c, s), q in quota_state.items()},
                "baselined": list(baselined),
                "last_restock": {f"{c}|{s}": t for (c, s), t in last_restock.items()},
                "restock_history": {c: v[-200:] for c, v in restock_history.items()},
            }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        traceback.print_exc()


# ------------------------------------------------------------------ embeds
def restock_embed(code, lane, delta=None, vip=False):
    quota = parse_quota(lane.get("available_quota"))
    desc = f"**{EVENTS.get(code, code)}** · {lane.get('label')}"
    if delta is not None and delta > 0:
        desc += f"  ·  📈 **+{delta} tiket**"
    title = f"🟢 RESTOCK · {lane.get('member_name')}"
    color = COLOR_GREEN
    if vip:
        title = f"⭐ VIP RESTOCK · {lane.get('member_name')}"
        color = COLOR_GOLD
    return discord.Embed(
        title=title, color=color, description=desc,
    ).add_field(name="🗓️ Sesi", value=str(lane.get("session_label") or "-"), inline=True
    ).add_field(name="📅 Tanggal", value=str(lane.get("session_date") or "-"), inline=True
    ).add_field(
        name="🕒 Waktu",
        value=f"{hhmm(lane.get('session_start_time'))} - {hhmm(lane.get('session_end_time'))}",
        inline=True,
    ).add_field(name="📊 Kuota", value=f"`{quota}`", inline=True
    ).add_field(name="💰 Harga", value=format_rupiah(lane.get("price")), inline=True
    ).add_field(name="🧩 Kode sesi", value=f"`{lane.get('session_detail_code')}`", inline=False)


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


# ------------------------------------------------------------------ bot
class RadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.main_loop = None
        self.poll_task = None
        self.save_task = None
        self.started_at = time.time()

    async def setup_hook(self):
        self.main_loop = asyncio.get_running_loop()
        if POLL_ENABLED and POLL_EVENTS:
            self.poll_task = asyncio.create_task(poll_loop())
        self.save_task = asyncio.create_task(save_state_loop())
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log(f"[JKT48] Bot aktif sebagai {self.user}")


bot = RadarBot()

EVENT_CHOICES = [
    app_commands.Choice(name="2 Shoot", value="EX5B99"),
    app_commands.Choice(name="MNG", value="EX24AE"),
    app_commands.Choice(name="Semua event", value="*"),
]


async def member_autocomplete(interaction: discord.Interaction, current: str):
    names = set()
    for group in known_members.values():
        names.update(group)
    query = norm(current)
    matches = sorted(n for n in names if query in norm(n))[:25]
    return [app_commands.Choice(name=n, value=n) for n in matches]


# FITUR BARU: rate limit command per user
def check_command_rate(uid: str, min_gap: float = 2.0):
    now = time.time()
    last = _user_last_command.get(uid, 0)
    if now - last < min_gap:
        return False
    _user_last_command[uid] = now
    return True


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
    if not check_command_rate(str(interaction.user.id)):
        return await interaction.response.send_message(
            "⏳ Terlalu cepat, coba lagi sebentar.", ephemeral=True
        )
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
            lines.append(f"\n**{name}**")
            last_member = name
        quota = parse_quota(lane.get("available_quota")) or 0
        icon = "🟢" if quota > 0 else "🔴"
        lines.append(
            f"{icon} {lane.get('session_label') or '-'} · {lane.get('session_date') or '-'} "
            f"{hhmm(lane.get('session_start_time'))}-{hhmm(lane.get('session_end_time'))} · "
            f"{lane.get('label') or '-'} — kuota **{quota}** · {format_rupiah(lane.get('price'))}"
        )

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
        lanes = [
            dict(v) for (c, _), v in lane_state.items()
            if c == code and (show_all or query in norm(v.get("member_name")))
        ]
        reported = last_report.get(code)

    await interaction.response.defer(ephemeral=True)

    if reported is None:
        await interaction.followup.send(
            f"Belum ada data **{ev_name}**. Tunggu beberapa detik sampai poller "
            f"selesai memindai, lalu coba lagi.", ephemeral=True,
        )
        return
    if not lanes:
        await interaction.followup.send(
            f"Tidak ada jalur **{ev_name}** untuk \"{member}\". "
            f"Cek ejaan nama, atau pakai `semua`.", ephemeral=True,
        )
        return

    available = sum(1 for l in lanes if (parse_quota(l.get("available_quota")) or 0) > 0)
    age = time.time() - reported
    header = (
        f"Tersedia **{available}** dari **{len(lanes)}** jalur · "
        f"diperbarui <t:{int(reported)}:R>"
    )
    if age > STALE_SECONDS:
        header += "\n⚠️ Data sudah lama, sumber data mungkin berhenti melapor."

    pages = stock_pages(lanes)
    who = "Semua member" if show_all else member
    for i, page in enumerate(pages[:STOCK_MAX_EMBEDS]):
        embed = discord.Embed(
            title=f"📊 Stok {ev_name} · {who}",
            description=(header + "\n" if i == 0 else "") + page,
            color=COLOR_GREEN if available else COLOR_RED,
        )
        if len(pages) > 1:
            embed.set_footer(text=f"Halaman {i + 1}/{min(len(pages), STOCK_MAX_EMBEDS)}")
        await interaction.followup.send(embed=embed, ephemeral=True)
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
@app_commands.describe(
    member="Nama member (atau 'semua' untuk menghapus semua)",
    event="Hapus hanya untuk event ini (opsional)",
)
@app_commands.choices(event=EVENT_CHOICES)
@app_commands.autocomplete(member=member_autocomplete)
async def berhenti(interaction: discord.Interaction, member: str,
                   event: app_commands.Choice[str] = None):
    uid = str(interaction.user.id)
    clear_all = norm(member) in ("semua", "*", "all")
    ev_filter = event.value if event else None

    with subs_lock:
        data = load_subs()
        items = data.get(uid, [])
        before = len(items)
        if clear_all and not ev_filter:
            items = []
        elif clear_all and ev_filter:
            items = [i for i in items if i["event"] != ev_filter]
        else:
            target = norm(member)
            items = [
                i for i in items
                if not (i["member"] == target and (ev_filter is None or i["event"] == ev_filter))
            ]
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


# FITUR BARU: /riwayat
@bot.tree.command(name="riwayat", description="Riwayat restock terakhir per event")
@app_commands.describe(event="Event yang ingin dilihat riwayatnya", limit="Jumlah (1-20)")
@app_commands.choices(event=[
    app_commands.Choice(name="2 Shoot", value="EX5B99"),
    app_commands.Choice(name="MNG", value="EX24AE"),
])
async def riwayat(interaction: discord.Interaction, event: app_commands.Choice[str],
                  limit: app_commands.Range[int, 1, 20] = 10):
    with lock:
        items = list(restock_history.get(event.value, []))[-limit:]
    if not items:
        return await interaction.response.send_message(
            f"Belum ada riwayat restock untuk **{EVENTS[event.value]}**.",
            ephemeral=True,
        )
    lines = []
    for it in reversed(items):
        ts = it.get("at", 0)
        lines.append(
            f"<t:{int(ts)}:R> · **{it.get('member', '?')}** · "
            f"{it.get('lane', '?')} · +{it.get('delta', 0)}"
        )
    embed = discord.Embed(
        title=f"📜 Riwayat restock · {EVENTS[event.value]}",
        description="\n".join(lines),
        color=COLOR_GREEN,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# FITUR BARU: /cari
@bot.tree.command(name="cari", description="Cari member di semua event sekaligus")
@app_commands.describe(member="Nama member")
@app_commands.autocomplete(member=member_autocomplete)
async def cari(interaction: discord.Interaction, member: str):
    query = norm(member)
    await interaction.response.defer(ephemeral=True)
    embeds = []
    for code, name in EVENTS.items():
        with lock:
            lanes = [
                dict(v) for (c, _), v in lane_state.items()
                if c == code and query in norm(v.get("member_name"))
            ]
        if not lanes:
            continue
        available = sum(1 for l in lanes if (parse_quota(l.get("available_quota")) or 0) > 0)
        lines = []
        for l in sorted(lanes, key=lambda x: str(x.get("session_date") or "")):
            q = parse_quota(l.get("available_quota")) or 0
            icon = "🟢" if q > 0 else "🔴"
            lines.append(
                f"{icon} {l.get('session_label') or '-'} · {l.get('session_date') or '-'} · "
                f"{l.get('label') or '-'} — **{q}**"
            )
        embed = discord.Embed(
            title=f"🔍 {name} · {member}",
            description=(
                f"Tersedia **{available}** / **{len(lanes)}** jalur\n\n"
                + "\n".join(lines[:30])
            ),
            color=COLOR_GREEN if available else COLOR_RED,
        )
        embeds.append(embed)
    if not embeds:
        return await interaction.followup.send(
            f"Tidak ditemukan **{member}** di event manapun.", ephemeral=True
        )
    await interaction.followup.send(embeds=embeds[:5], ephemeral=True)


@bot.tree.command(name="status", description="Cek kondisi poller")
async def status_cmd(interaction: discord.Interaction):
    lines = []
    for code, name in EVENTS.items():
        s = poll_status.get(code)
        if not s:
            lines.append(f"⚪ **{name}** — belum ada data")
            continue
        txt = f"{'🟢' if s['ok'] else '🔴'} **{name}** — <t:{int(s['at'])}:R>"
        if not s["ok"]:
            txt += f"\n   ↳ gagal {s['fails']}x: {s['error']}"
        lines.append(txt)
    # FITUR BARU: uptime
    up = time.time() - bot.started_at
    h, m = divmod(int(up), 3600)
    m //= 60
    lines.append(f"\n⏱️ Uptime: **{h}j {m}m**")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# ------------------------------------------------------------------ rate-limited send
async def safe_send(channel, **kwargs):
    now = time.time()
    wait = _last_send_time[0] + MIN_SEND_GAP - now
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        await channel.send(**kwargs)
    except discord.HTTPException as e:
        if e.status == 429:
            retry = getattr(e, "retry_after", None) or 5.0
            log(f"[RATE] 429, tunggu {retry:.1f}s")
            await asyncio.sleep(retry)
            try:
                await channel.send(**kwargs)
            except discord.HTTPException as e2:
                log(f"[RATE] Gagal setelah retry: {e2}")
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

    # FITUR BARU: cooldown per-user
    now = time.time()
    for uid, user_lanes in per_user.items():
        last = _user_last_notify.get(uid, 0)
        if now - last < USER_NOTIFY_COOLDOWN:
            continue
        _user_last_notify[uid] = now

        for start in range(0, len(user_lanes), 10):
            chunk = user_lanes[start:start + 10]
            sdc = str(chunk[0].get("session_detail_code") or "")
            delta = deltas.get((code, sdc))
            await safe_send(
                channel,
                content=f"<@{uid}> 🔔 **Restock!**",
                embeds=[restock_embed(code, lane, delta) for lane in chunk],
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
        )
    if len(lanes) > 10:
        await safe_send(
            channel,
            content=f"…dan {len(lanes) - 10} sesi baru lainnya.",
        )


# --------------- SPAM KHUSUS 2 SHOOT ---------------
async def spam_loop_2shoot(code, lane, delta):
    key = (code, lane["session_detail_code"])
    sent = 0
    reason = "cap"

    try:
        channel = await get_channel()

        while sent < SPAM_MAX:
            with lock:
                quota_now = quota_state.get(key, 0)
                age = time.time() - last_report.get(code, 0)

            if quota_now <= 0:
                reason = "so"
                break
            if age > STALE_SECONDS:
                reason = "stale"
                break

            lane_now = {**lane, "available_quota": quota_now}
            await safe_send(
                channel,
                content=(
                    f"{vip_mention()} 🚨 **RESTOCK 2 SHOOT** · "
                    f"{lane['member_name']} · {lane['label']} "
                    f"({lane.get('session_label')}) · 📈 +{delta}"
                ),
                embed=restock_embed(code, lane_now, delta, vip=True),
                allowed_mentions=vip_allowed(),
            )
            sent += 1
            await asyncio.sleep(SPAM_INTERVAL)

        texts = {
            "so": f"🔴 **{lane['member_name']}** · {lane['label']} sold out kembali. "
                  f"Spam dihentikan ({sent}x).",
            "stale": f"⚠️ Spam **{lane['member_name']}** dihentikan: sumber data berhenti melapor.",
            "cap": f"⚠️ Spam **{lane['member_name']}** dihentikan di batas {SPAM_MAX}x, "
                   f"tiket masih tersedia.",
        }
        await safe_send(
            channel,
            content=f"{vip_mention()} {texts[reason]}",
            allowed_mentions=vip_allowed(),
        )
    except Exception:
        traceback.print_exc()
    finally:
        spam_tasks.pop(key, None)


def ensure_spam_2shoot(code, lane, delta):
    if code != "EX5B99":
        return
    key = (code, lane["session_detail_code"])
    if key in spam_tasks and not spam_tasks[key].done():
        return
    active = sum(1 for t in spam_tasks.values() if not t.done())
    if active >= MAX_CONCURRENT_SPAM:
        log(f"[SPAM] Skip {key}: sudah {active} task aktif")
        return
    spam_tasks[key] = asyncio.create_task(spam_loop_2shoot(code, lane, delta))


# ------------------------------------------------------------------ poller
class PollError(Exception):
    pass


def flatten_sessions(payload):
    lanes = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return lanes
    for sess in data:
        if not isinstance(sess, dict):
            continue
        for m in sess.get("session_members") or []:
            if not isinstance(m, dict) or not m.get("session_detail_code"):
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


async def fetch_event(http, code):
    headers = {
        "User-Agent": JKT48_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Referer": f"https://jkt48.com/purchase/exclusive?code={code}",
        **JKT48_EXTRA_HEADERS,
    }
    if JKT48_COOKIE:
        headers["Cookie"] = JKT48_COOKIE

    async with http.get(
        API_URL.format(code=code), headers=headers, proxy=JKT48_PROXY,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        text = await resp.text()
        if resp.status == 429:
            raise PollError("HTTP 429 (kena rate limit)")
        if resp.status in (401, 403):
            server = resp.headers.get("Server", "-")
            mitigated = resp.headers.get("cf-mitigated", "")
            snippet = " ".join(text.split())[:160]
            if mitigated or "just a moment" in text.lower() or "cloudflare" in text.lower():
                hint = "DIBLOKIR CLOUDFLARE"
            elif resp.status == 401 or "login" in text.lower() or "unauth" in text.lower():
                hint = "kemungkinan butuh login: isi JKT48_COOKIE"
            else:
                hint = "penyebab tidak jelas"
            log(f"[POLL] {code} HTTP {resp.status} server={server} "
                f"cf-mitigated={mitigated!r} body={snippet!r}")
            raise PollError(f"HTTP {resp.status} - {hint} (server={server})")
        if resp.status != 200:
            raise PollError(f"HTTP {resp.status}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise PollError("Respons bukan JSON")

    lanes = flatten_sessions(payload)
    if not lanes:
        msg = payload.get("message") if isinstance(payload, dict) else ""
        raise PollError(f"Tidak ada data jalur di respons ({str(msg)[:80]})")
    return lanes


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


async def poll_loop():
    await bot.wait_until_ready()
    log(f"[POLL] Aktif: {', '.join(POLL_EVENTS)} tiap ~{POLL_INTERVAL:.0f}s")
    fails = {c: 0 for c in POLL_EVENTS}
    alerted = set()

    while True:
        try:
            async with aiohttp.ClientSession() as http:
                while True:
                    extra_sleep = 0.0
                    for code in POLL_EVENTS:
                        try:
                            lanes = await fetch_event(http, code)
                            restocks, new_sessions, vip = process_report(code, lanes)
                            poll_status[code] = {
                                "ok": True, "at": time.time(), "error": "", "fails": 0
                            }
                            log(f"[POLL] {EVENTS[code]}: jalur={len(lanes)} "
                                f"restock={restocks} baru={new_sessions} vip={vip}")

                            if code in alerted:
                                alerted.discard(code)
                                await poll_alert(
                                    f"✅ Pemantauan **{EVENTS[code]}** pulih kembali."
                                )
                            fails[code] = 0
                        except asyncio.CancelledError:
                            raise
                        except Exception as error:
                            fails[code] += 1
                            reason = (
                                str(error) if isinstance(error, PollError)
                                else f"{type(error).__name__}: {error}"
                            )
                            poll_status[code] = {
                                "ok": False, "at": time.time(),
                                "error": reason, "fails": fails[code],
                            }
                            log(f"[POLL] {EVENTS[code]} gagal ({fails[code]}x): {reason}")
                            if "429" in reason:
                                extra_sleep = max(extra_sleep, 60.0)
                            if "403" in reason:
                                extra_sleep = max(
                                    extra_sleep,
                                    min(600.0, 30.0 * 2 ** (fails[code] - 1)),
                                )
                            if fails[code] >= POLL_FAIL_ALERT and code not in alerted:
                                alerted.add(code)
                                await poll_alert(
                                    f"⚠️ Pemantauan **{EVENTS[code]}** gagal "
                                    f"{fails[code]}x berturut-turut: {reason}. "
                                    f"Cek JKT48_COOKIE / akses server."
                                )
                        await asyncio.sleep(random.uniform(1.0, 2.5))

                    await asyncio.sleep(
                        POLL_INTERVAL + random.uniform(0, 3) + extra_sleep
                    )
        except Exception:
            # FITUR BARU: auto-restart poller jika crash
            log("[POLL] Poller crash, restart dalam 10s...")
            traceback.print_exc()
            await asyncio.sleep(10)


# ------------------------------------------------------------------ proses laporan
def process_report(code, lanes):
    restocks = []
    new_sessions = []
    vip_active = []
    deltas = {}
    now = time.time()

    with lock:
        first_scan = code not in baselined
        baselined.add(code)
        last_report[code] = now
        members = known_members.setdefault(code, set())

        for lane in lanes:
            sdc = str(lane.get("session_detail_code") or "").strip()
            quota = parse_quota(lane.get("available_quota"))
            name = str(lane.get("member_name") or "").strip()

            if not sdc or sdc == "Tidak diketahui" or quota is None:
                continue

            if name and name != "Tidak diketahui":
                members.add(name)

            key = (code, sdc)
            prev = quota_state.get(key)
            quota_state[key] = quota
            lane_state[key] = {**lane, "available_quota": quota}

            is_new_session = prev is None and not first_scan

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

            if is_restock:
                last = last_restock.get(key, 0)
                if now - last >= RESTOCK_COOLDOWN:
                    restocks.append(lane)
                    deltas[key] = delta
                    last_restock[key] = now
                    # FITUR BARU: simpan history
                    restock_history[code].append({
                        "at": now, "member": name,
                        "lane": lane.get("label"), "delta": delta,
                        "session": lane.get("session_label"),
                    })
                    restock_history[code] = restock_history[code][-200:]

                    if code == "EX5B99" and is_vip(code, lane):
                        vip_active.append((lane, delta))

            if is_new_session and quota > 0:
                new_sessions.append(lane)

    if bot.main_loop is None or not bot.is_ready():
        return len(restocks), len(new_sessions), len(vip_active)

    if code == "EX5B99":
        if restocks:
            asyncio.run_coroutine_threadsafe(
                notify_subscribers(code, restocks, deltas), bot.main_loop
            )
        if new_sessions:
            asyncio.run_coroutine_threadsafe(
                notify_new_sessions(code, new_sessions), bot.main_loop
            )
        for lane, delta in vip_active:
            bot.main_loop.call_soon_threadsafe(
                ensure_spam_2shoot, code, dict(lane), delta
            )
    elif code == "EX24AE":
        if restocks or new_sessions:
            combined = restocks + [l for l in new_sessions if l not in restocks]
            if combined:
                asyncio.run_coroutine_threadsafe(
                    notify_subscribers(code, combined, deltas), bot.main_loop
                )

    return len(restocks), len(new_sessions), len(vip_active)


def record_remote_poll(code, error=""):
    prev = poll_status.get(code) or {}
    fails = prev.get("fails", 0) + 1 if error else 0
    poll_status[code] = {
        "ok": not error, "at": time.time(), "error": error, "fails": fails,
    }

    if bot.main_loop is None or not bot.is_ready():
        return
    if error and fails == POLL_FAIL_ALERT:
        text = f"⚠️ Worker gagal mengambil **{EVENTS[code]}** {fails}x berturut-turut: {error}"
    elif not error and prev.get("fails", 0) >= POLL_FAIL_ALERT:
        text = f"✅ Pemantauan **{EVENTS[code]}** pulih kembali."
    else:
        return
    asyncio.run_coroutine_threadsafe(poll_alert(text), bot.main_loop)


async def save_state_loop():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        save_state()


# ------------------------------------------------------------------ dashboard API
def snapshot(compact=False):
    now = time.time()
    with lock:
        events = {}
        for code, name in EVENTS.items():
            lanes = []
            for (c, sdc), v in lane_state.items():
                if c != code:
                    continue
                if compact:
                    lanes.append({
                        "m": v.get("member_name"), "l": v.get("label"),
                        "q": parse_quota(v.get("available_quota")) or 0,
                        "s": sdc, "se": v.get("session_label"),
                    })
                else:
                    lanes.append({
                        "member": v.get("member_name"), "lane": v.get("label"),
                        "quota": parse_quota(v.get("available_quota")) or 0,
                        "price": v.get("price"), "sdc": sdc,
                        "session": v.get("session_label"),
                        "date": v.get("session_date"),
                        "start": hhmm(v.get("session_start_time")),
                        "end": hhmm(v.get("session_end_time")),
                        "restock_at": last_restock.get((c, sdc)),
                        "vip": is_vip(code, v),
                    })
            events[code] = {
                "name": name, "updated": last_report.get(code), "lanes": lanes,
            }
    if compact:
        return {"now": now, "events": events}
    return {
        "now": now, "stale_after": STALE_SECONDS, "events": events,
        "poller": {"enabled": POLL_ENABLED, "status": poll_status},
    }


# FITUR BARU: statistik global
def stats_snapshot():
    with lock:
        total_lanes = len(lane_state)
        total_restock = sum(len(v) for v in restock_history.values())
        per_event = {c: len(restock_history.get(c, [])) for c in EVENTS}
    return {
        "uptime_seconds": time.time() - bot.started_at,
        "total_lanes": total_lanes,
        "total_restock_events": total_restock,
        "restock_per_event": per_event,
        "poll_status": poll_status,
    }


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # FITUR BARU: senyapkan log HTTP default

    def send_json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_SIZE:
            return None, "Ukuran payload tidak valid."
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return None, f"JSON tidak valid: {e}"
        if not isinstance(data, dict):
            return None, "Payload harus JSON object."
        return data, None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Notify-Secret, X-Ingest-Token")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        if url.path == "/health":
            return self.send_json(200, {
                "ok": True, "service": "jkt48-notifier",
                "poller": {"enabled": POLL_ENABLED, "events": POLL_EVENTS,
                           "status": poll_status},
            })

        if url.path == "/api/stats":  # FITUR BARU
            if DASHBOARD_KEY:
                given = (qs.get("key") or [self.headers.get("X-Dashboard-Key", "")])[0]
                if not hmac.compare_digest(given, DASHBOARD_KEY):
                    return self.send_json(401, {"ok": False, "error": "Key salah."})
            return self.send_json(200, stats_snapshot())

        if DASHBOARD_KEY:
            given = (qs.get("key") or [self.headers.get("X-Dashboard-Key", "")])[0]
            if not hmac.compare_digest(given, DASHBOARD_KEY):
                return self.send_json(401, {"ok": False, "error": "Key dashboard salah."})

        if url.path == "/api/lanes":
            compact = qs.get("compact", ["0"])[0] in ("1", "true", "yes")
            return self.send_json(200, snapshot(compact=compact))

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

    def _process_event_payload(self, code, page_url, lanes, remote_error):
        """Shared handler untuk /notify dan /ingest."""
        if code not in EVENTS:
            return 400, {"ok": False, "error": f"Kode event tidak diizinkan: {code}"}
        if not page_url.startswith("https://jkt48.com/purchase/exclusive"):
            return 400, {"ok": False, "error": "URL halaman tidak diizinkan."}
        if remote_error:
            record_remote_poll(code, " ".join(str(remote_error).split())[:200])
            return 200, {"ok": True, "code": code, "recorded": "error"}
        if not isinstance(lanes, list) or len(lanes) > 1000:
            return 400, {"ok": False, "error": "Daftar jalur tidak valid."}

        lanes = [l for l in lanes if isinstance(l, dict)]
        restocks, new_sessions, vip = process_report(code, lanes)
        record_remote_poll(code)
        log(f"[JKT48] {EVENTS[code]}: jalur={len(lanes)} restock={restocks} "
            f"baru={new_sessions} vip={vip}")
        return 200, {
            "ok": True, "code": code, "laneCount": len(lanes),
            "restocks": restocks, "newSessions": new_sessions, "vipActive": vip,
        }

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/notify":
            secret = self.headers.get("X-Notify-Secret", "")
            if not NOTIFY_SECRET or not hmac.compare_digest(secret, NOTIFY_SECRET):
                return self.send_json(401, {"ok": False, "error": "Unauthorized."})
        elif path == "/ingest":  # FITUR BARU
            if INGEST_TOKEN:
                token = (
                    self.headers.get("X-Ingest-Token", "")
                    or (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
                )
                if not hmac.compare_digest(token, INGEST_TOKEN):
                    return self.send_json(401, {"ok": False, "error": "Ingest token salah."})
        else:
            return self.send_json(404, {"ok": False, "error": "Endpoint tidak ditemukan."})

        try:
            data, err = self._read_json()
            if err:
                return self.send_json(400, {"ok": False, "error": err})

            code = str(data.get("code") or "").strip().upper()
            page_url = str(data.get("pageUrl") or "")
            lanes = data.get("lanes")
            remote_error = data.get("error")

            status, body = self._process_event_payload(
                code, page_url, lanes, remote_error
            )
            self.send_json(status, body)
        except Exception as error:
            traceback.print_exc()
            self.send_json(500, {
                "ok": False,
                "error": f"{type(error).__name__}: {str(error)[:300]}",
            })


def run_http():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"[JKT48] Notifier aktif di http://{HOST}:{PORT}/notify")
    log(f"[JKT48] Ingest endpoint: http://{HOST}:{PORT}/ingest")
    log(f"[JKT48] Dashboard di http://{HOST}:{PORT}/")
    server.serve_forever()


def main():
    if not TOKEN or not CHANNEL_ID or not NOTIFY_SECRET:
        raise SystemExit(
            "Set DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, dan NOTIFY_SECRET terlebih dahulu."
        )

    if not SUBS_FILE.exists() and SEED_FILE.exists() and SEED_FILE != SUBS_FILE:
        SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUBS_FILE.write_text(SEED_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    load_state()

    if not VIP_USER_ID:
        log("[WARNING] VIP_USER_ID belum diatur.")

    if not DASHBOARD_FILE.is_file():
        log(f"[WARNING] dashboard.html tidak ditemukan di {DASHBOARD_FILE}")

    threading.Thread(target=run_http, daemon=True).start()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()