"""
JKT48 Ticket Radar - notifier berbasis bot Discord.

- Hanya mengirim notifikasi RESTOCK (kuota 0 -> >0).
- Slash command: /pantau, /berhenti, /daftar
- Member VIP: ping berulang sampai sold out kembali.

Kebutuhan:  pip install -U discord.py
Environment:
  DISCORD_BOT_TOKEN   token bot (wajib)
  DISCORD_CHANNEL_ID  ID channel tujuan notifikasi (wajib)
  VIP_USER_ID         ID numerik akun yang di-ping berulang (wajib agar benar-benar ter-ping)
  NOTIFY_SECRET       kunci rahasia yang harus dikirim ekstensi (wajib)
  PORT                port HTTP (default 8765)
  SUBS_FILE           lokasi subscriptions.json (opsional, mis. /data/subscriptions.json)
  DISCORD_GUILD_ID    (opsional) ID server, supaya command langsung muncul
  SPAM_INTERVAL       detik antar ping VIP (default 4)
  SPAM_MAX            maksimal ping per restock per jalur (default 100)
"""
import asyncio
import hmac
import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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

subs_lock = threading.Lock()


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


@bot.tree.command(name="pantau", description="Notifikasi saat tiket member restock")
@app_commands.describe(member="Nama member (atau 'semua')", event="Event yang dipantau")
@app_commands.choices(event=EVENT_CHOICES)
@app_commands.autocomplete(member=member_autocomplete)
async def pantau(interaction: discord.Interaction, member: str,
                 event: app_commands.Choice[str] = None):
    key = "*" if norm(member) in ("semua", "*", "all") else norm(member)
    ev = event.value if event else "*"
    uid = str(interaction.user.id)

    with subs_lock:
        data = load_subs()
        items = data.setdefault(uid, [])
        entry = {"member": key, "event": ev}
        if entry not in items:
            items.append(entry)
        save_subs(data)

    ev_name = "semua event" if ev == "*" else EVENTS[ev]
    who = "semua member" if key == "*" else member
    await interaction.response.send_message(
        f"✅ Kamu akan di-mention saat **{who}** restock di **{ev_name}**.",
        ephemeral=True,
    )


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


async def notify_restocks(code, lanes):
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
            "stale": f"⚠️ Ping **{lane['member_name']}** dihentikan: extension berhenti melapor "
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


# ------------------------------------------------------------------ proses laporan
def process_report(code, lanes):
    restocks = []
    vip_active = []

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

            if quota > 0:
                if prev == 0 or (prev is None and not first_scan):
                    restocks.append(lane)
                if is_vip(code, lane):
                    vip_active.append(lane)

    if bot.main_loop is None or not bot.is_ready():
        return len(restocks), len(vip_active)

    if restocks:
        asyncio.run_coroutine_threadsafe(notify_restocks(code, restocks), bot.main_loop)

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
        self.send_json(200, {"ok": True, "service": "jkt48-notifier"})

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