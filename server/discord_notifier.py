import asyncio
import hmac
import json
import os
import random
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
NOTIFY_SECRET = os.environ.get("NOTIFY_SECRET", "").strip()
MAX_BODY_SIZE = 500_000

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0") or 0)
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)
VIP_USER_ID = os.environ.get("VIP_USER_ID", "").strip()
VIP_FALLBACK_TEXT = "@muhammadridhankhoirullah"
SPAM_INTERVAL = float(os.environ.get("SPAM_INTERVAL", "4"))
SPAM_MAX = int(os.environ.get("SPAM_MAX", "100"))
STALE_SECONDS = 150  # hentikan ping jika extension berhenti melapor

EVENTS = {"EX5B99": "2 Shoot", "EX24AE": "MNG"}

# ------------------------------------------------------------------ poller server-side
# Server memanggil API JKT48 sendiri, jadi tetap jalan walau laptop/browser mati.
POLL_ENABLED = os.environ.get("POLL_ENABLED", "1") != "0"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "20"))        # detik antar putaran
POLL_FAIL_ALERT = int(os.environ.get("POLL_FAIL_ALERT", "5"))       # gagal berturut-turut -> alert
POLL_EVENTS = [
    c.strip().upper()
    for c in os.environ.get("POLL_EVENTS", ",".join(EVENTS)).split(",")
    if c.strip().upper() in EVENTS
]
API_URL = os.environ.get(
    "JKT48_API_URL", "https://jkt48.com/api/v1/exclusives/{code}/bonus?lang=id"
)
# Isi jika API butuh login: salin header Cookie dari DevTools (Network -> request bonus).
JKT48_COOKIE = os.environ.get("JKT48_COOKIE", "").strip()
JKT48_USER_AGENT = os.environ.get(
    "JKT48_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
# Proxy opsional (mis. http://user:pass@host:port) jika IP server diblokir.
JKT48_PROXY = os.environ.get("JKT48_PROXY", "").strip() or None
# Header tambahan (mis. Authorization / X-CSRF-TOKEN) dalam bentuk JSON object.
try:
    JKT48_EXTRA_HEADERS = json.loads(os.environ.get("JKT48_EXTRA_HEADERS", "") or "{}")
except json.JSONDecodeError:
    JKT48_EXTRA_HEADERS = {}

# Member VIP: di-ping berulang saat restock, untuk 2 Shoot dan MNG.
VIP_NAMES = [
    "Fiony Alveria", "Aurhel Alana", "Michelle Alexandra",
    "Hillary Abigail", "Adeline Wijaya", "Oline Manuel",
    "Abigail Rachel", "Catherina Vallencia", "Jacqueline Immanuela",
    "Nur Intan", "Putry Jazyta", "Astrella Virgiananda",
]

VIP_MEMBERS = {
    "EX5B99": VIP_NAMES,  # 2 Shoot
    "EX24AE": VIP_NAMES,  # MNG
}

SEED_FILE = Path(__file__).with_name("subscriptions.json")
SUBS_FILE = Path(os.environ.get("SUBS_FILE") or SEED_FILE)

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
quota_state = {}      # (code, session_detail_code) -> quota
baselined = set()     # code yang sudah pernah dipindai
last_report = {}      # code -> epoch terakhir menerima laporan
known_members = {}    # code -> set nama member
spam_tasks = {}       # (code, session_detail_code) -> asyncio.Task
lane_state = {}       # (code, session_detail_code) -> data jalur terakhir (untuk cek stok)

subs_lock = threading.Lock()
poll_status = {}      # code -> {"ok": bool, "at": epoch, "error": str, "fails": int}


def load_subs():
    try:
        return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_subs(data):
    tmp = SUBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SUBS_FILE)


# ------------------------------------------------------------------ embeds
def restock_embed(code, lane):
    quota = parse_quota(lane.get("available_quota"))
    return discord.Embed(
        title=f"🟢 RESTOCK · {lane.get('member_name')}",
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

    async def setup_hook(self):
        self.main_loop = asyncio.get_running_loop()
        if POLL_ENABLED and POLL_EVENTS:
            self.poll_task = asyncio.create_task(poll_loop())
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
    names = set()
    for group in known_members.values():
        names.update(group)
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


STOCK_CHUNK = 3800   # batas karakter deskripsi per embed
STOCK_MAX_EMBEDS = 5


def stock_pages(lanes):
    """Susun baris stok, lalu pecah jadi beberapa halaman."""
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
            f"selesai memindai, lalu coba lagi.",
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


async def notify_restocks(code, lanes, new_sessions=None):
    """Mention subscriber biasa. Ping VIP ditangani spam_loop."""
    channel = await get_channel()
    subs = load_subs()
    new_sessions = new_sessions or []
    new_session_keys = {(l.get("session_detail_code"), norm(l.get("member_name"))) for l in new_sessions}

    per_user = {}
    for lane in lanes:
        name = norm(lane.get("member_name"))
        is_new = (lane.get("session_detail_code"), name) in new_session_keys

        for uid, items in subs.items():
            if uid == VIP_USER_ID and is_vip(code, lane):
                continue  # sudah dapat ping berulang
            for item in items:
                if item["event"] not in ("*", code):
                    continue
                # Cocokkan member
                if item["member"] in ("*", name) or (
                    item["member"] != "*" and item["member"] in name
                ):
                    per_user.setdefault(uid, []).append(lane)
                    break

    # Untuk 2 Shoot: kirim juga notifikasi sesi baru ke channel umum
    # (tanpa mention user tertentu, atau mention VIP)
    if code == "EX5B99" and new_sessions:
        # Kirim notifikasi sesi baru ke channel (tanpa mention subscriber)
        for lane in new_sessions:
            if is_vip(code, lane):
                continue  # VIP sudah ditangani spam_loop
            await channel.send(
                content=f"🆕 **Sesi/Jalur baru terdeteksi di 2 Shoot!**",
                embed=restock_embed(code, lane),
            )

    for uid, user_lanes in per_user.items():
        for start in range(0, len(user_lanes), 10):
            chunk = user_lanes[start:start + 10]
            await channel.send(
                content=f"<@{uid}> 🔔 **Restock!**",
                embeds=[restock_embed(code, lane) for lane in chunk],
                allowed_mentions=discord.AllowedMentions(
                    users=[discord.Object(id=int(uid))]
                ),
            )
    """Mention subscriber biasa. Ping VIP ditangani spam_loop."""
    channel = await get_channel()
    subs = load_subs()

    per_user = {}
    for lane in lanes:
        name = norm(lane.get("member_name"))
        for uid, items in subs.items():
            if uid == VIP_USER_ID and is_vip(code, lane):
                continue  # sudah dapat ping berulang
            for item in items:
                if item["event"] not in ("*", code):
                    continue
                if item["member"] in ("*", name) or (
                    item["member"] != "*" and item["member"] in name
                ):
                    per_user.setdefault(uid, []).append(lane)
                    break

    for uid, user_lanes in per_user.items():
        for start in range(0, len(user_lanes), 10):
            chunk = user_lanes[start:start + 10]
            await channel.send(
                content=f"<@{uid}> 🔔 **Restock!**",
                embeds=[restock_embed(code, lane) for lane in chunk],
                allowed_mentions=discord.AllowedMentions(
                    users=[discord.Object(id=int(uid))]
                ),
            )


async def spam_loop(code, lane):
    key = (code, lane["session_detail_code"])
    sent = 0
    reason = "cap"

    try:
        channel = await get_channel()

        while sent < SPAM_MAX:
            with lock:
                quota = quota_state.get(key, 0)
                age = time.time() - last_report.get(code, 0)

            if quota <= 0:
                reason = "so"
                break
            if age > STALE_SECONDS:
                reason = "stale"
                break

            lane_now = {**lane, "available_quota": quota}
            await channel.send(
                content=(
                    f"{vip_mention()} 🚨 **RESTOCK {EVENTS.get(code, code)}** · "
                    f"{lane['member_name']} · {lane['label']} ({lane.get('session_label')})"
                ),
                embed=restock_embed(code, lane_now),
                allowed_mentions=vip_allowed(),
            )
            sent += 1
            await asyncio.sleep(SPAM_INTERVAL)

        texts = {
            "so": f"🔴 **{lane['member_name']}** · {lane['label']} "
                  f"({EVENTS.get(code, code)}, {lane.get('session_label')}) sold out kembali. "
                  f"Ping dihentikan ({sent}x).",
            "stale": f"⚠️ Ping **{lane['member_name']}** dihentikan: sumber data berhenti melapor "
                     f"(status terakhir masih tersedia).",
            "cap": f"⚠️ Ping **{lane['member_name']}** dihentikan di batas {SPAM_MAX}x, "
                   f"tiket masih tersedia.",
        }
        await channel.send(
            content=f"{vip_mention()} {texts[reason]}",
            allowed_mentions=vip_allowed(),
        )
    except Exception:
        traceback.print_exc()
    finally:
        spam_tasks.pop(key, None)


def ensure_spam(code, lane):
    key = (code, lane["session_detail_code"])
    if key in spam_tasks and not spam_tasks[key].done():
        return
    spam_tasks[key] = asyncio.create_task(spam_loop(code, lane))


# ------------------------------------------------------------------ poller
class PollError(Exception):
    pass


def flatten_sessions(payload):
    """Ubah respons API (data[].session_members[]) menjadi daftar jalur datar."""
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
                hint = "DIBLOKIR CLOUDFLARE (IP server/challenge), cookie biasa tidak cukup"
            elif resp.status == 401 or "login" in text.lower() or "unauth" in text.lower():
                hint = "kemungkinan butuh login: isi JKT48_COOKIE"
            else:
                hint = "penyebab tidak jelas"
            print(f"[POLL] {code} HTTP {resp.status} server={server} cf-mitigated={mitigated!r} body={snippet!r}")
            raise PollError(f"HTTP {resp.status} - {hint} (server={server})")
        if resp.status != 200:
            raise PollError(f"HTTP {resp.status}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise PollError("Respons bukan JSON (kemungkinan halaman verifikasi/Cloudflare)")

    lanes = flatten_sessions(payload)
    if not lanes:
        msg = payload.get("message") if isinstance(payload, dict) else ""
        raise PollError(f"Tidak ada data jalur di respons ({str(msg)[:80]})")
    return lanes


async def poll_alert(text):
    try:
        channel = await get_channel()
        await channel.send(content=f"{vip_mention()} {text}", allowed_mentions=vip_allowed())
    except Exception:
        traceback.print_exc()


async def poll_loop():
    await bot.wait_until_ready()
    print(f"[POLL] Aktif: {', '.join(POLL_EVENTS)} tiap ~{POLL_INTERVAL:.0f}s")
    fails = {c: 0 for c in POLL_EVENTS}
    alerted = set()

    async with aiohttp.ClientSession() as http:
        while True:
            extra_sleep = 0.0
            for code in POLL_EVENTS:
                try:
                    lanes = await fetch_event(http, code)
                    restocks, vip = process_report(code, lanes)
                    poll_status[code] = {"ok": True, "at": time.time(), "error": "", "fails": 0}
                    print(f"[POLL] {EVENTS[code]}: jalur={len(lanes)} restock={restocks} vip_aktif={vip}")

                    if code in alerted:
                        alerted.discard(code)
                        await poll_alert(f"✅ Pemantauan **{EVENTS[code]}** pulih kembali.")
                    fails[code] = 0
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    fails[code] += 1
                    reason = str(error) if isinstance(error, PollError) else f"{type(error).__name__}: {error}"
                    poll_status[code] = {"ok": False, "at": time.time(), "error": reason, "fails": fails[code]}
                    print(f"[POLL] {EVENTS[code]} gagal ({fails[code]}x): {reason}")
                    if "429" in reason:
                        extra_sleep = max(extra_sleep, 60.0)
                    if fails[code] >= POLL_FAIL_ALERT and code not in alerted:
                        alerted.add(code)
                        await poll_alert(
                            f"⚠️ Pemantauan **{EVENTS[code]}** gagal {fails[code]}x berturut-turut: "
                            f"{reason}. Cek JKT48_COOKIE / akses server."
                        )
                await asyncio.sleep(random.uniform(1.0, 2.5))  # jeda kecil antar event

            await asyncio.sleep(POLL_INTERVAL + random.uniform(0, 3) + extra_sleep)


# ------------------------------------------------------------------ proses laporan
def process_report(code, lanes):
    restocks = []
    vip_active = []
    new_sessions = []  # jalur/sesi baru yang belum pernah terdeteksi

    with lock:
        first_scan = code not in baselined
        baselined.add(code)
        last_report[code] = time.time()
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

            # Deteksi jalur/sesi baru (belum pernah terdeteksi)
            is_new_session = prev is None and not first_scan

            if quota > 0:
                # Restock: kuota naik dari 0, atau sesi baru dengan kuota > 0
                if prev == 0 or is_new_session:
                    restocks.append(lane)
                if is_vip(code, lane):
                    vip_active.append(lane)

            if is_new_session:
                new_sessions.append(lane)

    if bot.main_loop is None or not bot.is_ready():
        return len(restocks), len(vip_active)

    # Filter notifikasi berdasarkan aturan event
    if code == "EX24AE":
        # MNG: hanya kirim jika ada penambahan tiket (restock) atau sesi baru
        if restocks or new_sessions:
            asyncio.run_coroutine_threadsafe(
                notify_restocks(code, restocks, new_sessions), bot.main_loop
            )
    else:
        # 2 Shoot: kirim restock biasa + sesi baru (walau member tidak dipilih)
        if restocks or new_sessions:
            asyncio.run_coroutine_threadsafe(
                notify_restocks(code, restocks, new_sessions), bot.main_loop
            )

    for lane in vip_active:
        bot.main_loop.call_soon_threadsafe(ensure_spam, code, dict(lane))

    return len(restocks), len(vip_active)

# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[HTTP]", fmt % args)

    def send_json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        # Health check untuk platform hosting.
        self.send_json(200, {
            "ok": True, "service": "jkt48-notifier",
            "poller": {"enabled": POLL_ENABLED, "events": POLL_EVENTS, "status": poll_status},
        })

    def do_POST(self):
        secret = self.headers.get("X-Notify-Secret", "")
        if not NOTIFY_SECRET or not hmac.compare_digest(secret, NOTIFY_SECRET):
            return self.send_json(401, {"ok": False, "error": "Unauthorized."})

        if urlparse(self.path).path != "/notify":
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
            if not isinstance(lanes, list) or len(lanes) > 1000:
                return self.send_json(400, {"ok": False, "error": "Daftar jalur tidak valid."})

            lanes = [l for l in lanes if isinstance(l, dict)]
            restocks, vip = process_report(code, lanes)

            print(f"[JKT48] {EVENTS[code]}: jalur={len(lanes)} restock={restocks} vip_aktif={vip}")
            self.send_json(200, {
                "ok": True, "code": code, "laneCount": len(lanes),
                "restocks": restocks, "vipActive": vip,
            })
        except Exception as error:
            traceback.print_exc()
            self.send_json(500, {"ok": False, "error": f"{type(error).__name__}: {str(error)[:300]}"})


def run_http():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[JKT48] Notifier aktif di http://{HOST}:{PORT}/notify")
    server.serve_forever()


def main():
    if not TOKEN or not CHANNEL_ID or not NOTIFY_SECRET:
        raise SystemExit("Set DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, dan NOTIFY_SECRET terlebih dahulu.")

    # Salin data awal ke lokasi penyimpanan jika belum ada.
    if not SUBS_FILE.exists() and SEED_FILE.exists() and SEED_FILE != SUBS_FILE:
        SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUBS_FILE.write_text(SEED_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    if not VIP_USER_ID:
        print("[WARNING] VIP_USER_ID belum diatur: tag VIP tidak akan benar-benar mem-ping.")

    threading.Thread(target=run_http, daemon=True).start()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()