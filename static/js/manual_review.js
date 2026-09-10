// --- MANUAL REVIEW QUEUE (C29) ---
// Dépend de utils.js (getRootPath, CSRF) et websocket.js (`socket`).

(function () {
    var queue = [];
    var currentIndex = 0;
    var currentReviewId = null;
    var selectedProvider = null;
    var includeProviders = [];
    var manualCompletion = false;
    var mergeFields = false;
    var fieldPicks = null;
    var FIELD_PICK_KEYS = [
        "title", "cover", "year", "status", "format", "publisher",
        "age_rating", "localized_name", "summary", "genres", "tags", "staff"
    ];
    var LIST_FIELD_PICKS = { genres: true, tags: true, staff: true };
    var ALL_TARGETED_FIELD_KEYS = [
        "summary", "cover", "staff", "genres", "tags", "year",
        "status", "publisher", "age", "weblinks", "alt_titles", "language"
    ];
    var EDIT_SEND_ALIASES = {
        cover_url: "cover",
        age_rating: "age",
        localized_name: "alt_titles",
        staff: "staff",
        writers: "staff",
        pencillers: "staff"
    };
    // Companion embed and workshop series Review: scope the whole queue to a
    // single series so the user only ever reviews the series they opened (never
    // the first in the global pending queue, and no auto-advance into others).
    var companionOnlySeriesId = null;
    var companionOnlyReviewId = "";
    var baselinePreview = null;
    var phase = "pick"; // pick | cover | edit | waiting | recap
    var session = emptySession();
    var editEnabled = true;
    var coverPickEnabled = false;
    var coverPicked = false;
    var providerCoverUrl = "";
    var soundsEnabled = false;
    var opening = false;
    var localPurgeInFlight = false;
    var researchInFlight = false;
    var actionInFlight = false;
    var loadQueueSeq = 0;
    var waitingSettleTimer = null;
    var previouslyFocused = null;
    var listViewOpen = false;
    var bulkAcceptInFlight = false;
    // La file est chargée par page : chaque review transporte ses cartes candidates
    // (résumés compris), tout demander d'un coup ferait payer l'ouverture de la
    // modale à une grosse bibliothèque. La page est donc demandée explicitement, sa
    // troncature est dite à l'écran, et son épuisement charge la suivante.
    var QUEUE_PAGE_SIZE = 200;
    var queueTotal = 0;
    var queueTruncated = false;
    var queueRefillInFlight = false;
    var SHOW_BELOW_PREF_KEY = "mk_mr_show_below";
    var showBelowThreshold = loadShowBelowPref();
    /** review_id → true after scrape_complete (blocks re-arming streaming). */
    var finalizedStreamIds = Object.create(null);

    function loadShowBelowPref() {
        try {
            return localStorage.getItem(SHOW_BELOW_PREF_KEY) === "1";
        } catch (e) {
            return false;
        }
    }

    function saveShowBelowPref(on) {
        try {
            localStorage.setItem(SHOW_BELOW_PREF_KEY, on ? "1" : "0");
        } catch (e) {
            /* private mode / blocked storage */
        }
    }

    function syncShowBelowCheckbox() {
        var cb = document.getElementById("mrShowBelow");
        if (cb) cb.checked = !!showBelowThreshold;
    }

    function emptySession() {
        return {
            done: 0,
            skipped: 0,
            top1: 0,
            edits: 0,
            purged: 0,
            researches: 0,
            fusions: 0,
            weak_picks: 0,
            score_sum: 0,
            score_n: 0,
            super_used: false,
            batch_no_reviews: false
        };
    }

    function t(key, fallback) {
        return (window.AppTranslations && window.AppTranslations[key]) || fallback || key;
    }

    function api(path, opts) {
        return fetch(getRootPath() + path, opts || {}).then(function (res) {
            return res.json().then(function (body) {
                if (!res.ok || body.success === false) {
                    throw new Error((body && (body.error || body.msg)) || ("HTTP " + res.status));
                }
                return body;
            });
        });
    }

    function scoreClass(score) {
        var s = Number(score);
        if (isNaN(s)) return "mr-score-mid";
        if (s >= 0.85) return "mr-score-high";
        if (s >= 0.7) return "mr-score-good";
        if (s >= 0.6) return "mr-score-mid";
        return "mr-score-low";
    }

    // Échappement partagé (utils.js) : voir escapeHtmlText, l'apostrophe incluse.
    function escapeHtml(value) {
        return window.escapeHtmlText(value);
    }

    function sessionAvgScore() {
        if (!session.score_n) return 0;
        return session.score_sum / session.score_n;
    }

    function isSelectedWeak(review, provider) {
        if (!review || !provider) return false;
        var above = review.above || [];
        var i;
        for (i = 0; i < above.length; i++) {
            if (above[i].provider === provider) {
                return !!above[i].below_threshold;
            }
        }
        var below = review.below || [];
        for (i = 0; i < below.length; i++) {
            if (below[i].provider === provider) return true;
        }
        return false;
    }

    function selectedCardScore(review, provider) {
        var bands = (review.above || []).concat(review.below || []);
        for (var i = 0; i < bands.length; i++) {
            if (bands[i].provider === provider && typeof bands[i].score === "number") {
                return bands[i].score;
            }
        }
        return null;
    }

    function recordSessionConfirm(review, detail, fieldEdits, fusionSources) {
        session.done += 1;
        session.edits += fieldEdits || 0;
        if (detail && detail.is_top1) session.top1 += 1;
        if (fusionSources > 0) session.fusions += 1;
        if (isSelectedWeak(review, selectedProvider)) session.weak_picks += 1;
        var sc = (detail && typeof detail.score === "number")
            ? detail.score
            : selectedCardScore(review, selectedProvider);
        if (typeof sc === "number" && !isNaN(sc)) {
            session.score_sum += sc;
            session.score_n += 1;
        }
        if (isSuperReviewOn()) session.super_used = true;
    }

    function achievementCatalog() {
        return [
            {
                id: "purge_master", priority: 100, accent: "coral", mono: "VD",
                test: function (s) { return (s.purged || 0) > 0; },
                flavor: function (s) {
                    return t("mr_ach_purge_master_flavor", "File balayée : {0} review(s) purgée(s).")
                        .replace("{0}", String(s.purged || 0));
                }
            },
            {
                id: "spectator", priority: 95, accent: "coral", mono: "SP",
                test: function (s) { return s.done === 0 && s.skipped > 0; },
                flavor: function (s) {
                    return t("mr_ach_spectator_flavor", "Rien confirmé — {0} série(s) passée(s).")
                        .replace("{0}", String(s.skipped));
                }
            },
            {
                id: "empty_session", priority: 90, accent: "amber", mono: "☕",
                test: function (s) {
                    return (s.done + s.skipped + (s.purged || 0) + (s.researches || 0)) === 0;
                },
                flavor: function (s) {
                    if (s && s.batch_no_reviews) {
                        return t(
                            "mr_wait_idle_flavor",
                            "Aucune review créée. Les séries étaient déjà à jour — coche « Forcer la mise à jour » pour relancer Super Review."
                        );
                    }
                    return t("mr_ach_empty_session_flavor", "Session ouverte… et refermée. Le café attend.");
                }
            },
            {
                id: "super_marathon", priority: 88, accent: "amber", mono: "SR",
                test: function (s) { return s.super_used && s.done >= 1; },
                flavor: function (s) {
                    return t("mr_ach_super_marathon_flavor", "Super Review actif · {0} confirmation(s).")
                        .replace("{0}", String(s.done));
                }
            },
            {
                id: "alchemist", priority: 85, accent: "violet", mono: "AL",
                test: function (s) { return (s.fusions || 0) >= 1; },
                flavor: function (s) {
                    return t("mr_ach_alchemist_flavor", "{0} fusion(s) — tu as mélangé les sources.")
                        .replace("{0}", String(s.fusions || 0));
                }
            },
            {
                id: "nugget", priority: 82, accent: "amber", mono: "★",
                test: function (s) { return (s.weak_picks || 0) >= 1; },
                flavor: function (s) {
                    return t("mr_ach_nugget_flavor", "{0} pick(s) dans la bande faible — belle chasse.")
                        .replace("{0}", String(s.weak_picks || 0));
                }
            },
            {
                id: "relancer", priority: 80, accent: "sky", mono: "↻",
                test: function (s) { return (s.researches || 0) >= 1; },
                flavor: function (s) {
                    return t("mr_ach_relancer_flavor", "{0} re-recherche(s) avec un nouveau titre.")
                        .replace("{0}", String(s.researches || 0));
                }
            },
            {
                id: "oracle", priority: 75, accent: "teal", mono: "T1",
                test: function (s) {
                    return s.done >= 3 && (s.top1 / s.done) >= 0.8;
                },
                flavor: function (s) {
                    return t("mr_ach_oracle_flavor", "{0}/{1} top-1 — confiance dans le meilleur score.")
                        .replace("{0}", String(s.top1))
                        .replace("{1}", String(s.done));
                }
            },
            {
                id: "rebel", priority: 72, accent: "coral", mono: "≠",
                test: function (s) { return s.done >= 2 && s.top1 === 0; },
                flavor: function (s) {
                    return t("mr_ach_rebel_flavor", "{0} confirms sans jamais prendre le #1.")
                        .replace("{0}", String(s.done));
                }
            },
            {
                id: "sculptor", priority: 68, accent: "violet", mono: "✎",
                test: function (s) { return s.edits >= 5 && s.done >= 1; },
                flavor: function (s) {
                    return t("mr_ach_sculptor_flavor", "{0} champ(s) retouchés avant envoi.")
                        .replace("{0}", String(s.edits));
                }
            },
            {
                id: "lightning", priority: 65, accent: "lime", mono: "⚡",
                test: function (s) { return s.done >= 3 && s.edits === 0; },
                flavor: function (s) {
                    return t("mr_ach_lightning_flavor", "{0} confirms sans retouche — décision éclair.")
                        .replace("{0}", String(s.done));
                }
            },
            {
                id: "gourmet", priority: 62, accent: "teal", mono: "◆",
                test: function (s) {
                    return s.score_n >= 3 && sessionAvgScore() >= 0.85;
                },
                flavor: function (s) {
                    return t("mr_ach_gourmet_flavor", "Score moyen {0} sur {1} accept(s).")
                        .replace("{0}", sessionAvgScore().toFixed(2))
                        .replace("{1}", String(s.score_n));
                }
            },
            {
                id: "sprinter", priority: 58, accent: "lime", mono: "≫",
                test: function (s) { return s.done >= 10; },
                flavor: function (s) {
                    return t("mr_ach_sprinter_flavor", "{0} séries confirmées — gros volume.")
                        .replace("{0}", String(s.done));
                }
            },
            {
                id: "balanced", priority: 55, accent: "sky", mono: "≈",
                test: function (s) { return s.done >= 2 && s.skipped >= 2; },
                flavor: function (s) {
                    return t("mr_ach_balanced_flavor", "{0} confirms · {1} passées — équilibre.")
                        .replace("{0}", String(s.done))
                        .replace("{1}", String(s.skipped));
                }
            },
            {
                id: "warmup", priority: 40, accent: "teal", mono: "1",
                test: function (s) { return s.done === 1; },
                flavor: function () {
                    return t("mr_ach_warmup_flavor", "Une confirmation — l’échauffement est fait.");
                }
            },
            {
                id: "curator", priority: 10, accent: "teal", mono: "★",
                test: function (s) { return s.done >= 1; },
                flavor: function (s) {
                    return t("mr_ach_curator_flavor", "Session menée : {0} confirmée(s), {1} passée(s).")
                        .replace("{0}", String(s.done))
                        .replace("{1}", String(s.skipped));
                }
            }
        ];
    }

    function pickAchievements(s) {
        var catalog = achievementCatalog();
        var matched = [];
        for (var i = 0; i < catalog.length; i++) {
            var a = catalog[i];
            try {
                if (a.test(s)) matched.push(a);
            } catch (e) { /* ignore */ }
        }
        matched.sort(function (x, y) { return y.priority - x.priority; });
        var hero = matched[0] || null;
        var badges = [];
        for (var j = 1; j < matched.length && badges.length < 3; j++) {
            badges.push(matched[j]);
        }
        return { hero: hero, badges: badges };
    }

    function achievementTitle(id) {
        var map = {
            purge_master: t("mr_ach_purge_master_title", "Videur de file"),
            spectator: t("mr_ach_spectator_title", "Spectateur VIP"),
            empty_session: t("mr_ach_empty_session_title", "Pause café"),
            super_marathon: t("mr_ach_super_marathon_title", "Marathon café"),
            alchemist: t("mr_ach_alchemist_title", "Alchimiste"),
            nugget: t("mr_ach_nugget_title", "Chasseur de pépites"),
            relancer: t("mr_ach_relancer_title", "Relanceur"),
            oracle: t("mr_ach_oracle_title", "Oracle Top-1"),
            rebel: t("mr_ach_rebel_title", "Contre-courant"),
            sculptor: t("mr_ach_sculptor_title", "Sculpteur de meta"),
            lightning: t("mr_ach_lightning_title", "Décision éclair"),
            gourmet: t("mr_ach_gourmet_title", "Gourmet"),
            sprinter: t("mr_ach_sprinter_title", "Sprinter"),
            balanced: t("mr_ach_balanced_title", "Équilibriste"),
            warmup: t("mr_ach_warmup_title", "Échauffement"),
            curator: t("mr_ach_curator_title", "Curateur")
        };
        return map[id] || id;
    }

    function renderRecapAchievements() {
        var picked = pickAchievements(session);
        var panel = document.getElementById("mrRecapPanel");
        var heroTitle = document.getElementById("mrRecapHeroTitle");
        var heroFlavor = document.getElementById("mrRecapHeroFlavor");
        var heroMono = document.getElementById("mrRecapMedalMono");
        var badgesEl = document.getElementById("mrRecapBadges");
        var hero = picked.hero;

        if (panel) {
            panel.setAttribute("data-ach-id", hero ? hero.id : "");
            panel.setAttribute("data-ach-accent", hero ? hero.accent : "teal");
            panel.style.setProperty("--mr-ach-accent", accentColor(hero ? hero.accent : "teal"));
            panel.classList.remove("mr-recap-enter");
            // retrigger enter animation
            void panel.offsetWidth;
            panel.classList.add("mr-recap-enter");
        }
        if (heroTitle) {
            heroTitle.textContent = hero
                ? achievementTitle(hero.id)
                : t("mr_recap_title", "Session de review terminée");
        }
        if (heroFlavor) {
            heroFlavor.textContent = hero
                ? hero.flavor(session)
                : t("mr_recap_title", "Session de review terminée");
        }
        if (heroMono) {
            heroMono.textContent = hero ? hero.mono : "★";
        }
        if (badgesEl) {
            badgesEl.innerHTML = "";
            picked.badges.forEach(function (b, idx) {
                var chip = document.createElement("span");
                chip.className = "mr-recap-badge";
                chip.style.setProperty("--mr-badge-accent", accentColor(b.accent));
                chip.style.animationDelay = (idx * 40) + "ms";
                chip.setAttribute("title", b.flavor(session));
                chip.setAttribute("data-ach-id", b.id);
                chip.innerHTML =
                    '<span class="mr-recap-badge-dot" aria-hidden="true"></span>' +
                    '<span class="mr-recap-badge-label">' + escapeHtml(achievementTitle(b.id)) + "</span>";
                badgesEl.appendChild(chip);
            });
            badgesEl.style.display = picked.badges.length ? "" : "none";
        }
    }

    function accentColor(name) {
        var map = {
            teal: "#2dd4bf",
            sky: "#38bdf8",
            coral: "#fb7185",
            amber: "#fbbf24",
            lime: "#a3e635",
            violet: "#a78bfa"
        };
        return map[name] || map.teal;
    }

    function renderRecapKpis() {
        var d = document.getElementById("mrRecapDone");
        var s = document.getElementById("mrRecapSkipped");
        var t1 = document.getElementById("mrRecapTop1");
        var e = document.getElementById("mrRecapEdits");
        var p = document.getElementById("mrRecapPurged");
        var purgedWrap = document.getElementById("mrRecapPurgedWrap");
        var r = document.getElementById("mrRecapResearches");
        var researchesWrap = document.getElementById("mrRecapResearchesWrap");
        var f = document.getElementById("mrRecapFusions");
        var fusionsWrap = document.getElementById("mrRecapFusionsWrap");
        var w = document.getElementById("mrRecapWeak");
        var weakWrap = document.getElementById("mrRecapWeakWrap");
        var avg = document.getElementById("mrRecapAvgScore");
        var avgWrap = document.getElementById("mrRecapAvgWrap");

        if (d) d.textContent = String(session.done);
        if (s) s.textContent = String(session.skipped);
        if (t1) t1.textContent = String(session.top1);
        if (e) e.textContent = String(session.edits);
        if (p) p.textContent = String(session.purged || 0);
        if (purgedWrap) purgedWrap.style.display = (session.purged > 0) ? "" : "none";
        if (r) r.textContent = String(session.researches || 0);
        if (researchesWrap) researchesWrap.style.display = (session.researches > 0) ? "" : "none";
        if (f) f.textContent = String(session.fusions || 0);
        if (fusionsWrap) fusionsWrap.style.display = (session.fusions > 0) ? "" : "none";
        if (w) w.textContent = String(session.weak_picks || 0);
        if (weakWrap) weakWrap.style.display = (session.weak_picks > 0) ? "" : "none";
        if (avg) avg.textContent = session.score_n ? sessionAvgScore().toFixed(2) : "—";
        if (avgWrap) avgWrap.style.display = session.score_n ? "" : "none";
    }

    function asList(value) {
        if (!value) return [];
        if (Array.isArray(value)) {
            return value.map(function (v) {
                return String(v == null ? "" : v).trim();
            }).filter(Boolean);
        }
        return String(value).split(/[,;]/).map(function (s) { return s.trim(); }).filter(Boolean);
    }

    function joinList(value, max) {
        var items = asList(value);
        if (!items.length) return "";
        if (max && items.length > max) {
            return items.slice(0, max).join(", ") + " +" + (items.length - max);
        }
        return items.join(", ");
    }

    function fieldHasValue(value) {
        if (value == null || value === false) return false;
        if (Array.isArray(value)) return value.some(function (v) {
            return String(v == null ? "" : v).trim() !== "";
        });
        return String(value).trim() !== "";
    }

    function cardFieldValue(card, field) {
        if (!card) return null;
        if (field === "cover") return card.cover_url;
        if (field === "summary") return card.summary || card.summary_excerpt;
        return card[field];
    }

    function findCard(review, provider) {
        if (!review || !provider) return null;
        var bands = [review.above || [], review.below || []];
        var b, i, card;
        for (b = 0; b < bands.length; b++) {
            for (i = 0; i < bands[b].length; i++) {
                card = bands[b][i];
                if (card && card.provider === provider) return card;
            }
        }
        return null;
    }

    function defaultFieldPicks(review, masterProvider) {
        var picks = {};
        var card = findCard(review, masterProvider);
        if (!card) return picks;
        FIELD_PICK_KEYS.forEach(function (field) {
            if (fieldHasValue(cardFieldValue(card, field))) {
                picks[field] = [masterProvider];
            }
        });
        return picks;
    }

    function ensureFieldPicks(review) {
        if (!manualCompletion || !selectedProvider) return;
        if (!fieldPicks) fieldPicks = defaultFieldPicks(review, selectedProvider);
    }

    function resetFieldPicks() {
        fieldPicks = null;
    }

    function selectMaster(provider) {
        var changed = provider !== selectedProvider;
        selectedProvider = provider;
        includeProviders = includeProviders.filter(function (p) { return p !== selectedProvider; });
        if (manualCompletion && changed) resetFieldPicks();
    }

    function fieldIsPicked(field, provider) {
        if (!fieldPicks || !fieldPicks[field]) return false;
        return fieldPicks[field].indexOf(provider) >= 0;
    }

    function fusionProvidersFromPicks(picks) {
        var seen = {};
        var out = [];
        Object.keys(picks || {}).forEach(function (field) {
            (picks[field] || []).forEach(function (p) {
                if (!p || p === selectedProvider || seen[p]) return;
                seen[p] = true;
                out.push(p);
            });
        });
        return out;
    }

    function pickRequestExtras() {
        if (!manualCompletion) {
            var fusionList = includeProviders.filter(function (p) {
                return p && p !== selectedProvider;
            });
            return {
                include_providers: fusionList,
                fused: fusionList.length > 0,
                manual_completion: false
            };
        }
        var picks = fieldPicks || {};
        var fromPicks = fusionProvidersFromPicks(picks);
        return {
            include_providers: fromPicks,
            manual_completion: true,
            merge_fields: !!mergeFields,
            field_picks: picks,
            fused: fromPicks.length > 0
        };
    }

    function fieldPickLabel(field) {
        var keys = {
            title: "mr_field_title",
            cover: "mr_meta_cover",
            year: "mr_meta_year",
            status: "mr_meta_status",
            format: "mr_meta_format",
            publisher: "mr_meta_publisher",
            age_rating: "mr_meta_age",
            localized_name: "mr_meta_localized",
            summary: "mr_field_summary",
            genres: "mr_meta_genres",
            tags: "mr_meta_tags",
            staff: "mr_meta_staff"
        };
        return t(keys[field] || field, field);
    }

    function fieldPickInput(field, provider, hasValue) {
        if (!manualCompletion || !hasValue || !provider) return "";
        var picked = fieldIsPicked(field, provider);
        var locked = !!(mergeFields && LIST_FIELD_PICKS[field] &&
            provider === selectedProvider && picked);
        var label = t("mr_pick_field", "Use this {0}").replace("{0}", fieldPickLabel(field));
        return '<input type="checkbox" data-mr-field="' + escapeHtml(field) +
            '" data-mr-provider="' + escapeHtml(provider) + '"' +
            (picked ? " checked" : "") +
            (locked ? " disabled" : "") +
            ' aria-label="' + escapeHtml(label) + '">';
    }

    function fieldHitAttrs(field, provider) {
        return ' data-mr-field-hit data-mr-chip-field="' + escapeHtml(field) +
            '" data-mr-chip-provider="' + escapeHtml(provider || "") + '"';
    }

    function onFieldPickChange(field, provider, checked) {
        var review = currentReview();
        ensureFieldPicks(review);
        if (!fieldPicks) fieldPicks = {};
        var current = (fieldPicks[field] || []).slice();
        var masterCard = findCard(review, selectedProvider);
        var masterHas = !!(masterCard && fieldHasValue(cardFieldValue(masterCard, field)));
        if (mergeFields && LIST_FIELD_PICKS[field]) {
            if (provider === selectedProvider) {
                if (masterHas && current.indexOf(selectedProvider) < 0) {
                    current.unshift(selectedProvider);
                }
                fieldPicks[field] = current;
            } else if (checked) {
                if (current.indexOf(provider) < 0) current.push(provider);
                if (masterHas && current.indexOf(selectedProvider) < 0) {
                    current.unshift(selectedProvider);
                }
                fieldPicks[field] = current;
            } else {
                fieldPicks[field] = current.filter(function (p) { return p !== provider; });
                if (masterHas && fieldPicks[field].indexOf(selectedProvider) < 0) {
                    fieldPicks[field].unshift(selectedProvider);
                }
            }
        } else if (checked) {
            fieldPicks[field] = [provider];
        } else if (masterHas) {
            fieldPicks[field] = [selectedProvider];
        } else if (current.length) {
            fieldPicks[field] = current;
        } else {
            delete fieldPicks[field];
        }
        syncFieldPickUi();
    }

    function syncFieldPickUi() {
        var panel = document.getElementById("mrPickPanel");
        if (!panel) return;
        var inputs = panel.querySelectorAll("input[data-mr-field]");
        var i, input, field, provider, picked, locked;
        for (i = 0; i < inputs.length; i++) {
            input = inputs[i];
            field = input.getAttribute("data-mr-field");
            provider = input.getAttribute("data-mr-provider");
            picked = fieldIsPicked(field, provider);
            input.checked = picked;
            locked = !!(mergeFields && LIST_FIELD_PICKS[field] &&
                provider === selectedProvider && picked);
            input.disabled = locked;
        }
        var chips = panel.querySelectorAll("[data-mr-chip-field]");
        for (i = 0; i < chips.length; i++) {
            picked = fieldIsPicked(
                chips[i].getAttribute("data-mr-chip-field"),
                chips[i].getAttribute("data-mr-chip-provider")
            );
            chips[i].classList.toggle("is-picked", picked);
        }
        renderFusionBar();
    }

    function bindFieldPickInputs(root) {
        if (!root) return;
        var blockers = root.querySelectorAll("[data-mr-aside], [data-mr-field-hit]");
        var b;
        for (b = 0; b < blockers.length; b++) {
            ["click", "mousedown", "pointerdown"].forEach(function (type) {
                blockers[b].addEventListener(type, function (ev) {
                    ev.stopPropagation();
                });
            });
        }
        var inputs = root.querySelectorAll("input[data-mr-field]");
        var i, input;
        for (i = 0; i < inputs.length; i++) {
            input = inputs[i];
            input.addEventListener("change", function (ev) {
                ev.stopPropagation();
                onFieldPickChange(
                    this.getAttribute("data-mr-field"),
                    this.getAttribute("data-mr-provider"),
                    this.checked
                );
            });
        }
    }

    function syncManualCompletionControls() {
        var manualCb = document.getElementById("mrManualCompletion");
        var mergeCb = document.getElementById("mrMergeFields");
        if (manualCb) manualCb.checked = !!manualCompletion;
        if (mergeCb) {
            mergeCb.checked = !!(manualCompletion && mergeFields);
            mergeCb.disabled = !manualCompletion;
            mergeCb.title = manualCompletion
                ? t("mr_merge_fields_title", "")
                : t("mr_merge_fields_needs_manual", "Turn on Manual completion first.");
        }
    }

    function restorePicksFromPreview(preview) {
        if (!preview || !preview._manual_completion || !preview._field_picks) return;
        manualCompletion = true;
        mergeFields = !!preview._merge_fields;
        fieldPicks = preview._field_picks;
        syncManualCompletionControls();
    }

    function renderCover(c) {
        var coverSrc = safeCoverUrl(c.cover_url);
        var img = coverSrc
            ? '<img class="mr-cover" src="' + escapeHtml(coverSrc) + '" alt="" loading="lazy">'
            : '<div class="mr-cover mr-cover-empty" aria-hidden="true"></div>';
        var input = fieldPickInput("cover", c.provider, fieldHasValue(c.cover_url));
        if (!input) return img;
        return '<label class="mr-cover-pick' +
            (fieldIsPicked("cover", c.provider) ? " is-picked" : "") + '"' +
            fieldHitAttrs("cover", c.provider) + ">" + input + img + "</label>";
    }

    function renderTitle(c) {
        var text = escapeHtml(c.title || "—");
        var input = fieldPickInput("title", c.provider, fieldHasValue(c.title));
        if (!input) return '<div class="mr-title">' + text + "</div>";
        return '<label class="mr-title mr-field-hit' +
            (fieldIsPicked("title", c.provider) ? " is-picked" : "") + '"' +
            fieldHitAttrs("title", c.provider) + ">" + input + text + "</label>";
    }

    function renderMetaChips(c) {
        var chips = [];
        function push(field, label, value, isList, onlyIfMissing) {
            var present = fieldHasValue(value);
            if (onlyIfMissing && present) return;
            var display = present
                ? (isList ? joinList(value, 8) : String(value))
                : "—";
            var pickable = !!(manualCompletion && present);
            var picked = pickable && fieldIsPicked(field, c.provider);
            var tag = pickable ? "label" : "span";
            chips.push(
                "<" + tag + ' class="mr-chip' +
                (present ? "" : " mr-chip-missing") +
                (pickable ? " mr-field-hit" : "") +
                (picked ? " is-picked" : "") + '"' +
                (pickable ? fieldHitAttrs(field, c.provider) : "") +
                (present ? "" : ' title="' + escapeHtml(t("mr_field_missing", "Champ manquant")) + '"') +
                ">" +
                fieldPickInput(field, c.provider, present) +
                '<span class="mr-chip-label">' +
                escapeHtml(label) +
                "</span> " +
                escapeHtml(display) +
                "</" + tag + ">"
            );
        }
        // Cover : chip rouge si absente ; chip cliquable si complétion (l'image l'est aussi)
        push("cover", t("mr_meta_cover", "Cover"), c.cover_url, false, !manualCompletion);
        push("year", t("mr_meta_year", "Year"), c.year, false, false);
        push("status", t("mr_meta_status", "Status"), c.status, false, false);
        push("format", t("mr_meta_format", "Format"), c.format, false, false);
        push("publisher", t("mr_meta_publisher", "Publisher"), c.publisher, false, false);
        push("age_rating", t("mr_meta_age", "Age"), c.age_rating, false, false);
        push("localized_name", t("mr_meta_localized", "Localized"), c.localized_name, false, false);
        push("genres", t("mr_meta_genres", "Genres"), c.genres, true, false);
        push("tags", t("mr_meta_tags", "Tags"), c.tags, true, false);
        push("staff", t("mr_meta_staff", "Staff"), c.staff, true, false);
        return '<div class="mr-meta">' + chips.join("") + "</div>";
    }

    function renderSummary(c) {
        var summary = (c.summary || c.summary_excerpt || "").trim();
        if (!summary) {
            return '<div class="mr-summary mr-summary-empty">' +
                escapeHtml(t("mr_no_summary", "No summary available")) +
                "</div>";
        }
        var input = fieldPickInput("summary", c.provider, true);
        if (!input) {
            return '<div class="mr-summary">' + escapeHtml(summary) + "</div>";
        }
        return '<label class="mr-summary mr-field-hit' +
            (fieldIsPicked("summary", c.provider) ? " is-picked" : "") + '"' +
            fieldHitAttrs("summary", c.provider) + ">" +
            input +
            '<span class="mr-summary-text">' + escapeHtml(summary) + "</span></label>";
    }

    function formatFusionBarText(master, sources) {
        var m = master || "—";
        var src = (sources || []).filter(Boolean);
        if (!src.length) {
            return t("mr_fusion_bar_solo", "Master: {0} · no fusion").replace("{0}", m);
        }
        return t("mr_fusion_bar_with", "Master: {0} · Fusion: {1}")
            .replace("{0}", m)
            .replace("{1}", src.join(", "));
    }

    function renderFusionBar() {
        var bar = document.getElementById("mrFusionBar");
        if (!bar) return;
        if (phase !== "pick" || !selectedProvider) {
            bar.style.display = "none";
            bar.textContent = "";
            return;
        }
        var sources = manualCompletion
            ? fusionProvidersFromPicks(fieldPicks)
            : includeProviders.filter(function (p) { return p && p !== selectedProvider; });
        bar.style.display = "";
        bar.innerHTML = "<strong>" + escapeHtml(formatFusionBarText(selectedProvider, sources)) + "</strong>";
    }

    function renderEditFusionBar(preview) {
        var bar = document.getElementById("mrEditFusionBar");
        if (!bar) return;
        var master = (preview && preview._provider_used) || selectedProvider || "—";
        var sources = (preview && preview._fusion_providers) || [];
        if (!Array.isArray(sources)) sources = [];
        sources = sources.filter(function (p) { return p && p !== master; });
        bar.style.display = "";
        bar.innerHTML = "<strong>" + escapeHtml(formatFusionBarText(master, sources)) + "</strong>";
    }

    function playTone(kind) {
        if (!soundsEnabled) return;
        try {
            var Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            var ctx = new Ctx();
            var o = ctx.createOscillator();
            var g = ctx.createGain();
            o.connect(g);
            g.connect(ctx.destination);
            var freq = kind === "skip" ? 220 : kind === "confirm" ? 660 : 440;
            o.frequency.value = freq;
            g.gain.value = 0.04;
            o.start();
            setTimeout(function () {
                o.stop();
                ctx.close();
            }, 90);
        } catch (e) { /* ignore */ }
    }

    /**
     * Companion embed shell: no sidebar, so the review options come from the
     * server config (window.COMPANION_EMBED.options) instead of checkboxes.
     * Reading the absent DOM used to leave coverPickEnabled false forever, which
     * is why the Companion Super Review never offered the cover picker (BF107).
     */
    function embedOptions() {
        var cfg = window.COMPANION_EMBED;
        return cfg && cfg.options ? cfg.options : null;
    }

    function syncOptionsFromSidebar() {
        var editCb = document.getElementById("sidebar_manual_review_edit");
        var soundCb = document.getElementById("sidebar_manual_review_sounds");
        var coverCb = document.getElementById("sidebar_manual_review_cover");
        var embed = embedOptions();
        if (embed && !editCb && !coverCb) {
            editEnabled = embed.edit !== false;
            soundsEnabled = false;
            coverPickEnabled = !!embed.coverPick;
            return;
        }
        var wsConfig = window.WORKSHOP_CONFIG;
        if (wsConfig && !editCb && !coverCb) {
            editEnabled = wsConfig.edit !== false;
            soundsEnabled = false;
            coverPickEnabled = !!wsConfig.coverPick;
            return;
        }
        if (editCb) {
            var mrVal = editCb.getAttribute("data-mr-edit");
            editEnabled = mrVal != null ? mrVal === "true" : !!editCb.checked;
        } else {
            editEnabled = true;
        }
        soundsEnabled = soundCb ? !!soundCb.checked : false;
        coverPickEnabled = coverCb ? !!coverCb.checked : false;
    }

    function workshopForceReviewShot() {
        var shot = window.WORKSHOP_FORCE_REVIEW;
        return shot && typeof shot === "object" ? shot : null;
    }

    function isWorkshopPage() {
        return !!(document.documentElement && document.documentElement.classList.contains("workshop-page"));
    }

    function applyWorkshopQueueScope() {
        var shot = workshopForceReviewShot();
        if (!shot) return;
        var sid = shot.seriesId != null ? shot.seriesId : window.WORKSHOP_SERIES_ID;
        if (sid == null || sid === "") return;
        companionOnlySeriesId = Number(sid);
        companionOnlyReviewId = "";
    }

    function isManualModeOn() {
        var cb = document.getElementById("sidebar_manual_review_mode");
        if (cb) return !!cb.checked;
        var shot = workshopForceReviewShot();
        return !!(shot && (shot.review || shot.super));
    }

    function isCoverPickOn() {
        syncOptionsFromSidebar();
        return !!coverPickEnabled;
    }

    function isConfirmBeforeWriteOn() {
        var edit = document.getElementById("sidebar_manual_review_edit");
        if (!edit) return false;
        // Quand MR est off, la case pilote CONFIRM_BEFORE_WRITE (dataset).
        if (isManualModeOn()) return false;
        return (edit.dataset.confirmWrite || "false") === "true" || !!edit.checked;
    }

    function isReviewQueueModeOn() {
        return isManualModeOn() || isConfirmBeforeWriteOn();
    }

    function isAutoConfirmReview(review) {
        return !!(review && review.flow === "auto_confirm");
    }

    function isSuperReviewOn() {
        var embed = embedOptions();
        if (embed) return !!embed.superReview;
        var shot = workshopForceReviewShot();
        if (shot && shot.super) return true;
        if (!isManualModeOn()) return false;
        var cb = document.getElementById("sidebar_manual_review_super");
        return !!(cb && !cb.disabled && cb.checked);
    }

    function updateWaitPanelCopy() {
        var superOn = isSuperReviewOn();
        var textEl = document.getElementById("mrWaitText");
        var hintEl = document.getElementById("mrWaitHint");
        var warnEl = document.getElementById("mrWaitSuperWarn");
        if (researchInFlight) {
            if (textEl) {
                textEl.textContent = t(
                    "mr_wait_research_text",
                    "Nouvelle recherche en cours… les candidats vont être remplacés."
                );
            }
            if (hintEl) {
                hintEl.style.display = "";
                hintEl.textContent = t(
                    "mr_wait_research_hint",
                    "Patiente un instant — le scrape tourne avec le titre modifié."
                );
            }
            if (warnEl) warnEl.style.display = superOn ? "" : "none";
            return;
        }
        if (textEl) {
            textEl.textContent = superOn
                ? t("mr_wait_super_text", "Super Review: every scraper is running. This takes a while — coffee recommended.")
                : t("mr_wait_text", "The scraper is querying providers…");
        }
        if (hintEl) {
            hintEl.style.display = superOn ? "none" : "";
            hintEl.textContent = t(
                "mr_wait_hint",
                "Tu peux fermer et revenir plus tard — la file continue de se remplir."
            );
        }
        if (warnEl) {
            warnEl.style.display = superOn ? "" : "none";
        }
    }

    function isModalOpen() {
        var modal = document.getElementById("manualReviewModal");
        if (!modal || modal.dataset.kind === "volume") return false;
        var d = modal.style.display;
        return d && d !== "none";
    }

    function updateBadge(count) {
        var badge = document.getElementById("mrQueueBadge");
        var kpi = document.getElementById("kpiReviews");
        var n = typeof count === "number" ? count : queue.length;
        if (badge) badge.textContent = String(n);
        if (kpi) kpi.textContent = String(n);
        var openBtn = document.getElementById("mrOpenQueueBtn");
        if (openBtn) {
            if (n > 0) {
                openBtn.hidden = false;
                openBtn.style.display = "";
                openBtn.classList.add("has-pending");
            } else {
                openBtn.hidden = true;
                openBtn.classList.remove("has-pending");
            }
        }
        if (listViewOpen) renderListPanel();
    }

    function safeCoverUrl(url) {
        return toDisplayCoverUrl(url);
    }

    function reanchorIndex() {
        if (currentReviewId) {
            for (var i = 0; i < queue.length; i++) {
                if (queue[i].review_id === currentReviewId) {
                    currentIndex = i;
                    return;
                }
            }
            // Review courante disparue
            currentReviewId = null;
        }
        if (currentIndex >= queue.length) {
            currentIndex = Math.max(0, queue.length - 1);
        }
        var cur = queue[currentIndex];
        currentReviewId = cur ? cur.review_id : null;
    }

    function removeFromQueue(reviewId) {
        if (!reviewId) return;
        queue = queue.filter(function (r) { return r.review_id !== reviewId; });
        if (currentReviewId === reviewId) currentReviewId = null;
        reanchorIndex();
        updateBadge(queue.length);
    }

    function setActionBusy(busy) {
        actionInFlight = !!busy;
        ["mrPickBtn", "mrConfirmBtn", "mrSkipBtn"].forEach(function (id) {
            var btn = document.getElementById(id);
            if (btn) btn.disabled = !!busy;
        });
    }

    function currentReview() {
        var r = queue[currentIndex] || null;
        if (r) currentReviewId = r.review_id;
        return r;
    }

    function loadQueue() {
        var seq = ++loadQueueSeq;
        return api("/api/manual-reviews?limit=" + QUEUE_PAGE_SIZE).then(function (data) {
            if (seq !== loadQueueSeq) {
                return { data: data, prevEmpty: false, stale: true };
            }
            var prevEmpty = queue.length === 0;
            queue = data.reviews || [];
            if (companionOnlySeriesId != null) {
                queue = queue.filter(function (r) {
                    if (Number(r.series_id) !== companionOnlySeriesId) return false;
                    if (companionOnlyReviewId && String(r.review_id) !== companionOnlyReviewId) return false;
                    return true;
                });
            }
            queue.forEach(function (r) {
                if (!r) return;
                var rid = String(r.review_id || "");
                if (finalizedStreamIds[rid] || !r.streaming) {
                    r.streaming = false;
                    if (rid) finalizedStreamIds[rid] = true;
                } else {
                    r.streaming = true;
                }
            });
            queueTotal = companionOnlySeriesId != null
                ? queue.length
                : (data.count != null ? data.count : queue.length);
            // `queue.length > 0` est la garde qui empêche la boucle de rechargement :
            // une page revenue vide met fin à la pagination, quoi que dise le total.
            queueTruncated = queue.length > 0 && queueTotal > queue.length;
            updateBadge(queueTotal);
            reanchorIndex();
            return { data: data, prevEmpty: prevEmpty, stale: false };
        });
    }

    function showModalShell() {
        var modal = document.getElementById("manualReviewModal");
        if (!modal) return;
        previouslyFocused = document.activeElement;
        modal.style.display = "flex";
        modal.setAttribute("aria-hidden", "false");
        // Focus initial : champ recherche ou bouton pick
        var focusTarget = document.getElementById("mrSeriesQuery") || document.getElementById("mrPickBtn");
        if (focusTarget) {
            try { focusTarget.focus(); } catch (e) { /* ignore */ }
        }
    }

    function trapFocus(e) {
        if (!isModalOpen() || e.key !== "Tab") return;
        var modal = document.getElementById("manualReviewModal");
        if (!modal) return;
        var focusables = modal.querySelectorAll(
            'button:not([disabled]):not([style*="display: none"]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        var list = Array.prototype.filter.call(focusables, function (el) {
            return el.offsetParent !== null || el === document.activeElement;
        });
        if (!list.length) return;
        var first = list[0];
        var last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    // Lien de vérification vers la fiche série Kavita, affiché dans l'en-tête
    // (commun aux phases pick/cover/edit) — évite de valider la mauvaise série
    // sur un titre ambigu. Masqué si le library_id n'est pas encore résolu
    // (voir kavita_api.py::get_cached_library_id) ou si KAVITA_UI_URL est vide.
    function updateKavitaLink(review) {
        var link = document.getElementById("mrKavitaLink");
        if (!link) return;
        var base = window.KAVITA_UI_URL || "";
        if (review && review.library_id != null && review.series_id != null && base) {
            link.href = base + "/library/" + review.library_id + "/series/" + review.series_id;
            link.style.display = "";
        } else {
            link.removeAttribute("href");
            link.style.display = "none";
        }
    }

    function ensureStreamStatusBar(review) {
        var host = document.getElementById("mrPickPanel") || document.getElementById("mrAboveList");
        if (!host) return;
        var bar = document.getElementById("mrStreamStatus");
        var streaming = !!(review && review.streaming);
        if (!streaming) {
            if (bar) bar.remove();
            return;
        }
        if (!bar) {
            bar = document.createElement("div");
            bar.id = "mrStreamStatus";
            bar.className = "stream-status-bar";
            bar.style.cssText = "display:flex;align-items:center;gap:8px;margin:0 0 10px;font-size:12px;color:var(--text-muted,#94a3b8);";
            var spin = document.createElement("span");
            spin.className = "stream-spinner";
            var label = document.createElement("span");
            label.className = "mr-stream-label";
            bar.appendChild(spin);
            bar.appendChild(label);
            if (host.id === "mrAboveList" && host.parentNode) {
                host.parentNode.insertBefore(bar, host);
            } else {
                host.insertBefore(bar, host.firstChild);
            }
        }
        var labelEl = bar.querySelector(".mr-stream-label");
        if (labelEl) {
            var n = ((review.above || []).length) + ((review.below || []).length);
            labelEl.textContent = t(
                "mr_streaming",
                "Scraping en cours… {0} candidat(s) reçus"
            ).replace("{0}", String(n));
        }
    }

    function shouldShowBelow(review) {
        if (!review) return false;
        var below = review.below || [];
        if (!below.length) return false;
        if (showBelowThreshold) return true;
        var above = review.above || [];
        return !review.streaming && !above.length;
    }

    function assembleCandidates(review) {
        var all = [];
        if (!review) return all;
        (review.above || []).forEach(function (c) {
            all.push({ card: c, weak: false });
        });
        if (shouldShowBelow(review)) {
            (review.below || []).forEach(function (c) {
                all.push({ card: c, weak: true });
            });
        }
        return all;
    }

    function reconcileSelectionToVisible(all) {
        var visible = {};
        var i;
        for (i = 0; i < all.length; i++) {
            if (all[i].card && all[i].card.provider) {
                visible[all[i].card.provider] = true;
            }
        }
        includeProviders = includeProviders.filter(function (p) {
            return !!visible[p];
        });
        if (selectedProvider && !visible[selectedProvider]) {
            selectedProvider = all.length ? all[0].card.provider : null;
            if (selectedProvider) {
                includeProviders = includeProviders.filter(function (p) {
                    return p !== selectedProvider;
                });
            }
            if (manualCompletion) resetFieldPicks();
        }
        if (!selectedProvider && all.length) {
            selectedProvider = all[0].card.provider;
            if (manualCompletion) resetFieldPicks();
        }
    }

    function updateHiddenBelowHint(review) {
        var hint = document.getElementById("mrHiddenBelowHint");
        if (!hint) return;
        var above = (review && review.above) || [];
        var below = (review && review.below) || [];
        var show =
            !!review &&
            !!review.streaming &&
            !showBelowThreshold &&
            !above.length &&
            below.length > 0;
        if (!show) {
            hint.style.display = "none";
            hint.textContent = "";
            return;
        }
        hint.textContent = t(
            "mr_hidden_below",
            "{0} below threshold — check to show"
        ).replace("{0}", String(below.length));
        hint.style.display = "";
    }

    function markStreamingComplete(reviewId) {
        if (!reviewId) return null;
        var rid = String(reviewId);
        finalizedStreamIds[rid] = true;
        for (var i = 0; i < queue.length; i++) {
            if (String(queue[i].review_id) === rid) {
                queue[i].streaming = false;
                return queue[i];
            }
        }
        return null;
    }

    function mergeStreamedCandidate(payload) {
        if (researchInFlight) return;
        if (!payload || !payload.review_id || !payload.card) return;
        var rid = String(payload.review_id);
        var review = null;
        for (var i = 0; i < queue.length; i++) {
            if (String(queue[i].review_id) === rid) {
                review = queue[i];
                break;
            }
        }
        if (!review) {
            // Review not in local queue yet — soft insert so Companion can show it.
            review = {
                review_id: rid,
                series_id: payload.series_id,
                series_name: "",
                state: "awaiting_pick",
                above: [],
                below: [],
                streaming: true,
                query: ""
            };
            queue.push(review);
            if (companionOnlySeriesId != null && Number(review.series_id) !== companionOnlySeriesId) {
                queue = queue.filter(function (r) { return Number(r.series_id) === companionOnlySeriesId; });
            }
            reanchorIndex();
        }
        var band = payload.band === "below" ? "below" : "above";
        var provider = payload.card.provider;
        review.above = (review.above || []).filter(function (c) { return c.provider !== provider; });
        review.below = (review.below || []).filter(function (c) { return c.provider !== provider; });
        if (!review[band]) review[band] = [];
        review[band].push(payload.card);
        // Late candidate after scrape_complete: do not re-arm streaming (filet).
        if (!finalizedStreamIds[rid]) {
            review.streaming = true;
        } else {
            review.streaming = false;
        }
        if (isModalOpen() && String(currentReviewId) === rid) {
            renderCandidates();
        }
    }

    function renderCandidates(opts) {
        var review = currentReview();
        var aboveEl = document.getElementById("mrAboveList");
        var belowEl = document.getElementById("mrBelowList");
        var nameEl = document.getElementById("mrSeriesQuery");
        var posEl = document.getElementById("mrQueuePos");
        var aboveLabel = document.getElementById("mrAboveLabel");
        var belowLabel = document.getElementById("mrBelowLabel");
        var emptyEl = document.getElementById("mrNoCandidates");
        var pickPanel = document.getElementById("mrPickPanel");
        var keepScroll = !!(opts && opts.keepScroll);
        var savedScroll = (keepScroll && pickPanel) ? pickPanel.scrollTop : 0;
        if (!aboveEl || !belowEl) return;
        syncShowBelowCheckbox();
        syncManualCompletionControls();
        ensureStreamStatusBar(review);

        aboveEl.innerHTML = "";
        belowEl.innerHTML = "";
        if (!review) {
            if (nameEl && document.activeElement !== nameEl) nameEl.value = "";
            if (aboveLabel) aboveLabel.style.display = "none";
            if (belowLabel) belowLabel.style.display = "none";
            updateHiddenBelowHint(null);
            if (emptyEl) emptyEl.style.display = "";
            updateKavitaLink(null);
            renderFusionBar();
            return;
        }
        if (nameEl && document.activeElement !== nameEl) {
            nameEl.value = review.query || review.series_name || ("#" + review.series_id);
        }
        if (posEl) posEl.textContent = (currentIndex + 1) + " / " + queue.length;
        updateKavitaLink(review);

        var above = review.above || [];
        var showingBelow = shouldShowBelow(review);
        var all = assembleCandidates(review);
        updateHiddenBelowHint(review);
        reconcileSelectionToVisible(all);

        if (aboveLabel) aboveLabel.style.display = above.length ? "" : "none";
        if (belowLabel) {
            belowLabel.style.display = showingBelow ? "" : "none";
        }
        if (emptyEl) emptyEl.style.display = all.length ? "none" : "";

        var showMerge = all.length > 1 && !manualCompletion;
        ensureFieldPicks(review);

        all.forEach(function (entry, idx) {
            var c = entry.card;
            var el = document.createElement("div");
            el.className = "mr-candidate" + (entry.weak ? " mr-weak" : "") +
                (c.provider === selectedProvider ? " is-selected" : "");
            el.dataset.provider = c.provider;
            el.dataset.index = String(idx + 1);
            el.setAttribute("role", "button");
            el.tabIndex = 0;
            el.setAttribute("aria-pressed", c.provider === selectedProvider ? "true" : "false");

            var cover = renderCover(c);
            var score = (typeof c.score === "number") ? c.score.toFixed(2) : "—";
            var included = includeProviders.indexOf(c.provider) >= 0;
            var isMaster = c.provider === selectedProvider;
            var hotkey = idx < 9
                ? '<span class="mr-hotkey">' + (idx + 1) + "</span>"
                : "";
            var aside;
            if (all.length <= 1) {
                aside = '<div class="mr-candidate-aside"></div>';
            } else if (isMaster) {
                aside = '<div class="mr-candidate-aside" data-mr-aside>' +
                    '<span class="mr-master-badge">' + escapeHtml(t("mr_master", "Master")) + "</span>" +
                    "</div>";
            } else if (showMerge) {
                aside = '<div class="mr-candidate-aside" data-mr-aside>' +
                    '<label class="mr-include">' +
                    '<input type="checkbox" ' + (included ? "checked" : "") +
                    ' data-include="' + escapeHtml(c.provider) + '"> ' +
                    escapeHtml(t("mr_source", "Source")) +
                    "</label></div>";
            } else {
                aside = '<div class="mr-candidate-aside"></div>';
            }

            el.innerHTML =
                cover +
                '<div class="mr-candidate-body">' +
                '<div class="mr-candidate-top">' +
                hotkey +
                '<span class="mr-provider">' + escapeHtml(c.provider || "") + "</span>" +
                '<span class="mr-score ' + scoreClass(c.score) + '">' + score + "</span>" +
                "</div>" +
                renderTitle(c) +
                renderMetaChips(c) +
                renderSummary(c) +
                (entry.weak
                    ? '<span class="mr-weak-tag">' + escapeHtml(t("mr_weak", "weak")) + "</span>"
                    : "") +
                "</div>" +
                aside;

            el.addEventListener("click", function (ev) {
                if (ev.target.closest("[data-mr-aside], [data-mr-field-hit]")) return;
                if (c.provider === selectedProvider) return;
                selectMaster(c.provider);
                renderCandidates();
            });
            var cb = el.querySelector("input[data-include]");
            if (cb) {
                cb.addEventListener("change", function () {
                    var p = cb.getAttribute("data-include");
                    if (cb.checked) {
                        if (includeProviders.indexOf(p) < 0) includeProviders.push(p);
                    } else {
                        includeProviders = includeProviders.filter(function (x) { return x !== p; });
                    }
                    renderFusionBar();
                });
            }
            bindFieldPickInputs(el);
            (entry.weak ? belowEl : aboveEl).appendChild(el);
        });
        renderFusionBar();
        if (keepScroll && pickPanel) {
            pickPanel.scrollTop = savedScroll;
        } else {
            scrollSelectedCandidateIntoView();
        }
    }

    function scrollSelectedCandidateIntoView() {
        if (phase !== "pick" || !selectedProvider) return;
        var selected = document.querySelector("#mrPickPanel .mr-candidate.is-selected");
        if (!selected) return;
        requestAnimationFrame(function () {
            if (typeof selected.scrollIntoView === "function") {
                selected.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
            } else {
                var panel = document.getElementById("mrPickPanel");
                if (!panel) return;
                var top = selected.offsetTop - panel.clientHeight / 3;
                panel.scrollTop = Math.max(0, top);
            }
        });
    }

    function canGoBack() {
        if (phase === "cover") return true;
        if (phase === "edit") {
            if (isAutoConfirmReview(currentReview())) return currentIndex > 0;
            return true;
        }
        if (phase === "pick" && currentIndex > 0) return true;
        return false;
    }

    function updateBackBtn() {
        var backBtn = document.getElementById("mrBackBtn");
        if (backBtn) backBtn.style.display = canGoBack() ? "" : "none";
    }

    function goToPrevReview() {
        if (currentIndex <= 0) return false;
        currentIndex -= 1;
        selectedProvider = null;
        includeProviders = [];
        resetFieldPicks();
        baselinePreview = null;
        showCurrentReview();
        return true;
    }

    // showCurrentReview() est le seul endroit qui restaure le panneau d'édition
    // d'une review déjà pointée (awaiting_confirm / auto-confirm) et ses sources
    // de fusion : y passer dans les deux sens évite d'afficher une liste de
    // candidats pour une série dont le fournisseur est déjà choisi.
    function goToNextReview() {
        if (currentIndex >= queue.length - 1) return false;
        currentIndex += 1;
        selectedProvider = null;
        includeProviders = [];
        resetFieldPicks();
        baselinePreview = null;
        showCurrentReview();
        return true;
    }

    function kbdKeyHtml(label, wide) {
        return '<kbd class="mr-kbd-key' + (wide ? " is-wide" : "") + '">' +
            escapeHtml(label) + "</kbd>";
    }

    function kbdGroupHtml(keys, label) {
        var keysHtml = keys.map(function (k) {
            var wide = k.length > 2;
            return kbdKeyHtml(k, wide);
        }).join("");
        return '<span class="mr-kbd-group">' +
            '<span class="mr-kbd-keys">' + keysHtml + "</span>" +
            '<span class="mr-kbd-label">' + escapeHtml(label) + "</span>" +
            "</span>";
    }

    function renderKbdDock(next) {
        var dock = document.getElementById("mrKbdHint");
        if (!dock) return;
        var enter = t("mr_kbd_key_enter", "Entrée");
        var esc = t("mr_kbd_key_esc", "Échap");
        var groups = [];
        if (next === "pick") {
            groups = [
                kbdGroupHtml(["1", "2", "…", "9"], t("mr_kbd_act_pick", "Choisir")),
                kbdGroupHtml(["↑", "↓", "←", "→", "⌫"], t("mr_kbd_act_nav", "Naviguer")),
                kbdGroupHtml([enter], t("mr_kbd_act_confirm", "Confirmer")),
                kbdGroupHtml([esc], t("mr_kbd_act_skip", "Passer"))
            ];
        } else if (next === "cover") {
            groups = [
                kbdGroupHtml([enter], t("mr_kbd_act_cover_continue", "Continuer")),
                kbdGroupHtml([esc], t("mr_kbd_act_cover_skip", "Garder provider")),
                kbdGroupHtml(["⌫"], t("mr_kbd_act_back", "Retour"))
            ];
        } else if (next === "edit") {
            var curEdit = currentReview();
            if (isAutoConfirmReview(curEdit)) {
                groups = [
                    kbdGroupHtml([enter], t("mr_kbd_act_confirm", "Confirmer")),
                    kbdGroupHtml([esc], t("mr_kbd_act_skip", "Passer"))
                ];
            } else {
                groups = [
                    kbdGroupHtml([enter], t("mr_kbd_act_confirm", "Confirmer")),
                    kbdGroupHtml([esc, "⌫"], t("mr_kbd_act_back", "Retour"))
                ];
            }
        } else if (next === "waiting") {
            groups = [
                kbdGroupHtml([esc], t("mr_kbd_act_later", "Plus tard"))
            ];
        } else if (next === "recap") {
            groups = [
                kbdGroupHtml([enter, esc], t("mr_kbd_act_close", "Fermer"))
            ];
        }
        if (!groups.length) {
            dock.innerHTML = "";
            dock.style.display = "none";
            return;
        }
        dock.innerHTML = groups.join('<span class="mr-kbd-sep" aria-hidden="true"></span>');
        dock.style.display = "flex";
    }

    function setPhase(next) {
        phase = next;
        var pick = document.getElementById("mrPickPanel");
        var wait = document.getElementById("mrWaitPanel");
        var cover = document.getElementById("mrCoverPanel");
        var edit = document.getElementById("mrEditPanel");
        var recap = document.getElementById("mrRecapPanel");
        var pickBtn = document.getElementById("mrPickBtn");
        var confirmBtn = document.getElementById("mrConfirmBtn");
        var skipBtn = document.getElementById("mrSkipBtn");
        var coverContinueBtn = document.getElementById("mrCoverContinueBtn");
        var coverSkipBtn = document.getElementById("mrCoverSkipBtn");
        var waitBtn = document.getElementById("mrWaitBtn");
        var laterBtn = document.getElementById("mrLaterBtn");
        var closeRecapBtn = document.getElementById("mrCloseRecapBtn");
        var statsLink = document.getElementById("mrRecapStatsLink");
        var seriesBlock = document.querySelector(".mr-series-block");
        var fusionBar = document.getElementById("mrFusionBar");
        if (pick) pick.style.display = next === "pick" ? "block" : "none";
        if (wait) wait.style.display = next === "waiting" ? "flex" : "none";
        if (cover) cover.style.display = next === "cover" ? "block" : "none";
        if (edit) edit.style.display = next === "edit" ? "block" : "none";
        if (recap) recap.style.display = next === "recap" ? "block" : "none";
        if (pickBtn) pickBtn.style.display = next === "pick" ? "" : "none";
        if (confirmBtn) confirmBtn.style.display = next === "edit" ? "" : "none";
        if (skipBtn) skipBtn.style.display = (next === "pick" || next === "edit") ? "" : "none";
        if (coverContinueBtn) coverContinueBtn.style.display = next === "cover" ? "" : "none";
        if (coverSkipBtn) coverSkipBtn.style.display = next === "cover" ? "" : "none";
        if (waitBtn) waitBtn.style.display = next === "waiting" ? "" : "none";
        if (laterBtn) {
            laterBtn.style.display = (next === "waiting" && !researchInFlight) ? "" : "none";
        }
        if (closeRecapBtn) closeRecapBtn.style.display = next === "recap" ? "" : "none";
        if (statsLink) statsLink.style.display = next === "recap" ? "" : "none";
        if (seriesBlock) seriesBlock.style.display = next === "recap" ? "none" : "";
        var nagCta = document.getElementById("mrRecapNagCta");
        if (nagCta && next !== "recap") nagCta.style.display = "none";
        updateBackBtn();
        if (next === "waiting") {
            updateWaitPanelCopy();
        }
        renderKbdDock(next);
        var queryInput = document.getElementById("mrSeriesQuery");
        var researchBtn = document.getElementById("mrResearchBtn");
        // Pendant l'attente du premier scrape, on peut déjà forcer un autre
        // titre. Une re-recherche déjà lancée désactive le champ (garde JS).
        var canResearch = (
            next === "pick" ||
            next === "edit" ||
            (next === "waiting" && !researchInFlight)
        );
        if (queryInput) queryInput.disabled = !canResearch;
        if (researchBtn) researchBtn.style.display = canResearch ? "" : "none";
        if (fusionBar && next !== "pick") {
            fusionBar.style.display = "none";
        }
        if (next === "pick") {
            renderFusionBar();
        }
        if (next !== "cover" && typeof stopCoverSearch === "function") {
            stopCoverSearch();
        }
    }

    window.mrGoBack = function () {
        if (phase === "cover") {
            setPhase("pick");
            return;
        }
        if (phase === "edit") {
            var cur = currentReview();
            if (isAutoConfirmReview(cur)) {
                goToPrevReview();
                return;
            }
            if (isCoverPickOn()) {
                enterCoverPhase(baselinePreview || {});
                return;
            }
            setPhase("pick");
            return;
        }
        if (phase === "pick") {
            goToPrevReview();
        }
    };

    function updateCoverPreview(url) {
        var img = document.getElementById("mrCoverPreview");
        var empty = document.getElementById("mrCoverPreviewEmpty");
        var safe = toDisplayCoverUrl(url);
        if (img) {
            if (safe) {
                img.src = safe;
                img.style.display = "";
            } else {
                img.removeAttribute("src");
                img.style.display = "none";
            }
        }
        if (empty) empty.style.display = safe ? "none" : "";
    }

    function enterCoverPhase(preview) {
        baselinePreview = preview || baselinePreview || {};
        coverPicked = false;
        providerCoverUrl = (baselinePreview && baselinePreview.cover_url) || "";
        var review = currentReview();
        var qInput = document.getElementById("mrCoverQuery");
        // Toujours recalculer depuis la review courante — ne pas réutiliser
        // mrCoverQuery (sinon le nom de la 1re série du batch reste collé).
        var q = (review && (review.series_name || review.query)) || "";
        if (qInput) qInput.value = q;
        var nameEl = document.getElementById("mrSeriesQuery");
        var posEl = document.getElementById("mrQueuePos");
        if (nameEl && document.activeElement !== nameEl && review) {
            nameEl.value = review.query || review.series_name || ("#" + review.series_id);
        }
        if (posEl && review) {
            posEl.textContent = (currentIndex + 1) + " / " + queue.length;
        }
        updateKavitaLink(review);
        updateCoverPreview(providerCoverUrl);
        setPhase("cover");
        mrSearchCovers();
    }

    window.mrSearchCovers = function () {
        var review = currentReview();
        if (!review) return;
        var qInput = document.getElementById("mrCoverQuery");
        var grid = document.getElementById("mrCoversGrid");
        var query = (qInput && qInput.value ? qInput.value : "").trim()
            || review.query
            || review.series_name
            || "";
        if (!query || !grid || typeof startCoverSearch !== "function") return;
        startCoverSearch({
            seriesId: review.series_id,
            query: query,
            gridEl: grid,
            onPick: function (url) {
                if (!baselinePreview) baselinePreview = {};
                baselinePreview.cover_url = url || "";
                coverPicked = true;
                updateCoverPreview(url);
                grid.querySelectorAll(".cover-item").forEach(function (el) {
                    el.classList.toggle("is-selected", el.dataset.url === url);
                });
            }
        });
    };

    window.mrCoverContinue = function () {
        syncOptionsFromSidebar();
        if (editEnabled) {
            renderEdit(baselinePreview || {});
            setPhase("edit");
            return;
        }
        mrConfirmCurrent();
    };

    window.mrCoverSkip = function () {
        if (!baselinePreview) baselinePreview = {};
        baselinePreview.cover_url = providerCoverUrl || baselinePreview.cover_url || "";
        coverPicked = false;
        updateCoverPreview(baselinePreview.cover_url);
        mrCoverContinue();
    };

    var AGE_TOKENS = ["safe", "suggestive", "mature", "r18", "x18"];
    var AGE_ALIASES = { erotica: "r18", pornographic: "x18" };
    var FIELD_LABEL_FALLBACKS = {
        title: "Title",
        summary: "Summary",
        year: "Year",
        status: "Status",
        genres: "Genres",
        tags: "Tags",
        publisher: "Publisher",
        age_rating: "Age rating",
        format: "Format",
        cover_url: "Cover URL",
        localized_name: "Localized title",
        staff: "Staff",
        writers: "Writers",
        pencillers: "Pencillers"
    };

    function normalizeAgeRatingToken(raw) {
        if (raw == null) return "";
        var s = String(raw).trim().toLowerCase();
        if (!s) return "";
        if (AGE_ALIASES[s]) return AGE_ALIASES[s];
        if (AGE_TOKENS.indexOf(s) !== -1) return s;
        return "";
    }

    function fieldLabel(key) {
        return t("mr_field_" + key, FIELD_LABEL_FALLBACKS[key] || key);
    }

    function editSendKey(fieldKey) {
        if (!fieldKey) return null;
        if (fieldKey === "title" || fieldKey === "format") return null;
        if (EDIT_SEND_ALIASES[fieldKey]) return EDIT_SEND_ALIASES[fieldKey];
        if (ALL_TARGETED_FIELD_KEYS.indexOf(fieldKey) >= 0) return fieldKey;
        return null;
    }

    function seriesWriteFields(preview) {
        var raw = preview && preview._active_fields;
        // Clé absente (vieux preview) = ALL. Tableau vide = override NONE : tout geler.
        if (!Array.isArray(raw)) {
            return ALL_TARGETED_FIELD_KEYS.slice();
        }
        return raw.slice();
    }

    function fieldIsWriteLocked(sendKey, preview) {
        if (!sendKey) return false;
        return seriesWriteFields(preview).indexOf(sendKey) < 0;
    }

    function setEditSendEnabled(sendKey, enabled) {
        var wrap = document.getElementById("mrEditFields");
        if (!wrap || !sendKey) return;
        wrap.querySelectorAll("[data-field]").forEach(function (el) {
            if (editSendKey(el.getAttribute("data-field")) !== sendKey) return;
            el.disabled = !enabled;
            var field = el.closest(".mr-edit-field");
            if (field) field.classList.toggle("is-send-off", !enabled);
        });
        if (sendKey === "cover") {
            wrap.classList.toggle("is-cover-send-off", !enabled);
        }
    }

    function collectSendFields() {
        var seen = {};
        var out = [];
        document.querySelectorAll("#mrEditFields input[data-mr-send]").forEach(function (cb) {
            var key = cb.getAttribute("data-mr-send");
            if (!key || seen[key]) return;
            seen[key] = true;
            if (cb.checked && !cb.disabled) out.push(key);
        });
        return out;
    }

    function previewFieldString(preview, key) {
        var val = preview ? preview[key] : "";
        if (val == null) val = "";
        if (Array.isArray(val)) val = val.join(", ");
        else if (typeof val === "object") val = JSON.stringify(val);
        else val = String(val);
        if (key === "age_rating") val = normalizeAgeRatingToken(val);
        return val;
    }

    function buildEditField(key, opts) {
        opts = opts || {};
        var val = previewFieldString(baselinePreview, key);
        var sendKey = opts.sendKey !== undefined ? opts.sendKey : editSendKey(key);
        var displayOnly = !!opts.displayOnly || sendKey === null;
        var locked = !displayOnly && fieldIsWriteLocked(sendKey, baselinePreview);
        var sendOn = !displayOnly && !locked && opts.sendOn !== false;
        var group = document.createElement("div");
        group.className = "mr-edit-field" + (opts.compact ? " mr-edit-compact" : "")
            + (opts.wide ? " mr-edit-wide" : "")
            + (opts.extraClass ? (" " + opts.extraClass) : "");
        if (displayOnly) group.classList.add("is-display-only");
        if (locked) group.classList.add("is-write-locked");
        if (!displayOnly && !sendOn) group.classList.add("is-send-off");

        var head = document.createElement("div");
        head.className = "mr-edit-label";
        if (!displayOnly && sendKey && !opts.hideSend) {
            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.className = "mr-edit-send";
            cb.setAttribute("data-mr-send", sendKey);
            cb.checked = sendOn;
            cb.disabled = locked;
            cb.title = locked
                ? t("mr_edit_send_locked", "Not in this series' targeted fields — Kavita will be left as-is.")
                : t("mr_edit_send_title", "Checked: this field is written to Kavita. Unchecked: Kavita is left as-is.");
            cb.setAttribute("aria-label", t("mr_edit_send", "Send {0}").replace("{0}", fieldLabel(key)));
            cb.addEventListener("change", function () {
                setEditSendEnabled(sendKey, cb.checked && !cb.disabled);
            });
            head.appendChild(cb);
        }
        var name = document.createElement("span");
        name.className = "mr-edit-label-text";
        name.textContent = fieldLabel(key);
        head.appendChild(name);
        if (locked || displayOnly) {
            var lock = document.createElement("span");
            lock.className = "mr-edit-lock";
            lock.setAttribute("aria-hidden", "true");
            lock.textContent = "🔒";
            head.appendChild(lock);
            head.title = displayOnly
                ? t("mr_edit_never_writable", "Kavita does not accept this field — display only.")
                : t("mr_edit_send_locked", "Not in this series' targeted fields — Kavita will be left as-is.");
        }
        group.appendChild(head);

        var control;
        if (key === "age_rating") {
            control = document.createElement("select");
            control.className = "mr-edit-input";
            control.setAttribute("data-field", key);
            control.id = "mr-field-" + key;
            var noneOpt = document.createElement("option");
            noneOpt.value = "";
            noneOpt.textContent = t("mr_age_none", "(none)");
            control.appendChild(noneOpt);
            [
                ["safe", "mr_age_safe", "Everyone"],
                ["suggestive", "mr_age_suggestive", "Teen"],
                ["mature", "mr_age_mature", "Mature 17+"],
                ["r18", "mr_age_r18", "R18+"],
                ["x18", "mr_age_x18", "X18+"]
            ].forEach(function (row) {
                var opt = document.createElement("option");
                opt.value = row[0];
                opt.textContent = t(row[1], row[2]);
                control.appendChild(opt);
            });
            control.value = val;
        } else if (opts.rows) {
            control = document.createElement("textarea");
            control.className = "mr-edit-input";
            control.setAttribute("data-field", key);
            control.id = "mr-field-" + key;
            control.rows = opts.rows;
            control.spellcheck = false;
            control.value = val;
        } else {
            control = document.createElement("input");
            control.className = "mr-edit-input";
            control.type = "text";
            control.setAttribute("data-field", key);
            control.id = "mr-field-" + key;
            control.spellcheck = false;
            control.autocomplete = "off";
            control.value = val;
        }
        if (displayOnly || locked || !sendOn) {
            control.disabled = true;
        }
        group.appendChild(control);
        return group;
    }

    function syncEditCoverThumb(img, url) {
        if (!img) return;
        var safe = typeof toDisplayCoverUrl === "function" ? toDisplayCoverUrl(url) : (url || "");
        if (safe) {
            img.src = safe;
            img.style.display = "";
            img.alt = fieldLabel("cover_url");
        } else {
            img.removeAttribute("src");
            img.style.display = "none";
            img.alt = "";
        }
        var empty = img.parentElement
            ? img.parentElement.querySelector(".mr-edit-cover-empty")
            : null;
        if (empty) empty.style.display = safe ? "none" : "";
    }

    function renderEdit(preview) {
        baselinePreview = preview || {};
        // Compat : preview serveur expose `staff` ; UI historique writers/pencillers
        if (baselinePreview.staff && !baselinePreview.writers && !baselinePreview.pencillers) {
            baselinePreview.writers = "";
            baselinePreview.pencillers = "";
        }
        // Canon âge dès l'entrée edit (évite faux diff erotica → r18)
        baselinePreview.age_rating = normalizeAgeRatingToken(baselinePreview.age_rating);

        renderEditFusionBar(baselinePreview);
        var wrap = document.getElementById("mrEditFields");
        if (!wrap) return;
        wrap.innerHTML = "";
        wrap.className = "mr-edit-fiche";

        var top = document.createElement("div");
        top.className = "mr-edit-fiche-top";

        var coverCol = document.createElement("div");
        coverCol.className = "mr-edit-cover-col";
        var coverLocked = fieldIsWriteLocked("cover", baselinePreview);
        var coverHead = document.createElement("div");
        coverHead.className = "mr-edit-label";
        var coverCb = document.createElement("input");
        coverCb.type = "checkbox";
        coverCb.className = "mr-edit-send";
        coverCb.setAttribute("data-mr-send", "cover");
        coverCb.checked = !coverLocked;
        coverCb.disabled = coverLocked;
        coverCb.title = coverLocked
            ? t("mr_edit_send_locked", "Not in this series' targeted fields — Kavita will be left as-is.")
            : t("mr_edit_send_title", "Checked: this field is written to Kavita. Unchecked: Kavita is left as-is.");
        coverCb.setAttribute("aria-label", t("mr_edit_send", "Send {0}").replace("{0}", fieldLabel("cover_url")));
        coverCb.addEventListener("change", function () {
            setEditSendEnabled("cover", coverCb.checked && !coverCb.disabled);
        });
        coverHead.appendChild(coverCb);
        var coverName = document.createElement("span");
        coverName.className = "mr-edit-label-text";
        coverName.textContent = fieldLabel("cover_url");
        coverHead.appendChild(coverName);
        if (coverLocked) {
            var coverLock = document.createElement("span");
            coverLock.className = "mr-edit-lock";
            coverLock.setAttribute("aria-hidden", "true");
            coverLock.textContent = "🔒";
            coverHead.appendChild(coverLock);
            coverHead.title = t("mr_edit_send_locked", "Not in this series' targeted fields — Kavita will be left as-is.");
            coverCol.classList.add("is-write-locked");
        }
        coverCol.appendChild(coverHead);
        var thumbWrap = document.createElement("div");
        thumbWrap.className = "mr-edit-cover-thumb-wrap";
        var thumb = document.createElement("img");
        thumb.className = "mr-edit-cover-thumb";
        thumb.alt = "";
        var thumbEmpty = document.createElement("div");
        thumbEmpty.className = "mr-edit-cover-empty";
        thumbEmpty.textContent = "—";
        thumbWrap.appendChild(thumb);
        thumbWrap.appendChild(thumbEmpty);
        coverCol.appendChild(thumbWrap);

        var coverDetails = document.createElement("details");
        coverDetails.className = "mr-edit-cover-url";
        var coverSummary = document.createElement("summary");
        coverSummary.textContent = t("mr_cover_url_toggle", "Cover URL");
        coverDetails.appendChild(coverSummary);
        var coverField = buildEditField("cover_url", {
            rows: 2,
            extraClass: "mr-edit-cover-url-field",
            hideSend: true
        });
        // Label déjà dans summary — on masque le label interne du champ
        var coverLabel = coverField.querySelector(".mr-edit-label");
        if (coverLabel) coverLabel.style.display = "none";
        coverDetails.appendChild(coverField);
        coverCol.appendChild(coverDetails);
        top.appendChild(coverCol);

        var metaCol = document.createElement("div");
        metaCol.className = "mr-edit-meta-col";
        metaCol.appendChild(buildEditField("title"));
        metaCol.appendChild(buildEditField("localized_name", { rows: 2 }));

        var metaRow = document.createElement("div");
        metaRow.className = "mr-edit-meta-row";
        ["year", "status", "age_rating", "format"].forEach(function (key) {
            metaRow.appendChild(buildEditField(key, { compact: true }));
        });
        metaCol.appendChild(metaRow);
        metaCol.appendChild(buildEditField("publisher", { compact: true }));
        top.appendChild(metaCol);
        wrap.appendChild(top);

        var body = document.createElement("div");
        body.className = "mr-edit-fiche-body";
        body.appendChild(buildEditField("summary", { rows: 6, wide: true }));

        var dual = document.createElement("div");
        dual.className = "mr-edit-dual";
        dual.appendChild(buildEditField("genres", { rows: 2 }));
        dual.appendChild(buildEditField("tags", { rows: 2 }));
        body.appendChild(dual);

        var hasStaff = !!(baselinePreview.staff);
        var hasSplit = !!(baselinePreview.writers || baselinePreview.pencillers);
        if (hasStaff && !hasSplit) {
            body.appendChild(buildEditField("staff", { rows: 2, wide: true }));
        } else if (hasSplit) {
            var staffDual = document.createElement("div");
            staffDual.className = "mr-edit-dual";
            if (baselinePreview.writers) staffDual.appendChild(buildEditField("writers", { rows: 2 }));
            if (baselinePreview.pencillers) {
                staffDual.appendChild(buildEditField("pencillers", {
                    rows: 2,
                    hideSend: !!baselinePreview.writers
                }));
            }
            body.appendChild(staffDual);
        } else {
            body.appendChild(buildEditField("staff", { rows: 2, wide: true }));
        }
        wrap.appendChild(body);

        if (coverLocked) wrap.classList.add("is-cover-send-off");
        var coverInput = wrap.querySelector('[data-field="cover_url"]');
        syncEditCoverThumb(thumb, coverInput ? coverInput.value : baselinePreview.cover_url);
        if (coverInput) {
            var onCoverChange = function () {
                syncEditCoverThumb(thumb, coverInput.value);
            };
            coverInput.addEventListener("input", onCoverChange);
            coverInput.addEventListener("change", onCoverChange);
        }
    }

    function collectEdits() {
        var edited = {};
        var fieldEdits = 0;
        document.querySelectorAll("#mrEditFields [data-field]").forEach(function (el) {
            if (el.disabled) return;
            var key = el.getAttribute("data-field");
            var raw = el.value;
            var base = baselinePreview ? baselinePreview[key] : "";
            if (Array.isArray(base)) base = base.join(", ");
            else if (base == null) base = "";
            else if (typeof base === "object") base = JSON.stringify(base);
            else base = String(base);
            if (key === "age_rating") {
                raw = normalizeAgeRatingToken(raw);
                base = normalizeAgeRatingToken(base);
            }
            if (String(raw) !== String(base)) {
                fieldEdits += 1;
                if (key === "genres" || key === "tags" || key === "writers" || key === "pencillers") {
                    edited[key] = raw.split(/[,;]/).map(function (s) { return s.trim(); }).filter(Boolean);
                } else if (key === "year") {
                    var n = parseInt(raw, 10);
                    edited[key] = isNaN(n) ? raw : n;
                } else {
                    edited[key] = raw;
                }
            }
        });
        return { edited: edited, field_edits: fieldEdits };
    }

    function showRecapIfEmpty() {
        if (queue.length) return false;
        // Page épuisée alors que la file en contient encore : aller chercher la
        // suivante. Sans ça, la 201e review et les suivantes n'étaient jamais
        // servies et le récap annonçait « tout est fait » à leur place.
        if (queueTruncated && !queueRefillInFlight) {
            queueRefillInFlight = true;
            loadQueue().then(function () {
                queueRefillInFlight = false;
                if (queue.length) showCurrentReview();
                else showRecapIfEmpty();
            }).catch(function () {
                // Page suivante inaccessible : ne pas laisser la modale en plan.
                queueRefillInFlight = false;
                queueTruncated = false;
                showRecapIfEmpty();
            });
            return true;
        }
        // Batch encore actif (barre de progression visible, `batch.js`) : la file
        // vidée n'est qu'un creux temporaire entre deux séries, pas la vraie fin —
        // sans ce garde-fou le récap s'affichait puis basculait sur la review
        // suivante quelques secondes plus tard dès qu'elle arrivait. Le masque
        // d'attente évite ce flash ; `mrOnBatchProgress()` → `settleWaitingAfterWork()`
        // rebasculera vers la review suivante ou le vrai récap une fois le batch
        // réellement terminé (`phase !== "waiting"` évite de re-déclencher ce garde-fou
        // à ce moment-là, puisque `batchProgressTotal` ne retombe à 0 qu'avec ~1.5s
        // de délai après la fin réelle — voir `batch.js::applyBatchProgressPayload`).
        if (phase !== "waiting" && typeof batchProgressTotal === "number" && batchProgressTotal > 0) {
            var queryElWait = document.getElementById("mrSeriesQuery");
            var posElWait = document.getElementById("mrQueuePos");
            if (queryElWait) queryElWait.value = "";
            if (posElWait) posElWait.textContent = "";
            updateKavitaLink(null);
            setPhase("waiting");
            return true;
        }
        setPhase("recap");
        var queryEl = document.getElementById("mrSeriesQuery");
        var posEl = document.getElementById("mrQueuePos");
        if (queryEl) queryEl.value = "";
        if (posEl) posEl.textContent = "";
        updateKavitaLink(null);
        renderRecapAchievements();
        renderRecapKpis();
        updateBadge(0);
        try {
            if (window.SupporterNag && typeof window.SupporterNag.onMrRecap === "function") {
                window.SupporterNag.onMrRecap(session);
            }
        } catch (e) { /* pubs supporter : jamais bloquer le récap MR */ }
        return true;
    }

    function showCurrentReview() {
        var review = currentReview();
        if (!review) {
            showRecapIfEmpty();
            return;
        }
        // Auto-confirm ou preview déjà prêt → reprise post-pick
        if (review.preview && (isAutoConfirmReview(review) || review.state === "awaiting_confirm")) {
            selectedProvider = review.base_provider
                || (review.above && review.above[0] && review.above[0].provider)
                || selectedProvider;
            // Restore Sources from persisted preview so confirm re-merges the
            // same fusion (reopen / queue jump used to wipe includeProviders).
            includeProviders = ((review.preview && review.preview._fusion_providers) || [])
                .filter(function (p) { return p && p !== selectedProvider; });
            restorePicksFromPreview(review.preview);
            var nameEl = document.getElementById("mrSeriesQuery");
            var posEl = document.getElementById("mrQueuePos");
            if (nameEl && document.activeElement !== nameEl) {
                nameEl.value = review.query || review.series_name || ("#" + review.series_id);
            }
            if (posEl) posEl.textContent = (currentIndex + 1) + " / " + queue.length;
            updateKavitaLink(review);
            baselinePreview = review.preview || {};
            syncOptionsFromSidebar();
            // MR + cover pick : ne pas sauter la phase cover au reopen / jump
            // (auto_confirm / CBW n'active jamais le toggle cover — MR mode requis).
            if (!isAutoConfirmReview(review) && isCoverPickOn()) {
                enterCoverPhase(baselinePreview);
                return;
            }
            renderEdit(review.preview);
            setPhase("edit");
            return;
        }
        syncManualCompletionControls();
        setPhase("pick");
        renderCandidates();
    }

    function advanceAfterRemove(reviewId) {
        removeFromQueue(reviewId);
        selectedProvider = null;
        includeProviders = [];
        resetFieldPicks();
        manualCompletion = false;
        mergeFields = false;
        syncManualCompletionControls();
        baselinePreview = null;
        coverPicked = false;
        providerCoverUrl = "";
        if (showRecapIfEmpty()) return;
        showCurrentReview();
    }

    // --- VUE LISTE (choisir une série / tout accepter) ---
    // Panneau indépendant de la machine à états `phase` (pick/cover/edit/...) :
    // s'affiche PAR-DESSUS le panneau courant sans y toucher, pour pouvoir y
    // revenir tel quel à la fermeture (setPhase(phase) suffit à le restaurer).
    function topCandidate(review) {
        var above = (review && review.above) || [];
        if (above.length) return { card: above[0], weak: false };
        var below = (review && review.below) || [];
        if (below.length) return { card: below[0], weak: true };
        return null;
    }

    function renderListPanel() {
        var body = document.getElementById("mrListBody");
        var emptyEl = document.getElementById("mrListEmpty");
        var truncatedEl = document.getElementById("mrListTruncated");
        if (truncatedEl) {
            if (queueTruncated) {
                truncatedEl.textContent = t(
                    "mr_list_truncated",
                    "Les {0} plus anciennes sur {1} — traitez-les, la suite se chargera ensuite."
                ).replace("{0}", String(queue.length)).replace("{1}", String(queueTotal));
                truncatedEl.style.display = "";
            } else {
                truncatedEl.style.display = "none";
            }
        }
        if (!body) return;
        body.innerHTML = "";
        if (!queue.length) {
            if (emptyEl) emptyEl.style.display = "";
            return;
        }
        if (emptyEl) emptyEl.style.display = "none";

        queue.forEach(function (review) {
            var top = topCandidate(review);
            var row = document.createElement("button");
            row.type = "button";
            row.className = "mr-list-row" + (review.review_id === currentReviewId ? " is-current" : "");
            row.setAttribute("aria-current", review.review_id === currentReviewId ? "true" : "false");
            row.onclick = function () { mrJumpToReview(review.review_id); };

            var nameSpan = document.createElement("span");
            nameSpan.className = "mr-list-row-name";
            nameSpan.textContent = review.series_name || review.query || ("#" + review.series_id);
            row.appendChild(nameSpan);

            var scoreSpan = document.createElement("span");
            if (top) {
                var pct = Math.round((top.card.score || 0) * 100);
                scoreSpan.className = "mr-score " + scoreClass(top.card.score) + (top.weak ? " mr-weak" : "");
                scoreSpan.textContent = pct + "% · " + (top.card.provider || "");
            } else {
                scoreSpan.className = "mr-score mr-score-low";
                scoreSpan.textContent = t("mr_list_no_hit", "Aucun candidat");
            }
            row.appendChild(scoreSpan);

            body.appendChild(row);
        });
    }

    function setPanelButtonsVisibility(hidden) {
        [
            "mrPickBtn", "mrConfirmBtn", "mrSkipBtn", "mrCoverContinueBtn",
            "mrCoverSkipBtn", "mrWaitBtn", "mrLaterBtn", "mrCloseRecapBtn", "mrBackBtn"
        ].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = hidden ? "none" : "";
        });
        // Ré-applique l'état normal de setPhase() une fois la liste refermée.
        if (!hidden) setPhase(phase);
    }

    function openListView() {
        listViewOpen = true;
        renderListPanel();
        ["mrPickPanel", "mrWaitPanel", "mrCoverPanel", "mrEditPanel", "mrRecapPanel"].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = "none";
        });
        var listPanel = document.getElementById("mrListPanel");
        if (listPanel) listPanel.style.display = "block";
        setPanelButtonsVisibility(true);
        var toggleBtn = document.getElementById("mrListToggleBtn");
        if (toggleBtn) toggleBtn.classList.add("is-active");
    }

    function closeListView() {
        listViewOpen = false;
        var listPanel = document.getElementById("mrListPanel");
        if (listPanel) listPanel.style.display = "none";
        var toggleBtn = document.getElementById("mrListToggleBtn");
        if (toggleBtn) toggleBtn.classList.remove("is-active");
        setPanelButtonsVisibility(false);
    }

    window.mrToggleListView = function () {
        if (isWorkshopPage()) return;
        if (!queue.length && !listViewOpen) return;
        if (listViewOpen) closeListView();
        else openListView();
    };

    window.mrJumpToReview = function (reviewId) {
        var idx = -1;
        for (var i = 0; i < queue.length; i++) {
            if (queue[i].review_id === reviewId) { idx = i; break; }
        }
        if (idx === -1) return;
        currentIndex = idx;
        currentReviewId = reviewId;
        selectedProvider = null;
        includeProviders = [];
        resetFieldPicks();
        baselinePreview = null;
        coverPicked = false;
        providerCoverUrl = "";
        closeListView();
        showCurrentReview();
    };

    window.mrBulkAccept = function () {
        if (isWorkshopPage() || bulkAcceptInFlight) return;
        var input = document.getElementById("mrListThreshold");
        var threshold = input ? parseFloat(input.value) : 0.6;
        if (isNaN(threshold)) threshold = 0.6;
        threshold = Math.max(0.3, Math.min(1, threshold));

        var confirmMsg = t(
            "mr_list_bulk_confirm",
            "Accepter automatiquement toutes les reviews dont le meilleur candidat dépasse {0}% ? Les autres restent en file."
        ).replace("{0}", Math.round(threshold * 100));
        if (!window.confirm(confirmMsg)) return;

        var btn = document.getElementById("mrBulkAcceptBtn");
        var feedback = document.getElementById("mrListFeedback");
        bulkAcceptInFlight = true;
        if (btn) btn.disabled = true;
        if (feedback) feedback.textContent = "";

        api("/api/manual-reviews/bulk-accept", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threshold: threshold })
        }).then(function (data) {
            var wasCurrentReview = currentReviewId;
            return loadQueue().then(function () {
                session.done += data.accepted || 0;
                if (feedback) {
                    var msg = t("mr_list_bulk_done", "{0} accepté(s), {1} laissée(s) en file.")
                        .replace("{0}", String(data.accepted || 0))
                        .replace("{1}", String(data.skipped || 0));
                    // Le seuil demandé peut descendre sous le seuil de match : dire
                    // combien de correspondances faibles ont été acceptées, plutôt
                    // que de les fondre dans le total.
                    if (data.accepted_weak) {
                        msg += " " + t("mr_list_bulk_weak", "Dont {0} correspondance(s) faible(s) — à vérifier.")
                            .replace("{0}", String(data.accepted_weak));
                    }
                    // `data.failed` (backend) ne portait que des review_id bruts — sans
                    // ça les échecs individuels (ex: écriture Kavita refusée pendant le
                    // bulk-accept) disparaissaient silencieusement derrière le seul
                    // compteur "skipped", qui ne veut dire QUE "sous le seuil".
                    var failedList = Array.isArray(data.failed) ? data.failed : [];
                    if (failedList.length) {
                        var names = failedList.map(function (f) {
                            var match = null;
                            for (var i = 0; i < queue.length; i++) {
                                if (queue[i].review_id === f.review_id) { match = queue[i]; break; }
                            }
                            var label = match ? match.series_name : ("#" + f.review_id);
                            return label + (f.error ? " (" + f.error + ")" : "");
                        });
                        msg += " " + t("mr_list_bulk_failed", "⚠️ {0} échec(s) — restées en file : {1}")
                            .replace("{0}", String(failedList.length))
                            .replace("{1}", names.join(", "));
                    }
                    feedback.textContent = msg;
                    feedback.className = failedList.length ? "field-hint m-0 field-hint--error" : "field-hint m-0";
                }
                renderListPanel();
                if (!queue.length) {
                    closeListView();
                    showRecapIfEmpty();
                    return;
                }
                // La série affichée derrière la liste a pu être acceptée : ré-ancre
                // sur une review qui existe encore.
                if (wasCurrentReview) reanchorIndex();
            });
        }).catch(function (err) {
            if (feedback) feedback.textContent = err.message || String(err);
        }).then(function () {
            bulkAcceptInFlight = false;
            if (btn) btn.disabled = false;
        });
    };

    function markSeriesStatus(seriesId, status) {
        var sid = String(seriesId == null ? "" : seriesId);
        if (!/^\d+$/.test(sid)) return;
        document.querySelectorAll('.series-item input[value="' + sid + '"]').forEach(function (inp) {
            var item = inp.closest(".series-item");
            if (!item) return;
            if (typeof applySeriesStatusBadge === "function") {
                applySeriesStatusBadge(item, status);
            } else {
                item.setAttribute("data-status", status);
                var badge = item.querySelector(".series-status .badge");
                if (!badge) return;
                if (status === "COMPLETED") {
                    badge.className = "badge badge-completed";
                    badge.innerText = t("filter_completed", "Completed");
                } else if (status === "NEEDS_RELOCK") {
                    badge.className = "badge badge-needs-relock";
                    badge.innerText = t("filter_needs_relock", "Needs seal");
                } else if (status === "PENDING_REVIEW") {
                    badge.className = "badge badge-review";
                    badge.innerText = t("filter_pending_review", "Review");
                } else if (status === "PENDING") {
                    badge.className = "badge badge-pending";
                    badge.innerText = t("filter_pending", "Pending");
                }
            }
        });
        if (typeof filterSeries === "function") filterSeries();
    }

    /**
     * Ouvre la modal et charge la file.
     * @param {object} opts - {resetSession: bool, waiting: bool}
     */
    window.openManualReviewModal = function (opts) {
        opts = opts || {};
        if (opening) return;
        opening = true;
        applyWorkshopQueueScope();
        syncOptionsFromSidebar();
        showModalShell();
        if (!opts.waiting) playTone("pick");

        loadQueue().then(function () {
            if (opts.resetSession !== false) {
                currentIndex = 0;
                currentReviewId = null;
                selectedProvider = null;
                includeProviders = [];
                resetFieldPicks();
                manualCompletion = false;
                mergeFields = false;
                syncManualCompletionControls();
                baselinePreview = null;
                reanchorIndex();
                if (opts.resetSession) {
                    session = emptySession();
                    try {
                        if (window.SupporterNag && typeof window.SupporterNag.resetMrSession === "function") {
                            window.SupporterNag.resetMrSession();
                        }
                    } catch (e) { /* noop */ }
                }
            }
            if (opts.waiting && !queue.length) {
                setPhase("waiting");
                return;
            }
            if (!queue.length) {
                setPhase("recap");
                showRecapIfEmpty();
                return;
            }
            showCurrentReview();
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            opening = false;
        });
    };

    /** Ouvre la modal en mode attente au lancement d’un batch / sync (MR ou confirm-before-write). */
    window.mrPrepareForBatch = function () {
        if (!isReviewQueueModeOn()) return;
        applyWorkshopQueueScope();
        if (waitingSettleTimer) {
            clearTimeout(waitingSettleTimer);
            waitingSettleTimer = null;
        }
        if (isModalOpen() && (phase === "pick" || phase === "edit" || phase === "cover" || phase === "waiting")) {
            if (phase !== "waiting" && !queue.length) setPhase("waiting");
            return;
        }
        window.openManualReviewModal({ waiting: true, resetSession: true });
    };

    /**
     * Fin de batch / sync : quitte l’écran d’attente si aucune review n’est arrivée
     * (ex. séries déjà COMPLETED sans Force Update → skip « Déjà à jour »).
     */
    function settleWaitingAfterWork(opts) {
        opts = opts || {};
        if (!isModalOpen() || phase !== "waiting" || researchInFlight) return;
        if (waitingSettleTimer) clearTimeout(waitingSettleTimer);
        var delay = opts.immediate ? 0 : 450;
        waitingSettleTimer = setTimeout(function () {
            waitingSettleTimer = null;
            if (!isModalOpen() || phase !== "waiting" || researchInFlight) return;
            loadQueue().then(function () {
                if (!isModalOpen() || phase !== "waiting") return;
                if (queue.length) {
                    currentIndex = 0;
                    selectedProvider = null;
                    includeProviders = [];
                    showCurrentReview();
                    playTone("pick");
                    return;
                }
                session.batch_no_reviews = true;
                showRecapIfEmpty();
            }).catch(function () {
                if (phase === "waiting" && !queue.length) {
                    session.batch_no_reviews = true;
                    showRecapIfEmpty();
                }
            });
        }, delay);
    }

    window.mrOnBatchProgress = function (payload) {
        if (!payload || !isReviewQueueModeOn()) return;
        if (payload.stopped) {
            settleWaitingAfterWork({ immediate: true });
            return;
        }
        var rem = parseInt(payload.remaining, 10);
        if (isNaN(rem)) return;
        var hasActive = !!payload.active;
        if (rem === 0 && !hasActive) {
            settleWaitingAfterWork();
        }
    };

    /** Sync unitaire terminé (force-sync) : même garde-fou si rien n’a été mis en file. */
    window.mrOnSyncSettled = function () {
        if (!isReviewQueueModeOn()) return;
        settleWaitingAfterWork();
    };

    window.mrReviewLater = function () {
        window.closeManualReviewModal();
    };

    window.closeManualReviewModal = function () {
        var workshopShot = workshopForceReviewShot();
        window.WORKSHOP_FORCE_REVIEW = null;
        if (workshopShot) {
            companionOnlySeriesId = null;
            companionOnlyReviewId = "";
        }
        var modal = document.getElementById("manualReviewModal");
        if (modal) {
            modal.style.display = "none";
            modal.setAttribute("aria-hidden", "true");
        }
        if (listViewOpen) closeListView();
        resetFieldPicks();
        manualCompletion = false;
        mergeFields = false;
        syncManualCompletionControls();
        includeProviders = [];
        selectedProvider = null;
        actionInFlight = false;
        coverPicked = false;
        setActionBusy(false);
        if (previouslyFocused && typeof previouslyFocused.focus === "function") {
            try { previouslyFocused.focus(); } catch (e) { /* ignore */ }
        }
        previouslyFocused = null;
        // C33 Companion embed : fermeture sans confirm/skip → cancel
        companionNotifyDone("cancel");
    };

    // Resolve the real postMessage parent of the embed. When the overlay injects
    // the MR iframe straight into the Kavita page (http-in-http), the parent is
    // the Kavita page (topOrigin). Legacy nested mode uses the extension origin.
    // Mixed-content tab mode: top-level MetaKavita tab opened via window.open —
    // notify opener (Kavita) then close this tab.
    function companionParentTarget() {
        var cfg = window.COMPANION_EMBED;
        if (!cfg) return "";
        var target = cfg.topOrigin || cfg.parentOrigin;
        if (!target || typeof target !== "string") return "";
        if (
            target.indexOf("chrome-extension://") === 0 ||
            target.indexOf("moz-extension://") === 0 ||
            target.indexOf("http://") === 0 ||
            target.indexOf("https://") === 0
        ) {
            return target;
        }
        return "";
    }

    function companionIsStandaloneTab() {
        try {
            return !!(window.COMPANION_EMBED && window.top === window);
        } catch (e) {
            return !!window.COMPANION_EMBED;
        }
    }

    function companionCloseStandaloneTab() {
        if (!companionIsStandaloneTab()) return;
        try {
            if (window.opener && !window.opener.closed) {
                window.opener.focus();
            }
        } catch (e) { /* cross-origin / closed */ }
        // Defer close so focus can return to the Kavita tab first.
        setTimeout(function () {
            try {
                window.close();
            } catch (e2) { /* browser may ignore if not script-opened */ }
        }, 80);
    }

    var companionDoneSent = false;
    function companionNotifyDone(outcome) {
        var cfg = window.COMPANION_EMBED;
        if (!cfg || companionDoneSent) return;
        companionDoneSent = true;
        var payload = {
            source: "metakavita-companion",
            type: "mk:mr-done",
            seriesId: cfg.seriesId,
            outcome: outcome || "cancel"
        };
        var target = companionParentTarget();
        try {
            // In-page iframe → Kavita (or extension) parent.
            if (window.parent && window.parent !== window && target) {
                window.parent.postMessage(payload, target);
            }
        } catch (e) { /* ignore */ }
        try {
            // Mixed-content tab → notify the Kavita opener for cache-bust, then close.
            if (companionIsStandaloneTab() && window.opener && !window.opener.closed && target) {
                window.opener.postMessage(payload, target);
            }
        } catch (e2) { /* ignore */ }
        companionCloseStandaloneTab();
    }

    window.mrSubmitPick = function () {
        var review = currentReview();
        if (!review || !selectedProvider || actionInFlight) return;
        syncOptionsFromSidebar();
        var extras = pickRequestExtras();
        var fusionList = extras.include_providers || [];
        var body = {
            base_provider: selectedProvider,
            include_providers: fusionList,
            prefer_edit: !!(editEnabled || coverPickEnabled),
            fused: extras.fused,
            weak_pick: isSelectedWeak(review, selectedProvider),
            super_review: isSuperReviewOn()
        };
        body.manual_completion = !!extras.manual_completion;
        if (extras.manual_completion) {
            body.merge_fields = !!extras.merge_fields;
            body.field_picks = extras.field_picks || {};
        }
        if (isWorkshopPage()) body.workshop = true;
        setActionBusy(true);
        api("/api/manual-reviews/" + review.review_id + "/choice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        }).then(function (data) {
            playTone("pick");
            if (data.mode === "preview") {
                baselinePreview = data.preview || {};
                coverPicked = false;
                providerCoverUrl = baselinePreview.cover_url || "";
                // Keep local queue in sync so list-jump / reopen restores Sources.
                review.state = "awaiting_confirm";
                review.preview = baselinePreview;
                review.base_provider = data.base_provider || selectedProvider;
                includeProviders = (data.include_providers || fusionList || [])
                    .filter(function (p) { return p && p !== selectedProvider; });
                restorePicksFromPreview(data.preview || baselinePreview);
                if (coverPickEnabled) {
                    enterCoverPhase(baselinePreview);
                    return;
                }
                renderEdit(baselinePreview);
                setPhase("edit");
                return;
            }
            if (data.detail && data.detail.workshop) {
                if (typeof window.workshopApplyReview === "function") {
                    window.workshopApplyReview(data.detail);
                }
                coverPicked = false;
                removeFromQueue(review.review_id);
                window.closeManualReviewModal();
                return;
            }
            recordSessionConfirm(review, data.detail, 0, fusionList.length);
            var nextStatus = (data.detail && data.detail.status) || (data.message === "NEEDS_RELOCK" ? "NEEDS_RELOCK" : "COMPLETED");
            markSeriesStatus(review.series_id, nextStatus);
            companionNotifyDone("confirm");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            setActionBusy(false);
        });
    };

    window.mrConfirmCurrent = function () {
        var review = currentReview();
        if (!review || !selectedProvider || actionInFlight) return;
        var packed;
        if (phase === "cover") {
            packed = { edited: {}, field_edits: 0 };
            if (coverPicked && baselinePreview && baselinePreview.cover_url) {
                packed.edited.cover_url = baselinePreview.cover_url;
                packed.field_edits = 1;
            }
        } else {
            packed = collectEdits();
            if (coverPicked && baselinePreview && baselinePreview.cover_url) {
                if (!packed.edited) packed.edited = {};
                if (packed.edited.cover_url == null) {
                    packed.edited.cover_url = baselinePreview.cover_url;
                }
            }
        }
        var extras = pickRequestExtras();
        var fusionList = extras.include_providers || [];
        var sendFields = (phase === "edit") ? collectSendFields() : null;
        var coverWanted = !sendFields || sendFields.indexOf("cover") >= 0;
        if (!coverWanted) {
            if (packed.edited) delete packed.edited.cover_url;
        }
        var confirmBody = {
            base_provider: selectedProvider,
            include_providers: fusionList,
            edited_fields: packed.edited,
            field_edits: packed.field_edits,
            fused: extras.fused,
            weak_pick: isSelectedWeak(review, selectedProvider),
            super_review: isSuperReviewOn(),
            cover_picked: !!(coverPicked && coverWanted)
        };
        if (sendFields !== null) confirmBody.send_fields = sendFields;
        confirmBody.manual_completion = !!extras.manual_completion;
        if (extras.manual_completion) {
            confirmBody.merge_fields = !!extras.merge_fields;
            confirmBody.field_picks = extras.field_picks || {};
        }
        if (isWorkshopPage()) confirmBody.workshop = true;
        setActionBusy(true);
        api("/api/manual-reviews/" + review.review_id + "/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(confirmBody)
        }).then(function (data) {
            playTone("confirm");
            if (data.detail && data.detail.workshop) {
                if (typeof window.workshopApplyReview === "function") {
                    window.workshopApplyReview(data.detail);
                }
                coverPicked = false;
                removeFromQueue(review.review_id);
                window.closeManualReviewModal();
                return;
            }
            recordSessionConfirm(review, data.detail, packed.field_edits, fusionList.length);
            var nextStatus = (data.detail && data.detail.status) || (data.message === "NEEDS_RELOCK" ? "NEEDS_RELOCK" : "COMPLETED");
            markSeriesStatus(review.series_id, nextStatus);
            coverPicked = false;
            companionNotifyDone("confirm");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            setActionBusy(false);
        });
    };

    window.mrSkipCurrent = function () {
        var review = currentReview();
        if (!review || actionInFlight) return;
        setActionBusy(true);
        api("/api/manual-reviews/" + review.review_id + "/skip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        }).then(function () {
            playTone("skip");
            session.skipped += 1;
            markSeriesStatus(review.series_id, "PENDING");
            companionNotifyDone("skip");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            setActionBusy(false);
        });
    };

    window.mrResearchCurrent = function () {
        var review = currentReview();
        if (!review || researchInFlight) return;
        var input = document.getElementById("mrSeriesQuery");
        var btn = document.getElementById("mrResearchBtn");
        var query = (input && input.value ? input.value : "").trim();
        if (!query) {
            alert(t("mr_research_empty", "Saisis un titre de recherche."));
            if (input) input.focus();
            return;
        }
        var prevLabel = btn ? btn.textContent : "";
        researchInFlight = true;
        setPhase("waiting");

        api("/api/manual-reviews/" + review.review_id + "/research", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query })
        }).then(function (data) {
            var updated = data.review;
            if (!updated || !updated.review_id) {
                throw new Error(data.error || t("mr_research_fail", "Aucun candidat pour cette recherche."));
            }
            var idx = -1;
            for (var i = 0; i < queue.length; i++) {
                if (queue[i].review_id === updated.review_id) { idx = i; break; }
            }
            if (idx >= 0) {
                queue[idx] = Object.assign({}, queue[idx], updated);
                currentIndex = idx;
            } else {
                queue.push(updated);
                currentIndex = queue.length - 1;
            }
            selectedProvider = null;
            includeProviders = [];
            resetFieldPicks();
            baselinePreview = null;
            session.researches = (session.researches || 0) + 1;
            researchInFlight = false;
            setPhase("pick");
            renderCandidates();
            playTone("pick");
        }).catch(function (err) {
            researchInFlight = false;
            var review = currentReview();
            if (review && review.review_id) markStreamingComplete(review.review_id);
            setPhase("pick");
            renderCandidates();
            alert(err.message || String(err) || t("mr_research_fail", "Aucun candidat pour cette recherche."));
        }).then(function () {
            researchInFlight = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = prevLabel || t("mr_research", "Rechercher");
            }
            if (input) {
                input.disabled = false;
                if (phase === "pick") input.focus();
            }
        });
    };

    window.mrPurgeQueue = function () {
        var n = queue.length;
        var msg = t(
            "mr_purge_confirm",
            "Purger toute la file de reviews manuelles ? Les séries repasseront en attente (sans écriture Kavita)."
        );
        if (n > 0) msg += "\n(" + n + ")";
        if (!window.confirm(msg)) return;

        localPurgeInFlight = true;
        api("/api/manual-reviews/purge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        }).then(function (data) {
            var ids = data.series_ids || [];
            var deleted = data.deleted != null ? data.deleted : ids.length;
            ids.forEach(function (sid) { markSeriesStatus(sid, "PENDING"); });
            // Conserve les stats déjà faites ; compte seulement le reste purgé.
            session.purged = (session.purged || 0) + Math.max(0, deleted);
            queue = [];
            currentIndex = 0;
            selectedProvider = null;
            includeProviders = [];
            baselinePreview = null;
            updateBadge(0);
            showRecapIfEmpty();
            var doneMsg = t("mr_purge_done", "File purgée : {0} review(s) supprimée(s).");
            alert(doneMsg.replace("{0}", String(deleted)));
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            localPurgeInFlight = false;
        });
    };

    function onKey(e) {
        if (!isModalOpen()) return;
        trapFocus(e);
        if (listViewOpen) {
            if (e.key === "Escape") {
                e.preventDefault();
                closeListView();
            }
            return;
        }
        if (actionInFlight && e.key === "Enter") {
            e.preventDefault();
            return;
        }
        var inField = e.target && (
            e.target.tagName === "INPUT" ||
            e.target.tagName === "TEXTAREA" ||
            e.target.isContentEditable
        );
        if (inField && e.key !== "Escape") {
            // Champ titre review : Entrée = re-recherche (comme override)
            if (e.target && e.target.id === "mrSeriesQuery" && e.key === "Enter") {
                e.preventDefault();
                mrResearchCurrent();
                return;
            }
            // En phase edit : Entrée dans un input confirme ; textarea = newline
            // sauf Ctrl/Cmd+Entrée.
            if (phase === "edit" && e.key === "Enter") {
                if (e.target.tagName === "TEXTAREA" && !(e.ctrlKey || e.metaKey)) return;
                e.preventDefault();
                mrConfirmCurrent();
            }
            return;
        }
        if (e.key === "Escape") {
            e.preventDefault();
            if (phase === "waiting") {
                if (researchInFlight) return;
                mrReviewLater();
                return;
            }
            if (phase === "cover") {
                mrCoverSkip();
                return;
            }
            if (phase === "edit") {
                if (isAutoConfirmReview(currentReview())) {
                    mrSkipCurrent();
                } else if (isCoverPickOn()) {
                    enterCoverPhase(baselinePreview || {});
                } else {
                    setPhase("pick");
                }
                return;
            }
            if (phase === "recap") {
                window.closeManualReviewModal();
                return;
            }
            mrSkipCurrent();
            return;
        }
        // Retour : Backspace (hors champs) — cover/edit→précédent, pick→review précédente
        if (e.key === "Backspace") {
            if (phase === "recap") return;
            if (!canGoBack()) return;
            e.preventDefault();
            mrGoBack();
            return;
        }
        if (phase === "cover" && e.key === "Enter") {
            if (e.target && e.target.id === "mrCoverQuery") {
                e.preventDefault();
                mrSearchCovers();
                return;
            }
            e.preventDefault();
            mrCoverContinue();
            return;
        }
        if (phase === "recap" && e.key === "Enter") {
            e.preventDefault();
            window.closeManualReviewModal();
            return;
        }
        if (phase === "pick" && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            var review = currentReview();
            if (!review) return;
            var above = review.above || [];
            var visible = above.length ? above : (review.below || []);
            if (!visible.length) return;
            var idx = 0;
            for (var i = 0; i < visible.length; i++) {
                if (visible[i].provider === selectedProvider) { idx = i; break; }
            }
            idx = e.key === "ArrowDown"
                ? Math.min(visible.length - 1, idx + 1)
                : Math.max(0, idx - 1);
            selectMaster(visible[idx].provider);
            renderCandidates();
            return;
        }
        if (phase === "pick" && e.key === "Enter") {
            e.preventDefault();
            mrSubmitPick();
            return;
        }
        if (phase === "edit" && e.key === "Enter") {
            // Entrée confirme (sauf dans un textarea, sauf Ctrl/Cmd+Entrée partout)
            if (e.target && e.target.tagName === "TEXTAREA" && !(e.ctrlKey || e.metaKey)) {
                return;
            }
            e.preventDefault();
            mrConfirmCurrent();
            return;
        }
        if (phase === "pick" && e.key === "ArrowRight") {
            e.preventDefault();
            goToNextReview();
            return;
        }
        if (phase === "pick" && e.key === "ArrowLeft") {
            e.preventDefault();
            goToPrevReview();
            return;
        }
        if (phase === "pick" && /^[1-9]$/.test(e.key)) {
            var keyIdx = parseInt(e.key, 10) - 1;
            var rev = currentReview();
            if (!rev) return;
            var visAbove = rev.above || [];
            var visibleList = visAbove.length ? visAbove : (rev.below || []);
            if (visibleList[keyIdx]) {
                selectMaster(visibleList[keyIdx].provider);
                renderCandidates();
            }
        }
    }

    document.addEventListener("keydown", onKey);

    function onQueueUpdated(prevEmpty) {
        // Jamais d’auto-open : l’ouverture se fait au lancement batch (waiting)
        // ou via le bouton Reviews. Ici on rafraîchit seulement si déjà ouverte.
        if (!isModalOpen()) return;
        if (phase === "waiting") {
            if (queue.length) {
                if (waitingSettleTimer) {
                    clearTimeout(waitingSettleTimer);
                    waitingSettleTimer = null;
                }
                if (prevEmpty) {
                    currentIndex = 0;
                    currentReviewId = null;
                    selectedProvider = null;
                    includeProviders = [];
                    reanchorIndex();
                }
                showCurrentReview();
                playTone("pick");
            }
            return;
        }
        // Review arrivée après un récap « rien à faire » (course batch_progress / queued)
        if (phase === "recap" && queue.length) {
            currentIndex = 0;
            currentReviewId = null;
            selectedProvider = null;
            includeProviders = [];
            reanchorIndex();
            showCurrentReview();
            playTone("pick");
            return;
        }
        if (phase === "pick") {
            if (prevEmpty && queue.length) {
                currentIndex = 0;
                currentReviewId = null;
                selectedProvider = null;
                includeProviders = [];
                reanchorIndex();
            }
            if (!queue.length) {
                showRecapIfEmpty();
                return;
            }
            // Une auto-confirm peut arriver en tête → bascule edit
            showCurrentReview();
            return;
        }
        if (phase === "edit") {
            if (!queue.length) {
                baselinePreview = null;
                showRecapIfEmpty();
                return;
            }
            // Review courante disparue → ancre suivante
            if (currentReviewId && !queue.some(function (r) { return r.review_id === currentReviewId; })) {
                baselinePreview = null;
                selectedProvider = null;
                includeProviders = [];
                showCurrentReview();
            }
        }
    }

    // Boot / reconnect: sync badge ; si modal ouverte, rafraîchir l'UI
    function syncQueueBadge() {
        loadQueue().then(function (r) {
            if (r && !r.stale && isModalOpen()) {
                onQueueUpdated(r.prevEmpty);
            }
        }).catch(function () { /* ignore */ });
    }

    if (typeof socket !== "undefined") {
        socket.on("connect", function () {
            syncQueueBadge();
        });
        socket.on("manual_review_pending_count", function (payload) {
            var n = (payload && payload.count) || 0;
            updateBadge(n);
            if (isModalOpen()) {
                loadQueue().then(function (r) {
                    if (r && !r.stale) onQueueUpdated(r.prevEmpty);
                }).catch(function () { /* ignore */ });
            } else if (n === 0) {
                queue = [];
                currentIndex = 0;
                currentReviewId = null;
            }
        });
        socket.on("manual_review_queued", function (payload) {
            if (payload && payload.series_id) {
                markSeriesStatus(payload.series_id, "PENDING_REVIEW");
            }
            // New/restarted stream for this review_id — allow streaming again.
            if (payload && payload.streaming && payload.review_id) {
                delete finalizedStreamIds[String(payload.review_id)];
            }
            loadQueue().then(function (r) {
                if (r && !r.stale) onQueueUpdated(r.prevEmpty);
            }).catch(function (err) {
                console.warn("[manual_review] queue refresh failed", err);
            });
        });
        socket.on("manual_review_candidate", function (payload) {
            mergeStreamedCandidate(payload);
        });
        socket.on("manual_review_scrape_complete", function (payload) {
            if (!payload || !payload.review_id) return;
            markStreamingComplete(payload.review_id);
            if (researchInFlight) return;
            if (isModalOpen() && String(currentReviewId) === String(payload.review_id)) {
                renderCandidates();
            }
            loadQueue().then(function (r) {
                if (r && !r.stale && isModalOpen()) {
                    if (String(currentReviewId) === String(payload.review_id)) {
                        showCurrentReview();
                    } else {
                        onQueueUpdated(r.prevEmpty);
                    }
                }
            }).catch(function () { /* ignore */ });
        });
        socket.on("manual_review_queue_summary", function (payload) {
            updateBadge((payload && payload.count) || 0);
            if (isModalOpen()) {
                loadQueue().then(function (r) {
                    if (r && !r.stale) onQueueUpdated(r.prevEmpty);
                }).catch(function () { /* ignore */ });
            }
        });
        socket.on("manual_review_confirmed", function (payload) {
            if (payload && payload.series_id) {
                markSeriesStatus(payload.series_id, payload.status || "COMPLETED");
            }            if (payload && payload.review_id) {
                if (isModalOpen()) {
                    var wasCurrent = currentReviewId === payload.review_id;
                    removeFromQueue(payload.review_id);
                    if (wasCurrent) {
                        selectedProvider = null;
                        includeProviders = [];
                        baselinePreview = null;
                        if (!showRecapIfEmpty()) {
                            showCurrentReview();
                        }
                    } else if (isModalOpen()) {
                        showCurrentReview();
                    }
                } else {
                    removeFromQueue(payload.review_id);
                }
            }
        });
        socket.on("manual_review_skipped", function (payload) {
            if (payload && payload.series_id) markSeriesStatus(payload.series_id, "PENDING");
            if (payload && payload.review_id) {
                if (isModalOpen()) {
                    var wasCurrentSkip = currentReviewId === payload.review_id;
                    removeFromQueue(payload.review_id);
                    if (wasCurrentSkip) {
                        selectedProvider = null;
                        includeProviders = [];
                        baselinePreview = null;
                        if (!showRecapIfEmpty()) {
                            showCurrentReview();
                        }
                    } else if (isModalOpen()) {
                        showCurrentReview();
                    }
                } else {
                    removeFromQueue(payload.review_id);
                }
            }
        });
        socket.on("manual_review_refreshed", function (payload) {
            if (!payload || !payload.review_id) return;
            loadQueue().then(function (r) {
                if (r && r.stale) return;
                if (isModalOpen() && currentReviewId === payload.review_id) {
                    selectedProvider = null;
                    includeProviders = [];
                    baselinePreview = null;
                    showCurrentReview();
                } else if (isModalOpen()) {
                    onQueueUpdated(r.prevEmpty);
                }
            }).catch(function () { /* ignore */ });
        });
        socket.on("manual_review_purged", function (payload) {
            // Purge déclenchée depuis cette UI : le récap local gère déjà les stats.
            if (localPurgeInFlight || (!queue.length && phase === "recap")) {
                var remoteIds = (payload && payload.series_ids) || [];
                remoteIds.forEach(function (sid) { markSeriesStatus(sid, "PENDING"); });
                updateBadge(0);
                return;
            }
            var ids = (payload && payload.series_ids) || [];
            var deleted = (payload && payload.deleted) != null ? payload.deleted : ids.length;
            ids.forEach(function (sid) { markSeriesStatus(sid, "PENDING"); });
            if (deleted > 0) session.purged = (session.purged || 0) + Math.max(0, deleted);
            queue = [];
            currentIndex = 0;
            currentReviewId = null;
            selectedProvider = null;
            includeProviders = [];
            baselinePreview = null;
            updateBadge(0);
            if (isModalOpen()) {
                showRecapIfEmpty();
            }
        });
        if (socket.connected) {
            syncQueueBadge();
        }
    }

    function onDomReady(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    function startCompanionEmbedBootstrap() {
        var cfg = window.COMPANION_EMBED;
        if (!cfg || cfg.seriesId == null) return;
        var waitEl = document.getElementById("companionWait");
        var targetSid = Number(cfg.seriesId);
        var targetRid = cfg.reviewId ? String(cfg.reviewId) : "";
        // Scope every subsequent loadQueue() to this series only.
        companionOnlySeriesId = targetSid;
        companionOnlyReviewId = targetRid;

        function findMatch() {
            for (var i = 0; i < queue.length; i++) {
                if (Number(queue[i].series_id) !== targetSid) continue;
                if (targetRid && String(queue[i].review_id) !== targetRid) continue;
                return queue[i];
            }
            return null;
        }

        function tryOpen() {
            return loadQueue().then(function () {
                var match = findMatch();
                if (!match) return false;
                if (waitEl) waitEl.style.display = "none";
                window.openManualReviewModal({ resetSession: true });
                window.mrJumpToReview(match.review_id);
                return true;
            });
        }

        tryOpen().then(function (ok) {
            if (ok) return;
            var ticks = 0;
            var timer = setInterval(function () {
                ticks += 1;
                tryOpen().then(function (opened) {
                    if (opened) {
                        clearInterval(timer);
                        return;
                    }
                    if (ticks >= 120) {
                        clearInterval(timer);
                        if (waitEl) {
                            var msg =
                                (window.AppTranslations && window.AppTranslations.companion_wait_timeout) ||
                                "Timed out — open Manual Review in MetaKavita or retry.";
                            var p = waitEl.querySelector("p");
                            if (p) p.textContent = msg;
                            var spin = waitEl.querySelector(".companion-wait-spinner");
                            if (spin) spin.style.display = "none";
                        }
                        try {
                            if (window.parent && window.parent !== window) {
                                var target = companionParentTarget();
                                if (target) {
                                    window.parent.postMessage({
                                        source: "metakavita-companion",
                                        type: "mk:mr-timeout",
                                        seriesId: targetSid
                                    }, target);
                                }
                            }
                        } catch (e) { /* ignore */ }
                    }
                }).catch(function () {
                    if (ticks >= 120) clearInterval(timer);
                });
            }, 2000);
        }).catch(function () { /* ignore */ });

        if (typeof socket !== "undefined") {
            socket.on("manual_review_queued", function (payload) {
                if (payload && Number(payload.series_id) === targetSid) {
                    tryOpen();
                }
            });
            socket.on("manual_review_candidate", function (payload) {
                if (!payload || Number(payload.series_id) !== targetSid) return;
                mergeStreamedCandidate(payload);
                if (waitEl && waitEl.style.display !== "none") {
                    tryOpen();
                }
            });
            socket.on("manual_review_scrape_complete", function (payload) {
                if (!payload || Number(payload.series_id) !== targetSid) return;
                markStreamingComplete(payload.review_id);
                if (isModalOpen() && String(currentReviewId) === String(payload.review_id)) {
                    renderCandidates();
                }
                loadQueue().then(function () {
                    var match = findMatch();
                    if (!match) return;
                    if (waitEl) waitEl.style.display = "none";
                    if (!isModalOpen()) {
                        window.openManualReviewModal({ resetSession: true });
                    }
                    window.mrJumpToReview(match.review_id);
                }).catch(function () { /* ignore */ });
            });
        }
    }

    function wireShowBelowCheckbox() {
        var cb = document.getElementById("mrShowBelow");
        if (!cb || cb.__mkShowBelowWired) return;
        cb.__mkShowBelowWired = true;
        syncShowBelowCheckbox();
        cb.addEventListener("change", function () {
            showBelowThreshold = !!cb.checked;
            saveShowBelowPref(showBelowThreshold);
            if (isModalOpen()) renderCandidates();
        });
    }

    function wireManualCompletionControls() {
        var manualCb = document.getElementById("mrManualCompletion");
        var mergeCb = document.getElementById("mrMergeFields");
        if (manualCb && !manualCb.__mkManualWired) {
            manualCb.__mkManualWired = true;
            manualCb.addEventListener("change", function () {
                manualCompletion = !!manualCb.checked;
                if (!manualCompletion) {
                    mergeFields = false;
                    resetFieldPicks();
                } else {
                    resetFieldPicks();
                    includeProviders = [];
                }
                syncManualCompletionControls();
                if (isModalOpen()) renderCandidates();
            });
        }
        if (mergeCb && !mergeCb.__mkMergeWired) {
            mergeCb.__mkMergeWired = true;
            mergeCb.addEventListener("change", function () {
                if (!manualCompletion) {
                    mergeCb.checked = false;
                    return;
                }
                mergeFields = !!mergeCb.checked;
                if (!mergeFields && fieldPicks) {
                    Object.keys(fieldPicks).forEach(function (field) {
                        if (LIST_FIELD_PICKS[field] && fieldPicks[field] && fieldPicks[field].length > 1) {
                            fieldPicks[field] = fieldPicks[field].indexOf(selectedProvider) >= 0
                                ? [selectedProvider]
                                : fieldPicks[field].slice(0, 1);
                        }
                    });
                }
                if (isModalOpen()) renderCandidates({ keepScroll: true });
            });
        }
        syncManualCompletionControls();
    }

    onDomReady(function () {
        wireShowBelowCheckbox();
        wireManualCompletionControls();
        syncQueueBadge();
        startCompanionEmbedBootstrap();
    });

    // Compat sidebar : ouverture explicite uniquement
    window.mrTryOpenPending = function () {
        loadQueue().then(function () {
            if (queue.length > 0) {
                window.openManualReviewModal({ resetSession: true });
            }
        }).catch(function () { /* ignore */ });
    };
})();
