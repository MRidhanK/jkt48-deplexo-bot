/* JKT48 History Exporter v3
 * Jalankan di DevTools Console pada https://jkt48.com/my-page saat sudah login.
 * Mencoba membaca endpoint My Tickets resmi yang dipakai halaman akun, menggunakan
 * sesi browser yang sudah login (credentials same-origin). Tidak membaca cookie/token,
 * tidak mengirim data ke server lain, dan hanya mengunduh JSON ke perangkat sendiri.
 * Jika API tidak tersedia, fallback ke tabel/daftar yang terlihat di halaman aktif.
 */
(async () => {
  const norm = s => String(s ?? '').replace(/\s+/g, ' ').trim();
  const guessCategory = t => {
    const s = String(t || '').toUpperCase();
    if (/EX5B99|EXD1A1|2\s*[- ]?SHOT/.test(s)) return '2SHOT';
    if (/EX2F12|VIDEO\s*CALL|VIRTUAL\s*CALL|\bVC\b/.test(s)) return 'VC';
    if (/EX24AE|EXA6F1|MEET\s*(?:AND|&)\s*GREET|PERSONAL MEET|PHOTOCARD|M\s*&\s*G|\bMNG\b/.test(s)) return 'MNG';
    if (/THEATER|TEATER|PERTUNJUKAN/.test(s)) return 'THEATER';
    if (/POINT|POIN|TOP.?UP/.test(s)) return 'POINT';
    if (/MERCH|PRODUCT|PRODUK|GOODS/.test(s)) return 'PRODUCT';
    return 'OTHER';
  };
  const tables = [...document.querySelectorAll('table')].map((table, ti) => {
    const rows = [...table.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(td => norm(td.innerText || td.textContent))).filter(r => r.some(Boolean));
    if (!rows.length) return null;
    const hasHeader = table.querySelector('thead tr') || table.querySelector('tr th');
    const headers = hasHeader ? rows.shift() : rows[0].map((_, i) => `kolom_${i + 1}`);
    return { table_index: ti, headers, rows: rows.map(cells => ({ cells, raw_text: cells.join(' | ') })) };
  }).filter(Boolean);
  const visibleRows = [...document.querySelectorAll('[role="row"], .history-item, .transaction-item, li')]
    .map((el, i) => ({ row_index: i, raw_text: norm(el.innerText || el.textContent) }))
    .filter(x => x.raw_text && x.raw_text.length > 8)
    .filter((x, i, a) => a.findIndex(y => y.raw_text === x.raw_text) === i)
    .slice(0, 1000);

  let apiTickets = [];
  let apiError = '';
  if (/^(www\.)?jkt48\.com$/i.test(location.hostname)) {
    try {
      const from = '2020-01-01';
      const to = '2035-12-31';
      let page = 1;
      let totalPages = 1;
      const maxPages = 100;
      while (page <= totalPages && page <= maxPages) {
        const params = new URLSearchParams({ lang: 'id', limit: '100', page: String(page), from, to });
        const response = await fetch(`/api/v1/accounts/my-tickets?${params.toString()}`, {
          method: 'GET', credentials: 'same-origin', cache: 'no-store',
          headers: { Accept: 'application/json, text/plain, */*' }
        });
        if (!response.ok) throw new Error(`My Tickets HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload || !Array.isArray(payload.data)) throw new Error('Respons API tidak memiliki array data');
        apiTickets.push(...payload.data);
        totalPages = Math.max(1, Number(payload._meta?.total_page || 1));
        if (!payload.data.length) break;
        page += 1;
      }
    } catch (err) {
      apiError = String(err?.message || err);
      apiTickets = [];
    }
  } else {
    apiError = 'Buka exporter di halaman jkt48.com agar sesi My Tickets bisa digunakan.';
  }

  const transactions = [];
  if (apiTickets.length) {
    for (const t of apiTickets) {
      const ref = norm(t.reference_code);
      const transactionNumbers = Array.isArray(t.transaction_numbers) ? t.transaction_numbers : [];
      const qty = Math.max(1, Number(t.bought_count ?? t.quantity ?? t.qty ?? 1) || 1);
      const used = Math.max(0, Number(t.used_count ?? 0) || 0);
      const item = norm(t.name || t.ticket_label || 'Tiket JKT48');
      const member = norm(t.member_name || '');
      const eventDetail = [t.session_label, t.lane_label, t.date, t.start_time, t.end_time].filter(Boolean).join(' | ');
      transactions.push({
        ...t,
        id: [ref, transactionNumbers.join(','), t.date || '', t.session_label || '', t.lane_label || '', member, item].join('|'),
        reference_code: ref,
        transaction_numbers: transactionNumbers,
        item,
        event_name: item,
        event_detail: eventDetail,
        member,
        member_name: member,
        qty,
        bought_count: qty,
        used_count: used,
        category: guessCategory([ref, t.ticket_type, t.ticket_label, item].join(' ')),
        source_page: location.href
      });
    }
  } else {
    for (const table of tables) {
      for (const row of table.rows || []) {
        const cells = row.cells || [];
        const o = { raw_text: row.raw_text || cells.join(' | '), source_page: location.href };
        table.headers.forEach((header, i) => {
          const h = norm(header).toLowerCase();
          const value = norm(cells[i]);
          if (!value) return;
          if (/reference.?code|kode referensi|referensi|reference|invoice|order|transaction.?number/.test(h)) o.reference_code = value;
          if (/^sesi|session/.test(h)) o.session_label = value;
          if (/tanggal|date|waktu|created/.test(h)) o.date = value;
          if (/nominal|amount|total|harga|price|rupiah|idr/.test(h)) o.amount = value;
          if (/status|payment|pembayaran/.test(h)) o.status = value;
          if (/acara|kegiatan|event/.test(h)) o.event_name = value;
          if (/detail event|detail kegiatan/.test(h)) o.event_detail = value;
          if (/produk|product|deskripsi|description|item|nama|layanan|jenis/.test(h) && !/member/.test(h)) o.item = value;
          if (/nama member|member/.test(h)) o.member = value;
          if (/\bbeli\b|bought|quantity|qty/.test(h)) { o.qty = Math.max(1, Number(value.replace(/[^0-9]/g, '')) || 1); o.bought_count = o.qty; }
          if (/terpakai|used/.test(h)) o.used_count = Number(value.replace(/[^0-9]/g, '')) || 0;
        });
        o.item = o.event_name || o.item || o.raw_text;
        o.member_name = o.member || '';
        o.reference_code = o.reference_code || '';
        o.category = guessCategory([o.reference_code, o.event_name, o.event_detail, o.item, o.raw_text].join(' '));
        o.id = [o.reference_code, o.date || '', o.session_label || '', o.event_detail || '', o.member || '', o.qty || 1].join('|');
        transactions.push(o);
      }
    }
    if (!transactions.length) {
      for (const row of visibleRows) transactions.push({ raw_text: row.raw_text, source_page: location.href, item: row.raw_text, qty: 1, category: guessCategory(row.raw_text), reference_code: '' });
    }
  }

  const payload = {
    exporter: 'jkt48-history-exporter-v3',
    exported_at: new Date().toISOString(),
    page_title: document.title,
    page_url: location.href,
    source: apiTickets.length ? 'jkt48-my-tickets-api-same-origin' : 'visible-page-fallback',
    api_error: apiError || null,
    count: transactions.length,
    tables,
    transactions,
    tickets: transactions,
    visible_rows: visibleRows
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `jkt48-history-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
  console.info(`JKT48 History Exporter v3: ${transactions.length} transaksi diekspor; sumber=${payload.source}; reference_code tersedia pada data My Tickets API.`);
  if (!apiTickets.length) console.warn(`API My Tickets tidak berhasil dibaca: ${apiError}. JSON memakai fallback tabel/daftar yang terlihat; reference_code mungkin tidak tersedia jika tidak tampil di halaman.`);
})();
