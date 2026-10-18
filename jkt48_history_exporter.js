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
  for (const table of tables) {
    const headers = table.headers || [];
    for (const row of table.rows || []) {
      const o = { raw_text: row.raw_text || (row.cells || []).join(' | '), source_page: location.href };
      headers.forEach((header, i) => {
        const h = norm(header).toLowerCase(); const value = norm((row.cells || [])[i]);
        if (!value) return;
        if (/tanggal|date|waktu|created/.test(h)) o.date = value;
        if (/nominal|amount|total|harga|price|rupiah|idr/.test(h)) o.amount = value;
        if (/status|payment|pembayaran/.test(h)) o.status = value;
        if (/referensi|reference|invoice|order|transaksi|transaction|kode/.test(h)) o.ref = value;
        if (/produk|product|detail|deskripsi|description|item|nama|layanan|jenis/.test(h)) o.item = value;
      });
      transactions.push(o);
    }
  }
  if (!transactions.length) for (const row of lists) transactions.push({ raw_text: row.raw_text, source_page: location.href });
  const payload = { exporter: 'jkt48-history-exporter-v1', exported_at: new Date().toISOString(), page_title: document.title, page_url: location.href, tables, transactions, visible_rows: lists };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `jkt48-history-${new Date().toISOString().slice(0,10)}.json`; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  console.info(`JKT48 History Exporter: ${tables.length} tabel dan ${lists.length} baris daftar diekspor. Periksa JSON sebelum mengimpor.`);
})();
