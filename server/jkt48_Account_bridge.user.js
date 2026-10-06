// ==UserScript==
// @name         JKT48 Ticket Radar - Browser Ticket Reader
// @namespace    voltvoltre.jkt48.radar
// @version      3.0.0
// @description  Membaca tiket My Page JKT48 dari browser dan mengirim hasilnya ke Dashboard Radar tanpa membuka tab baru
// @match        https://jkt48.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const params = new URLSearchParams(
        window.location.search
    );

    /*
     * Script hanya aktif ketika dashboard sedang
     * menjalankan browser fetch.
     */
    if (
        params.get("radar_fetch") !== "1"
    ) {
        return;
    }

    /*
     * Token ini hanya bridge-token sementara
     * dari dashboard -> iframe -> dashboard.
     *
     * BUKAN access_token akun JKT48.
     */
    const bridgeToken =
        params.get("token") || "";

    /*
     * Origin dashboard.
     *
     * Contoh:
     * https://domain-dashboard-kamu.com
     */
    const parentOrigin =
        params.get("parent_origin") ||
        "";

    const from =
        params.get("from") ||
        formatDate(
            new Date()
        );

    const to =
        params.get("to") ||
        formatDate(
            new Date(
                Date.now() +
                32 * 86400000
            )
        );

    const embedded =
        params.get("embedded") === "1";

    // =========================================================
    // BASIC VALIDATION
    // =========================================================

    if (!bridgeToken) {
        console.error(
            "[JKT48 Radar] Bridge token tidak ditemukan."
        );
        return;
    }

    if (!parentOrigin) {
        console.error(
            "[JKT48 Radar] Parent origin tidak ditemukan."
        );
        return;
    }

    // =========================================================
    // LOGGER
    // =========================================================

    function log(...args) {
        console.log(
            "[JKT48 Radar]",
            ...args
        );
    }

    function warn(...args) {
        console.warn(
            "[JKT48 Radar]",
            ...args
        );
    }

    function error(...args) {
        console.error(
            "[JKT48 Radar]",
            ...args
        );
    }

    // =========================================================
    // HELPER
    // =========================================================

    function sleep(ms) {
        return new Promise(resolve => {
            setTimeout(
                resolve,
                ms
            );
        });
    }

    function cleanText(value) {
        return String(
            value == null
                ? ""
                : value
        )
            .replace(/\u00a0/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    function normalizeForCompare(value) {
        return cleanText(
            value
        )
            .toLowerCase()
            .replace(/[–—]/g, "-");
    }

    function formatDate(date) {
        const y =
            date.getFullYear();

        const m =
            String(
                date.getMonth() + 1
            ).padStart(
                2,
                "0"
            );

        const d =
            String(
                date.getDate()
            ).padStart(
                2,
                "0"
            );

        return `${y}-${m}-${d}`;
    }

    function clamp(
        value,
        min,
        max
    ) {
        return Math.max(
            min,
            Math.min(
                max,
                value
            )
        );
    }

    // =========================================================
    // PARENT MESSAGE BRIDGE
    // =========================================================

    function sendParentMessage(
        type,
        payload = {}
    ) {
        try {
            if (
                !window.parent ||
                window.parent === window
            ) {
                /*
                 * Ini bisa terjadi kalau URL dibuka langsung.
                 * Tetap log agar mudah debugging.
                 */
                warn(
                    "Tidak berada di iframe parent."
                );
                return;
            }

            window.parent.postMessage(
                {
                    source:
                        "jkt48-ticket-radar",

                    type,

                    token:
                        bridgeToken,

                    ...payload
                },
                parentOrigin
            );
        } catch (e) {
            error(
                "postMessage gagal:",
                e
            );
        }
    }

    function sendStatus(
        message,
        progress = null
    ) {
        log(
            message
        );

        sendParentMessage(
            "status",
            {
                message,
                progress
            }
        );
    }

    function sendError(
        message
    ) {
        error(
            message
        );

        sendParentMessage(
            "error",
            {
                error:
                    message
            }
        );
    }

    // =========================================================
    // OPTIONAL HIDDEN PAGE OVERLAY
    // =========================================================

    /*
     * Karena halaman ini biasanya berada di iframe 1x1,
     * overlay sebenarnya tidak terlihat oleh user.
     *
     * Tetap kita buat agar debugging manual di URL JKT48
     * tetap nyaman.
     */
    function ensureOverlay() {
        let overlay =
            document.getElementById(
                "jkt48-radar-reader-overlay"
            );

        if (overlay) {
            return overlay;
        }

        overlay =
            document.createElement(
                "div"
            );

        overlay.id =
            "jkt48-radar-reader-overlay";

        overlay.innerHTML = `
            <div
                id="jkt48-radar-reader-card"
            >
                <div
                    id="jkt48-radar-reader-icon"
                >
                    🎟️
                </div>

                <div
                    id="jkt48-radar-reader-title"
                >
                    JKT48 Ticket Radar
                </div>

                <div
                    id="jkt48-radar-reader-status"
                >
                    Menyiapkan pembacaan tiket…
                </div>

                <div
                    id="jkt48-radar-reader-progress"
                >
                    <div></div>
                </div>
            </div>
        `;

        const style =
            document.createElement(
                "style"
            );

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
                width: min(
                    460px,
                    calc(100vw - 32px)
                );
                padding: 28px;
                border-radius: 22px;
                background: #ffffff;
                box-shadow:
                    0 25px 80px
                    rgba(0,0,0,.25);
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
                border-radius: 999px;
                background: #f1f1f1;
            }

            #jkt48-radar-reader-progress > div {
                height: 100%;
                width: 0%;
                border-radius: inherit;
                background: #ef233c;
                transition:
                    width .2s ease;
            }
        `;

        (
            document.head ||
            document.documentElement
        ).appendChild(
            style
        );

        (
            document.body ||
            document.documentElement
        ).appendChild(
            overlay
        );

        return overlay;
    }

    function setLocalStatus(
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
                clamp(
                    progress,
                    0,
                    100
                ) + "%";
        }
    }

    function closeOverlay() {
        const overlay =
            document.getElementById(
                "jkt48-radar-reader-overlay"
            );

        if (overlay) {
            overlay.remove();
        }
    }

    // =========================================================
    // MONTH
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

    // =========================================================
    // DATE PARSER
    // =========================================================

    function parseDateFromText(
        text
    ) {
        const value =
            cleanText(
                text
            );

        /*
         * Format:
         * SUN, OCT 11, 2026
         * SAT, OCT 24, 2026
         */

        let match =
            value.match(
                /(?:MON|TUE|WED|THU|FRI|SAT|SUN)[,.\s-]*(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)[,\s]+(\d{1,2})[,\s]+(\d{4})/i
            );

        if (!match) {
            /*
             * Fallback:
             * OCT 24, 2026
             */
            match =
                value.match(
                    /\b(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)[,\s]+(\d{1,2})[,\s]+(\d{4})\b/i
                );
        }

        if (!match) {
            return "";
        }

        const month =
            MONTHS[
                match[1]
                    .toLowerCase()
            ];

        const day =
            Number(
                match[2]
            );

        const year =
            Number(
                match[3]
            );

        if (
            month === undefined ||
            !day ||
            !year
        ) {
            return "";
        }

        const date =
            new Date(
                year,
                month,
                day
            );

        if (
            date.getFullYear() !== year ||
            date.getMonth() !== month ||
            date.getDate() !== day
        ) {
            return "";
        }

        return formatDate(
            date
        );
    }

    // =========================================================
    // CATEGORY
    // =========================================================

    function detectCategory(
        text
    ) {
        const t =
            normalizeForCompare(
                text
            );

        /*
         * M&G harus dicek lebih dulu.
         */
        if (
            t.includes(
                "meet & greet"
            ) ||
            t.includes(
                "meet and greet"
            ) ||
            t.includes(
                "meet &greet"
            ) ||
            t.includes(
                "m&g"
            )
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
            t.includes(
                "virtual call"
            ) ||
            t.includes(
                "video call"
            ) ||
            t.includes(
                "virtualcall"
            ) ||
            t.includes(
                "video_call"
            ) ||
            /\bvc\b/.test(t)
        ) {
            return "VC";
        }

        if (
            t.includes(
                "theater show"
            ) ||
            t.includes(
                "theatre show"
            ) ||
            t.includes(
                "theater"
            ) ||
            t.includes(
                "theatre"
            ) ||
            t.includes(
                "show"
            ) ||
            t.includes(
                "pajama drive"
            ) ||
            t.includes(
                "seishun girls"
            ) ||
            t.includes(
                "aitakatta"
            )
        ) {
            return "SHOW";
        }

        return "OTHER";
    }

    // =========================================================
    // CATEGORY LABEL
    // =========================================================

    function categoryLabel(
        category
    ) {
        switch (
            category
        ) {
            case "MNG":
                return "Meet & Greet";

            case "2SHOT":
                return "2 Shoot";

            case "VC":
                return "Virtual Call";

            case "SHOW":
                return "Theater Show";

            default:
                return "Ticket";
        }
    }

    // =========================================================
    // TIME
    // =========================================================

    function extractTime(
        text
    ) {
        const value =
            cleanText(
                text
            );

        /*
         * Mendukung:
         * 14:00–16:00
         * 14:00-16:00
         * 14.00–16.00
         */
        const match =
            value.match(
                /\b(\d{1,2})[:.](\d{2})\s*[–—-]\s*(\d{1,2})[:.](\d{2})\b/
            );

        if (!match) {
            return {
                start_time: "",
                end_time: ""
            };
        }

        return {
            start_time:
                `${match[1].padStart(2, "0")}:${match[2]}`,

            end_time:
                `${match[3].padStart(2, "0")}:${match[4]}`
        };
    }

    // =========================================================
    // RECEPTION
    // =========================================================

    function extractReception(
        text
    ) {
        const value =
            cleanText(
                text
            );

        const match =
            value.match(
                /RECEPTION\s+(\d{1,2})[:.](\d{2})(?:\s*[–—-]\s*(\d{1,2})[:.](\d{2}))?/i
            );

        if (!match) {
            return {
                reception_start_time: "",
                reception_end_time: ""
            };
        }

        return {
            reception_start_time:
                `${match[1].padStart(2, "0")}:${match[2]}`,

            reception_end_time:
                match[3] && match[4]
                    ? `${match[3].padStart(2, "0")}:${match[4]}`
                    : ""
        };
    }

    // =========================================================
    // SESSION
    // =========================================================

    function extractSession(
        text
    ) {
        const value =
            cleanText(
                text
            );

        const match =
            value.match(
                /\bSesi\s+(\d+)\b/i
            );

        if (!match) {
            return "";
        }

        return (
            "Sesi " +
            match[1]
        );
    }

    // =========================================================
    // LANE
    // =========================================================

    function extractLane(
        text
    ) {
        const value =
            cleanText(
                text
            );

        const match =
            value.match(
                /\bLane\s+(\d+)\b/i
            );

        if (!match) {
            return "";
        }

        return match[1];
    }

    // =========================================================
    // TICKET COUNT
    // =========================================================

    function extractTicketCount(
        text
    ) {
        const value =
            cleanText(
                text
            );

        /*
         * 2 TICKETS
         */
        let match =
            value.match(
                /\b(\d+)\s+TICKETS?\b/i
            );

        if (match) {
            return Number(
                match[1]
            );
        }

        /*
         * 1 ENTRY
         * 2 ENTRIES
         */
        match =
            value.match(
                /\b(\d+)\s+ENTR(?:Y|IES)\b/i
            );

        if (match) {
            return Number(
                match[1]
            );
        }

        /*
         * Indonesian
         */
        match =
            value.match(
                /\b(\d+)\s+tiket\b/i
            );

        if (match) {
            return Number(
                match[1]
            );
        }

        return 1;
    }

    // =========================================================
    // MEMBER NAME HELPERS
    // =========================================================

    function looksLikeMemberName(
        value
    ) {
        const text =
            cleanText(
                value
            );

        if (
            text.length < 3 ||
            text.length > 80
        ) {
            return false;
        }

        const upper =
            text.toUpperCase();

        const blacklist = [
            "SESI",
            "LANE",
            "ADD TO CALENDAR",
            "JKT48 POINTS",
            "JKT48 POINT",
            "THEATER SHOW",
            "MEET & GREET",
            "MEET AND GREET",
            "2SHOT",
            "2 SHOT",
            "VIRTUAL CALL",
            "VIDEO CALL",
            "RECEPTION",
            "TICKETS",
            "TICKET",
            "ENTRY",
            "ENTRIES",
            "OFC / GENERAL",
            "PENDING",
            "MIXED"
        ];

        if (
            blacklist.some(
                item =>
                    upper === item
            )
        ) {
            return false;
        }

        if (
            blacklist.some(
                item =>
                    upper.includes(item)
            )
        ) {
            return false;
        }

        if (
            /^\d/.test(text)
        ) {
            return false;
        }

        if (
            /\d{1,2}:\d{2}/.test(
                text
            )
        ) {
            return false;
        }

        if (
            parseDateFromText(
                text
            )
        ) {
            return false;
        }

        /*
         * Nama umumnya terdiri dari huruf,
         * spasi, titik, apostrof, atau tanda minus.
         */
        if (
            !/^[A-Za-zÀ-ÿ.'’\- ]+$/.test(
                text
            )
        ) {
            return false;
        }

        return true;
    }

    function guessMemberName(
        container,
        category
    ) {
        if (
            !container ||
            (
                category !== "MNG" &&
                category !== "2SHOT" &&
                category !== "VC"
            )
        ) {
            return "";
        }

        const selectors = [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "strong",
            "b"
        ];

        const candidates = [];

        for (
            const selector
            of selectors
        ) {
            const nodes =
                Array.from(
                    container.querySelectorAll(
                        selector
                    )
                );

            for (
                const node
                of nodes
            ) {
                const value =
                    cleanText(
                        node.innerText
                    );

                if (
                    !value
                ) {
                    continue;
                }

                if (
                    looksLikeMemberName(
                        value
                    )
                ) {
                    candidates.push(
                        value
                    );
                }
            }
        }

        /*
         * Ambil kandidat pertama yang masuk akal.
         */
        if (
            candidates.length
        ) {
            return candidates[0];
        }

        /*
         * Fallback berdasarkan baris teks.
         */
        const lines =
            (
                container.innerText ||
                ""
            )
                .split(/\n+/)
                .map(
                    cleanText
                )
                .filter(Boolean);

        for (
            const line
            of lines
        ) {
            if (
                looksLikeMemberName(
                    line
                )
            ) {
                return line;
            }
        }

        return "";
    }

    // =========================================================
    // EVENT TITLE
    // =========================================================

    function guessEventTitle(
        container,
        category
    ) {
        const text =
            cleanText(
                container?.innerText ||
                ""
            );

        if (
            category === "MNG" ||
            category === "2SHOT" ||
            category === "VC"
        ) {
            /*
             * Untuk event personal:
             * cari teks panjang yang bukan member/
             * session/lane/time.
             */
            const lines =
                text.split(/\n+/)
                    .map(
                        cleanText
                    )
                    .filter(Boolean);

            for (
                const line
                of lines
            ) {
                if (
                    /festival/i.test(
                        line
                    )
                ) {
                    return line;
                }

                if (
                    /personal meet/i.test(
                        line
                    )
                ) {
                    return line;
                }
            }
        }

        /*
         * SHOW:
         * Cari heading paling masuk akal.
         */
        const headings =
            Array.from(
                container.querySelectorAll(
                    "h1,h2,h3,h4,h5,h6"
                )
            )
                .map(
                    el =>
                        cleanText(
                            el.innerText
                        )
                )
                .filter(Boolean);

        for (
            const heading
            of headings
        ) {
            if (
                !/sesi|lane|meet & greet|2shot|reception|pending|mixed/i.test(
                    heading
                )
            ) {
                return heading;
            }
        }

        return "";
    }

    // =========================================================
    // CARD VALIDATION
    // =========================================================

    function hasTicketSignals(
        text
    ) {
        const t =
            normalizeForCompare(
                text
            );

        const signals = [
            /\b\d+\s+tickets?\b/i,
            /\b\d+\s+entr(?:y|ies)\b/i,
            /\b\d+\s+tiket\b/i,
            /\bSesi\s+\d+\b/i,
            /\bLane\s+\d+\b/i,
            /meet\s*&\s*greet/i,
            /meet and greet/i,
            /\b2\s*shot\b/i,
            /virtual call/i,
            /video call/i,
            /theater show/i,
            /pajama drive/i
        ];

        return signals.some(
            regex =>
                regex.test(
                    t
                )
        );
    }

    // =========================================================
    // FIND CARD ROOT
    // =========================================================

    function findBestCardRoot(
        element
    ) {
        let current =
            element;

        let best =
            element;

        /*
         * Naik beberapa level untuk mencari
         * container event card.
         */
        for (
            let i = 0;
            i < 8 &&
            current;
            i++
        ) {
            const text =
                cleanText(
                    current.innerText ||
                    ""
                );

            if (
                text.length > 80 &&
                text.length < 5000 &&
                parseDateFromText(text) &&
                hasTicketSignals(text)
            ) {
                best =
                    current;
            }

            current =
                current.parentElement;
        }

        return best;
    }

    // =========================================================
    // FIND TICKET CARDS
    // =========================================================

    function findTicketCards() {
        /*
         * Mulai dari elemen yang memiliki tanggal.
         */
        const all =
            Array.from(
                document.querySelectorAll(
                    "div,article,section,li"
                )
            );

        const roots =
            new Set();

        for (
            const element
            of all
        ) {
            const text =
                cleanText(
                    element.innerText ||
                    ""
                );

            if (
                !text
            ) {
                continue;
            }

            if (
                !parseDateFromText(
                    text
                )
            ) {
                continue;
            }

            if (
                !hasTicketSignals(
                    text
                )
            ) {
                continue;
            }

            const root =
                findBestCardRoot(
                    element
                );

            if (
                root
            ) {
                roots.add(
                    root
                );
            }
        }

        /*
         * Buang nested duplicate.
         */
        const cards =
            Array.from(
                roots
            ).filter(
                card => {
                    return !Array.from(
                        roots
                    ).some(
                        other =>
                            other !== card &&
                            other.contains(
                                card
                            )
                    );
                }
            );

        return cards;
    }

    // =========================================================
    // PARSE CARD
    // =========================================================

    function parseCard(
        card
    ) {
        if (
            !card
        ) {
            return null;
        }

        const rawText =
            card.innerText ||
            "";

        const text =
            cleanText(
                rawText
            );

        if (
            !text
        ) {
            return null;
        }

        const date =
            parseDateFromText(
                text
            );

        if (
            !date
        ) {
            return null;
        }

        const category =
            detectCategory(
                text
            );

        const time =
            extractTime(
                text
            );

        const reception =
            extractReception(
                text
            );

        const session =
            extractSession(
                text
            );

        const lane =
            extractLane(
                text
            );

        const boughtCount =
            extractTicketCount(
                text
            );

        const memberName =
            guessMemberName(
                card,
                category
            );

        const eventTitle =
            guessEventTitle(
                card,
                category
            );

        /*
         * Jangan kirim card yang jelas bukan ticket.
         */
        const likelyTicket =
            category !== "OTHER" ||
            session ||
            lane ||
            boughtCount > 0;

        if (
            !likelyTicket
        ) {
            return null;
        }

        return {
            category,

            ticket_label:
                categoryLabel(
                    category
                ),

            event_title:
                eventTitle,

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
                reception.reception_start_time,

            reception_end_time:
                reception.reception_end_time,

            bought_count:
                boughtCount,

            used_count:
                0,

            remaining_count:
                Math.max(
                    0,
                    boughtCount
                ),

            source:
                "browser_dom",

            source_text:
                text.slice(
                    0,
                    5000
                )
        };
    }

    // =========================================================
    // DEDUPE
    // =========================================================

    function dedupeTickets(
        tickets
    ) {
        const map =
            new Map();

        for (
            const ticket
            of tickets
        ) {
            const key = [
                ticket.category,
                ticket.date,
                ticket.event_title,
                ticket.member_name,
                ticket.session_label,
                ticket.lane,
                ticket.start_time,
                ticket.end_time,
                ticket.bought_count
            ].join("|");

            if (
                !map.has(key)
            ) {
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
    // WAIT FOR DOM
    // =========================================================

    async function waitForDomReady() {
        if (
            document.readyState ===
            "loading"
        ) {
            await new Promise(
                resolve => {
                    document.addEventListener(
                        "DOMContentLoaded",
                        resolve,
                        {
                            once: true
                        }
                    );
                }
            );
        }

        /*
         * Tunggu React / Next / Vue selesai render.
         */
        await sleep(1200);
    }

    // =========================================================
    // WAIT FOR TICKETS
    // =========================================================

    async function waitForTickets() {
        for (
            let i = 0;
            i < 40;
            i++
        ) {
            const bodyText =
                cleanText(
                    document.body?.innerText ||
                    ""
                );

            const found =
                parseDateFromText(
                    bodyText
                ) &&
                hasTicketSignals(
                    bodyText
                );

            if (
                found
            ) {
                return true;
            }

            await sleep(
                500
            );
        }

        return false;
    }

    // =========================================================
    // SCROLL / LOAD LAZY CONTENT
    // =========================================================

    async function scrollAll() {
        let lastHeight =
            0;

        let stableCount =
            0;

        const maxRounds =
            35;

        for (
            let i = 0;
            i < maxRounds;
            i++
        ) {
            const currentHeight =
                document.documentElement
                    .scrollHeight;

            const progress =
                Math.min(
                    70,
                    15 +
                    i * 2
                );

            setLocalStatus(
                "Membaca seluruh daftar tiket…\n" +
                `Scroll ${i + 1}/${maxRounds}`,
                progress
            );

            sendStatus(
                "Membaca seluruh daftar tiket…\n" +
                `Memuat data ${i + 1}/${maxRounds}`,
                progress
            );

            window.scrollTo(
                0,
                currentHeight
            );

            /*
             * Beberapa halaman lazy-load
             * setelah scroll.
             */
            await sleep(
                650
            );

            const newHeight =
                document.documentElement
                    .scrollHeight;

            if (
                newHeight === lastHeight
            ) {
                stableCount++;
            } else {
                stableCount = 0;
            }

            lastHeight =
                newHeight;

            if (
                stableCount >= 3
            ) {
                break;
            }
        }

        /*
         * Kembali ke atas.
         */
        window.scrollTo(
            0,
            0
        );

        await sleep(
            500
        );
    }

    // =========================================================
    // PAGINATION BUTTON HANDLER
    // =========================================================

    async function tryLoadMore() {
        /*
         * Beberapa implementasi page memakai
         * button "Load more".
         */
        const buttons =
            Array.from(
                document.querySelectorAll(
                    "button,a"
                )
            );

        const loadMore =
            buttons.find(
                el => {
                    const text =
                        cleanText(
                            el.innerText
                        );

                    return /load more|selanjutnya|berikutnya|next|lihat lebih/i.test(
                        text
                    );
                }
            );

        if (
            !loadMore
        ) {
            return false;
        }

        if (
            loadMore.disabled
        ) {
            return false;
        }

        try {
            loadMore.click();

            await sleep(
                1200
            );

            return true;
        } catch (
            _
        ) {
            return false;
        }
    }

    // =========================================================
    // OBSERVE DOM CHANGES
    // =========================================================

    function createDomObserver(
        callback
    ) {
        const observer =
            new MutationObserver(
                () => {
                    callback();
                }
            );

        observer.observe(
            document.documentElement,
            {
                childList: true,
                subtree: true
            }
        );

        return observer;
    }

    // =========================================================
    // READ PAGE
    // =========================================================

    async function readTickets() {
        setLocalStatus(
            "Menunggu halaman My Page selesai dimuat…",
            5
        );

        sendStatus(
            "Menunggu halaman My Page selesai dimuat…",
            5
        );

        await waitForDomReady();

        setLocalStatus(
            "Mencari data tiket di halaman JKT48…",
            10
        );

        sendStatus(
            "Mencari data tiket di halaman JKT48…",
            10
        );

        /*
         * Beri waktu render.
         */
        await sleep(
            800
        );

        await waitForTickets();

        /*
         * Coba lazy content.
         */
        await scrollAll();

        /*
         * Coba sekali "Load More" bila ada.
         */
        for (
            let i = 0;
            i < 5;
            i++
        ) {
            const more =
                await tryLoadMore();

            if (
                !more
            ) {
                break;
            }

            await scrollAll();
        }

        setLocalStatus(
            "Menganalisis card tiket…",
            75
        );

        sendStatus(
            "Menganalisis card tiket…",
            75
        );

        /*
         * Tunggu perubahan DOM terakhir.
         */
        await sleep(
            500
        );

        const cards =
            findTicketCards();

        log(
            "Jumlah candidate card:",
            cards.length
        );

        const parsed =
            [];

        for (
            let i = 0;
            i < cards.length;
            i++
        ) {
            try {
                const ticket =
                    parseCard(
                        cards[i]
                    );

                if (
                    ticket
                ) {
                    parsed.push(
                        ticket
                    );
                }
            } catch (
                e
            ) {
                warn(
                    "Gagal parse card:",
                    e
                );
            }
        }

        const tickets =
            dedupeTickets(
                parsed
            );

        /*
         * Urutkan:
         * tanggal → jam → kategori → member
         */
        tickets.sort(
            (
                a,
                b
            ) => {
                const dateA =
                    `${a.date} ${a.start_time || "00:00"}`;

                const dateB =
                    `${b.date} ${b.start_time || "00:00"}`;

                return dateA.localeCompare(
                    dateB
                );
            }
        );

        return tickets;
    }

    // =========================================================
    // MAIN
    // =========================================================

    async function main() {
        ensureOverlay();

        setLocalStatus(
            "🎟️ Menyiapkan pembacaan tiket…",
            2
        );

        sendStatus(
            "🎟️ Menyiapkan pembacaan tiket…",
            2
        );

        /*
         * Pastikan halaman memang dapat digunakan.
         */
        if (
            !document.body
        ) {
            await waitForDomReady();
        }

        setLocalStatus(
            "🔐 Sesi browser JKT48 terdeteksi.\n" +
            "Membaca halaman My Page…",
            5
        );

        sendStatus(
            "🔐 Sesi browser JKT48 terdeteksi.\n" +
            "Membaca halaman My Page…",
            5
        );

        const tickets =
            await readTickets();

        log(
            "Hasil akhir:",
            tickets
        );

        /*
         * Tidak ditemukan tiket.
         */
        if (
            !tickets.length
        ) {
            throw new Error(
                "Tidak menemukan data tiket pada halaman My Page JKT48. " +
                "Pastikan bagian jadwal/tiket sudah tampil."
            );
        }

        setLocalStatus(
            `✅ ${tickets.length} tiket berhasil dibaca.\n` +
            "Mengirim hasil ke Dashboard Radar…",
            90
        );

        sendStatus(
            `✅ ${tickets.length} tiket berhasil dibaca.\n` +
            "Mengirim hasil ke Dashboard Radar…",
            90
        );

        /*
         * KIRIM DATA KE PARENT.
         *
         * Tidak ada:
         * - access_token
         * - refresh_token
         * - cf_clearance
         * - cookie
         *
         * Yang dikirim hanya hasil tiket.
         */
        sendParentMessage(
            "result",
            {
                from,

                to,

                fetched_at:
                    Math.floor(
                        Date.now() / 1000
                    ),

                source:
                    "jkt48_browser_dom",

                tickets
            }
        );

        setLocalStatus(
            `✅ ${tickets.length} tiket berhasil dibaca.\n` +
            "Data sudah dikirim ke Dashboard.",
            100
        );

        sendStatus(
            `✅ ${tickets.length} tiket berhasil dibaca.`,
            100
        );

        await sleep(
            1000
        );

        closeOverlay();

        /*
         * PENTING:
         * Tidak menggunakan window.close().
         *
         * Karena iframe tidak boleh mencoba
         * menutup tab/window user.
         */
        log(
            "Browser Ticket Reader selesai."
        );
    }

    // =========================================================
    // ERROR HANDLER
    // =========================================================

    main()
        .catch(
            e => {
                const message =
                    e?.message ||
                    String(e);

                error(
                    "Fetch gagal:",
                    e
                );

                ensureOverlay();

                setLocalStatus(
                    "❌ Fetch Akun Gagal\n\n" +
                    message,
                    0
                );

                sendError(
                    message
                );
            }
        );

})();