javascript:(() => {
    "use strict";

    // =========================================================
    // JKT48 TICKET RADAR - MOBILE BOOKMARKLET
    // =========================================================
    //
    // Cara kerja:
    // 1. Dashboard membuat bridge token.
    // 2. Dashboard mengarahkan kamu ke JKT48.
    // 3. Jalankan bookmarklet ini di halaman JKT48.
    // 4. Bookmarklet membaca session akun JKT48.
    // 5. Bookmarklet mengambil seluruh halaman My Tickets.
    // 6. Hasil dikirim ke backend Ticket Radar.
    // 7. Browser kembali ke dashboard.
    //
    // Tidak menggunakan:
    // - Tampermonkey
    // - Extension
    // - iframe
    // - window.open dari script ini
    // - cookie JKT48 yang dikirim ke backend
    //
    // =========================================================


    // =========================================================
    // CONFIG
    // =========================================================

    const CONFIG = {

        // Backend Ticket Radar
        RADAR_ORIGIN:
            "https://jkt48-deplexo-bot-production.up.railway.app",

        // Endpoint import hasil tiket
        IMPORT_PATH:
            "/api/my-tickets/import",

        // API session JKT48
        SESSION_PATH:
            "/api/auth/session",

        // API My Tickets JKT48
        MY_TICKETS_PATH:
            "/api/v1/accounts/my-tickets",

        // Bahasa API
        LANG:
            "id",

        // Record setiap halaman
        LIMIT:
            10,

        // Maksimum halaman
        MAX_PAGES:
            100,

        // Default range tanggal
        DATE_RANGE_DAYS:
            32,

        // Jeda antar halaman
        PAGE_DELAY:
            250,

        // Timeout fetch
        REQUEST_TIMEOUT:
            30000,

        // Debug
        DEBUG:
            true
    };


    // =========================================================
    // LOGGER
    // =========================================================

    function log(...args) {
        if (!CONFIG.DEBUG) {
            return;
        }

        console.log(
            "[JKT48 Ticket Radar]",
            ...args
        );
    }


    function warn(...args) {

        console.warn(
            "[JKT48 Ticket Radar]",
            ...args
        );

    }


    function error(...args) {

        console.error(
            "[JKT48 Ticket Radar]",
            ...args
        );

    }


    // =========================================================
    // HELPER
    // =========================================================

    function sleep(ms) {

        return new Promise(resolve => {
            setTimeout(resolve, ms);
        });

    }


    function clean(value) {

        return String(
            value ?? ""
        ).trim();

    }


    function parseJSON(text) {

        try {

            return JSON.parse(
                text || "{}"
            );

        } catch (e) {

            return null;

        }

    }


    // =========================================================
    // DATE HELPER
    // =========================================================

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
    // READ PARAMETERS
    // =========================================================

    function getParams() {

        const query =
            new URLSearchParams(
                location.search
            );

        const hash =
            new URLSearchParams(
                location.hash.replace(
                    /^#/,
                    ""
                )
            );

        function get(name) {

            return (
                hash.get(name) ||
                query.get(name) ||
                ""
            );

        }

        return {

            token:
                clean(
                    get("radar_token")
                ),

            from:
                clean(
                    get("from")
                ) ||
                getDefaultFrom(),

            to:
                clean(
                    get("to")
                ) ||
                getDefaultTo(),

            returnUrl:
                clean(
                    get("radar_return")
                )

        };

    }


    // =========================================================
    // VALIDATE RETURN URL
    // =========================================================

    function validateReturnUrl(value) {

        const fallback =
            CONFIG.RADAR_ORIGIN + "/";

        if (!value) {
            return fallback;
        }

        try {

            const url =
                new URL(value);

            /*
             * Hanya izinkan kembali ke
             * domain Ticket Radar sendiri.
             */
            if (
                url.origin !==
                CONFIG.RADAR_ORIGIN
            ) {

                warn(
                    "Return URL bukan domain Radar. Menggunakan fallback."
                );

                return fallback;

            }

            return url.toString();

        } catch (e) {

            return fallback;

        }

    }


    // =========================================================
    // FETCH WITH TIMEOUT
    // =========================================================

    async function fetchWithTimeout(
        url,
        options = {}
    ) {

        const controller =
            new AbortController();

        const timeout =
            setTimeout(
                () => {
                    controller.abort();
                },
                CONFIG.REQUEST_TIMEOUT
            );

        try {

            return await fetch(
                url,
                {
                    ...options,
                    signal:
                        controller.signal
                }
            );

        } finally {

            clearTimeout(timeout);

        }

    }


    // =========================================================
    // SESSION JKT48
    // =========================================================

    async function getJKT48Session() {

        log(
            "Membaca session JKT48..."
        );

        const response =
            await fetchWithTimeout(
                CONFIG.SESSION_PATH,
                {
                    method:
                        "GET",

                    credentials:
                        "include",

                    cache:
                        "no-store",

                    headers: {
                        "Accept":
                            "application/json",

                        "Accept-Language":
                            "id-ID,id;q=0.9,en;q=0.8",

                        "Cache-Control":
                            "no-cache",

                        "Pragma":
                            "no-cache"
                    }
                }
            );

        log(
            "Session HTTP:",
            response.status
        );

        if (
            response.status !== 200
        ) {

            throw new Error(
                "Session JKT48 gagal: HTTP " +
                response.status +
                ". Pastikan kamu sudah login di jkt48.com."
            );

        }

        const payload =
            parseJSON(
                await response.text()
            );

        if (
            !payload ||
            !payload.user
        ) {

            throw new Error(
                "Session akun JKT48 tidak ditemukan. " +
                "Silakan login terlebih dahulu."
            );

        }

        return payload;

    }


    // =========================================================
    // BUILD MY TICKETS URL
    // =========================================================

    function buildMyTicketsUrl(
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
            CONFIG.MY_TICKETS_PATH +
            "?" +
            params.toString()
        );

    }


    // =========================================================
    // FETCH ONE PAGE
    // =========================================================

    async function fetchMyTicketsPage(
        page,
        from,
        to,
        accessToken
    ) {

        const url =
            buildMyTicketsUrl(
                page,
                from,
                to
            );

        log(
            "GET My Tickets:",
            url
        );


        const headers = {

            "Accept":
                "application/json, text/plain, */*",

            "Accept-Language":
                "id-ID,id;q=0.9,en;q=0.8",

            "Cache-Control":
                "no-cache",

            "Pragma":
                "no-cache"

        };


        /*
         * Access token hanya berada
         * di memory browser selama proses.
         *
         * Tidak disimpan ke:
         * - localStorage
         * - sessionStorage
         * - cookie
         * - backend Radar
         */

        if (accessToken) {

            headers[
                "Authorization"
            ] =
                "Bearer " +
                accessToken;

        }


        const response =
            await fetchWithTimeout(
                url,
                {

                    method:
                        "GET",

                    credentials:
                        "include",

                    cache:
                        "no-store",

                    headers

                }
            );


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

            if (
                status === 401
            ) {

                throw new Error(
                    "My Tickets HTTP 401. " +
                    "Session akun JKT48 mungkin sudah kedaluwarsa."
                );

            }


            if (
                status === 403
            ) {

                throw new Error(
                    "My Tickets HTTP 403. " +
                    "JKT48/Cloudflare menolak request. " +
                    "Pastikan halaman JKT48 dibuka secara normal dan akun masih login."
                );

            }


            if (
                status === 429
            ) {

                throw new Error(
                    "My Tickets HTTP 429. " +
                    "Request terlalu cepat. Tunggu sebentar lalu ulangi."
                );

            }


            throw new Error(
                "My Tickets gagal: HTTP " +
                status
            );

        }


        const payload =
            parseJSON(
                await response.text()
            );


        if (!payload) {

            throw new Error(
                "Response My Tickets bukan JSON yang valid."
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
        from,
        to,
        accessToken
    ) {

        const allTickets =
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
                    page,
                    from,
                    to,
                    accessToken
                );


            const rows =
                Array.isArray(
                    payload.data
                )
                    ? payload.data.filter(
                        row =>
                            row &&
                            typeof row ===
                            "object"
                    )
                    : [];


            allTickets.push(
                ...rows
            );


            /*
             * API JKT48 menyediakan:
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
                 * Fallback kalau metadata
                 * tidak tersedia.
                 */

                if (
                    rows.length <
                    CONFIG.LIMIT
                ) {

                    totalPages =
                        page;

                } else {

                    totalPages =
                        page + 1;

                }

            }


            log(
                `Page ${page}/${totalPages}`,
                "records:",
                rows.length
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
                allTickets,

            pagesFetched:
                Math.max(
                    1,
                    page - 1
                ),

            totalPages

        };

    }


    // =========================================================
    // REMOVE EXACT DUPLICATES
    // =========================================================

    function deduplicateTickets(
        tickets
    ) {

        const seen =
            new Set();

        const result =
            [];


        for (
            const ticket
            of tickets
        ) {

            let key;


            try {

                key =
                    JSON.stringify(
                        ticket
                    );

            } catch (e) {

                /*
                 * Kalau object gagal stringify,
                 * biarkan record tetap masuk.
                 */

                key =
                    "__UNSERIALIZABLE__" +
                    Math.random();

            }


            if (
                seen.has(key)
            ) {

                continue;

            }


            seen.add(
                key
            );

            result.push(
                ticket
            );

        }


        return result;

    }


    // =========================================================
    // PROFILE
    // =========================================================

    function getSafeProfile(
        session
    ) {

        const profile =
            session?.user?.profile ||
            {};


        /*
         * Hanya nama display.
         *
         * Tidak mengirim:
         * - email
         * - nomor telepon
         * - alamat
         * - NIK / ID
         * - access_token
         * - refresh_token
         */

        return {

            nickname:
                clean(
                    profile.nickname
                ),

            full_name:
                clean(
                    profile.full_name
                )

        };

    }


    // =========================================================
    // SEND RESULT TO RADAR
    // =========================================================

    async function sendResultToRadar(
        params,
        session,
        ticketResult
    ) {

        const importUrl =
            CONFIG.RADAR_ORIGIN +
            CONFIG.IMPORT_PATH;


        const tickets =
            ticketResult.tickets;


        const payload = {

            /*
             * One-time bridge token
             */
            token:
                params.token,

            from:
                params.from,

            to:
                params.to,

            pages_fetched:
                ticketResult.pagesFetched,

            total_pages:
                ticketResult.totalPages,

            fetched_at:
                Math.floor(
                    Date.now() /
                    1000
                ),

            source:
                "jkt48_bookmarklet",

            profile:
                getSafeProfile(
                    session
                ),

            tickets:
                tickets

        };


        log(
            "Mengirim hasil ke Radar:",
            {
                records:
                    tickets.length,

                pages:
                    ticketResult.pagesFetched
            }
        );


        /*
         * Content-Type text/plain sengaja digunakan
         * agar browser tidak melakukan preflight JSON
         * yang tidak diperlukan untuk bridge sederhana.
         *
         * Backend tetap membaca body sebagai JSON.
         */

        const response =
            await fetchWithTimeout(
                importUrl,
                {

                    method:
                        "POST",

                    mode:
                        "cors",

                    credentials:
                        "omit",

                    headers: {

                        "Content-Type":
                            "text/plain;charset=UTF-8",

                        "Accept":
                            "application/json"

                    },

                    body:
                        JSON.stringify(
                            payload
                        )

                }
            );


        log(
            "Import Radar HTTP:",
            response.status
        );


        const responseText =
            await response.text();


        const result =
            parseJSON(
                responseText
            );


        if (
            !response.ok
        ) {

            throw new Error(
                "Import ke Ticket Radar gagal: HTTP " +
                response.status +
                (
                    result?.error
                        ? " — " + result.error
                        : ""
                )
            );

        }


        if (
            !result ||
            result.ok === false
        ) {

            throw new Error(
                result?.error ||
                result?.message ||
                "Server Ticket Radar menolak hasil My Tickets."
            );

        }


        return result;

    }


    // =========================================================
    // CLEAN URL
    // =========================================================

    function cleanJKT48Url() {

        try {

            const cleanUrl =
                location.pathname +
                (
                    location.search
                        ? location.search
                        : ""
                );

            history.replaceState(
                null,
                document.title,
                cleanUrl
            );

        } catch (e) {

            /*
             * Tidak fatal.
             */

        }

    }


    // =========================================================
    // MAIN
    // =========================================================

    async function main() {

        const originalTitle =
            document.title;


        document.title =
            "⏳ Fetch JKT48 → Ticket Radar";


        try {

            // -------------------------------------------------
            // PARAMETER
            // -------------------------------------------------

            const params =
                getParams();


            log(
                "Parameter:",
                {
                    from:
                        params.from,

                    to:
                        params.to,

                    hasToken:
                        Boolean(
                            params.token
                        )
                }
            );


            // -------------------------------------------------
            // VALIDASI TOKEN
            // -------------------------------------------------

            if (
                !params.token
            ) {

                throw new Error(
                    "Bridge token tidak ditemukan.\n\n" +
                    "Buka Fetch Akun dari Dashboard Ticket Radar terlebih dahulu."
                );

            }


            // -------------------------------------------------
            // VALIDASI DATE
            // -------------------------------------------------

            if (
                !/^\d{4}-\d{2}-\d{2}$/.test(
                    params.from
                )
            ) {

                throw new Error(
                    "Tanggal mulai tidak valid."
                );

            }


            if (
                !/^\d{4}-\d{2}-\d{2}$/.test(
                    params.to
                )
            ) {

                throw new Error(
                    "Tanggal akhir tidak valid."
                );

            }


            if (
                params.to <
                params.from
            ) {

                throw new Error(
                    "Tanggal akhir tidak boleh sebelum tanggal mulai."
                );

            }


            // -------------------------------------------------
            // SESSION
            // -------------------------------------------------

            const session =
                await getJKT48Session();


            const profile =
                getSafeProfile(
                    session
                );


            log(
                "Akun terdeteksi:",
                profile.nickname ||
                profile.full_name ||
                "User"
            );


            // -------------------------------------------------
            // ACCESS TOKEN
            // -------------------------------------------------

            /*
             * Access token hanya digunakan
             * selama proses request di memory.
             *
             * Tidak dikirim ke backend Radar.
             */

            const accessToken =
                clean(
                    session?.user?.access_token
                );


            // -------------------------------------------------
            // FETCH ALL MY TICKETS
            // -------------------------------------------------

            const ticketResult =
                await fetchAllTickets(
                    params.from,
                    params.to,
                    accessToken
                );


            // -------------------------------------------------
            // DEDUP
            // -------------------------------------------------

            const tickets =
                deduplicateTickets(
                    ticketResult.tickets
                );


            const finalResult = {

                tickets,

                pagesFetched:
                    ticketResult.pagesFetched,

                totalPages:
                    ticketResult.totalPages

            };


            log(
                "Fetch selesai:",
                {
                    records:
                        tickets.length,

                    pages:
                        finalResult.pagesFetched,

                    totalPages:
                        finalResult.totalPages
                }
            );


            // -------------------------------------------------
            // SEND TO BACKEND
            // -------------------------------------------------

            await sendResultToRadar(
                params,
                session,
                finalResult
            );


            // -------------------------------------------------
            // SUCCESS
            // -------------------------------------------------

            cleanJKT48Url();


            document.title =
                originalTitle;


            const returnUrl =
                validateReturnUrl(
                    params.returnUrl
                );


            alert(
                "✅ Fetch Akun selesai!\n\n" +
                tickets.length +
                " record tiket berhasil dibaca.\n" +
                finalResult.pagesFetched +
                " halaman berhasil diproses.\n\n" +
                "Ticket Radar akan menampilkan Jadwal Saya."
            );


            /*
             * Kembali ke Dashboard.
             */

            location.replace(
                returnUrl
            );

        } catch (e) {

            document.title =
                originalTitle;


            error(
                "Fetch gagal:",
                e
            );


            alert(
                "❌ Fetch Akun gagal\n\n" +
                (
                    e?.message ||
                    String(e)
                ) +
                "\n\n" +
                "Pastikan kamu sudah login ke JKT48 dan ulangi Fetch Akun."
            );

        }

    }


    // =========================================================
    // START
    // =========================================================

    main();

})();