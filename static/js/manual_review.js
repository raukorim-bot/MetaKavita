// --- MANUAL REVIEW QUEUE (C29) ---
// Dépend de utils.js (getRootPath, CSRF) et websocket.js (`socket`).

(function () {
    var queue = [];
    var currentIndex = 0;
    var selectedProvider = null;
    var includeProviders = [];
    var baselinePreview = null;
    var phase = "pick"; // pick | edit | recap
    var session = emptySession();
    var editEnabled = true;
    var soundsEnabled = false;
    var opening = false;
    var localPurgeInFlight = false;
    var researchInFlight = false;
    var waitingSettleTimer = null;

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

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
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

    function renderMetaChips(c) {
        var chips = [];
        function push(label, value, isList, onlyIfMissing) {
            var present = fieldHasValue(value);
            if (onlyIfMissing && present) return;
            var display = present
                ? (isList ? joinList(value, 8) : String(value))
                : "—";
            chips.push(
                '<span class="mr-chip' + (present ? "" : " mr-chip-missing") + '"' +
                (present ? "" : ' title="' + escapeHtml(t("mr_field_missing", "Champ manquant")) + '"') +
                '><span class="mr-chip-label">' +
                escapeHtml(label) +
                "</span> " +
                escapeHtml(display) +
                "</span>"
            );
        }
        // Cover déjà visible à gauche : chip rouge seulement si absente
        push(t("mr_meta_cover", "Cover"), c.cover_url, false, true);
        push(t("mr_meta_year", "Year"), c.year, false, false);
        push(t("mr_meta_status", "Status"), c.status, false, false);
        push(t("mr_meta_format", "Format"), c.format, false, false);
        push(t("mr_meta_publisher", "Publisher"), c.publisher, false, false);
        push(t("mr_meta_age", "Age"), c.age_rating, false, false);
        push(t("mr_meta_localized", "Localized"), c.localized_name, false, false);
        push(t("mr_meta_genres", "Genres"), c.genres, true, false);
        push(t("mr_meta_tags", "Tags"), c.tags, true, false);
        push(t("mr_meta_staff", "Staff"), c.staff, true, false);
        return '<div class="mr-meta">' + chips.join("") + "</div>";
    }

    function renderSummary(c) {
        var summary = (c.summary || c.summary_excerpt || "").trim();
        if (!summary) {
            return '<div class="mr-summary mr-summary-empty">' +
                escapeHtml(t("mr_no_summary", "No summary available")) +
                "</div>";
        }
        return '<div class="mr-summary">' + escapeHtml(summary) + "</div>";
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
        var sources = includeProviders.filter(function (p) { return p && p !== selectedProvider; });
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

    function syncOptionsFromSidebar() {
        var editCb = document.getElementById("sidebar_manual_review_edit");
        editEnabled = editCb ? !!editCb.checked : true;
        var soundCb = document.getElementById("sidebar_manual_review_sounds");
        soundsEnabled = soundCb ? !!soundCb.checked : false;
    }

    function isManualModeOn() {
        var cb = document.getElementById("sidebar_manual_review_mode");
        return cb ? !!cb.checked : false;
    }

    function isSuperReviewOn() {
        var cb = document.getElementById("sidebar_manual_review_super");
        return cb ? !!cb.checked : false;
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
        if (!modal) return false;
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
    }

    function currentReview() {
        return queue[currentIndex] || null;
    }

    function loadQueue() {
        return api("/api/manual-reviews").then(function (data) {
            var prevEmpty = queue.length === 0;
            queue = data.reviews || [];
            updateBadge(data.count != null ? data.count : queue.length);
            if (currentIndex >= queue.length) currentIndex = Math.max(0, queue.length - 1);
            return { data: data, prevEmpty: prevEmpty };
        });
    }

    function showModalShell() {
        var modal = document.getElementById("manualReviewModal");
        if (modal) modal.style.display = "flex";
    }

    function renderCandidates() {
        var review = currentReview();
        var aboveEl = document.getElementById("mrAboveList");
        var belowEl = document.getElementById("mrBelowList");
        var nameEl = document.getElementById("mrSeriesQuery");
        var posEl = document.getElementById("mrQueuePos");
        var aboveLabel = document.getElementById("mrAboveLabel");
        var belowLabel = document.getElementById("mrBelowLabel");
        var emptyEl = document.getElementById("mrNoCandidates");
        if (!aboveEl || !belowEl) return;

        aboveEl.innerHTML = "";
        belowEl.innerHTML = "";
        if (!review) {
            if (nameEl && document.activeElement !== nameEl) nameEl.value = "";
            if (aboveLabel) aboveLabel.style.display = "none";
            if (belowLabel) belowLabel.style.display = "none";
            if (emptyEl) emptyEl.style.display = "";
            renderFusionBar();
            return;
        }
        if (nameEl && document.activeElement !== nameEl) {
            nameEl.value = review.query || review.series_name || ("#" + review.series_id);
        }
        if (posEl) posEl.textContent = (currentIndex + 1) + " / " + queue.length;

        var all = [];
        var above = review.above || [];
        var below = review.below || [];
        // Plan: show below-threshold only when above is empty
        above.forEach(function (c) { all.push({ card: c, weak: false }); });
        if (!above.length) {
            below.forEach(function (c) { all.push({ card: c, weak: true }); });
        }

        if (aboveLabel) aboveLabel.style.display = above.length ? "" : "none";
        if (belowLabel) {
            belowLabel.style.display = (!above.length && below.length) ? "" : "none";
        }
        if (emptyEl) emptyEl.style.display = all.length ? "none" : "";

        if (!selectedProvider && all.length) {
            selectedProvider = all[0].card.provider;
        }

        var showMerge = all.length > 1;

        all.forEach(function (entry, idx) {
            var c = entry.card;
            var el = document.createElement("button");
            el.type = "button";
            el.className = "mr-candidate" + (entry.weak ? " mr-weak" : "") +
                (c.provider === selectedProvider ? " is-selected" : "");
            el.dataset.provider = c.provider;
            el.dataset.index = String(idx + 1);

            var cover = c.cover_url
                ? '<img class="mr-cover" src="' + escapeHtml(c.cover_url) + '" alt="" loading="lazy">'
                : '<div class="mr-cover mr-cover-empty"></div>';
            var score = (typeof c.score === "number") ? c.score.toFixed(2) : "—";
            var included = includeProviders.indexOf(c.provider) >= 0;
            var isMaster = c.provider === selectedProvider;
            var hotkey = idx < 9
                ? '<span class="mr-hotkey">' + (idx + 1) + "</span>"
                : "";
            var aside;
            if (!showMerge) {
                aside = '<div class="mr-candidate-aside"></div>';
            } else if (isMaster) {
                aside = '<div class="mr-candidate-aside">' +
                    '<span class="mr-master-badge">' + escapeHtml(t("mr_master", "Master")) + "</span>" +
                    "</div>";
            } else {
                aside = '<div class="mr-candidate-aside">' +
                    '<label class="mr-include" onclick="event.stopPropagation()">' +
                    '<input type="checkbox" ' + (included ? "checked" : "") +
                    ' data-include="' + escapeHtml(c.provider) + '"> ' +
                    escapeHtml(t("mr_source", "Source")) +
                    "</label></div>";
            }

            el.innerHTML =
                cover +
                '<div class="mr-candidate-body">' +
                '<div class="mr-candidate-top">' +
                hotkey +
                '<span class="mr-provider">' + escapeHtml(c.provider || "") + "</span>" +
                '<span class="mr-score ' + scoreClass(c.score) + '">' + score + "</span>" +
                "</div>" +
                '<div class="mr-title">' + escapeHtml(c.title || "—") + "</div>" +
                renderMetaChips(c) +
                renderSummary(c) +
                (entry.weak
                    ? '<span class="mr-weak-tag">' + escapeHtml(t("mr_weak", "weak")) + "</span>"
                    : "") +
                "</div>" +
                aside;

            el.addEventListener("click", function () {
                selectedProvider = c.provider;
                includeProviders = includeProviders.filter(function (p) { return p !== selectedProvider; });
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
            (entry.weak ? belowEl : aboveEl).appendChild(el);
        });
        renderFusionBar();
        scrollSelectedCandidateIntoView();
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
        if (phase === "edit") return true;
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
        setPhase("pick");
        renderCandidates();
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
        } else if (next === "edit") {
            groups = [
                kbdGroupHtml([enter], t("mr_kbd_act_confirm", "Confirmer")),
                kbdGroupHtml([esc, "⌫"], t("mr_kbd_act_back", "Retour"))
            ];
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
        var edit = document.getElementById("mrEditPanel");
        var recap = document.getElementById("mrRecapPanel");
        var pickBtn = document.getElementById("mrPickBtn");
        var confirmBtn = document.getElementById("mrConfirmBtn");
        var skipBtn = document.getElementById("mrSkipBtn");
        var waitBtn = document.getElementById("mrWaitBtn");
        var laterBtn = document.getElementById("mrLaterBtn");
        var closeRecapBtn = document.getElementById("mrCloseRecapBtn");
        var statsLink = document.getElementById("mrRecapStatsLink");
        var seriesBlock = document.querySelector(".mr-series-block");
        var fusionBar = document.getElementById("mrFusionBar");
        if (pick) pick.style.display = next === "pick" ? "block" : "none";
        if (wait) wait.style.display = next === "waiting" ? "flex" : "none";
        if (edit) edit.style.display = next === "edit" ? "block" : "none";
        if (recap) recap.style.display = next === "recap" ? "block" : "none";
        if (pickBtn) pickBtn.style.display = next === "pick" ? "" : "none";
        if (confirmBtn) confirmBtn.style.display = next === "edit" ? "" : "none";
        if (skipBtn) skipBtn.style.display = (next === "pick" || next === "edit") ? "" : "none";
        if (waitBtn) waitBtn.style.display = next === "waiting" ? "" : "none";
        if (laterBtn) {
            laterBtn.style.display = (next === "waiting" && !researchInFlight) ? "" : "none";
        }
        if (closeRecapBtn) closeRecapBtn.style.display = next === "recap" ? "" : "none";
        if (statsLink) statsLink.style.display = next === "recap" ? "" : "none";
        if (seriesBlock) seriesBlock.style.display = next === "recap" ? "none" : "";
        updateBackBtn();
        if (next === "waiting") {
            updateWaitPanelCopy();
        }
        renderKbdDock(next);
        var queryInput = document.getElementById("mrSeriesQuery");
        var researchBtn = document.getElementById("mrResearchBtn");
        var canResearch = (next === "pick" || next === "edit");
        if (queryInput) queryInput.disabled = !canResearch;
        if (researchBtn) researchBtn.style.display = canResearch ? "" : "none";
        if (fusionBar && next !== "pick") {
            fusionBar.style.display = "none";
        }
        if (next === "pick") {
            renderFusionBar();
        }
    }

    window.mrGoBack = function () {
        if (phase === "edit") {
            setPhase("pick");
            return;
        }
        if (phase === "pick") {
            goToPrevReview();
        }
    };

    var EDIT_KEYS = [
        "title", "summary", "year", "status", "genres", "tags",
        "publisher", "age_rating", "format", "cover_url", "localized_name",
        "staff", "writers", "pencillers"
    ];
    var EDIT_WIDE = {
        title: true, summary: true, genres: true, tags: true,
        cover_url: true, localized_name: true, staff: true, writers: true, pencillers: true
    };
    var EDIT_TEXTAREA = {
        summary: 5, genres: 2, tags: 2, cover_url: 2,
        localized_name: 2, staff: 2, writers: 2, pencillers: 2
    };

    function renderEdit(preview) {
        baselinePreview = preview || {};
        // Compat : preview serveur expose `staff` ; UI historique writers/pencillers
        if (baselinePreview.staff && !baselinePreview.writers && !baselinePreview.pencillers) {
            baselinePreview.writers = "";
            baselinePreview.pencillers = "";
        }
        renderEditFusionBar(baselinePreview);
        var wrap = document.getElementById("mrEditFields");
        if (!wrap) return;
        wrap.innerHTML = "";
        EDIT_KEYS.forEach(function (key) {
            // Éviter doublon staff + writers/pencillers vides
            if ((key === "writers" || key === "pencillers") && baselinePreview.staff
                && !baselinePreview.writers && !baselinePreview.pencillers) {
                return;
            }
            if (key === "staff" && (baselinePreview.writers || baselinePreview.pencillers)
                && !baselinePreview.staff) {
                return;
            }
            var val = baselinePreview[key];
            if (val == null) val = "";
            if (Array.isArray(val)) val = val.join(", ");
            else if (typeof val === "object") val = JSON.stringify(val);
            var group = document.createElement("div");
            group.className = "mr-edit-field" + (EDIT_WIDE[key] ? " mr-edit-wide" : "");
            var rows = EDIT_TEXTAREA[key];
            var control = rows
                ? '<textarea class="mr-edit-input" data-field="' + key + '" rows="' + rows + '" spellcheck="false"></textarea>'
                : '<input class="mr-edit-input" data-field="' + key + '" type="text" spellcheck="false" autocomplete="off">';
            group.innerHTML =
                '<label class="mr-edit-label" for="mr-field-' + key + '">' + key + "</label>" +
                control;
            wrap.appendChild(group);
            var input = group.querySelector("[data-field]");
            if (input) {
                input.id = "mr-field-" + key;
                input.value = String(val);
            }
        });
    }

    function collectEdits() {
        var edited = {};
        var fieldEdits = 0;
        document.querySelectorAll("#mrEditFields [data-field]").forEach(function (el) {
            var key = el.getAttribute("data-field");
            var raw = el.value;
            var base = baselinePreview ? baselinePreview[key] : "";
            if (Array.isArray(base)) base = base.join(", ");
            else if (base == null) base = "";
            else if (typeof base === "object") base = JSON.stringify(base);
            else base = String(base);
            if (String(raw) !== String(base)) {
                fieldEdits += 1;
                if (key === "genres" || key === "tags" || key === "writers" || key === "pencillers") {
                    edited[key] = raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
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
        setPhase("recap");
        var queryEl = document.getElementById("mrSeriesQuery");
        var posEl = document.getElementById("mrQueuePos");
        if (queryEl) queryEl.value = "";
        if (posEl) posEl.textContent = "";
        renderRecapAchievements();
        renderRecapKpis();
        updateBadge(0);
        return true;
    }

    function advanceAfterRemove(reviewId) {
        queue = queue.filter(function (r) { return r.review_id !== reviewId; });
        if (currentIndex >= queue.length) currentIndex = Math.max(0, queue.length - 1);
        selectedProvider = null;
        includeProviders = [];
        baselinePreview = null;
        updateBadge(queue.length);
        if (showRecapIfEmpty()) return;
        setPhase("pick");
        renderCandidates();
    }

    function markSeriesStatus(seriesId, status) {
        document.querySelectorAll('.series-item input[value="' + seriesId + '"]').forEach(function (inp) {
            var item = inp.closest(".series-item");
            if (!item) return;
            item.setAttribute("data-status", status);
            var badge = item.querySelector(".series-status .badge");
            if (!badge) return;
            if (status === "COMPLETED") {
                badge.className = "badge badge-completed";
                badge.innerText = t("filter_completed", "Completed");
            } else if (status === "PENDING_REVIEW") {
                badge.className = "badge badge-review";
                badge.innerText = t("filter_pending_review", "Review");
            } else if (status === "PENDING") {
                badge.className = "badge badge-pending";
                badge.innerText = t("filter_pending", "Pending");
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
        syncOptionsFromSidebar();
        showModalShell();
        if (!opts.waiting) playTone("pick");

        loadQueue().then(function () {
            if (opts.resetSession !== false) {
                currentIndex = 0;
                selectedProvider = null;
                includeProviders = [];
                baselinePreview = null;
                if (opts.resetSession) {
                    session = emptySession();
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
            setPhase("pick");
            renderCandidates();
        }).catch(function (err) {
            alert(err.message || String(err));
        }).then(function () {
            opening = false;
        });
    };

    /** Ouvre la modal en mode attente au lancement d’un batch / sync (mode manuel). */
    window.mrPrepareForBatch = function () {
        if (!isManualModeOn()) return;
        if (waitingSettleTimer) {
            clearTimeout(waitingSettleTimer);
            waitingSettleTimer = null;
        }
        if (isModalOpen() && (phase === "pick" || phase === "edit" || phase === "waiting")) {
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
                    setPhase("pick");
                    renderCandidates();
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
        if (!payload || !isManualModeOn()) return;
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
        if (!isManualModeOn()) return;
        settleWaitingAfterWork();
    };

    window.mrReviewLater = function () {
        window.closeManualReviewModal();
    };

    window.closeManualReviewModal = function () {
        var modal = document.getElementById("manualReviewModal");
        if (modal) modal.style.display = "none";
        // Si file non vide, le CTA topbar reste bien visible
        updateBadge(queue.length);
    };

    window.mrSubmitPick = function () {
        var review = currentReview();
        if (!review || !selectedProvider) return;
        syncOptionsFromSidebar();
        var fusionList = includeProviders.filter(function (p) { return p && p !== selectedProvider; });
        var body = {
            base_provider: selectedProvider,
            include_providers: fusionList,
            prefer_edit: !!editEnabled,
            fused: fusionList.length > 0,
            weak_pick: isSelectedWeak(review, selectedProvider),
            super_review: isSuperReviewOn()
        };
        api("/api/manual-reviews/" + review.review_id + "/choice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        }).then(function (data) {
            playTone("pick");
            if (data.mode === "preview") {
                renderEdit(data.preview || {});
                setPhase("edit");
                return;
            }
            recordSessionConfirm(review, data.detail, 0, fusionList.length);
            markSeriesStatus(review.series_id, "COMPLETED");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
        });
    };

    window.mrConfirmCurrent = function () {
        var review = currentReview();
        if (!review || !selectedProvider) return;
        var packed = collectEdits();
        var fusionList = includeProviders.filter(function (p) { return p && p !== selectedProvider; });
        api("/api/manual-reviews/" + review.review_id + "/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                base_provider: selectedProvider,
                include_providers: fusionList,
                edited_fields: packed.edited,
                field_edits: packed.field_edits,
                fused: fusionList.length > 0,
                weak_pick: isSelectedWeak(review, selectedProvider),
                super_review: isSuperReviewOn()
            })
        }).then(function (data) {
            playTone("confirm");
            recordSessionConfirm(review, data.detail, packed.field_edits, fusionList.length);
            markSeriesStatus(review.series_id, "COMPLETED");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
        });
    };

    window.mrSkipCurrent = function () {
        var review = currentReview();
        if (!review) return;
        api("/api/manual-reviews/" + review.review_id + "/skip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        }).then(function () {
            playTone("skip");
            session.skipped += 1;
            markSeriesStatus(review.series_id, "PENDING");
            advanceAfterRemove(review.review_id);
        }).catch(function (err) {
            alert(err.message || String(err));
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
            baselinePreview = null;
            session.researches = (session.researches || 0) + 1;
            researchInFlight = false;
            setPhase("pick");
            renderCandidates();
            playTone("pick");
        }).catch(function (err) {
            researchInFlight = false;
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
            if (phase === "edit") {
                setPhase("pick");
                return;
            }
            if (phase === "recap") {
                window.closeManualReviewModal();
                return;
            }
            mrSkipCurrent();
            return;
        }
        // Retour : Backspace (hors champs) — edit→pick, pick→review précédente
        if (e.key === "Backspace") {
            if (phase === "recap") return;
            if (!canGoBack()) return;
            e.preventDefault();
            mrGoBack();
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
            selectedProvider = visible[idx].provider;
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
            if (currentIndex < queue.length - 1) {
                currentIndex += 1;
                selectedProvider = null;
                includeProviders = [];
                setPhase("pick");
                renderCandidates();
            }
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
                selectedProvider = visibleList[keyIdx].provider;
                includeProviders = includeProviders.filter(function (p) {
                    return p !== selectedProvider;
                });
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
                    selectedProvider = null;
                    includeProviders = [];
                }
                setPhase("pick");
                renderCandidates();
                playTone("pick");
            }
            return;
        }
        // Review arrivée après un récap « rien à faire » (course batch_progress / queued)
        if (phase === "recap" && queue.length) {
            currentIndex = 0;
            selectedProvider = null;
            includeProviders = [];
            setPhase("pick");
            renderCandidates();
            playTone("pick");
            return;
        }
        if (phase === "pick") {
            if (prevEmpty && queue.length) {
                currentIndex = 0;
                selectedProvider = null;
                includeProviders = [];
            }
            renderCandidates();
        }
    }

    // Boot / reconnect: sync badge only (pas d’auto-open)
    function syncQueueBadge() {
        loadQueue().catch(function () { /* ignore */ });
    }

    if (typeof socket !== "undefined") {
        socket.on("connect", function () {
            syncQueueBadge();
        });
        socket.on("manual_review_pending_count", function (payload) {
            var n = (payload && payload.count) || 0;
            updateBadge(n);
            if (isModalOpen() && n > 0) {
                loadQueue().then(function (r) {
                    onQueueUpdated(r.prevEmpty);
                }).catch(function () { /* ignore */ });
            }
        });
        socket.on("manual_review_queued", function (payload) {
            if (payload && payload.series_id) {
                markSeriesStatus(payload.series_id, "PENDING_REVIEW");
            }
            loadQueue().then(function (r) {
                onQueueUpdated(r.prevEmpty);
            }).catch(function (err) {
                console.warn("[manual_review] queue refresh failed", err);
            });
        });
        socket.on("manual_review_queue_summary", function (payload) {
            updateBadge((payload && payload.count) || 0);
        });
        socket.on("manual_review_confirmed", function (payload) {
            if (payload && payload.series_id) markSeriesStatus(payload.series_id, "COMPLETED");
        });
        socket.on("manual_review_skipped", function (payload) {
            if (payload && payload.series_id) markSeriesStatus(payload.series_id, "PENDING");
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

    onDomReady(function () {
        syncQueueBadge();
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
