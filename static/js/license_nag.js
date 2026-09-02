/**
 * Pubs supporter MetaKavita (v1) — overlays rares → Buy Me a Coffee.
 * Pas de licence / Lemon. Classe .license = hook CSS futur.
 * Échec du module = no-op : ne doit jamais bloquer batch / MR.
 */
(function () {
    "use strict";

    var BMC_URL = "https://buymeacoffee.com/raukorim";
    var HONEYMOON_DAYS = 7;
    var MAX_NAGS_PER_DAY = 2;
    var HONOR_SNOOZE_DAYS = 30;
    var BMC_COOLDOWN_MS = 10 * 60 * 1000;
    var CONTINUE_DELAY_MS = 2500;
    var MIN_ACTIVITY_THRESHOLD = 10;
    var MILESTONE_SERIES = 100;
    var MILESTONE_REVIEWS = 50;

    var KEYS = {
        firstVisit: "mk_nag_first_visit",
        day: "mk_nag_day",
        lastVariant: "mk_nag_last_variant",
        shownCount: "mk_nag_shown_count",
        honorUntil: "mk_nag_honor_until",
        bmcClicked: "mk_nag_bmc_clicked_at",
        lifetimeSeries: "mk_nag_lifetime_series",
        lifetimeReviews: "mk_nag_lifetime_reviews",
        milestonesShown: "mk_nag_milestones_shown"
    };

    var continueTimer = null;
    var visible = false;
    /** Évite de recompter les confirms MR à chaque réouverture du récap. */
    var mrLifetimeNoted = false;

    function t(key, fallback) {
        try {
            return (window.AppTranslations && window.AppTranslations[key]) || fallback || key;
        } catch (e) {
            return fallback || key;
        }
    }

    function safeStorageGet(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    function safeStorageSet(key, value) {
        try {
            localStorage.setItem(key, value);
            return true;
        } catch (e) {
            return false;
        }
    }

    function todayIso() {
        var d = new Date();
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
    }

    function pad(n) {
        return n < 10 ? "0" + n : String(n);
    }

    function parseDay(iso) {
        if (!iso) return null;
        var m = String(iso).slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!m) return null;
        return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
    }

    function daysBetween(a, b) {
        return Math.floor((b.getTime() - a.getTime()) / 86400000);
    }

    function ensureFirstVisit() {
        var existing = safeStorageGet(KEYS.firstVisit);
        if (existing) return String(existing).slice(0, 10);
        var day = todayIso();
        safeStorageSet(KEYS.firstVisit, day);
        return day;
    }

    function inHoneymoon() {
        var start = parseDay(ensureFirstVisit());
        if (!start) return true;
        return daysBetween(start, parseDay(todayIso())) < HONEYMOON_DAYS;
    }

    function honorSnoozed() {
        var until = safeStorageGet(KEYS.honorUntil);
        if (!until) return false;
        var ts = Date.parse(until);
        if (isNaN(ts)) return false;
        return Date.now() < ts;
    }

    function setHonorSnooze() {
        var until = new Date(Date.now() + HONOR_SNOOZE_DAYS * 86400000);
        safeStorageSet(KEYS.honorUntil, until.toISOString());
    }

    function bmcCooldownActive() {
        var last = safeStorageGet(KEYS.bmcClicked);
        if (!last) return false;
        var ts = Date.parse(last);
        if (isNaN(ts)) return false;
        return Date.now() - ts < BMC_COOLDOWN_MS;
    }

    function markBmcClick() {
        safeStorageSet(KEYS.bmcClicked, new Date().toISOString());
    }

    function dayBucket() {
        var day = todayIso();
        var raw = safeStorageGet(KEYS.day);
        var bucket = null;
        try {
            bucket = raw ? JSON.parse(raw) : null;
        } catch (e) {
            bucket = null;
        }
        if (!bucket || bucket.day !== day) {
            bucket = { day: day, count: 0, sources: [] };
            safeStorageSet(KEYS.day, JSON.stringify(bucket));
        }
        return bucket;
    }

    function nagsToday() {
        var b = dayBucket();
        return Math.max(0, parseInt(b.count, 10) || 0);
    }

    function recordNagShown(variant, source) {
        var b = dayBucket();
        b.count = (parseInt(b.count, 10) || 0) + 1;
        if (!Array.isArray(b.sources)) b.sources = [];
        b.sources.push(source);
        safeStorageSet(KEYS.day, JSON.stringify(b));
        safeStorageSet(KEYS.lastVariant, variant);
        var n = parseInt(safeStorageGet(KEYS.shownCount) || "0", 10) || 0;
        safeStorageSet(KEYS.shownCount, String(n + 1));
    }

    function lifetimeActivity() {
        var series = parseInt(safeStorageGet(KEYS.lifetimeSeries) || "0", 10) || 0;
        var reviews = parseInt(safeStorageGet(KEYS.lifetimeReviews) || "0", 10) || 0;
        return series + reviews;
    }

    function hasMinimumActivity() {
        return lifetimeActivity() >= MIN_ACTIVITY_THRESHOLD;
    }

    function canShowOverlay() {
        if (inHoneymoon()) return false;
        if (!hasMinimumActivity()) return false;
        if (honorSnoozed()) return false;
        if (bmcCooldownActive()) return false;
        if (nagsToday() >= MAX_NAGS_PER_DAY) return false;
        return true;
    }

    function isRichMrSession(ctx) {
        var done = parseInt(ctx.done, 10) || 0;
        var edits = parseInt(ctx.edits, 10) || 0;
        var fusions = parseInt(ctx.fusions, 10) || 0;
        var researches = parseInt(ctx.researches, 10) || 0;
        var weak = parseInt(ctx.weak_picks, 10) || 0;
        var craft = edits + fusions + researches;
        if (done >= 8) return true;
        if (done >= 5 && craft >= 2) return true;
        if (done >= 3 && (fusions >= 1 || researches >= 2 || weak >= 2)) return true;
        var ach = String(ctx.achievement_id || "");
        if (ach && ach !== "empty_session" && ach !== "warmup") {
            return done >= 4;
        }
        return false;
    }

    function bumpLifetime(key, delta) {
        var n = parseInt(safeStorageGet(key) || "0", 10) || 0;
        n += Math.max(0, delta || 0);
        safeStorageSet(key, String(n));
        return n;
    }

    function milestonesShownSet() {
        try {
            var raw = safeStorageGet(KEYS.milestonesShown);
            var arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function markMilestone(id) {
        var arr = milestonesShownSet();
        if (arr.indexOf(id) === -1) {
            arr.push(id);
            safeStorageSet(KEYS.milestonesShown, JSON.stringify(arr));
        }
    }

    function noteLifetime(ctx) {
        if (!ctx) return;
        if (ctx.source === "batch") {
            bumpLifetime(KEYS.lifetimeSeries, parseInt(ctx.series_count, 10) || 0);
        } else if (ctx.source === "mr_recap") {
            if (mrLifetimeNoted) return;
            mrLifetimeNoted = true;
            bumpLifetime(KEYS.lifetimeReviews, parseInt(ctx.done, 10) || 0);
        } else if (ctx.source === "workshop") {
            bumpLifetime(KEYS.lifetimeSeries, parseInt(ctx.series_count, 10) || 0);
            bumpLifetime(KEYS.lifetimeReviews, parseInt(ctx.volumes_count, 10) || 0);
        }
    }

    function resetMrLifetimeNote() {
        mrLifetimeNoted = false;
    }

    function detectMilestone(ctx) {
        var shown = milestonesShownSet();
        var lifeSeries = parseInt(safeStorageGet(KEYS.lifetimeSeries) || "0", 10) || 0;
        var lifeReviews = parseInt(safeStorageGet(KEYS.lifetimeReviews) || "0", 10) || 0;
        if (lifeSeries >= MILESTONE_SERIES && shown.indexOf("series_100") === -1) {
            return { id: "series_100", lifetime_series: lifeSeries, lifetime_reviews: lifeReviews };
        }
        if (lifeReviews >= MILESTONE_REVIEWS && shown.indexOf("reviews_50") === -1) {
            return { id: "reviews_50", lifetime_series: lifeSeries, lifetime_reviews: lifeReviews };
        }
        return null;
    }

    function eligibleVariants(ctx) {
        var source = String(ctx.source || "");
        var out = [];
        var series = parseInt(ctx.series_count, 10) || 0;
        var done = parseInt(ctx.done, 10) || 0;
        var superOn = !!ctx.super_enabled;
        var ach = String(ctx.achievement_id || "");

        if (source === "batch") {
            out.push("batch_hero");
            if (series > 0) out.push("time_saved");
            if (superOn) out.push("super_glow");
        } else if (source === "mr_recap") {
            out.push("mr_craft");
            if (done > 0) out.push("time_saved");
            if (superOn) out.push("super_glow");
            if (ach && ach !== "empty_session") out.push("achievement_echo");
        } else if (source === "workshop") {
            out.push("workshop_craft");
            var volumes = parseInt(ctx.volumes_count, 10) || 0;
            if (volumes > 0 || series > 0) out.push("time_saved");
            if (superOn) out.push("super_glow");
        }

        if (ctx.milestone_hit) {
            if (out.indexOf("achievement_echo") === -1) out.push("achievement_echo");
        }

        if (!out.length) out = ["time_saved", "batch_hero"];
        return out;
    }

    function pickVariant(ctx) {
        var eligible = eligibleVariants(ctx);
        var last = safeStorageGet(KEYS.lastVariant);
        if (last && eligible.indexOf(last) !== -1 && eligible.length > 1) {
            eligible = eligible.filter(function (v) { return v !== last; });
        }
        var order = ctx.source === "mr_recap"
            ? ["mr_craft", "achievement_echo", "super_glow", "time_saved", "batch_hero"]
            : (ctx.source === "workshop"
                ? ["workshop_craft", "time_saved", "super_glow", "achievement_echo"]
                : ["batch_hero", "super_glow", "time_saved", "achievement_echo", "mr_craft"]);
        if (ctx.milestone_hit) {
            order = ["achievement_echo"].concat(order);
        }
        for (var i = 0; i < order.length; i++) {
            if (eligible.indexOf(order[i]) !== -1) return order[i];
        }
        return eligible[0];
    }

    function estimateMinutes(ctx) {
        var series = parseInt(ctx.series_count, 10) || 0;
        var done = parseInt(ctx.done, 10) || 0;
        var edits = parseInt(ctx.edits, 10) || 0;
        var volumes = parseInt(ctx.volumes_count, 10) || 0;
        // Estimation ludique : ~2 min / série batch, ~1.5 min / review + edits, ~1 min / volume atelier
        var mins = Math.round(series * 2 + done * 1.5 + edits * 0.5 + volumes * 1);
        return Math.max(1, mins);
    }

    function fillCopy(variant, ctx) {
        var series = parseInt(ctx.series_count, 10) || 0;
        var done = parseInt(ctx.done, 10) || 0;
        var edits = parseInt(ctx.edits, 10) || 0;
        var fusions = parseInt(ctx.fusions, 10) || 0;
        var researches = parseInt(ctx.researches, 10) || 0;
        var mins = estimateMinutes(ctx);
        var achTitle = ctx.achievement_title || "";
        var kicker = "";
        var title = "";
        var body = "";
        var estimate = "";

        if (variant === "batch_hero") {
            kicker = t("nag_kicker_batch", "Lot terminé avec soin");
            title = t("nag_title_batch", "Ta bibliothèque vient de s’enrichir");
            body = (t("nag_body_batch", "{0} série(s) soignée(s) d’un coup. MetaKavita est gratuit — un café (~5 €), c’est juste un merci doux.") || "")
                .replace("{0}", String(series));
        } else if (variant === "mr_craft") {
            kicker = t("nag_kicker_mr", "Session de review");
            title = t("nag_title_mr", "Tu as pris soin de ta collection");
            body = (t("nag_body_mr", "{0} confirms, {1} retouches, {2} fusions/recherches. Si la session t’a aidé, un café fait vraiment plaisir.") || "")
                .replace("{0}", String(done))
                .replace("{1}", String(edits))
                .replace("{2}", String(fusions + researches));
        } else if (variant === "super_glow") {
            kicker = t("nag_kicker_super", "Mode Super");
            title = t("nag_title_super", "Le Super a filé en coulisses");
            body = t("nag_body_super", "Auto-confirm et covers : moins de clics, plus de manga. Un café (~5 €) pour dire « merci » tout simplement ?");
        } else if (variant === "achievement_echo") {
            kicker = t("nag_kicker_ach", "Petit haut-fait");
            title = achTitle || t("nag_title_ach", "Belle session");
            body = t("nag_body_ach", "On a marqué le coup ensemble. Un café (~5 €) aide MetaKavita à garder ce rythme — sans pression.");
        } else if (variant === "workshop_craft") {
            var volCount = parseInt(ctx.volumes_count, 10) || parseInt(ctx.series_count, 10) || 1;
            kicker = t("nag_kicker_workshop", "Atelier des tomes");
            title = t("nag_title_workshop", "Tes tomes sont soignés aux petits oignons");
            body = (t("nag_body_workshop", "{0} écriture(s) réussie(s) dans Kavita depuis l'atelier. MetaKavita est gratuit — un café (~5 €), c’est juste un merci doux.") || "")
                .replace("{0}", String(volCount));
        } else {
            // time_saved
            kicker = t("nag_kicker_time", "Un petit clin d’œil");
            title = t("nag_title_time", "Tout ce temps, on te l’a rendu");
            body = (t("nag_body_time", "Environ {0} min de saisie évitées (estimation ludique). Si ça t’a fait du bien, un café réchauffe aussi le projet.") || "")
                .replace("{0}", String(mins));
            estimate = t("nag_estimate_label", "Estimation ludique — juste pour le fun");
        }

        return { kicker: kicker, title: title, body: body, estimate: estimate };
    }

    function els() {
        return {
            overlay: document.getElementById("licenseNagOverlay"),
            card: document.querySelector("#licenseNagOverlay .license-nag-card"),
            kicker: document.getElementById("licenseNagKicker"),
            title: document.getElementById("licenseNagTitle"),
            body: document.getElementById("licenseNagBody"),
            estimate: document.getElementById("licenseNagEstimate"),
            bmc: document.getElementById("licenseNagBmc"),
            bmcLabel: document.getElementById("licenseNagBmcLabel"),
            cont: document.getElementById("licenseNagContinue"),
            honor: document.getElementById("licenseNagHonor")
        };
    }

    function hideOverlay() {
        var e = els();
        if (continueTimer) {
            clearTimeout(continueTimer);
            continueTimer = null;
        }
        visible = false;
        if (e.overlay) {
            e.overlay.style.display = "none";
            e.overlay.hidden = true;
            e.overlay.classList.remove("is-open");
            e.overlay.setAttribute("aria-hidden", "true");
        }
        if (e.cont) e.cont.disabled = true;
    }

    function showOverlay(variant, ctx) {
        var e = els();
        if (!e.overlay || !e.card) return false;
        var copy = fillCopy(variant, ctx);
        e.card.setAttribute("data-variant", variant);
        if (e.kicker) e.kicker.textContent = copy.kicker;
        if (e.title) e.title.textContent = copy.title;
        if (e.body) e.body.textContent = copy.body;
        if (e.estimate) {
            if (copy.estimate) {
                e.estimate.textContent = copy.estimate;
                e.estimate.style.display = "";
            } else {
                e.estimate.style.display = "none";
            }
        }
        if (e.bmc) e.bmc.href = BMC_URL;
        if (e.bmcLabel) {
            e.bmcLabel.textContent = t("nag_bmc_cta", "Offrir un café à MetaKavita (~5 €)");
        }
        if (e.cont) {
            e.cont.disabled = true;
            e.cont.textContent = t("nag_continue", "Plus tard, avec plaisir");
        }
        if (e.honor) {
            e.honor.textContent = t("nag_honor_snooze", "J’ai déjà offert un café — pause 30 j");
        }

        e.overlay.hidden = false;
        e.overlay.style.display = "flex";
        e.overlay.classList.add("is-open");
        e.overlay.setAttribute("aria-hidden", "false");
        visible = true;

        if (continueTimer) clearTimeout(continueTimer);
        continueTimer = setTimeout(function () {
            if (e.cont) e.cont.disabled = false;
            continueTimer = null;
        }, CONTINUE_DELAY_MS);

        recordNagShown(variant, String(ctx.source || "unknown"));
        if (ctx.milestone_id) markMilestone(ctx.milestone_id);
        return true;
    }

    function shouldShow(ctx) {
        if (!canShowOverlay()) return false;
        if (ctx.source === "mr_recap" && !isRichMrSession(ctx)) return false;
        if (ctx.source === "batch") {
            if (ctx.stopped) return false;
            if ((parseInt(ctx.series_count, 10) || 0) <= 0) return false;
        }
        if (ctx.source === "workshop") {
            var volW = (parseInt(ctx.volumes_count, 10) || 0);
            var serW = (parseInt(ctx.series_count, 10) || 0);
            if (volW <= 0 && serW <= 0) return false;
        }
        return true;
    }

    function tryShow(ctx) {
        try {
            ctx = ctx || {};
            var milestone = detectMilestone(ctx);
            if (milestone) {
                ctx.milestone_hit = true;
                ctx.milestone_id = milestone.id;
                ctx.lifetime_series = milestone.lifetime_series;
                ctx.lifetime_reviews = milestone.lifetime_reviews;
                if (milestone.id === "series_100") {
                    ctx.achievement_title = t("nag_milestone_series", "100 séries enrichies");
                } else if (milestone.id === "reviews_50") {
                    ctx.achievement_title = t("nag_milestone_reviews", "50 reviews confirmées");
                }
            }
            if (!shouldShow(ctx)) return false;
            if (visible) return false;
            var variant = pickVariant(ctx);
            return showOverlay(variant, ctx);
        } catch (err) {
            try { console.warn("[supporter-nag]", err); } catch (e2) { /* noop */ }
            return false;
        }
    }

    function wireOverlayControls() {
        var e = els();
        if (e.cont) {
            e.cont.addEventListener("click", function () {
                hideOverlay();
            });
        }
        if (e.bmc) {
            e.bmc.addEventListener("click", function () {
                markBmcClick();
            });
        }
        if (e.honor) {
            e.honor.addEventListener("click", function () {
                setHonorSnooze();
                hideOverlay();
            });
        }
        // Pas de trap focus hostile ; Escape ne ferme pas avant Continuer (évite bypass 2.5s)
        document.addEventListener("keydown", function (ev) {
            if (!visible) return;
            if (ev.key === "Escape") {
                var cont = els().cont;
                if (cont && !cont.disabled) {
                    hideOverlay();
                }
            }
        });
    }

    function wireInlineBmcCooldown() {
        document.addEventListener("click", function (ev) {
            var a = ev.target && ev.target.closest
                ? ev.target.closest("a.license, a.bmc-link, a.so-license-cta")
                : null;
            if (!a) return;
            var href = (a.getAttribute("href") || "");
            if (href.indexOf("buymeacoffee") === -1) return;
            markBmcClick();
        }, true);
    }

    function isSuperEnabled() {
        try {
            // Identifiant réel de la case Mode Super dans la sidebar : le même que
            // celui lu par manual_review.js et config.js. Avec l'ancien nom, le
            // `if (el)` avalait le null sans un mot, la variante "super_glow"
            // n'était jamais éligible et ses trois traductions ne s'affichaient
            // jamais. La case est désactivée quand le mode manuel est éteint —
            // cochée mais grisée ne veut pas dire active.
            var el = document.getElementById("sidebar_manual_review_super");
            if (el) return !!(el.checked && !el.disabled);
            return false;
        } catch (e) {
            return false;
        }
    }

    function updateMrRecapCta(ctx) {
        try {
            var wrap = document.getElementById("mrRecapNagCta");
            if (!wrap) return;
            // CTA natif dans le récap (toujours, sauf honor snooze / honeymoon optionnel — plan: inline illimité)
            // On masque seulement si honor snooze pour récompenser le tippeur.
            if (honorSnoozed()) {
                wrap.style.display = "none";
                return;
            }
            var value = document.getElementById("mrRecapNagValue");
            var done = parseInt(ctx.done, 10) || 0;
            var edits = parseInt(ctx.edits, 10) || 0;
            if (value) {
                value.textContent = (t("nag_recap_value", "Cette session : {0} confirms, {1} edits. Un café (~5 €) aide MetaKavita.") || "")
                    .replace("{0}", String(done))
                    .replace("{1}", String(edits));
            }
            wrap.style.display = "";
        } catch (e) {
            /* noop */
        }
    }

    function onBatchComplete(payload) {
        try {
            payload = payload || {};
            if (payload.stopped) return;
            var total = 0;
            if (typeof batchProgressTotal === "number" && batchProgressTotal > 0) {
                total = batchProgressTotal;
            } else {
                total = parseInt(payload.total, 10) || 0;
            }
            if (total <= 0) return;
            // Aucune série réellement envoyée à Kavita (batch entièrement composé de
            // séries déjà à jour, skip silencieux côté enrich_series) : rien à fêter,
            // ne pas relancer le nagware supporter pour un lot qui n'a rien fait.
            var realSends = parseInt(payload.real_sends, 10);
            if (isNaN(realSends)) realSends = 0;
            if (realSends <= 0) return;
            // Léger délai pour laisser la barre / UI se poser
            setTimeout(function () {
                var ctx = {
                    source: "batch",
                    series_count: realSends > 0 ? realSends : total,
                    super_enabled: isSuperEnabled(),
                    stopped: false
                };
                noteLifetime(ctx);
                tryShow(ctx);
            }, 800);
        } catch (e) {
            /* noop */
        }
    }

    function onMrRecap(session) {
        try {
            session = session || {};
            var panel = document.getElementById("mrRecapPanel");
            var achId = panel ? (panel.getAttribute("data-ach-id") || "") : "";
            var achTitleEl = document.getElementById("mrRecapHeroTitle");
            var ctx = {
                source: "mr_recap",
                done: session.done || 0,
                skipped: session.skipped || 0,
                edits: session.edits || 0,
                fusions: session.fusions || 0,
                researches: session.researches || 0,
                weak_picks: session.weak_picks || 0,
                achievement_id: achId,
                achievement_title: achTitleEl ? achTitleEl.textContent : "",
                super_enabled: isSuperEnabled()
            };
            updateMrRecapCta(ctx);
            noteLifetime(ctx);
            // Overlay seulement si session riche + caps OK (batch du jour peut déjà avoir nagé)
            setTimeout(function () {
                tryShow(ctx);
            }, 600);
        } catch (e) {
            /* noop */
        }
    }

    function onWorkshopComplete(stats) {
        try {
            stats = stats || {};
            var written = parseInt(stats.written_count, 10) || parseInt(stats.volumes_count, 10) || 0;
            var seriesCount = parseInt(stats.series_count, 10) || 0;
            if (written <= 0 && seriesCount <= 0) return;
            var ctx = {
                source: "workshop",
                volumes_count: written,
                series_count: seriesCount,
                super_enabled: isSuperEnabled()
            };
            noteLifetime(ctx);
            setTimeout(function () {
                tryShow(ctx);
            }, 800);
        } catch (e) {
            /* noop */
        }
    }

    function init() {
        try {
            ensureFirstVisit();
            wireOverlayControls();
            wireInlineBmcCooldown();
        } catch (e) {
            try { console.warn("[supporter-nag] init", e); } catch (e2) { /* noop */ }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.SupporterNag = {
        tryShow: tryShow,
        hide: hideOverlay,
        markBmcClick: markBmcClick,
        onBatchComplete: onBatchComplete,
        onMrRecap: onMrRecap,
        onWorkshopComplete: onWorkshopComplete,
        resetMrSession: resetMrLifetimeNote,
        canShowOverlay: canShowOverlay,
        _test: {
            inHoneymoon: inHoneymoon,
            honorSnoozed: honorSnoozed,
            nagsToday: nagsToday,
            isRichMrSession: isRichMrSession,
            pickVariant: pickVariant,
            lifetimeActivity: lifetimeActivity,
            hasMinimumActivity: hasMinimumActivity,
            MIN_ACTIVITY_THRESHOLD: MIN_ACTIVITY_THRESHOLD,
            KEYS: KEYS
        }
    };
})();
