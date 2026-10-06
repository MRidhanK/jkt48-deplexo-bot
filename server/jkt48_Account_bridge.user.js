javascript:(() => {
    "use strict";

    // =========================================================
    // JKT48 TICKET RADAR
    // MOBILE BOOKMARKLET
    // =========================================================
    //
    // Cara:
    // 1. Dashboard membuat URL JKT48 + bridge token.
    // 2. Browser masuk ke jkt48.com.
    // 3. Jalankan bookmarklet ini.
    // 4. Bookmarklet mengambil semua My Tickets.
    // 5. Hasil dikirim ke Ticket Radar.
    // 6. Browser otomatis kembali ke dashboard.
    //
    // Tidak membutuhkan:
    // - Tampermonkey
    // - Extension
    // - iframe
    //
    // =========================================================

    const CONFIG = {

        // -----------------------------------------------------
        // Ticket Radar
        // -----------------------------------------------------

        RADAR_ORIGIN:
            "https://jkt48-deplexo-bot-production.up.railway.app",

        // -----------------------------------------------------
        // Endpoint import
        // -----------------------------------------------------

        IMPORT_PATH:
            "/api/my-tickets/import",

        // -----------------------------------------------------
        // API JKT48
        // -----------------------------------------------------

        SESSION_PATH:
            "/api/auth/session",

        MY_TICKETS_PATH:
            "/api/v1/accounts/my-tickets",

        // -----------------------------------------------------
        // API
        // -----------------------------------------------------

        LANG:
            "id",

        LIMIT:
            10,

        MAX_PAGES:
            100,

        // -----------------------------------------------------
        // Default tanggal
        // -----------------------------------------------------

        DATE_RANGE_DAYS:
            32,

        // -----------------------------------------------------
        // Delay antar halaman
        // -----------------------------------------------------

        PAGE_DELAY:
            250,

        // -----------------------------------------------------
        // Timeout
        // -----------------------------------------------------

        REQUEST_TIMEOUT:
            30000,

        // -----------------------------------------------------
        // Debug
        // -----------------------------------------------------

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

    function clean(value) {

        return String(
            value ?? ""
        ).trim();

    }


    function sleep(ms) {

        return new Promise(
            resolve => {

                setTimeout(
                    resolve,
                    ms
                );

            }
        );

    }


    function parseJSON(text) {

        try {

            return JSON.parse(
                text || "{}"
            );

        } catch {

            return null;

        }

    }


    // =========================================================
    // DATE
    // =========================================================

    function formatDate(date) {

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
            year +
            "-" +
            month +
            "-" +
            day
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
    // PARAMETER DARI URL
    // =========================================================

    function readParams() {

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
                    get(
                        "radar_token"
                    )
                ),

            from:
                clean(
                    get(
                        "from"
                    )
                ) ||
                getDefaultFrom(),

            to:
                clean(
                    get(
                        "to"
                    )
                ) ||
                getDefaultTo(),

            returnUrl:
                clean(
                    get(
                        "radar_return"
                    )
                )

        };

    }


    // =========================================================
    // VALIDATE PARAMETER
    // =========================================================

    function validateParams(
        params
    ) {

        if (
            !params.token
        ) {

            throw new Error(
                "Bridge token tidak ditemukan.\n\n" +
                "Buka Fetch Akun dari Dashboard terlebih dahulu."
            );

        }


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

    }


    // =========================================================
    // SAFE RETURN URL
    // =========================================================

    function getSafeReturnUrl(
        value
    ) {

        const fallback =
            CONFIG.RADAR_ORIGIN +
            "/";


        if (!value) {

            return fallback;

        }


        try {

            const url =
                new URL(
                    value
                );


            /*
             * Hanya izinkan
             * domain Ticket Radar.
             */

            if (
                url.origin !==
                CONFIG.RADAR_ORIGIN
            ) {

                return fallback;

            }


            return url.toString();

        } catch {

            return fallback;

        }

    }


    // =========================================================
    // FETCH WITH TIMEOUT
    // =========================================================

    async function fetchTimeout(
        url,
        options = {}
    ) {

        const controller =
            new AbortController();


        const timer =
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

            clearTimeout(
                timer
            );

        }

    }


    // =========================================================
    // BUILD MY TICKETS URL
    // =========================================================

    function buildMyTicketsUrl(
        page,
        from,
        to
    ) {

        const url =
            new URL(
                CONFIG.MY_TICKETS_PATH,
                location.origin
            );


        url.searchParams.set(
            "lang",
            CONFIG.LANG
        );


        url.searchParams.set(
            "limit",
            String(
                CONFIG.LIMIT
            )
        );


        url.searchParams.set(
            "page",
            String(
                page
            )
        );


        url.searchParams.set(
            "from",
            from
        );


        url.searchParams.set(
            "to",
            to
        );


        return url.toString();

    }


    // =========================================================
    // FETCH SESSION
    // =========================================================

    async function fetchSession() {

        const url =
            new URL(
                CONFIG.SESSION_PATH,
                location.origin
            ).toString();


        log(
            "Session:",
            url
        );


        const response =
            await fetchTimeout(
                url,
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


        const text =
            await response.text();


        const payload =
            parseJSON(
                text
            );


        log(
            "Session HTTP:",
            response.status,
            payload
        );


        if (
            response.status !==
            200
        ) {

            throw new Error(
                "Session JKT48 gagal: HTTP " +
                response.status
            );

        }


        if (
            !payload ||
            !payload.user
        ) {

            throw new Error(
                "Session akun JKT48 tidak ditemukan."
            );

        }


        return payload;

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
         * access_token hanya ada di memory.
         */

        if (
            accessToken
        ) {

            headers.Authorization =
                "Bearer " +
                accessToken;

        }


        log(
            "GET:",
            url
        );


        const response =
            await fetchTimeout(
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


        const text =
            await response.text();


        const payload =
            parseJSON(
                text
            );


        return {

            response,
            payload

        };

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

            page <=
            totalPages &&

            page <=
            CONFIG.MAX_PAGES

        ) {

            const result =
                await fetchMyTicketsPage(
                    page,
                    from,
                    to,
                    accessToken
                );


            const status =
                Number(
                    result.response.status
                );


            log(
                "Page",
                page,
                "HTTP",
                status
            );


            // -------------------------------------------------
            // Cloudflare
            // -------------------------------------------------

            if (
                status ===
                403
            ) {

                throw new Error(
                    "My Tickets HTTP 403.\n\n" +
                    "JKT48/Cloudflare menolak request browser."
                );

            }


            // -------------------------------------------------
            // Unauthorized
            // -------------------------------------------------

            if (
                status ===
                401
            ) {

                throw new Error(
                    "My Tickets HTTP 401.\n\n" +
                    "Session akun JKT48 sudah tidak valid."
                );

            }


            // -------------------------------------------------
            // HTTP error
            // -------------------------------------------------

            if (
                status !==
                200
            ) {

                throw new Error(
                    "My Tickets gagal: HTTP " +
                    status
                );

            }


            // -------------------------------------------------
            // JSON
            // -------------------------------------------------

            if (
                !result.payload
            ) {

                throw new Error(
                    "Response My Tickets bukan JSON valid."
                );

            }


            // -------------------------------------------------
            // API error
            // -------------------------------------------------

            if (
                result.payload.status ===
                false
            ) {

                throw new Error(
                    String(
                        result.payload.message ||
                        "API My Tickets mengembalikan status=false."
                    )
                );

            }


            // -------------------------------------------------
            // RECORD
            // -------------------------------------------------

            const rows =
                Array.isArray(
                    result.payload.data
                )
                    ? result.payload.data.filter(
                        row =>
                            row &&
                            typeof row ===
                            "object"
                    )
                    : [];


            allTickets.push(
                ...rows
            );


            // -------------------------------------------------
            // META
            // -------------------------------------------------

            const meta =
                result.payload._meta ||
                {};


            const total =
                Number(
                    meta.total_page
                );


            if (

                Number.isFinite(
                    total
                ) &&

                total >
                0

            ) {

                totalPages =
                    Math.min(
                        CONFIG.MAX_PAGES,
                        Math.floor(
                            total
                        )
                    );

            } else {

                /*
                 * Fallback:
                 * kalau record kurang dari limit,
                 * berarti halaman terakhir.
                 */

                if (
                    rows.length <
                    CONFIG.LIMIT
                ) {

                    totalPages =
                        page;

                } else {

                    totalPages =
                        page +
                        1;

                }

            }


            log(
                `Page ${page}/${totalPages}`,
                `record=${rows.length}`
            );


            page++;


            if (
                page <=
                totalPages
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
    // DEDUPLICATE
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

            } catch {

                key =
                    "__fallback__" +
                    Math.random();

            }


            if (
                seen.has(
                    key
                )
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
    // SAFE PROFILE
    // =========================================================

    function getSafeProfile(
        session
    ) {

        const profile =
            session?.user?.profile ||
            {};


        /*
         * Hanya data tampilan.
         *
         * Tidak mengirim:
         * - email
         * - phone
         * - address
         * - id_no
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
    // SEND DATA TO RADAR
    // =========================================================

    async function sendToRadar(
        params,
        tickets,
        pagesFetched,
        totalPages,
        session
    ) {

        const url =
            CONFIG.RADAR_ORIGIN +
            CONFIG.IMPORT_PATH;


        const payload = {

            token:
                params.token,

            from:
                params.from,

            to:
                params.to,

            pages_fetched:
                pagesFetched,

            total_pages:
                totalPages,

            fetched_at:
                Math.floor(
                    Date.now() /
                    1000
                ),

            source:
                "jkt48_mobile_bookmarklet",

            profile:
                getSafeProfile(
                    session
                ),

            tickets:
                tickets

        };


        const body =
            JSON.stringify(
                payload
            );


        log(
            "Send ke Radar:",
            {
                tickets:
                    tickets.length,

                pages:
                    pagesFetched
            }
        );


        /*
         * -----------------------------------------------------
         * POST no-cors
         * -----------------------------------------------------
         *
         * Response tidak perlu dibaca.
         *
         * Endpoint backend hanya perlu menerima payload.
         */

        try {

            await fetch(
                url,
                {

                    method:
                        "POST",

                    mode:
                        "no-cors",

                    credentials:
                        "omit",

                    cache:
                        "no-store",

                    headers: {

                        "Content-Type":
                            "text/plain;charset=UTF-8"

                    },

                    body:
                        body

                }
            );


            log(
                "Payload berhasil dikirim via fetch."
            );


            return true;

        } catch (fetchError) {

            warn(
                "Fetch no-cors gagal:",
                fetchError
            );

        }


        /*
         * -----------------------------------------------------
         * Fallback sendBeacon
         * -----------------------------------------------------
         */

        try {

            const blob =
                new Blob(
                    [body],
                    {

                        type:
                            "text/plain;charset=UTF-8"

                    }
                );


            const accepted =
                navigator.sendBeacon(
                    url,
                    blob
                );


            if (
                accepted
            ) {

                log(
                    "Payload diterima sendBeacon."
                );


                return true;

            }

        } catch (beaconError) {

            warn(
                "sendBeacon gagal:",
                beaconError
            );

        }


        throw new Error(
            "Data tiket gagal dikirim ke Ticket Radar."
        );

    }


    // =========================================================
    // CLEAN URL
    // =========================================================

    function cleanHash() {

        try {

            history.replaceState(
                null,
                document.title,
                location.pathname +
                location.search
            );

        } catch {

            // Tidak fatal.

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

            // =================================================
            // 1. PARAMETER
            // =================================================

            const params =
                readParams();


            validateParams(
                params
            );


            log(
                "Fetch dimulai",
                {
                    from:
                        params.from,

                    to:
                        params.to,

                    token:
                        "ADA"
                }
            );


            // =================================================
            // 2. SESSION
            // =================================================

            let session =
                null;


            let accessToken =
                "";


            /*
             * Session digunakan untuk mendapatkan:
             * - profile
             * - access_token
             *
             * Kalau endpoint session 404,
             * proses ticket tetap dicoba.
             */

            try {

                session =
                    await fetchSession();


                accessToken =
                    clean(
                        session?.user?.access_token
                    );


            } catch (sessionError) {

                warn(
                    "Session endpoint gagal.",
                    sessionError
                );

            }


            // =================================================
            // 3. FETCH SEMUA TIKET
            // =================================================

            const result =
                await fetchAllTickets(
                    params.from,
                    params.to,
                    accessToken
                );


            // =================================================
            // 4. DEDUP
            // =================================================

            const tickets =
                deduplicateTickets(
                    result.tickets
                );


            log(
                "Total tiket:",
                tickets.length
            );


            // =================================================
            // 5. SEND KE BACKEND
            // =================================================

            await sendToRadar(
                params,
                tickets,
                result.pagesFetched,
                result.totalPages,
                session
            );


            // =================================================
            // 6. CLEAN URL
            // =================================================

            cleanHash();


            document.title =
                originalTitle;


            // =================================================
            // 7. RETURN URL
            // =================================================

            const returnUrl =
                getSafeReturnUrl(
                    params.returnUrl
                );


            alert(
                "✅ Fetch Akun selesai!\n\n" +
                tickets.length +
                " record tiket berhasil dibaca.\n\n" +
                result.pagesFetched +
                " halaman berhasil diproses.\n\n" +
                "Kembali ke Ticket Radar..."
            );


            // =================================================
            // 8. KEMBALI KE DASHBOARD
            // =================================================

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
                )
            );

        }

    }


    // =========================================================
    // RUN
    // =========================================================

    main();

})();