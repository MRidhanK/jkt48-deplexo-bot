/* JKT48 History Exporter — jalankan di DevTools Console saat sedang login di halaman riwayat My Page.
 * Hanya membaca tabel/daftar yang dirender pada halaman aktif. Tidak membaca cookie/token,
 * tidak memanggil endpoint tersembunyi, dan tidak mengirim data ke server mana pun.
 * Jalankan lagi pada halaman riwayat berbeda untuk mengekspor halaman tersebut.
 */
(() => {
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  const tables = [...document.querySelectorAll('table')].map((table, ti) => {
    const rows = [...table.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(td => norm(td.innerText || td.textContent))).filter(r => r.some(Boolean));
    if (!rows.length) return null;
    const hasHeader = table.querySelector('thead tr') || table.querySelector('tr th');
    const headers = hasHeader ? rows.shift() : rows[0].map((_, i) => `kolom_${i+1}`);
    return { table_index: ti, headers, rows: rows.map(cells => ({ cells, raw_text: cells.join(' | ') })) };
  }).filter(Boolean);
  const lists = [...document.querySelectorAll('[role="row"], .history-item, .transaction-item, li')]
    .map((el, i) => ({ row_index: i, raw_text: norm(el.innerText || el.textContent) }))
    .filter(x => x.raw_text && x.raw_text.length > 8)
    .filter((x, i, a) => a.findIndex(y => y.raw_text === x.raw_text) === i)
    .slice(0, 1000);
  const transactions = [];
  const guessCategory = text => {
    const t = String(text || '').toLowerCase();
    if (/meet\s*(?:and|&)\s*greet|personal meet|photocard|m\s*&\s*g|\bmng\b/.test(t)) return 'MNG';
    if (/2\s*[- ]?shot/.test(t)) return '2SHOT';
    if (/video\s*call|virtual\s*call|\bvc\b/.test(t)) return 'VC';
    if (/theater|teater|pertunjukan|smiles come to you/.test(t)) return 'THEATER';
    if (/point|poin|top.?up/.test(t)) return 'POINT';
    if (/merch|product|produk|goods/.test(t)) return 'PRODUCT';
    return 'OTHER';
  };
  for (const table of tables) {
    const headers = table.headers || [];
    for (const row of table.rows || []) {
      const cells = row.cells || [];
      const o = { raw_text: row.raw_text || cells.join(' | '), source_page: location.href };
      headers.forEach((header, i) => {
        const h = norm(header).toLowerCase(); const value = norm(cells[i]);
        if (!value) return;
        if (/^sesi|session/.test(h)) o.session_label = value;
        if (/tanggal|date|waktu|created/.test(h)) o.date = value;
        if (/nominal|amount|total|harga|price|rupiah|idr/.test(h)) o.amount = value;
        if (/status|payment|pembayaran/.test(h)) o.status = value;
        if (/referensi|reference|invoice|order|transaksi|transaction|kode/.test(h)) o.ref = value;
        if (/acara|kegiatan|event/.test(h)) o.event_name = value;
        if (/detail event|detail kegiatan/.test(h)) o.event_detail = value;
        if (/produk|product|deskripsi|description|item|nama|layanan|jenis/.test(h) && !/member/.test(h)) o.item = value;
        if (/nama member|member/.test(h)) o.member = value;
        if (/\bbeli\b|bought|quantity|qty/.test(h)) { o.qty = Number(value.replace(/[^0-9]/g, '')) || 1; o.bought_count = o.qty; }
        if (/terpakai|used/.test(h)) o.used_count = Number(value.replace(/[^0-9]/g, '')) || 0;
      });
      o.item = o.event_name || o.item || o.raw_text;
      o.category = guessCategory([o.event_name, o.event_detail, o.item, o.raw_text].join(' '));
      o.id = [location.pathname, o.session_label || '', o.event_name || '', o.event_detail || '', o.member || '', o.qty || 1].join('|');
      transactions.push(o);
    }
  }
  if (!transactions.length) {
    for (const row of lists) transactions.push({ raw_text: row.raw_text, source_page: location.href, item: row.raw_text, qty: 1, category: guessCategory(row.raw_text) });
  }
  const payload = { exporter: 'jkt48-history-exporter-v2', exported_at: new Date().toISOString(), page_title: document.title, page_url: location.href, tables, transactions, visible_rows: lists };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `jkt48-history-${new Date().toISOString().slice(0,10)}.json`; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  console.info(`JKT48 History Exporter: ${tables.length} tabel dan ${lists.length} baris daftar diekspor. Periksa JSON sebelum mengimpor.`);
})();
