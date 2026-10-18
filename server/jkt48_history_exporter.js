
/*
 * JKT48 History Exporter v2
 *
 * Jalankan di DevTools Console saat login di halaman My Page.
 * Membaca tabel/daftar yang dirender pada halaman aktif.
 * Tidak membaca cookie/token dan tidak mengirim data ke server.
 * Status PENDING tetap disimpan.
 */

(() => {
  const norm = s => String(s ?? "").replace(/\s+/g, " ").trim();

  // Klasifikasi tiket.
  function detectTicketCategory(ticket) {
    const type = norm(ticket.ticket_type).toUpperCase();

    const text = [
      ticket.name,
      ticket.event_name,
      ticket.item,
      ticket.ticket_label,
      ticket.raw_text
    ].filter(Boolean).join(" ");

    // Gunakan tipe tiket resmi jika tersedia.
    if (type === "SHOW") return "SHOW";

    // Fallback untuk show jika ticket_type tidak tersedia di tabel.
    if (
      /\bpertaruhan cinta\b/i.test(text) ||
      /\bdalam undian\b/i.test(text)
    ) {
      return "SHOW";
    }

    // Periksa 2Shot sebelum M&G.
    if (/\b2\s*shot\b/i.test(text)) return "2Shot";

    if (
      /\bphotocard\b/i.test(text) ||
      /\bmeet\s*(?:and|&)\s*greet\b/i.test(text) ||
      /\bm\s*&\s*g\b/i.test(text) ||
      /\bmng\b/i.test(text)
    ) {
      return "M&G";
    }

    if (type === "EXCLUSIVE") return "M&G";

    return "Others";
  }

  // Ekstrak tabel.
  const tables = [...document.querySelectorAll("table")]
    .map((table, ti) => {
      const rows = [...table.querySelectorAll("tr")]
        .map(tr =>
          [...tr.querySelectorAll("th, td")]
            .map(td => norm(td.innerText || td.textContent))
        )
        .filter(row => row.some(Boolean));

      if (!rows.length) return null;

      const hasHeader = Boolean(
        table.querySelector("thead tr") ||
        table.querySelector("tr th")
      );

      const headers = hasHeader
        ? rows.shift()
        : rows[0].map((_, i) => `kolom_${i + 1}`);

      return {
        table_index: ti,
        headers,
        rows: rows.map(cells => ({
          cells,
          raw_text: cells.join(" | ")
        }))
      };
    })
    .filter(Boolean);

  // Ekstrak daftar yang terlihat.
  const lists = [
    ...document.querySelectorAll(
      '[role="row"], .history-item, .transaction-item, li'
    )
  ]
    .map((el, i) => ({
      row_index: i,
      raw_text: norm(el.innerText || el.textContent)
    }))
    .filter(x => x.raw_text && x.raw_text.length > 8)
    .filter((x, i, arr) =>
      arr.findIndex(y => y.raw_text === x.raw_text) === i
    )
    .slice(0, 1000);

  const transactions = [];

  // Konversi baris tabel menjadi transaksi.
  for (const table of tables) {
    for (const row of table.rows || []) {
      const o = {
        raw_text: row.raw_text || row.cells.join(" | "),
        source_page: location.href
      };

      (table.headers || []).forEach((header, i) => {
        const h = norm(header).toLowerCase();
        const value = norm(row.cells[i]);

        if (!value) return;

        // Pemetaan nama acara secara eksplisit.
        if (/acara\s*\/?\s*kegiatan|nama acara|event name/.test(h)) {
          o.name = value;
          o.event_name = value;
          o.item = value;
        } else if (/nama member|member/.test(h)) {
          o.member_name = value;
        } else if (/detail event/.test(h)) {
          o.event_detail = value;
        } else if (/tanggal|date|waktu|created/.test(h)) {
          o.date = value;
        } else if (/nominal|amount|total|harga|price|rupiah|idr/.test(h)) {
          o.amount = value;
        } else if (/status|payment|pembayaran/.test(h)) {
          o.status = value;
        } else if (/referensi|reference|invoice|order|transaksi|transaction|kode/.test(h)) {
          o.ref = value;
          o.reference_code = value;
        } else if (/ticket.?type|tipe.?tiket/.test(h)) {
          o.ticket_type = value.toUpperCase();
        } else if (/ticket.?label|label.?tiket/.test(h)) {
          o.ticket_label = value;
        } else if (/produk|product|deskripsi|description|layanan|jenis/.test(h)) {
          if (!o.item) o.item = value;
        }
      });

      // Jangan biarkan nama member menggantikan nama acara.
      o.category = detectTicketCategory(o);
      transactions.push(o);
    }
  }

  // Fallback jika halaman tidak mempunyai tabel.
  if (!transactions.length) {
    for (const row of lists) {
      const o = {
        raw_text: row.raw_text,
        source_page: location.href
      };

      o.category = detectTicketCategory(o);
      transactions.push(o);
    }
  }

  const payload = {
    exporter: "jkt48-history-exporter-v2",
    exported_at: new Date().toISOString(),
    page_title: document.title,
    page_url: location.href,
    tables,
    transactions,
    visible_rows: lists,
    summary: {
      total_transactions: transactions.length,
      categories: transactions.reduce((acc, ticket) => {
        const category = ticket.category || "Others";
        acc[category] = (acc[category] || 0) + 1;
        return acc;
      }, {}),
      pending_count: transactions.filter(ticket =>
        /\bpending\b/i.test(
          `${ticket.status || ""} ${ticket.raw_text || ""}`
        )
      ).length
    }
  };

  // Download file JSON.
  const blob = new Blob(
    [JSON.stringify(payload, null, 2)],
    { type: "application/json" }
  );

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");

  a.href = url;
  a.download = `jkt48-history-${new Date().toISOString().slice(0, 10)}.json`;

  document.body.appendChild(a);
  a.click();
  a.remove();

  setTimeout(() => URL.revokeObjectURL(url), 1000);

  console.info("JKT48 History Exporter selesai.");
  console.info("Tabel:", tables.length);
  console.info("Baris daftar:", lists.length);
  console.info("Transaksi:", transactions.length);
  console.info("Kategori:", payload.summary.categories);
  console.info("Status PENDING:", payload.summary.pending_count);
  console.info("Periksa JSON hasil ekspor sebelum mengimpor.");
})();
