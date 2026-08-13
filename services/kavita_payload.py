"""
Construction et écriture du payload Kavita à partir des données scrapers.

Extrait du mapping+write de `enrichment_engine` pour servir à la fois le chemin
auto et le mode manuel (preview / confirm).
"""

from __future__ import annotations

import copy
import logging
import re

from config_manager import get_max_tags, get_max_genres
from db_manager import (
    get_all_cached_data,
    get_lifetime_stats,
    update_status,
    record_enrichment_telemetry,
    set_cover_manual,
)
from translator import translate_text
from scrapers.utils import MATCH_SCORE_KEY
from kavita_api import lock_keys_from_payload
from kavita_constants import PUBLICATION_STATUS_MAP, AGE_RATING_MAP
from translations import get_ui_translations


# Rôles de staff. Les fournisseurs écrivent des rôles composés — « Story & Art »
# est le cas le plus courant d'un manga, AniList émet aussi « Cover Illustration »,
# « Art (Ch. 1-45) », « Story, Art »... Une chaîne de `elif` sur des sous-chaînes ne
# peut pas les traiter : le premier test gagne, donc « Story & Art » n'alimentait que
# les scénaristes (la moitié des mangas arrivaient sans dessinateur) et
# « Cover Illustration » passait pour du dessin intérieur. Le rôle est donc découpé,
# et chaque partie classée du plus spécifique au plus générique — `cover` avant
# `art`, `color` avant `art`, sinon « Cover Art » retomberait dans le dessin.
_ROLE_SEPARATORS = re.compile(r"[&,;/+]|\band\b|\bet\b")

_ROLE_RULES = (
    ("cover_artists", ("cover", "couverture")),
    ("colorists", ("color", "colour", "couleur")),
    ("translators", ("translat", "traduct")),
    ("letterers", ("letter", "lettrage")),
    ("inkers", ("ink", "encrage")),
    ("editors", ("edit", "éditeur", "editeur")),
    ("writers", ("story", "original", "scénar", "scenar", "script")),
    ("pencillers", ("art", "illustration", "dessin", "pencill")),
)


def staff_role_buckets(role) -> set:
    """Métiers Kavita auxquels un rôle de fournisseur contribue.

    Un rôle peut en alimenter plusieurs (« Story & Art ») ou aucun
    (« Assistant » : mieux vaut ne rien affirmer que de l'inventer dessinateur).
    """
    buckets = set()
    for part in _ROLE_SEPARATORS.split(str(role or "").lower()):
        if not part.strip():
            continue
        for bucket, needles in _ROLE_RULES:
            if any(needle in part for needle in needles):
                buckets.add(bucket)
                break
    return buckets


def mark_cover_manual(series_id):
    """
    Marque la couverture d'une série comme choisie à la main.

    Parité dashboard ``/update-cover`` et Manual Review ``force_cover_upload`` :
    sans ce marqueur, un futur sync avec AUTO_COVER réuploaderait la couverture
    du provider par-dessus le choix de l'utilisateur.

    Le verrou Kavita ne peut pas jouer ce rôle : MetaKavita pose ``lockCover``
    sur tous ses uploads (sinon le scan Kavita régénère la vignette depuis les
    fichiers), il ne distingue donc pas un choix manuel d'un upload automatique.
    """
    set_cover_manual(series_id, True)
    return True


def release_cover_manual(series_id):
    """Rend la couverture à la gestion automatique (couverture réécrasable)."""
    set_cover_manual(series_id, False)
    return True


def _dedupe_titles(values):
    """Order-preserving dedupe of tag/genre titles (strip + casefold key)."""
    seen, out = set(), []
    for v in values or []:
        key = (v or "").strip().casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _broadcast_enrichment_stats(deltas):
    """Pousse les compteurs lifetime vers le dashboard (Socket.IO)."""
    try:
        from extensions import socketio
        payload = {
            "series_enriched_delta": int((deltas or {}).get("series_enriched_delta", 0)),
            "matches_won_delta": int((deltas or {}).get("matches_won_delta", 0)),
            "series_missed_delta": int((deltas or {}).get("series_missed_delta", 0)),
            "lifetime": get_lifetime_stats(),
        }
        # Pass-through des clés manuelles / extras (mode review)
        for key, val in (deltas or {}).items():
            if key not in payload and key != "lifetime":
                payload[key] = val
        socketio.emit("enrichment_stats", payload)
    except Exception as exc:
        logging.debug("enrichment_stats emit skipped: %s", exc)


def _preview_list(values, limit=40):
    """UI comma-list for genres/tags — same order-preserving dedupe as Kavita write (BF66)."""
    if not values:
        return ""
    if isinstance(values, str):
        parts = [p.strip() for p in values.replace(";", ",").split(",") if p.strip()]
        return ", ".join(_dedupe_titles(parts)[:limit])
    out = []
    for v in values:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):
            title = v.get("title") or v.get("name") or ""
            if title:
                out.append(str(title).strip())
    return ", ".join(_dedupe_titles(out)[:limit])


def _staff_preview(staff):
    names = []
    for edge in staff or []:
        if not isinstance(edge, dict):
            continue
        name = edge.get("node", {}).get("name", {}).get("full", "")
        role = edge.get("role", "")
        if name:
            names.append(f"{name} ({role})" if role else name)
        if len(names) >= 12:
            break
    return ", ".join(names)


def build_preview_fields(provider_data: dict, localized_name=None) -> dict:
    """Dict plat UI-friendly pour le panneau d'édition manuel."""
    pd = provider_data or {}
    return {
        "title": pd.get("title") or "",
        "summary": pd.get("summary") or "",
        "year": pd.get("year") or "",
        "status": pd.get("status") or "",
        "genres": _preview_list(pd.get("genres")),
        "tags": _preview_list(pd.get("tags")),
        "publisher": pd.get("publisher") or "",
        "age_rating": pd.get("age_rating") or "",
        "format": pd.get("format") or "",
        "cover_url": pd.get("cover_url") or "",
        "localized_name": localized_name or "",
        "anilist_id": pd.get("anilist_id") or "",
        "mal_id": pd.get("mal_id") or "",
        "mangabaka_id": pd.get("mangabaka_id") or "",
        "staff": _staff_preview(pd.get("staff")),
        "url": pd.get("url") or "",
    }


def overlay_edited_preview(provider_data: dict, edited_preview) -> dict:
    """Applique un dict plat d'éditions UI sur une copie de provider_data."""
    data = copy.deepcopy(provider_data) if provider_data else {}
    if not edited_preview or not isinstance(edited_preview, dict):
        return data

    def _split_csv(raw):
        if raw is None:
            return None
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        text = str(raw).strip()
        if not text:
            return []
        return [p.strip() for p in text.split(",") if p.strip()]

    mapping_simple = (
        "title", "summary", "status", "publisher", "age_rating", "format",
        "cover_url", "url",
    )
    for key in mapping_simple:
        if key in edited_preview:
            data[key] = edited_preview[key]

    if "year" in edited_preview:
        raw_year = edited_preview["year"]
        if raw_year in (None, ""):
            data["year"] = None
        else:
            try:
                data["year"] = int(raw_year)
            except (TypeError, ValueError):
                # BF61: ne pas garder une string — Kavita attend un int YYYY.
                data["year"] = None

    if "genres" in edited_preview:
        data["genres"] = _split_csv(edited_preview["genres"])
    if "tags" in edited_preview:
        data["tags"] = _split_csv(edited_preview["tags"])

    # UI peut envoyer writers/pencillers (CSV ou listes) → staff edges
    def _names_to_staff(names, role):
        out = []
        for name in (_split_csv(names) or []):
            out.append({"role": role, "node": {"name": {"full": name}}})
        return out

    staff_edges = list(data.get("staff") or []) if isinstance(data.get("staff"), list) else []
    if "staff" in edited_preview and isinstance(edited_preview["staff"], str):
        # CSV "Name (Story), Name (Art)"
        staff_edges = []
        for part in _split_csv(edited_preview["staff"]) or []:
            role = "Story"
            name = part
            if "(" in part and part.endswith(")"):
                name, _, role_part = part.rpartition("(")
                name = name.strip()
                role = role_part.rstrip(")").strip() or "Story"
            if name:
                staff_edges.append({"role": role, "node": {"name": {"full": name}}})
        data["staff"] = staff_edges
    else:
        replaced = False
        if "writers" in edited_preview:
            staff_edges = [e for e in staff_edges if "story" not in str(e.get("role", "")).lower()
                           and "scénar" not in str(e.get("role", "")).lower()
                           and "original" not in str(e.get("role", "")).lower()]
            staff_edges.extend(_names_to_staff(edited_preview["writers"], "Story"))
            replaced = True
        if "pencillers" in edited_preview:
            staff_edges = [e for e in staff_edges if "art" not in str(e.get("role", "")).lower()
                           and "dessin" not in str(e.get("role", "")).lower()
                           and "illustration" not in str(e.get("role", "")).lower()
                           and "pencill" not in str(e.get("role", "")).lower()]
            staff_edges.extend(_names_to_staff(edited_preview["pencillers"], "Art"))
            replaced = True
        if replaced:
            data["staff"] = staff_edges

    for id_key in ("anilist_id", "mal_id", "mangabaka_id"):
        if id_key in edited_preview:
            val = edited_preview[id_key]
            if val in (None, ""):
                data[id_key] = None
            else:
                data[id_key] = val

    # localized_name n'est pas dans provider_data brut — stocké à part via build
    if "localized_name" in edited_preview:
        data["_edited_localized_name"] = edited_preview["localized_name"]

    return data


def build_kavita_payload(provider_data, metadata, active_fields, config, cache_data, force_update, series_id):
    """
    Pure-ish : mappe provider_data → metadata Kavita + champs généraux.

    Retourne un dict :
      metadata, localized_name, cover_url,
      external_ids {anilist, mal, mangabaka}, preview_fields

    Ne doit PAS appeler kavita.update_series_external_ids.
    """
    pd = copy.deepcopy(provider_data) if provider_data else {}
    # Clés internes scrapers — jamais envoyées à Kavita
    pd.pop("_provider_used", None)
    pd.pop("_fusion_providers", None)
    pd.pop(MATCH_SCORE_KEY, None)
    pd.pop("_score_tie", None)
    pd.pop("_tie_review_payload", None)
    edited_localized = pd.pop("_edited_localized_name", None)
    summary_already_translated = bool(pd.pop("_summary_translated", None))

    meta = copy.deepcopy(metadata) if metadata else {}
    localized_name_to_update = None
    external_ids = {"anilist": None, "mal": None, "mangabaka": None}
    active = list(active_fields or [])

    # 1. Résumé — skip si déjà traduit au park manual-review (pick en langue cible)
    if "summary" in active and pd.get("summary") and (not meta.get("summary") or force_update):
        if summary_already_translated:
            meta["summary"] = pd["summary"]
        else:
            target_lang = config.get("TARGET_LANG", "FR")
            meta["summary"] = translate_text(pd["summary"], config.get("DEEPL_API_KEY"), target_lang)
        meta["summaryLocked"] = True

    # 2. Année (BF61: int YYYY uniquement — pas de string / lock sur parse fail)
    if "year" in active and pd.get("year") not in (None, ""):
        try:
            year_int = int(pd["year"])
        except (TypeError, ValueError):
            year_int = None
        if year_int is not None and 1000 <= year_int <= 2100:
            meta["releaseYear"] = year_int
            meta["releaseYearLocked"] = True

    # 3. Statut
    if "status" in active and pd.get("status") in PUBLICATION_STATUS_MAP:
        meta["publicationStatus"] = PUBLICATION_STATUS_MAP[pd["status"]]
        meta["publicationStatusLocked"] = True

    # 4. Genres
    if "genres" in active and pd.get("genres"):
        meta["genres"] = [
            {"id": 0, "title": g}
            for g in _dedupe_titles(pd["genres"])[: get_max_genres(config)]
        ]
        meta["genresLocked"] = True

    # 5. Tags & personnages
    if "tags" in active:
        if pd.get("tags"):
            meta["tags"] = [
                {"id": 0, "title": tag}
                for tag in _dedupe_titles(pd["tags"])[: get_max_tags(config)]
            ]
            meta["tagsLocked"] = True
        if pd.get("characters"):
            characters_payload = []
            for c in pd["characters"]:
                name = None
                if isinstance(c, str):
                    name = c.strip()
                elif isinstance(c, dict):
                    node = c.get("node") if isinstance(c.get("node"), dict) else {}
                    nested_name = node.get("name")
                    if isinstance(nested_name, dict):
                        name = (
                            nested_name.get("full")
                            or nested_name.get("romaji")
                            or nested_name.get("native")
                            or ""
                        ).strip()
                    elif isinstance(nested_name, str):
                        name = nested_name.strip()
                    if not name:
                        raw = c.get("name") or c.get("full")
                        name = str(raw).strip() if raw else ""
                if name:
                    characters_payload.append({"id": 0, "name": name})
            if characters_payload:
                meta["characters"] = characters_payload
                meta["characterLocked"] = True

    # 6. Titres alternatifs
    if "alt_titles" in active:
        from localized_titles import resolve_effective_title_policy, resolve_localized_name

        mode, langs = resolve_effective_title_policy(
            config, (cache_data or {}).get("alt_title_langs") or ""
        )
        localized_name_to_update = resolve_localized_name(pd, mode=mode, langs=langs)

    if edited_localized is not None:
        localized_name_to_update = edited_localized or None

    # 7. Staff
    if "staff" in active:
        writers, pencillers, colorists, translators, cover_artists, editors, letterers, inkers = (
            [], [], [], [], [], [], [], [],
        )
        buckets = {
            "writers": writers,
            "pencillers": pencillers,
            "colorists": colorists,
            "translators": translators,
            "cover_artists": cover_artists,
            "editors": editors,
            "letterers": letterers,
            "inkers": inkers,
        }
        seen_per_bucket = {name: set() for name in buckets}
        for edge in pd.get("staff") or []:
            node = edge.get("node") or {}
            node_name = node.get("name") or {}
            name = node_name.get("full") or ""
            if not name:
                continue
            for bucket in staff_role_buckets(edge.get("role")):
                # Deux rôles du même métier pour la même personne (« Story & Art »
                # puis « Art ») : Kavita n'a que faire du doublon.
                if name in seen_per_bucket[bucket]:
                    continue
                seen_per_bucket[bucket].add(name)
                buckets[bucket].append({"id": 0, "name": name})

        if writers:
            meta["writers"] = writers
            meta["writerLocked"] = True
        if pencillers:
            meta["pencillers"] = pencillers
            meta["pencillerLocked"] = True
        if colorists:
            meta["colorists"] = colorists
            meta["coloristLocked"] = True
        if translators:
            meta["translators"] = translators
            meta["translatorLocked"] = True
        if cover_artists:
            meta["coverArtists"] = cover_artists
            meta["coverArtistLocked"] = True
        if editors:
            meta["editors"] = editors
            meta["editorLocked"] = True
        if letterers:
            meta["letterers"] = letterers
            meta["lettererLocked"] = True
        if inkers:
            meta["inkers"] = inkers
            meta["inkerLocked"] = True

    # 8. Éditeur
    if "publisher" in active and pd.get("publisher"):
        meta["publishers"] = [{"id": 0, "name": pd["publisher"]}]
        meta["publisherLocked"] = True

    # 9. Age rating
    if "age" in active and pd.get("age_rating"):
        mapped_rating = AGE_RATING_MAP.get(str(pd["age_rating"]).lower())
        if mapped_rating is not None:
            meta["ageRating"] = mapped_rating
            meta["ageRatingLocked"] = True

    # 10. Liens externes & IDs (collecte uniquement — pas d'appel Kavita ici)
    if "weblinks" in active:
        a_id = pd.get("anilist_id")
        m_id = pd.get("mal_id")
        mb_id = pd.get("mangabaka_id")
        external_ids = {"anilist": a_id, "mal": m_id, "mangabaka": mb_id}

        # force + RESET_CONTEXT_ON_FORCE → replace (drop stale Kavita links from
        # false positives). Otherwise merge/append into existing webLinks.
        replace_links = bool(
            force_update and config.get("RESET_CONTEXT_ON_FORCE", False)
        )
        if replace_links:
            links_list = []
        else:
            existing_links_raw = meta.get("webLinks")
            links_list = (
                [link.strip() for link in str(existing_links_raw).split(",")]
                if existing_links_raw
                else []
            )

        def add_weblink(url):
            if url and str(url).strip() and str(url).strip() not in links_list:
                links_list.append(str(url).strip())

        if a_id:
            add_weblink(f"https://anilist.co/manga/{a_id}")
        if m_id:
            add_weblink(f"https://myanimelist.net/manga/{m_id}")
        if mb_id:
            add_weblink(f"https://mangabaka.org/{mb_id}")
        if pd.get("url"):
            add_weblink(pd["url"])
        for link in pd.get("accumulated_links", []):
            add_weblink(link)

        safe_links = [str(l) for l in links_list if l is not None and str(l).strip()]
        if safe_links:
            meta["webLinks"] = ",".join(safe_links)
        elif replace_links:
            # Explicit clear so a failed/empty scrape does not keep old URLs.
            meta["webLinks"] = ""

    # 11. Langue (BF57) — uniquement si le champ est dans le masque ciblé.
    # Avant : écriture hors active_fields à chaque enrich réussi.
    if "language" in active:
        target_lang = (config.get("TARGET_LANG") or "").strip()
        if target_lang:
            current_lang = (meta.get("language") or "").strip()
            if force_update or not current_lang:
                meta["language"] = target_lang.lower()
                meta["languageLocked"] = True

    meta["seriesId"] = int(series_id)
    cover_url = pd.get("cover_url")

    preview_fields = build_preview_fields(pd, localized_name=localized_name_to_update)

    return {
        "metadata": meta,
        "localized_name": localized_name_to_update,
        "cover_url": cover_url,
        "external_ids": external_ids,
        "preview_fields": preview_fields,
        # Conservé pour le chemin cover (active_fields déjà résolu côté appelant)
        "_provider_data": pd,
    }


def _emit_series_status(series_id, status, series_name=None):
    """Pousse le statut cache vers le dashboard (badge live)."""
    try:
        from extensions import socketio
        socketio.emit(
            "series_status",
            {
                "series_id": int(series_id),
                "status": status,
                "series_name": series_name or "",
            },
        )
    except Exception as exc:
        logging.debug("series_status emit skipped: %s", exc)


def _schedule_seal_retry(series_id, series_name, delay_s=2.0, lock_keys=None):
    """Après soft-fail re-lock : retente un seal seul (sans re-scrape).

    `lock_keys` : les verrous que la passe d'écriture a réellement fermés. Sans
    cette liste, `seal_series_locks` se replie sur « tout verrou dont le champ
    porte du contenu », donc referme aussi les champs remplis par le scan de
    fichiers ou par Kavita+ que l'utilisateur avait laissés ouverts exprès —
    alors qu'ici l'appelant sait exactement ce qu'il vient d'écrire.

    Passe sous le même `_processing_lock` que `enrich_series` /
    `apply_manual_review` : sans ça, un re-scrape (force-sync, webhook, review
    manuelle) de la même série déclenché juste après l'écriture soft-fail
    pourrait s'exécuter en parallèle de ce retry, les deux touchant les mêmes
    verrous Kavita. Si la série est déjà réclamée par un autre traitement, le
    retry est abandonné sans bloquer — le filet de secours reste le bouton 🔒
    manuel et `POST /api/series/seal-locks-pending`.
    """
    import threading

    def _run():
        from services.enrichment_engine import _processing_lock, _processing_series_ids
        t = get_ui_translations()

        with _processing_lock:
            if series_id in _processing_series_ids:
                logging.info(t.get("log_seal_retry_skip", "[{0}] ⏭️ Retry seal ignoré : série déjà en cours de traitement.").format(series_name))
                return
            _processing_series_ids.add(series_id)

        try:
            from config_manager import load_config
            from kavita_api import KavitaAPI

            config = load_config()
            api = KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))
            if not api.authenticate():
                logging.warning(t.get("log_seal_retry_auth", "[{0}] ⚠️ Retry seal : auth Kavita échouée").format(series_name))
                return
            ok, msg = api.seal_series_locks(series_id, lock_keys=lock_keys)
            if ok:
                update_status(series_id, "COMPLETED")
                _emit_series_status(series_id, "COMPLETED", series_name)
                logging.info(t.get("log_seal_retry_ok", "[{0}] ✅ Retry seal OK — statut COMPLETED").format(series_name))
            else:
                logging.warning(t.get("log_seal_retry_fail", "[{0}] ⚠️ Retry seal échoué : {1}").format(series_name, msg))
        except Exception as exc:
            logging.warning(t.get("log_seal_retry_crash", "[{0}] ⚠️ Retry seal crash : {1}").format(series_name, exc))
        finally:
            with _processing_lock:
                _processing_series_ids.discard(series_id)

    timer = threading.Timer(delay_s, _run)
    timer.daemon = True
    timer.start()


def apply_kavita_payload(
    kavita,
    series_id,
    series_name,
    built,
    active_fields,
    config,
    used_providers,
    t,
):
    """
    Écrit external ids, metadata, general, cover ; COMPLETED ou NEEDS_RELOCK + télémétrie.

    Retourne (success, msg, used_providers).
    msg vaut ``NEEDS_RELOCK`` si écriture OK mais verrous non posés.
    """
    series_id = int(series_id)
    meta = built.get("metadata") or {}
    localized_name = built.get("localized_name")
    cover_url = built.get("cover_url")
    ext = built.get("external_ids") or {}
    active = list(active_fields or [])
    used = list(used_providers or [])

    logging.info(t.get("log_sending").format(series_name))

    ids_ok = True
    ids_msg = ""
    if "weblinks" in active:
        a_id, m_id, mb_id = ext.get("anilist"), ext.get("mal"), ext.get("mangabaka")
        if a_id or m_id or mb_id:
            ids_ok, ids_msg = kavita.update_series_external_ids(series_id, a_id, m_id, mb_id)
            if not ids_ok:
                logging.error(
                    t.get(
                        "log_kavita_refused",
                        "[{0}] ❌ Kavita a refusé la mise à jour : {1}",
                    ).format(series_name, t.get("log_external_ids_label", "IDs externes: {0}").format(ids_msg))
                )

    success, msg, meta_sealed = kavita.update_series_metadata(meta)

    general_ok = True
    general_msg = ""
    general_sealed = True
    # Verrous que l'écriture des champs généraux ferme : `update_series_general`
    # pose `localizedNameLocked` dès qu'un titre alternatif part, et rien d'autre.
    general_locks = {}
    # BF67: n'appeler general que si la metadata a réussi (atomicité soft).
    #
    # Le format ne déclenche plus l'appel : `UpdateSeriesDto` n'a jamais porté ni
    # `Format` ni `FormatLocked`, si bien qu'une passe n'ayant qu'un format à
    # « écrire » traversait quand même le chemin d'écriture des champs généraux
    # pour n'y rien écrire, et faisait dépendre son verdict de verrouillage d'un
    # appel sans objet.
    if success and localized_name:
        general_locks = {"localizedNameLocked": True}
        general_ok, general_msg, general_sealed = kavita.update_series_general(
            series_id,
            localized_name=localized_name,
        )
        if not general_ok:
            logging.error(
                t.get(
                    "log_kavita_refused",
                    "[{0}] ❌ Kavita a refusé la mise à jour : {1}",
                ).format(series_name, t.get("log_general_fields_label", "champs généraux: {0}").format(general_msg))
            )

    if success and general_ok:
        sealed = bool(meta_sealed and general_sealed)
        final_status = "COMPLETED" if sealed else "NEEDS_RELOCK"

        logging.info(t.get("log_success").format(series_name))
        if not sealed:
            logging.warning(
                t.get(
                    "log_needs_relock",
                    "[{0}] ⚠️ Écriture OK mais verrous non posés — statut À sceller.",
                ).format(series_name)
            )

        # Provenance relue à l'écriture : un choix manuel survenu pendant le run
        # (phase cover d'une Manual Review) doit être vu ici.
        cover_manual = bool(get_all_cached_data().get(series_id, {}).get("cover_manual"))
        explicit_cover = bool(built.get("force_cover_upload"))
        overwrite_manual = bool(config.get("COVER_FORCE_OVERWRITE"))
        cover_protected = cover_manual and not explicit_cover and not overwrite_manual

        if (
            "cover" in active
            and cover_url
            and not cover_protected
            and (config.get("AUTO_COVER") or explicit_cover)
        ):
            logging.info(t.get("log_cover_upload").format(series_name))
            cover_success, cover_msg = kavita.upload_series_cover(series_id, cover_url)
            if not cover_success:
                logging.warning(t.get("log_cover_fail").format(series_name, cover_msg))
            else:
                logging.info(t.get("log_cover_success").format(series_name))
                if explicit_cover:
                    # Choix explicite (cover pick MR / edit cover_url) : même
                    # protection que le modal dashboard `/update-cover`.
                    mark_cover_manual(series_id)
                    logging.info(
                        t.get(
                            "log_cover_marked_manual",
                            "🔒 [{0}] Couverture marquée comme choix manuel (protégée des scrapings automatiques).",
                        ).format(series_name)
                    )
                elif cover_manual:
                    # Écrasement assumé via l'interrupteur : la couverture
                    # redevient celle du provider, il n'y a plus rien à protéger.
                    release_cover_manual(series_id)
                    logging.warning(
                        t.get(
                            "log_cover_manual_overwritten",
                            "⚠️ [{0}] Couverture manuelle écrasée (« Écraser les couvertures manuelles » est actif).",
                        ).format(series_name)
                    )
        elif "cover" in active and cover_url and cover_protected:
            logging.info(t.get("log_cover_manual_protected", "[{0}] ⏭️ Couverture ignorée : choix manuel protégé.").format(series_name))

        # BF124 : IDs externes refusés = écriture incomplète. Tout ce qui a réussi
        # (metadata, généraux, couverture) reste écrit, mais on ne pose AUCUN statut
        # terminal : COMPLETED afficherait du vert avec des champs AniList/MAL vides
        # côté Kavita, et NEEDS_RELOCK serait auto-scellé en COMPLETED au passage
        # suivant sans jamais rejouer l'écriture des IDs. Même contrat que l'échec
        # des champs généraux (plus bas) : la série garde son statut précédent.
        if not ids_ok:
            return False, t.get("msg_external_ids_error", "Erreur IDs externes: {0}").format(ids_msg), used

        update_status(series_id, final_status)
        _emit_series_status(series_id, final_status, series_name)
        _broadcast_enrichment_stats(record_enrichment_telemetry(used))

        if not sealed:
            # Le rescellement se limite aux verrous de CES payloads : ce sont les
            # seuls que la passe a fermés. Sans la liste, le repli refermerait
            # tout verrou dont le champ porte du contenu côté Kavita — y compris
            # un éditeur ou un âge venus du scan de fichiers, que MetaKavita n'a
            # jamais écrits et que l'utilisateur avait laissés ouverts.
            _schedule_seal_retry(
                series_id,
                series_name,
                lock_keys=lock_keys_from_payload(meta, general_locks),
            )
            return True, "NEEDS_RELOCK", used

        return True, t.get("msg_success", "Succès"), used

    if success and not general_ok:
        logging.error(t.get("log_meta_ok_general_fail", "[{0}] Métadonnées OK mais champs généraux refusés : {1}").format(series_name, general_msg))
        return False, t.get("msg_general_fields_error", "Erreur champs généraux: {0}").format(general_msg), used

    logging.error(t.get("log_kavita_refused").format(series_name, msg))
    return False, t.get("msg_error", "Erreur: {0}").format(msg), used
