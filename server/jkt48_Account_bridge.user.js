// ==UserScript==
// @name         JKT48 Ticket Radar - Browser Ticket Reader
// @namespace    voltvoltre.jkt48.radar
// @version      2.0.0
// @description  Membaca tiket dari halaman My Tickets JKT48 seperti tampilan My Page
// @match        https://jkt48.com/*
// @grant        GM_xmlhttpRequest
// @connect      *
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const params = new URLSearchParams(location.search);

    if (params.get("radar_fetch") !== "1") {
        return;
    }

    const bridgeToken = params.get("token") || "";
    const callbackUrl = params.get("callback") || "";

    const from =
        params.get("from") ||
        new Date().toISOString().slice(0, 10);

    const to =
        params.get("to") ||
        new Date(Date.now() + 32 * 86400000)
            .toISOString()
            .slice(0, 10);

    // =========================================================
    // UI
    // =========================================================

    function ensureOverlay() {
        let overlay = document.getElementById(
            "jkt48-radar-reader-overlay"
        );

        if (overlay) {
            return overlay;
        }

        overlay = document.createElement("div");

        overlay.id =
            "jkt48-radar-reader-overlay";

        overlay.innerHTML = `
            <div id="jkt48-radar-reader-card">
                <div id="jkt48-radar-reader-icon">
                    🎟️
                </div>

                <div id="jkt48-radar-reader-title">
                    JKT48 Ticket Radar
                </div>

                <div id="jkt48-radar-reader-status">
                    Menyiapkan pembacaan tiket…
                </div>

                <div id="jkt48-radar-reader-progress">
                    <div></div>
                </div>
            </div>
        `;

        const style =
            document.createElement("style");

        style.textContent = `
            #jkt48-radar-reader-overlay {
                position: fixed;
                inset: 0;
                z-index: 2147483647;
                display: flex;
                align-items: center;
                justify-content: center;
                background: rgba(0,0,0,.18);
                backdrop-filter: blur(5px);
            }

            #jkt48-radar-reader-card {
                width: min(460px, calc(100vw - 32px));
                padding: 28px;
                border-radius: 22px;
                background: #fff;
                box-shadow:
                    0 25px 80px rgba(0,0,0,.25);
                text-align: center;
                font-family:
                    Inter,
                    system-ui,
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    sans-serif;
            }

            #jkt48-radar-reader-icon {
                font-size: 42px;
                margin-bottom: 8px;
            }

            #jkt48-radar-reader-title {
                font-size: 21px;
                font-weight: 800;
                color: #111827;
                margin-bottom: 8px;
            }

            #jkt48-radar-reader-status {
                font-size: 14px;
                line-height: 1.5;
                color: #6b7280;
                white-space: pre-line;
            }

            #jkt48-radar-reader-progress {
                width: 100%;
                height: 7px;
                margin-top: 20px;
                overflow: hidden;
                border-radius: 99px;
                background: #f1f1f1;
            }

            #jkt48-radar-reader-progress > div {
                height: 100%;
                width: 0%;
                border-radius: inherit;
                background: #ef233c;
                transition: width .2s ease;
            }
        `;

        document.head.appendChild(style);
        document.body.appendChild(overlay);

        return overlay;
    }

    function setStatus(
        message,
        progress = null
    ) {
        const overlay =
            ensureOverlay();

        const status =
            overlay.querySelector(
                "#jkt48-radar-reader-status"
            );

        const bar =
            overlay.querySelector(
                "#jkt48-radar-reader-progress > div"
            );

        if (status) {
            status.textContent =
                message;
        }

        if (
            bar &&
            progress !== null
        ) {
            bar.style.width =
                Math.max(
                    0,
                    Math.min(100, progress)
                ) + "%";
        }
    }

    function closeOverlay() {
        const el =
            document.getElementById(
                "jkt48-radar-reader-overlay"
            );

        if (el) {
            el.remove();
        }
    }

    // =========================================================
    // HELPER
    // =========================================================

    function sleep(ms) {
        return new Promise(resolve =>
            setTimeout(resolve, ms)
        );
    }

    function cleanText(value) {
        return String(value || "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function uniqueByJson(items) {
        const seen = new Set();
        const result = [];

        for (const item of items) {
            const key =
                JSON.stringify(item);

            if (seen.has(key)) {
                continue;
            }

            seen.add(key);
            result.push(item);
        }

        return result;
    }

    // =========================================================
    // DATE PARSER
    // =========================================================

    const MONTHS = {
        jan: 0,
        january: 0,
        feb: 1,
        february: 1,
        mar: 2,
        march: 2,
        apr: 3,
        april: 3,
        may: 4,
        jun: 5,
        june: 5,
        jul: 6,
        july: 6,
        aug: 7,
        august: 7,
        sep: 8,
        september: 8,
        oct: 9,
        october: 9,
        nov: 10,
        november: 10,
        dec: 11,
        december: 11
    };

    function parseDateFromText(text) {
        text = cleanText(text);

        // Contoh:
        // SUN, OCT 11, 2026
        // SAT, OCT 24, 2026

        const match =
            text.match(
                /(?:MON|TUE|WED|THU|FRI|SAT|SUN)[^A-Z]*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2}),\s+(\d{4})/i
            );

        if (!match) {
            return "";
        }

        const month =
            MONTHS[
                match[1].toLowerCase()
            ];

        const day =
            Number(match[2]);

        const year =
            Number(match[3]);

        if (
            month === undefined ||
            !year ||
            !day
        ) {
            return "";
        }

        const d =
            new Date(
                year,
                month,
                day
            );

        return [
            d.getFullYear(),
            String(
                d.getMonth() + 1
            ).padStart(2, "0"),
            String(
                d.getDate()
            ).padStart(2, "0")
        ].join("-");
    }

    // =========================================================
    // CATEGORY
    // =========================================================

    function detectCategory(text) {
        const t =
            cleanText(text)
                .toLowerCase();

        if (
            t.includes("meet & greet") ||
            t.includes("meet and greet") ||
            t.includes("m&g")
        ) {
            return "MNG";
        }

        if (
            t.includes("2shot") ||
            t.includes("2 shot")
        ) {
            return "2SHOT";
        }

        if (
            t.includes("virtual call") ||
            t.includes("video call") ||
            t.includes("virtualcall") ||
            t.includes("video_call") ||
            /\bvc\b/.test(t)
        ) {
            return "VC";
        }

        if (
            t.includes("theater") ||
            t.includes("show") ||
            t.includes("pajama drive") ||
            t.includes("seishun girls") ||
            t.includes("aitakatta")
        ) {
            return "SHOW";
        }

        return "OTHER";
    }

    // =========================================================
    // TIME
    // =========================================================

    function extractTime(text) {
        const matches =
            cleanText(text).match(
                /\b(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})\b/g
            );

        if (!matches || !matches.length) {
            return {
                start_time: "",
                end_time: ""
            };
        }

        const m =
            matches[0].match(
                /(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})/
            );

        if (!m) {
            return {
                start_time: "",
                end_time: ""
            };
        }

        return {
            start_time: m[1],
            end_time: m[2]
        };
    }

    // =========================================================
    // NUMBER OF TICKETS
    // =========================================================

    function extractTicketCount(text) {
        text = cleanText(text);

        let match =
            text.match(
                /(\d+)\s+TICKETS?/i
            );

        if (match) {
            return Number(match[1]);
        }

        match =
            text.match(
                /(\d+)\s+ENTR(?:Y|IES)/i
            );

        if (match) {
            return Number(match[1]);
        }

        match =
            text.match(
                /(\d+)\s+tiket/i
            );

        if (match) {
            return Number(match[1]);
        }

        return 1;
    }

    // =========================================================
    // LANE
    // =========================================================

    function extractLane(text) {
        const match =
            cleanText(text).match(
                /\bLane\s+(\d+)\b/i
            );

        if (!match) {
            return "";
        }

        return match[1];
    }

    // =========================================================
    // SESSION
    // =========================================================

    function extractSession(text) {
        const match =
            cleanText(text).match(
                /\bSesi\s+(\d+)\b/i
            );

        if (!match) {
            return "";
        }

        return "Sesi " + match[1];
    }

    // =========================================================
    // MEMBER
    // =========================================================

    function guessMemberName(
        container,
        text,
        category
    ) {
        const headings =
            Array.from(
                container.querySelectorAll(
                    "h1,h2,h3,h4,h5,h6,strong,b"
                )
            )
            .map(el =>
                cleanText(el.innerText)
            )
            .filter(Boolean);

        // Nama member biasanya muncul sebagai heading
        // di dalam card seperti gambar 2.
        const blacklist = [
            "SESI",
            "OFc / GENERAL",
            "OFc / GENERAL",
            "ADD TO CALENDAR",
            "JKT48 POINTS"
        ];

        for (const h of headings) {
            const upper =
                h.toUpperCase();

            if (
                blacklist.some(
                    x =>
                        upper === x ||
                        upper.includes(x)
                )
            ) {
                continue;
            }

            if (/^\d+/.test(h)) {
                continue;
            }

            if (
                h.length < 2 ||
                h.length > 80
            ) {
                continue;
            }

            // Jangan ambil judul event
            if (
                /pajama drive/i.test(h) ||
                /festival/i.test(h) ||
                /jkt48/i.test(h) ||
                /session/i.test(h)
            ) {
                continue;
            }

            if (
                category === "MNG" ||
                category === "2SHOT" ||
                category === "VC"
            ) {
                return h;
            }
        }

        return "";
    }

    // =========================================================
    // CARD DETECTION
    // =========================================================

    function findTicketCards() {
        const candidates =
            Array.from(
                document.querySelectorAll(
                    "article, li, section, div"
                )
            );

        const cards = [];

        for (const el of candidates) {
            const text =
                cleanText(
                    el.innerText || ""
                );

            if (!text) {
                continue;
            }

            const hasDate =
                parseDateFromText(text);

            const hasCategory =
                /meet\s*&\s*greet|meet and greet|2shot|2 shot|virtual call|video call|theater show/i
                    .test(text);

            const hasTicket =
                /\b\d+\s+(tickets?|entries?)\b/i
                    .test(text);

            const hasSession =
                /\bSesi\s+\d+\b/i.test(text);

            const hasLane =
                /\bLane\s+\d+\b/i.test(text);

            if (
                !hasDate ||
                !(
                    hasCategory ||
                    hasTicket ||
                    hasSession ||
                    hasLane
                )
            ) {
                continue;
            }

            // Hindari mengambil parent terlalu besar.
            const childCandidate =
                candidates.find(
                    other =>
                        other !== el &&
                        el.contains(other) &&
                        other !== el &&
                        cleanText(
                            other.innerText || ""
                        ).length > 40 &&
                        cleanText(
                            other.innerText || ""
                        ).length <
                            text.length
                );

            if (childCandidate) {
                continue;
            }

            cards.push(el);
        }

        return uniqueElements(cards);
    }

    function uniqueElements(items) {
        const result = [];
        const seen = new Set();

        for (const el of items) {
            let duplicate = false;

            for (const existing of result) {
                if (
                    existing === el ||
                    existing.contains(el) ||
                    el.contains(existing)
                ) {
                    duplicate = true;
                    break;
                }
            }

            if (!duplicate) {
                result.push(el);
            }
        }

        return result;
    }

    // =========================================================
    // PARSE CARD
    // =========================================================

    function parseCard(card) {
        const text =
            cleanText(
                card.innerText || ""
            );

        const date =
            parseDateFromText(text);

        if (!date) {
            return null;
        }

        const category =
            detectCategory(text);

        const time =
            extractTime(text);

        const session =
            extractSession(text);

        const lane =
            extractLane(text);

        const boughtCount =
            extractTicketCount(text);

        const memberName =
            guessMemberName(
                card,
                text,
                category
            );

        // Reception
        let receptionStart = "";
        let receptionEnd = "";

        const reception =
            text.match(
                /RECEPTION\s+(\d{1,2}:\d{2})(?:\s*[–-]\s*(\d{1,2}:\d{2}))?/i
            );

        if (reception) {
            receptionStart =
                reception[1] || "";

            receptionEnd =
                reception[2] || "";
        }

        return {
            category,

            ticket_label:
                category === "MNG"
                    ? "Meet & Greet"
                    : category === "2SHOT"
                        ? "2 Shoot"
                        : category === "VC"
                            ? "Virtual Call"
                            : category === "SHOW"
                                ? "Theater Show"
                                : "Ticket",

            date,

            member_name:
                memberName,

            session_label:
                session,

            lane_label:
                lane
                    ? "Lane " + lane
                    : "",

            lane,

            start_time:
                time.start_time,

            end_time:
                time.end_time,

            reception_start_time:
                receptionStart,

            reception_end_time:
                receptionEnd,

            bought_count:
                boughtCount,

            used_count: 0,

            source:
                "browser_dom",

            source_text:
                text.slice(0, 4000)
        };
    }

    // =========================================================
    // SCROLL PAGE
    // =========================================================

    async function scrollAll() {
        let lastHeight =
            document.documentElement.scrollHeight;

        let stableRounds = 0;

        for (let i = 0; i < 30; i++) {
            const progress =
                Math.min(
                    65,
                    10 + i * 2
                );

            setStatus(
                "Membaca halaman My Tickets…\n" +
                "Memuat seluruh daftar tiket...",
                progress
            );

            window.scrollTo({
                top:
                    document.documentElement
                        .scrollHeight,
                behavior: "smooth"
            });

            await sleep(700);

            const newHeight =
                document.documentElement
                    .scrollHeight;

            if (
                newHeight === lastHeight
            ) {
                stableRounds += 1;
            } else {
                stableRounds = 0;
            }

            lastHeight = newHeight;

            if (stableRounds >= 3) {
                break;
            }
        }

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });

        await sleep(500);
    }

    // =========================================================
    // FIND BEST PAGE
    // =========================================================

    async function waitForTicketPage() {
        for (let i = 0; i < 30; i++) {
            const bodyText =
                cleanText(
                    document.body?.innerText || ""
                );

            if (
                /pajama drive/i.test(bodyText) ||
                /meet\s*&\s*greet/i.test(bodyText) ||
                /meet and greet/i.test(bodyText) ||
                /2shot/i.test(bodyText) ||
                /virtual call/i.test(bodyText)
            ) {
                return;
            }

            await sleep(500);
        }
    }

    // =========================================================
    // FIND / NAVIGATE TO MY TICKETS
    // =========================================================

    async function openMyTickets() {
        const current =
            location.pathname.toLowerCase();

        // Sudah di halaman tickets
        if (
            current.includes("ticket") ||
            current.includes("my-page")
        ) {
            return true;
        }

        // Cari link My Tickets / ticket di halaman
        const links =
            Array.from(
                document.querySelectorAll("a")
            );

        const ticketLink =
            links.find(a =>
                /my tickets|ticket|tiket/i.test(
                    cleanText(a.innerText)
                )
            );

        if (ticketLink) {
            ticketLink.click();

            await sleep(1500);

            return true;
        }

        return false;
    }

    // =========================================================
    // SEND TO BACKEND
    // =========================================================

    function sendToBackend(
        tickets
    ) {
        return new Promise(
            (resolve, reject) => {
                GM_xmlhttpRequest({
                    method: "POST",

                    url: callbackUrl,

                    anonymous: true,

                    headers: {
                        "Content-Type":
                            "application/json",

                        "Accept":
                            "application/json"
                    },

                    data: JSON.stringify({
                        token:
                            bridgeToken,

                        from,

                        to,

                        fetched_at:
                            Math.floor(
                                Date.now() / 1000
                            ),

                        source:
                            "jkt48_browser_dom",

                        tickets
                    }),

                    timeout: 30000,

                    onload(response) {
                        let result = {};

                        try {
                            result =
                                JSON.parse(
                                    response.responseText ||
                                    "{}"
                                );
                        } catch (_) {}

                        if (
                            response.status >= 200 &&
                            response.status < 300
                        ) {
                            resolve(result);
                            return;
                        }

                        reject(
                            new Error(
                                result.error ||
                                result.message ||
                                "Backend HTTP " +
                                response.status
                            )
                        );
                    },

                    onerror() {
                        reject(
                            new Error(
                                "Gagal menghubungi backend Ticket Radar."
                            )
                        );
                    },

                    ontimeout() {
                        reject(
                            new Error(
                                "Request ke backend timeout."
                            )
                        );
                    }
                });
            }
        );
    }

    // =========================================================
    // MAIN
    // =========================================================

    async function main() {
        if (!bridgeToken) {
            throw new Error(
                "Bridge token tidak ditemukan."
            );
        }

        if (!callbackUrl) {
            throw new Error(
                "Callback backend tidak ditemukan."
            );
        }

        ensureOverlay();

        setStatus(
            "Membuka halaman tiket akun JKT48…",
            5
        );

        const opened =
            await openMyTickets();

        if (!opened) {
            throw new Error(
                "Link My Tickets tidak ditemukan di halaman JKT48."
            );
        }

        await waitForTicketPage();

        setStatus(
            "Halaman tiket ditemukan.\n" +
            "Membaca daftar seperti tampilan My Page…",
            12
        );

        await sleep(1000);

        await scrollAll();

        setStatus(
            "Menganalisis kartu tiket…",
            72
        );

        const cards =
            findTicketCards();

        console.log(
            "[JKT48 Radar] Ticket cards:",
            cards.length
        );

        const tickets = [];

        for (const card of cards) {
            try {
                const parsed =
                    parseCard(card);

                if (!parsed) {
                    continue;
                }

                tickets.push(parsed);
            } catch (error) {
                console.warn(
                    "[JKT48 Radar] Card parse error:",
                    error
                );
            }
        }

        const uniqueTickets =
            dedupeTickets(tickets);

        console.log(
            "[JKT48 Radar] Parsed tickets:",
            uniqueTickets
        );

        setStatus(
            `Berhasil membaca ${uniqueTickets.length} tiket.\n` +
            "Mengirim ke dashboard…",
            88
        );

        const response =
            await sendToBackend(
                uniqueTickets
            );

        if (
            response &&
            response.ok === false
        ) {
            throw new Error(
                response.error ||
                response.message ||
                "Backend menolak data."
            );
        }

        setStatus(
            `✅ ${uniqueTickets.length} tiket berhasil dibaca.\n` +
            "Data sudah dikirim ke Ticket Radar.",
            100
        );

        await sleep(1800);

        closeOverlay();

        // Jangan paksa close apabila Chrome
        // menolak window.close()
        try {
            window.close();
        } catch (_) {}
    }

    // =========================================================
    // DEDUPE
    // =========================================================

    function dedupeTickets(
        tickets
    ) {
        const map =
            new Map();

        for (const ticket of tickets) {
            const key = [
                ticket.category,
                ticket.date,
                ticket.member_name,
                ticket.session_label,
                ticket.lane,
                ticket.start_time,
                ticket.end_time,
                ticket.bought_count
            ].join("|");

            if (!map.has(key)) {
                map.set(
                    key,
                    ticket
                );
            }
        }

        return Array.from(
            map.values()
        );
    }

    // =========================================================
    // ERROR
    // =========================================================

    main().catch(error => {
        console.error(
            "[JKT48 Radar]",
            error
        );

        ensureOverlay();

        setStatus(
            "❌ Fetch Akun gagal\n\n" +
            (
                error?.message ||
                String(error)
            ),
            0
        );
    });

})();