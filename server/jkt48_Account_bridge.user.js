javascript:(() => {
    "use strict";

    // =========================================================
    // JKT48 TICKET RADAR
    // MOBILE BOOKMARKLET
    // =========================================================
    //
    // Jalankan bookmarklet ini ketika sedang berada di:
    // https://jkt48.com/
    //
    // Tidak membutuhkan:
    // - Tampermonkey
    // - Extension
    // - iframe
    //
    // =========================================================


    const CONFIG = {

        // -----------------------------------------------------
        // Backend Ticket Radar
        // -----------------------------------------------------

        RADAR_ORIGIN:
            "https://jkt48-deplexo-bot-production.up.railway.app",

        // -----------------------------------------------------
        // Endpoint import
        // -----------------------------------------------------

        IMPORT_PATH:
            "/api/my-tickets/import",

        // -----------------------------------------------------
        // Endpoint session JKT48
        // -----------------------------------------------------

        SESSION_PATH:
            "/api/auth/session",

        // -----------------------------------------------------
        // Endpoint My Tickets
        // -----------------------------------------------------

        MY_TICKETS_PATH:
            "/api/v1/accounts/my-tickets",

        // -----------------------------------------------------
        // API language
        // -----------------------------------------------------

        LANG:
            "id",

        // -----------------------------------------------------
        // Limit API
        // -----------------------------------------------------

        LIMIT:
            10,

        // -----------------------------------------------------
        // Max page
        // -----------------------------------------------------

        MAX_PAGES:
            100,

        // -----------------------------------------------------
        // Timeout
        // -----------------------------------------------------

        REQUEST_TIMEOUT:
            30000,

        // -----------------------------------------------------
        // Jeda halaman
        // -----------------------------------------------------

        PAGE_DELAY:
            250,

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
    // DATE
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

        return (
            y +
            "-" +
            m +
            "-" +
            d
        );

    }


    function getDefaultFrom() {

        return formatDate(
            new Date()
        );

    }


    function getDefaultTo() {

        const date =
            new Date(
                Date.now() +
                32 *
                86400000
            );

        return formatDate(
            date
        );

    }


    // =========================================================
    // READ TOKEN / DATE FROM URL
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
    // VALIDATE PARAMETER
    // =========================================================

    function validateParams(params) {

        if (!params.token) {

            throw new Error(
                "Bridge token tidak ditemukan.\n\n" +
                "Tekan Fetch Akun dari Dashboard Ticket Radar terlebih dahulu."
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
             * Jangan izinkan redirect
             * ke domain lain.
             */

            if (
                url.origin !==
                CONFIG.RADAR_ORIGIN
            ) {

                warn(
                    "Return URL bukan domain Radar."
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
    // BUILD API URL
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
    // GET SESSION
    // =========================================================

    async function getSession() {

        const url =
            new URL(
                CONFIG.SESSION_PATH,
                location.origin
            ).toString();


        log(
            "GET session:",
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
            "Session:",
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
                "Akun JKT48 tidak terdeteksi."
            );

        }


        return payload;

    }


    // =========================================================
    // FETCH ONE PAGE
    // =========================================================

    async function getMyTicketsPage(
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
         * Token hanya hidup
         * selama script berjalan.
         */

        if (
            accessToken
        ) {

            headers[
                "Authorization"
            ] =
                "Bearer " +
                accessToken;

        }


        log(
            "GET My Tickets:",
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


        log(
            "My Tickets:",
            response.status,
            "page:",
            page,
            payload
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

        let page =
            1;

        let totalPages =
            1;

        const allTickets =
            [];


        while (

            page <=
            totalPages &&

            page <=
            CONFIG.MAX_PAGES

        ) {


            const result =
                await getMyTicketsPage(
                    page,
                    from,
                    to,
                    accessToken
                );


            const status =
                Number(
                    result.response.status
                );


            /*
             * Cloudflare / forbidden.
             */

            if (
                status === 403
            ) {

                throw new Error(
                    "My Tickets HTTP 403.\n\n" +
                    "JKT48/Cloudflare menolak request browser."
                );

            }


            /*
             * Session expired.
             */

            if (
                status === 401
            ) {

                throw new Error(
                    "My Tickets HTTP 401.\n\n" +
                    "Session akun JKT48 sudah tidak valid."
                );

            }


            /*
             * Error lain.
             */

            if (
                status !== 200
            ) {

                throw new Error(
                    "My Tickets gagal: HTTP " +
                    status
                );

            }


            if (
                !result.payload
            ) {

                throw new Error(
                    "Response My Tickets bukan JSON valid."
                );

            }


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


            /*
             * Data tiket.
             */

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


            /*
             * Baca _meta.total_page.
             */

            const meta =
                result.payload._meta ||
                {};


            const parsedTotal =
                Number(
                    meta.total_page
                );


            if (

                Number.isFinite(
                    parsedTotal
                ) &&

                parsedTotal >
                0

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
                 * Fallback.
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
                "Progress:",
                page +
                "/" +
                totalPages,
                "records:",
                rows.length
            );


            page++;


            /*
             * Jangan terlalu cepat.
             */

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

            totalPages:
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

            } catch (e) {

                key =
                    "__UNSERIALIZABLE__" +
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

    function safeProfile(
        session
    ) {

        const profile =
            session?.user?.profile ||
            {};


        /*
         * Hanya data display.
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
    // SEND RESULT
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
                safeProfile(
                    session
                ),

            /*
             * Yang dikirim hanya tiket.
             */

            tickets:
                tickets

        };


        const body =
            JSON.stringify(
                payload
            );


        log(
            "Mengirim:",
            {
                records:
                    tickets.length,

                pages:
                    pagesFetched
            }
        );


        /*
         * -----------------------------------------------------
         * Cara utama:
         *
         * fetch POST no-cors.
         *
         * Karena response tidak perlu dibaca,
         * browser tidak membutuhkan CORS response header
         * untuk menyelesaikan request.
         * -----------------------------------------------------
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
                "POST no-cors terkirim."
            );


            return true;

        } catch (e) {

            warn(
                "fetch no-cors gagal:",
                e
            );

        }


        /*
         * -----------------------------------------------------
         * Fallback sendBeacon.
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
                    "sendBeacon diterima browser."
                );

                return true;

            }

        } catch (e) {

            warn(
                "sendBeacon gagal:",
                e
            );

        }


        throw new Error(
            "Hasil tiket gagal dikirim ke Ticket Radar."
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

        } catch (e) {

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
            "⏳ JKT48 Radar Fetch...";


        try {

            // -------------------------------------------------
            // PARAMETER
            // -------------------------------------------------

            const params =
                readParams();


            validateParams(
                params
            );


            log(
                "Parameter:",
                {

                    from:
                        params.from,

                    to:
                        params.to,

                    token:
                        "ADA"

                }
            );


            // -------------------------------------------------
            // SESSION
            // -------------------------------------------------

            let session =
                null;


            let accessToken =
                "";


            /*
             * Session terlebih dahulu.
             */

            try {

                session =
                    await getSession();


                accessToken =
                    clean(
                        session?.user?.access_token
                    );

            } catch (sessionError) {

                /*
                 * Jangan langsung berhenti.
                 *
                 * Kita masih mencoba My Tickets
                 * menggunakan cookie browser.
                 */

                warn(
                    "Session endpoint gagal, tetap mencoba My Tickets.",
                    sessionError
                );

            }


            // -------------------------------------------------
            // FETCH MY TICKETS
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


            log(
                "Fetch selesai:",
                {

                    records:
                        tickets.length,

                    pages:
                        ticketResult.pagesFetched,

                    totalPages:
                        ticketResult.totalPages

                }
            );


            // -------------------------------------------------
            // SEND TO SERVER
            // -------------------------------------------------

            await sendToRadar(
                params,
                tickets,
                ticketResult.pagesFetched,
                ticketResult.totalPages,
                session
            );


            // -------------------------------------------------
            // SUCCESS
            // -------------------------------------------------

            cleanHash();


            document.title =
                originalTitle;


            const returnUrl =
                getSafeReturnUrl(
                    params.returnUrl
                );


            alert(
                "✅ Fetch Akun selesai!\n\n" +

                tickets.length +
                " record tiket berhasil dibaca.\n" +

                ticketResult.pagesFetched +
                " halaman berhasil diproses.\n\n" +

                "Data sudah dikirim ke Ticket Radar."
            );


            /*
             * Kembali ke dashboard.
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
                )
            );

        }

    }


    // =========================================================
    // START
    // =========================================================

    main();

})();