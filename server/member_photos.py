"""
Foto member untuk dashboard JKT48 Ticket Radar.

Taruh file ini di folder yang sama dengan jkt48_notifier.py.
Foto dibaca dari folder `members/` (nama file = nama panggilan, mis. nayla.png).

Cara cocok:
  1. PHOTO_ALIASES (manual) -> dipakai lebih dulu.
  2. Otomatis: salah satu kata di nama lengkap member sama persis dengan
     nama file (tanpa ekstensi). Kata pertama dicoba lebih dulu.
"""
import os
from pathlib import Path
from urllib.parse import quote

# Urutan prioritas bila satu member punya beberapa file (mis. alya.jpg dan alya.png).
ALLOWED_EXT = (".jpg", ".jpeg", ".webp", ".png")

# Isi untuk member yang nama panggilannya TIDAK ada di nama lengkapnya.
# Format:  "nama lengkap persis seperti di jkt48.com": "nama file tanpa ekstensi"
PHOTO_ALIASES = {
    # "Nama Lengkap Member": "namafile",
}

CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
}


def _norm(text):
    return " ".join(str(text or "").split()).casefold()


_ALIASES = {_norm(k): str(v).strip().casefold() for k, v in PHOTO_ALIASES.items()}


def _resolve_members_dir() -> Path:
    env_path = os.environ.get("MEMBERS_DIR", "").strip()
    if env_path:
        p = Path(env_path)
        if p.is_dir():
            return p
        print(f"[WARN] MEMBERS_DIR={env_path} tidak ditemukan, fallback ke pencarian otomatis.")
    here = Path(__file__).resolve().parent
    candidates = [
        here / "members",
        here / "server" / "members",
        here.parent / "server" / "members",
        here.parent / "members",
        Path.cwd() / "members",
        Path.cwd() / "server" / "members",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


MEMBERS_DIR = _resolve_members_dir()
_cache = {"mtime": None, "by_stem": {}, "files": set()}


def _scan():
    """Daftar file foto. Dibaca ulang otomatis kalau isi folder berubah."""
    try:
        mtime = MEMBERS_DIR.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, by_stem={}, files=set())
        return _cache
    if _cache["mtime"] == mtime:
        return _cache
    by_stem, files = {}, set()
    try:
        entries = [f for f in MEMBERS_DIR.iterdir() if f.is_file()]
    except OSError:
        entries = []
    for ext in ALLOWED_EXT:  # ekstensi yang lebih awal = prioritas lebih tinggi
        for f in entries:
            if f.suffix.lower() == ext:
                files.add(f.name)
                by_stem.setdefault(f.stem.casefold(), f.name)
    _cache.update(mtime=mtime, by_stem=by_stem, files=files)
    return _cache


print(f"[INIT] Folder foto member: {MEMBERS_DIR} "
      f"(ada={MEMBERS_DIR.is_dir()}, foto={len(_scan()['by_stem'])})")


def photo_file(name):
    """Nama file foto untuk seorang member, atau None."""
    idx = _scan()
    key = _norm(name)
    alias = _ALIASES.get(key)
    if alias:
        f = idx["by_stem"].get(alias)
        if f:
            return f
    for token in key.split():
        f = idx["by_stem"].get(token)
        if f:
            return f
    return None


def photos_for(names):
    """{nama member (sudah dinormalisasi): url foto} untuk dikirim ke dashboard."""
    out = {}
    for name in names:
        f = photo_file(name)
        if f:
            out[_norm(name)] = "/members/" + quote(f)
    return out


def read_photo(filename):
    """(isi file, content-type) atau None. Hanya file yang ada di daftar yang boleh dibaca."""
    idx = _scan()
    if filename not in idx["files"]:
        return None
    try:
        data = (MEMBERS_DIR / filename).read_bytes()
    except OSError:
        return None
    return data, CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def check(names):
    """Laporan pencocokan: siapa yang sudah punya foto, siapa belum, foto mana yang tak terpakai."""
    idx = _scan()
    matched, missing = {}, []
    for n in sorted(set(names)):
        f = photo_file(n)
        if f:
            matched[n] = f
        else:
            missing.append(n)
    used = set(matched.values())
    unused = sorted(stem for stem, f in idx["by_stem"].items() if f not in used)
    return {
        "dir": str(MEMBERS_DIR),
        "dir_exists": MEMBERS_DIR.is_dir(),
        "photo_count": len(idx["by_stem"]),
        "matched": matched,
        "missing": missing,
        "unused_photos": unused,
        "hint": 'Untuk member di "missing", isi PHOTO_ALIASES di member_photos.py '
                '("Nama Lengkap": "namafile") dengan file dari "unused_photos".',
    }