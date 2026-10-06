// ==UserScript==
// @name         JKT48 Ticket Radar - Browser Ticket Reader
// @namespace    voltvoltre.jkt48.radar
// @version      3.1.0
// @description  Membaca tiket dari My Page JKT48 di browser dan mengirim hasilnya ke Dashboard Radar tanpa membuka tab baru
// @match        https://jkt48.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    // =========================================================
    // CONFIGURATION
    // =========================================================

    const params = new URLSearchParams(
        window.location.search
    );

    /*
     * Script HANYA dijalankan ketika dashboard
     * memanggil halaman JKT48 sebagai browser bridge.
     */
    if (
        params.get("radar_fetch") !== "1"
    ) {
        return;
    }

    /*
     * Temporary bridge token.
     *
     * INI BUKAN:
     * - access_token
     * - refresh_token
     * - cf_clearance
     *
     * Token ini hanya untuk mencocokkan
     * request dengan dashboard.
     */
    const bridgeToken =
        params.get("token") || "";

    /*
     * Origin dashboard.
     *
     * Contoh:
     * https://radar.example.com
     */
    const parentOrigin =
        params.get("parent_origin") || "";

    /*
     * Range tanggal.
     */
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

    // =========================================================
    // VALIDATION
    // =========================================================

    if (
        !bridgeToken
    ) {
        console.error(
            "[JKT48 Radar] Bridge token tidak ditemukan."
        );
        return;
    }

    if (
        !parentOrigin
    ) {
        console.error(
            "[JKT48 Radar] Parent origin tidak ditemukan."
        );
        return;
    }

    // =========================================================
    // LOGGER
    // =========================================================

    function log(
        ...args
    ) {
        console.log(
            "[JKT48 Radar]",
            ...args
        );
    }

    function warn(
        ...args
    ) {
        console.warn(
            "[JKT48 Radar]",
            ...args
        );
    }

    function error(
        ...args
    ) {
        console.error(
            "[JKT48 Radar]",
            ...args
        );
    }

    // =========================================================
    // HELPERS
    // =========================================================

    function sleep(
        ms
    ) {
        return new Promise(
            resolve =>
                setTimeout(
                    resolve,
                    ms
                )
        );
    }

    function cleanText(
        value
    ) {
        return String(
            value ?? ""
        )
            .replace(
                /\u00a0/g,
                " "
            )
            .replace(
                /\s+/g,
                " "
            )
            .trim();
    }

    function normalizeText(
        value
    ) {
        return cleanText(
            value
        )
            .toLowerCase()
            .replace(
                /[–—]/g,
                "-"
            );
    }

    function formatDate(
        date
    ) {
        const year =
            date.getFullYear();

        const month =
            String(
                date.getMonth() + 1
            ).padStart(
                2,
                "0"
            );

        const day =
            String(
                date.getDate()
            ).padStart(
                2,
                "0"
            );

        return (
            `${year}-${month}-${day}`
        );
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
    // PARENT COMMUNICATION
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
                warn(
                    "Parent window tidak tersedia."
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

        } catch (
            e
        ) {
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
    // OPTIONAL LOCAL DEBUG OVERLAY
    // =========================================================

    /*
     * Ketika halaman JKT48 dijalankan sebagai iframe tersembunyi,
     * overlay juga tersembunyi.
     *
     * Kalau userscript dibuka secara manual,
     * overlay akan membantu debugging.
     */

    function ensureOverlay() {
        let overlay =
            document.getElementById(
                "jkt48-radar-reader-overlay"
            );

        if (
            overlay
        ) {
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

                background:
                    rgba(0, 0, 0, .18);

                backdrop-filter:
                    blur(6px);
            }

            #jkt48-radar-reader-card {
                width:
                    min(
                        460px,
                        calc(100vw - 32px)
                    );

                padding: 28px;

                border-radius: 22px;

                background:
                    #ffffff;

                box-shadow:
                    0 25px 80px
                    rgba(0,0,0,.25);

                text-align:
                    center;

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

                color:
                    #111827;

                margin-bottom: 8px;
            }

            #jkt48-radar-reader-status {
                font-size: 14px;
                line-height: 1.5;

                color:
                    #6b7280;

                white-space:
                    pre-line;
            }

            #jkt48-radar-reader-progress {
                width: 100%;
                height: 7px;

                margin-top: 20px;

                overflow:
                    hidden;

                border-radius:
                    999px;

                background:
                    #f1f1f1;
            }

            #jkt48-radar-reader-progress > div {
                height: 100%;
                width: 0%;

                border-radius:
                    inherit;

                background:
                    #ef233c;

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

        if (
            status
        ) {
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

        if (
            overlay
        ) {
            overlay.remove();
        }
    }

    // =========================================================
    // MONTH MAP
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
         * Contoh:
         *
         * SUN, OCT 11, 2026
         * SAT, OCT 24, 2026
         */

        let match =
            value.match(
                /(?:MON|TUE|WED|THU|FRI|SAT|SUN)[,.\s-]*(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)[,\s]+(\d{1,2})[,\s]+(\d{4})/i
            );

        /*
         * Fallback:
         *
         * OCT 24, 2026
         */
        if (
            !match
        ) {
            match =
                value.match(
                    /\b(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)[,\s]+(\d{1,2})[,\s]+(\d{4})\b/i
                );
        }

        if (
            !match
        ) {
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

        /*
         * Validasi date.
         */
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
            normalizeText(
                text
            );

        /*
         * Urutan penting.
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
            t.includes(
                "2shot"
            ) ||
            t.includes(
                "2 shot"
            )
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
    // TIME PARSER
    // =========================================================

    function extractTime(
        text
    ) {
        const value =
            cleanText(
                text
            );

        const match =
            value.match(
                /\b(\d{1,2})[:.](\d{2})\s*[–—-]\s*(\d{1,2})[:.](\d{2})\b/
            );

        if (
            !match
        ) {
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
    // RECEPTION PARSER
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

        if (
            !match
        ) {
            return {
                reception_start_time: "",
                reception_end_time: ""
            };
        }

        return {
            reception_start_time:
                `${match[1].padStart(2, "0")}:${match[2]}`,

            reception_end_time:
                match[3] &&
                match[4]
                    ? `${match[3].padStart(2, "0")}:${match[4]}`
                    : ""
        };
    }

    // =========================================================
    // SESSION PARSER
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

        if (
            !match
        ) {
            return "";
        }

        return (
            "Sesi " +
            match[1]
        );
    }

    // =========================================================
    // LANE PARSER
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

        if (
            !match
        ) {
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

        if (
            match
        ) {
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

        if (
            match
        ) {
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

        if (
            match
        ) {
            return Number(
                match[1]
            );
        }

        return 1;
    }

    // =========================================================
    // NAME VALIDATION
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
            "THEATRE SHOW",
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
            "MIXED",
            "SHOW"
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
                    upper.includes(
                        item
                    )
            )
        ) {
            return false;
        }

        if (
            /^\d/.test(
                text
            )
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
         * Nama:
         * huruf
         * spasi
         * titik
         * apostrof
         * minus
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

    // =========================================================
    // MEMBER NAME
    // =========================================================

    function guessMemberName(
        container,
        category
    ) {
        if (
            !container
        ) {
            return "";
        }

        if (
            category !== "MNG" &&
            category !== "2SHOT" &&
            category !== "VC"
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
                const text =
                    cleanText(
                        node.innerText
                    );

                if (
                    looksLikeMemberName(
                        text
                    )
                ) {
                    candidates.push(
                        text
                    );
                }
            }
        }

        if (
            candidates.length
        ) {
            return candidates[0];
        }

        /*
         * Fallback:
         * cari berdasarkan baris.
         */
        const lines =
            String(
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
            !text
        ) {
            return "";
        }

        const lines =
            text
                .split(/\n+/)
                .map(
                    cleanText
                )
                .filter(Boolean);

        /*
         * M&G / 2SHOT / VC.
         */
        if (
            category === "MNG" ||
            category === "2SHOT" ||
            category === "VC"
        ) {
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

                if (
                    /photocard/i.test(
                        line
                    )
                ) {
                    return line;
                }
            }
        }

        /*
         * SHOW.
         */
        const headings =
            Array.from(
                container.querySelectorAll(
                    "h1,h2,h3,h4,h5,h6"
                )
            )
                .map(
                    node =>
                        cleanText(
                            node.innerText
                        )
                )
                .filter(Boolean);

        for (
            const heading
            of headings
        ) {
            if (
                !/sesi|lane|meet & greet|meet and greet|2shot|reception|pending|mixed/i.test(
                    heading
                )
            ) {
                return heading;
            }
        }

        return "";
    }

    // =========================================================
    // TICKET SIGNAL
    // =========================================================

    function hasTicketSignals(
        text
    ) {
        const t =
            cleanText(
                text
            );

        const signals = [
            /\b\d+\s+TICKETS?\b/i,
            /\b\d+\s+ENTR(?:Y|IES)\b/i,
            /\b\d+\s+tiket\b/i,
            /\bSesi\s+\d+\b/i,
            /\bLane\s+\d+\b/i,
            /meet\s*&\s*greet/i,
            /meet and greet/i,
            /\b2\s*shot\b/i,
            /virtual call/i,
            /video call/i,
            /theater show/i,
            /theatre show/i,
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
         * Naik beberapa level.
         */
        for (
            let i = 0;
            i < 10 &&
            current;
            i++
        ) {
            const text =
                cleanText(
                    current.innerText ||
                    ""
                );

            /*
             * Card yang masuk akal:
             * tidak terlalu kecil
             * tidak terlalu besar
             */
            if (
                text.length >= 60 &&
                text.length <= 6000 &&
                parseDateFromText(
                    text
                ) &&
                hasTicketSignals(
                    text
                )
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
    // FIND CARDS
    // =========================================================

    function findTicketCards() {
        const elements =
            Array.from(
                document.querySelectorAll(
                    "article,section,li,div"
                )
            );

        const roots =
            new Set();

        for (
            const element
            of elements
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

        const candidates =
            Array.from(
                roots
            );

        /*
         * Buang parent yang hanya
         * mengandung card lain.
         */
        const cards =
            candidates.filter(
                card =>
                    !candidates.some(
                        other =>
                            other !== card &&
                            other.contains(
                                card
                            )
                    )
            );

        /*
         * Safety dedupe berdasarkan DOM.
         */
        return Array.from(
            new Set(
                cards
            )
        );
    }

    // =========================================================
    // PARSE ONE CARD
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
         * Jangan ambil sesuatu yang terlalu samar.
         */
        const hasStrongSignal =
            category !== "OTHER" ||
            Boolean(
                session
            ) ||
            Boolean(
                lane
            );

        if (
            !hasStrongSignal
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
    // DEDUPE TICKETS
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
                !map.has(
                    key
                )
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
    // WAIT DOM
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
         * Tunggu framework JKT48 selesai render.
         */
        await sleep(
            1200
        );
    }

    // =========================================================
    // WAIT TICKET CONTENT
    // =========================================================

    async function waitForTicketContent() {
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

            /*
             * Minimal harus ada tanggal
             * dan salah satu ticket signal.
             */
            const hasDate =
                Boolean(
                    parseDateFromText(
                        bodyText
                    )
                );

            const hasSignal =
                hasTicketSignals(
                    bodyText
                );

            if (
                hasDate &&
                hasSignal
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
    // SCROLL
    // =========================================================

    async function scrollAll() {
        let lastHeight =
            0;

        let stableRounds =
            0;

        const maxRounds =
            35;

        for (
            let round = 0;
            round < maxRounds;
            round++
        ) {
            const height =
                document.documentElement
                    .scrollHeight;

            const progress =
                Math.min(
                    70,
                    15 +
                    round * 2
                );

            const message =
                "Membaca seluruh daftar tiket…\n" +
                `Memuat bagian ${round + 1}/${maxRounds}`;

            setLocalStatus(
                message,
                progress
            );

            sendStatus(
                message,
                progress
            );

            window.scrollTo(
                0,
                height
            );

            await sleep(
                700
            );

            const newHeight =
                document.documentElement
                    .scrollHeight;

            if (
                newHeight === lastHeight
            ) {
                stableRounds++;
            } else {
                stableRounds = 0;
            }

            lastHeight =
                newHeight;

            /*
             * Tiga kali sama berarti
             * kemungkinan sudah sampai bawah.
             */
            if (
                stableRounds >= 3
            ) {
                break;
            }
        }

        window.scrollTo(
            0,
            0
        );

        await sleep(
            500
        );
    }

    // =========================================================
    // TRY LOAD MORE
    // =========================================================

    async function tryLoadMore() {
        const elements =
            Array.from(
                document.querySelectorAll(
                    "button,a"
                )
            );

        const candidates =
            elements.filter(
                element => {
                    const text =
                        cleanText(
                            element.innerText
                        );

                    return (
                        /load more/i.test(
                            text
                        ) ||
                        /lihat lebih/i.test(
                            text
                        ) ||
                        /selanjutnya/i.test(
                            text
                        ) ||
                        /berikutnya/i.test(
                            text
                        ) ||
                        /\bnext\b/i.test(
                            text
                        )
                    );
                }
            );

        const button =
            candidates[0];

        if (
            !button
        ) {
            return false;
        }

        if (
            button.disabled
        ) {
            return false;
        }

        /*
         * Jangan klik kalau element memang
         * tidak terlihat.
         */
        const rect =
            button.getBoundingClientRect();

        if (
            rect.width === 0 ||
            rect.height === 0
        ) {
            return false;
        }

        try {
            button.click();

            await sleep(
                1300
            );

            return true;

        } catch (
            e
        ) {
            warn(
                "Load more gagal:",
                e
            );

            return false;
        }
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

        const found =
            await waitForTicketContent();

        if (
            !found
        ) {
            /*
             * Tidak langsung gagal.
             *
             * Beri kesempatan page melakukan
             * client-side rendering.
             */
            await sleep(
                2000
            );
        }

        // -----------------------------------------------------
        // LOAD CONTENT
        // -----------------------------------------------------

        await scrollAll();

        // -----------------------------------------------------
        // TRY PAGINATION / LOAD MORE
        // -----------------------------------------------------

        for (
            let i = 0;
            i < 5;
            i++
        ) {
            const loaded =
                await tryLoadMore();

            if (
                !loaded
            ) {
                break;
            }

            await sleep(
                500
            );

            await scrollAll();
        }

        // -----------------------------------------------------
        // PARSE
        // -----------------------------------------------------

        setLocalStatus(
            "Menganalisis card tiket…",
            75
        );

        sendStatus(
            "Menganalisis card tiket…",
            75
        );

        await sleep(
            500
        );

        const cards =
            findTicketCards();

        log(
            "Candidate cards:",
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
                const result =
                    parseCard(
                        cards[i]
                    );

                if (
                    result
                ) {
                    parsed.push(
                        result
                    );
                }

            } catch (
                e
            ) {
                warn(
                    "Card parse error:",
                    e
                );
            }
        }

        const tickets =
            dedupeTickets(
                parsed
            );

        /*
         * Urutan:
         * date
         * start_time
         * category
         * member
         */
        tickets.sort(
            (
                a,
                b
            ) => {
                const left =
                    [
                        a.date,
                        a.start_time ||
                            "00:00",
                        a.category,
                        a.member_name ||
                            ""
                    ].join(
                        " "
                    );

                const right =
                    [
                        b.date,
                        b.start_time ||
                            "00:00",
                        b.category,
                        b.member_name ||
                            ""
                    ].join(
                        " "
                    );

                return left.localeCompare(
                    right
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
            "🎟️ Menyiapkan browser reader…",
            2
        );

        sendStatus(
            "🎟️ Menyiapkan browser reader…",
            2
        );

        /*
         * Pastikan document siap.
         */
        if (
            !document.body
        ) {
            await waitForDomReady();
        }

        // -----------------------------------------------------
        // SESSION
        // -----------------------------------------------------

        setLocalStatus(
            "🔐 Menggunakan sesi browser JKT48…",
            5
        );

        sendStatus(
            "🔐 Menggunakan sesi browser JKT48…",
            5
        );

        /*
         * TIDAK:
         * - mengambil access_token
         * - mengambil refresh_token
         * - membaca document.cookie
         * - membaca cf_clearance
         *
         * Browser sendiri yang membawa session saat
         * halaman JKT48 dimuat.
         */

        await sleep(
            800
        );

        // -----------------------------------------------------
        // READ
        // -----------------------------------------------------

        const tickets =
            await readTickets();

        log(
            "Final ticket count:",
            tickets.length
        );

        log(
            "Tickets:",
            tickets
        );

        // -----------------------------------------------------
        // EMPTY
        // -----------------------------------------------------

        if (
            !tickets.length
        ) {
            throw new Error(
                "Tidak menemukan tiket pada halaman My Page JKT48. " +
                "Pastikan jadwal tiket sudah tampil dan halaman tidak sedang loading."
            );
        }

        // -----------------------------------------------------
        // SEND
        // -----------------------------------------------------

        const message =
            `✅ ${tickets.length} tiket berhasil dibaca.\n` +
            "Mengirim hasil ke Dashboard Radar…";

        setLocalStatus(
            message,
            90
        );

        sendStatus(
            message,
            90
        );

        /*
         * HANYA DATA TIKET.
         *
         * Tidak ada credential akun.
         */
        sendParentMessage(
            "result",
            {
                from,

                to,

                fetched_at:
                    Math.floor(
                        Date.now() /
                        1000
                    ),

                source:
                    "jkt48_browser_dom",

                tickets
            }
        );

        // -----------------------------------------------------
        // FINISH
        // -----------------------------------------------------

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

        /*
         * Jangan:
         *
         * window.close()
         *
         * window.open()
         *
         * location.href = ...
         *
         * Karena iframe harus tetap menjadi
         * bagian dari dashboard.
         */
        closeOverlay();

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