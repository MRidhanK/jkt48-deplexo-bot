# JKT48 Ticket Radar - deploy ke Deplexo

Struktur:
- `server/`     : bot Discord + server HTTP (dideploy ke Deplexo)
- `extension/`  : ekstensi Chrome (dipasang di browser, TIDAK ikut deploy)
- `Dockerfile`  : dipakai Deplexo untuk membangun container

## 0. Amankan token (WAJIB)
1. Discord Developer Portal -> aplikasi bot -> Bot -> Reset Token. Simpan token baru.
2. Token lama di README lamamu dianggap bocor. Jangan tulis token di file yang masuk Git.

## 1. Buat NOTIFY_SECRET
    python -c "import secrets; print(secrets.token_urlsafe(32))"
Simpan hasilnya. Nilai yang sama dipakai di Deplexo dan di ekstensi.

## 2. Upload ke GitHub (repo PRIVAT)
Isi repo = isi folder ini (Dockerfile, server/, extension/ boleh ikut).
    git init
    git add .
    git commit -m "jkt48 notifier"
    git branch -M main
    git remote add origin https://github.com/USERNAME/REPO.git
    git push -u origin main
Cek dulu: tidak ada file berisi token di repo.

## 3. Deploy di Deplexo
1. Login ke deplexo.com dengan GitHub, pilih repo tadi.
2. Deplexo mendeteksi Dockerfile dan membangun container.
3. Isi environment variable di dashboard:
   - DISCORD_BOT_TOKEN  (token baru)
   - DISCORD_CHANNEL_ID
   - DISCORD_GUILD_ID
   - VIP_USER_ID
   - NOTIFY_SECRET
   - PORT (hanya jika Deplexo meminta port tertentu; default 8765)
   - SUBS_FILE=/data/subscriptions.json (hanya jika Deplexo menyediakan volume di /data)
4. Deploy. Buka subdomain yang diberikan di browser: harus tampil
   {"ok": true, "service": "jkt48-notifier"}
5. Di log harus ada: "Bot aktif sebagai ...".
   Matikan bot di laptop dulu supaya tidak jalan dobel.

## 4. Pasang ekstensi
1. Edit extension/background.js:
   - NOTIFIER_URL  = "https://SUBDOMAIN-DEPLEXO/notify"
   - NOTIFY_SECRET = "secret yang sama"
2. Edit extension/manifest.json: ganti GANTI-SUBDOMAIN-DEPLEXO dengan subdomain yang sama.
3. chrome://extensions -> aktifkan Developer mode -> Load unpacked -> pilih folder extension/
   (atau tekan Reload jika sudah terpasang).
4. Buka halaman jkt48.com/purchase/exclusive. Log di Deplexo harus menampilkan baris
   "[JKT48] ...: jalur=... restock=... vip_aktif=...".

## 5. Tes
- Di Discord: /daftar, /pantau, /berhenti harus muncul dan menjawab.
- Kalau ekstensi dapat 401: NOTIFY_SECRET tidak sama.
- Kalau ekstensi tidak bisa menghubungi server: cek URL (harus https) dan manifest.

## Catatan
- Ekstensi tetap butuh Chrome terbuka di halaman jkt48.com.
- Tanpa volume persisten, hasil /pantau bisa hilang saat container restart/redeploy
  dan kembali ke server/subscriptions.json.
