// ==UserScript==
// @name         JKT48 Ticket Radar - Browser Session Fetch
// @namespace    voltvoltre.jkt48.radar
// @version      5.0.0
// @description  Fetch My Tickets JKT48 langsung dari browser tanpa membuka tab, popup, atau iframe
//
// ============================================================
// CONFIG UTAMA
// ============================================================
//
// GANTI domain ini dengan domain dashboard kamu.
//
// Contoh:
// @match https://jkt48-deplexo-bot-production.up.railway.app/
//
// Untuk localhost:
// @match http://localhost:*/*
// @match http://127.0.0.1:*/*
//
// ============================================================
//
// @match        https://jkt48-deplexo-bot-production.up.railway.app/
// @match        http://localhost:*/*
// @match        http://127.0.0.1:*/*
//
// ============================================================
//
// JKT48
// ============================================================
//
// @connect      jkt48.com
//
// ============================================================
//
// Tampermonkey
// ============================================================
//
// @grant        GM_xmlhttpRequest
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const CONFIG = {

        // -----------------------------------------------------
        // Domain JKT48
        // -----------------------------------------------------

        JKT48_ORIGIN:
            "https://jkt48.com",

        // -----------------------------------------------------
        // Endpoint session
        // -----------------------------------------------------

        SESSION_PATH:
            "/api/auth/session",

        // -----------------------------------------------------
        // Endpoint My Tickets
        // -----------------------------------------------------

        MY_TICKETS_PATH:
            "/api/v1/accounts/my-tickets",

        // -----------------------------------------------------
        // Bahasa API
        // -----------------------------------------------------

        LANG:
            "id",

        // -----------------------------------------------------
        // Jumlah record per page
        //
        // API yang kamu tunjukkan:
        // limit=10
        // -----------------------------------------------------

        LIMIT:
            10,

        // -----------------------------------------------------
        // Maksimum page yang boleh dibaca
        // -----------------------------------------------------

        MAX_PAGES:
            100,

        // -----------------------------------------------------
        // Range default
        //
        // Hari mulai = hari ini
        // Hari akhir = +32 hari
        // -----------------------------------------------------

        DATE_RANGE_DAYS:
            32,

        // -----------------------------------------------------
        // Timeout request
        // -----------------------------------------------------

        REQUEST_TIMEOUT:
            30000,

        // -----------------------------------------------------
        // Jeda antar halaman
        // -----------------------------------------------------

        PAGE_DELAY:
            200,

        // -----------------------------------------------------
        // Debug console
        //
        // true  = tampilkan log detail
        // false = log minimal
        // -----------------------------------------------------

        DEBUG:
            true
    };

    // =========================================================
    // CONSTANT
    // =========================================================

    const SOURCE =
        "jkt48-ticket-radar";

    const VERSION =
        "5.0.0";

    // Origin dashboard otomatis mengikuti
    // halaman tempat userscript berjalan.
    const DASHBOARD_ORIGIN =
        location.origin;

    const SESSION_URL =
        CONFIG.JKT48_ORIGIN +
        CONFIG.SESSION_PATH;

    const MY_TICKETS_URL =
        CONFIG.JKT48_ORIGIN +
        CONFIG.MY_TICKETS_PATH;

    // =========================================================
    // STATE
    // =========================================================

    let running =
        false;

    // =========================================================
    // LOGGER
    // =========================================================

    function log(...args) {
        if (
            CONFIG.DEBUG
        ) {
            console.log(
                "[JKT48 Radar]",
                ...args
            );
        }
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
        return new Promise(
            resolve =>
                setTimeout(
                    resolve,
                    ms
                )
        );
    }

    function clean(value) {
        return String(
            value ?? ""
        ).trim();
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
    // DATE
    // =========================================================

    function formatDate(
        date
    ) {
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

        return (
            `${y}-${m}-${d}`
        );
    }

    function getDefaultFrom() {
        return formatDate(
            new Date()
        );
    }

    function getDefaultTo() {
        return formatDate(
            new Date(
                Date.now() +
                CONFIG.DATE_RANGE_DAYS *
                86400000
            )
        );
    }

    // =========================================================
    // SAFE JSON
    // =========================================================

    function parseJSON(
        text
    ) {
        try {
            return JSON.parse(
                text || "{}"
            );
        } catch (
            _
        ) {
            return null;
        }
    }

    // =========================================================
    // DASHBOARD MESSAGE
    // =========================================================

    function sendDashboard(
        type,
        payload = {}
    ) {
        try {

            window.postMessage(
                {
                    source:
                        SOURCE,

                    version:
                        VERSION,

                    type,

                    ...payload
                },

                DASHBOARD_ORIGIN
            );

        } catch (
            e
        ) {

            error(
                "Gagal mengirim message ke dashboard:",
                e
            );

        }
    }

    function sendReady() {

        sendDashboard(
            "ready",
            {
                message:
                    "JKT48 Browser Session Bridge aktif.",

                timestamp:
                    Date.now()
            }
        );

    }

    function sendStatus(
        token,
        message,
        progress = null
    ) {

        sendDashboard(
            "status",
            {
                token,
                message,
                progress
            }
        );

    }

    function sendError(
        token,
        message
    ) {

        sendDashboard(
            "error",
            {
                token,
                error:
                    message
            }
        );

    }

    function sendResult(
        token,
        payload
    ) {

        sendDashboard(
            "result",
            {
                token,
                ...payload
            }
        );

    }

    // =========================================================
    // GM XMLHTTP REQUEST
    // =========================================================

    function request(
        options
    ) {

        return new Promise(
            (
                resolve,
                reject
            ) => {

                GM_xmlhttpRequest({

                    method:
                        options.method ||
                        "GET",

                    url:
                        options.url,

                    /*
                     * Jangan anonymous=true.
                     *
                     * Kita ingin browser mempertahankan
                     * konteks credential/session untuk
                     * request JKT48.
                     */
                    anonymous:
                        false,

                    headers:
                        options.headers ||
                        {},

                    data:
                        options.data,

                    timeout:
                        options.timeout ||
                        CONFIG.REQUEST_TIMEOUT,

                    responseType:
                        "text",

                    onload:
                        response => {

                            resolve(
                                response
                            );

                        },

                    onerror:
                        response => {

                            reject(
                                new Error(
                                    "GM_xmlhttpRequest network error"
                                )
                            );

                        },

                    ontimeout:
                        () => {

                            reject(
                                new Error(
                                    "Request timeout setelah " +
                                    (
                                        options.timeout ||
                                        CONFIG.REQUEST_TIMEOUT
                                    ) +
                                    " ms."
                                )
                            );

                        }

                });

            }
        );

    }

    // =========================================================
    // GET SESSION JKT48
    // =========================================================

    async function getJKT48Session(
        token
    ) {

        sendStatus(
            token,
            "🔐 Membaca session akun JKT48 dari browser…",
            5
        );

        const response =
            await request({

                method:
                    "GET",

                url:
                    SESSION_URL,

                headers: {

                    "Accept":
                        "application/json",

                    "Accept-Language":
                        "id-ID,id;q=0.9,en;q=0.8",

                    "Cache-Control":
                        "no-cache",

                    "Pragma":
                        "no-cache",

                    "Referer":
                        CONFIG.JKT48_ORIGIN +
                        "/my-page"
                }

            });

        log(
            "Session HTTP:",
            response.status
        );

        if (
            Number(
                response.status
            ) !== 200
        ) {

            throw new Error(
                "/api/auth/session gagal. HTTP " +
                response.status
            );

        }

        const payload =
            parseJSON(
                response.responseText
            );

        if (
            !payload ||
            !payload.user
        ) {

            throw new Error(
                "Sesi akun JKT48 tidak ditemukan. " +
                "Pastikan kamu sudah login di JKT48."
            );

        }

        const user =
            payload.user;

        const accessToken =
            clean(
                user.access_token
            );

        if (
            !accessToken
        ) {

            throw new Error(
                "access_token tidak ditemukan pada session JKT48."
            );

        }

        /*
         * Token hanya disimpan dalam memory:
         *
         * const accessToken
         *
         * Tidak:
         * - localStorage
         * - sessionStorage
         * - cookie
         * - backend dashboard
         */
        return {
            user,
            accessToken
        };

    }

    // =========================================================
    // BUILD MY TICKETS URL
    // =========================================================

    function buildMyTicketsURL(
        page,
        from,
        to
    ) {

        const params =
            new URLSearchParams();

        params.set(
            "lang",
            CONFIG.LANG
        );

        params.set(
            "limit",
            String(
                CONFIG.LIMIT
            )
        );

        params.set(
            "page",
            String(page)
        );

        params.set(
            "from",
            from
        );

        params.set(
            "to",
            to
        );

        return (
            MY_TICKETS_URL +
            "?" +
            params.toString()
        );

    }

    // =========================================================
    // FETCH ONE PAGE
    // =========================================================

    async function fetchMyTicketsPage(
        token,
        page,
        from,
        to,
        accessToken
    ) {

        const url =
            buildMyTicketsURL(
                page,
                from,
                to
            );

        const progress =
            clamp(
                10 +
                (
                    page *
                    70 /
                    10
                ),
                10,
                80
            );

        sendStatus(
            token,
            "🎟️ Membaca My Tickets…\n" +
            `Halaman ${page}`,
            progress
        );

        log(
            "GET:",
            url
        );

        const response =
            await request({

                method:
                    "GET",

                url,

                headers: {

                    "Accept":
                        "application/json, text/plain, */*",

                    "Accept-Language":
                        "id-ID,id;q=0.9,en;q=0.8",

                    "Cache-Control":
                        "no-cache",

                    "Pragma":
                        "no-cache",

                    "Referer":
                        CONFIG.JKT48_ORIGIN +
                        "/my-page",

                    /*
                     * API session kamu menunjukkan
                     * access_token.
                     *
                     * Token hanya dipakai untuk
                     * request ke JKT48.
                     */
                    "Authorization":
                        "Bearer " +
                        accessToken
                }

            });

        const status =
            Number(
                response.status
            );

        log(
            "My Tickets HTTP:",
            status,
            "page:",
            page
        );

        if (
            status !== 200
        ) {

            let detail =
                `HTTP ${status}`;

            /*
             * 403 khusus Cloudflare.
             */
            if (
                status === 403
            ) {

                detail +=
                    " — Cloudflare/JKT48 menolak request browser.";

            }

            throw new Error(
                "My Tickets gagal: " +
                detail
            );

        }

        const payload =
            parseJSON(
                response.responseText
            );

        if (
            !payload
        ) {

            throw new Error(
                "Response My Tickets bukan JSON valid."
            );

        }

        if (
            payload.status === false
        ) {

            throw new Error(
                String(
                    payload.message ||
                    "API My Tickets mengembalikan status=false."
                )
            );

        }

        return payload;

    }

    // =========================================================
    // FETCH ALL PAGES
    // =========================================================

    async function fetchAllTickets(
        token,
        from,
        to,
        accessToken
    ) {

        const all =
            [];

        let page =
            1;

        let totalPages =
            1;

        while (
            page <= totalPages &&
            page <= CONFIG.MAX_PAGES
        ) {

            const payload =
                await fetchMyTicketsPage(
                    token,
                    page,
                    from,
                    to,
                    accessToken
                );

            const rows =
                Array.isArray(
                    payload.data
                )
                    ? payload.data
                    : [];

            all.push(
                ...rows.filter(
                    row =>
                        row &&
                        typeof row ===
                        "object"
                )
            );

            /*
             * Baca metadata API:
             *
             * _meta.total_page
             */
            const meta =
                payload._meta ||
                {};

            const parsedTotal =
                Number(
                    meta.total_page
                );

            if (
                Number.isFinite(
                    parsedTotal
                ) &&
                parsedTotal > 0
            ) {

                totalPages =
                    Math.min(
                        CONFIG.MAX_PAGES,
                        Math.floor(
                            parsedTotal
                        )
                    );

            } else {

                /*
                 * Fallback kalau _meta tidak ada.
                 */
                if (
                    rows.length <
                    CONFIG.LIMIT
                ) {
                    break;
                }

                totalPages =
                    page + 1;

            }

            log(
                `Page ${page}/${totalPages}:`,
                rows.length,
                "record"
            );

            page++;

            if (
                page <= totalPages
            ) {

                await sleep(
                    CONFIG.PAGE_DELAY
                );

            }

        }

        return {
            tickets:
                all,

            pages_fetched:
                Math.max(
                    1,
                    page - 1
                ),

            total_pages:
                totalPages
        };

    }

    // =========================================================
    // START FETCH
    // =========================================================

    async function startFetch(
        message
    ) {

        if (
            running
        ) {

            warn(
                "Fetch sedang berjalan."
            );

            return;

        }

        const token =
            clean(
                message?.token
            );

        if (
            !token
        ) {

            warn(
                "Fetch command tanpa token."
            );

            return;

        }

        const from =
            clean(
                message?.from
            ) ||
            getDefaultFrom();

        const to =
            clean(
                message?.to
            ) ||
            getDefaultTo();

        running =
            true;

        try {

            // -------------------------------------------------
            // VALIDATE DATE
            // -------------------------------------------------

            if (
                !/^\d{4}-\d{2}-\d{2}$/.test(
                    from
                ) ||
                !/^\d{4}-\d{2}-\d{2}$/.test(
                    to
                )
            ) {

                throw new Error(
                    "Format tanggal harus YYYY-MM-DD."
                );

            }

            if (
                to < from
            ) {

                throw new Error(
                    "Tanggal akhir tidak boleh sebelum tanggal awal."
                );

            }

            // -------------------------------------------------
            // SESSION
            // -------------------------------------------------

            const session =
                await getJKT48Session(
                    token
                );

            /*
             * Ambil access token hanya
             * dalam memory.
             */
            const accessToken =
                session.accessToken;

            // -------------------------------------------------
            // USER INFO
            // -------------------------------------------------

            const profile =
                session.user?.profile ||
                {};

            sendStatus(
                token,
                "✅ Akun JKT48 terdeteksi.\n" +
                `Halo ${profile.nickname || profile.full_name || "User"}\n` +
                "Membaca My Tickets…",
                8
            );

            // -------------------------------------------------
            // MY TICKETS
            // -------------------------------------------------

            const result =
                await fetchAllTickets(
                    token,
                    from,
                    to,
                    accessToken
                );

            /*
             * Buang duplikat persis.
             */
            const seen =
                new Set();

            const tickets =
                result.tickets.filter(
                    ticket => {

                        let key;

                        try {

                            key =
                                JSON.stringify(
                                    ticket
                                );

                        } catch (
                            _
                        ) {

                            key =
                                String(
                                    Math.random()
                                );

                        }

                        if (
                            seen.has(
                                key
                            )
                        ) {

                            return false;

                        }

                        seen.add(
                            key
                        );

                        return true;

                    }
                );

            // -------------------------------------------------
            // SUCCESS
            // -------------------------------------------------

            sendStatus(
                token,
                `✅ ${tickets.length} record berhasil dibaca.\n` +
                "Mengirim hasil ke Dashboard…",
                92
            );

            /*
             * HANYA data tiket dikirim.
             *
             * Tidak dikirim:
             * - access_token
             * - refresh_token
             * - cookie
             * - cf_clearance
             */
            sendResult(
                token,
                {

                    from,

                    to,

                    pages_fetched:
                        result.pages_fetched,

                    total_pages:
                        result.total_pages,

                    fetched_at:
                        Math.floor(
                            Date.now() /
                            1000
                        ),

                    source:
                        "jkt48_browser_session",

                    profile: {

                        nickname:
                            profile.nickname ||
                            "",

                        full_name:
                            profile.full_name ||
                            ""
                    },

                    tickets

                }
            );

            sendStatus(
                token,
                `✅ Fetch Akun selesai.\n${tickets.length} record diterima Dashboard.`,
                100
            );

            log(
                "Fetch selesai:",
                {
                    records:
                        tickets.length,

                    pages:
                        result.pages_fetched
                }
            );

        } catch (
            e
        ) {

            const message =
                e?.message ||
                String(
                    e
                );

            error(
                "Fetch JKT48 gagal:",
                e
            );

            sendError(
                token,
                message
            );

        } finally {

            running =
                false;

        }

    }

    // =========================================================
    // MESSAGE LISTENER
    // =========================================================

    window.addEventListener(
        "message",
        event => {

            /*
             * Hanya message dari window
             * dashboard itu sendiri.
             */
            if (
                event.source !==
                window
            ) {
                return;
            }

            /*
             * Pastikan origin sama
             * dengan dashboard.
             */
            if (
                event.origin !==
                DASHBOARD_ORIGIN
            ) {
                return;
            }

            const data =
                event.data;

            if (
                !data ||
                data.source !==
                SOURCE
            ) {
                return;
            }

            if (
                data.type !==
                "fetch"
            ) {
                return;
            }

            log(
                "Fetch command diterima."
            );

            startFetch(
                data
            );

        }
    );

    // =========================================================
    // READY
    // =========================================================

    /*
     * Beritahu Dashboard bahwa
     * Tampermonkey sudah aktif.
     */
    sendReady();

    log(
        `Browser Session Bridge ${VERSION} aktif.`
    );

})();