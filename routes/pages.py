"""
Blueprint des pages HTML principales : tableau de bord (/) et statistiques (/stats).

⚠️ Endpoints réels : 'pages.index' et 'pages.stats' (voir routes/auth.py pour le
rappel sur le nommage des endpoints après passage aux Blueprints).
"""

import logging

from flask import Blueprint, request, render_template

from config_manager import (
    load_config,
    get_kavita_ui_url,
    get_kavita_plus_url,
    get_disabled_library_ids,
)
from db_manager import get_all_cached_data, clean_orphaned_cache, get_provider_stats, get_lifetime_stats
from kavita_api import KavitaAPI
from scrapers.utils import get_match_accept_threshold
from translations import translations
from scrapers import ScraperRegistry
from services.changelog_service import get_current_version
from services.mr_achievements import evaluate_from_lifetime
from services.stats_service import compute_playful_stats
from services.scraper_diagnostics import list_scrapers_inventory

pages_bp = Blueprint('pages', __name__)


def _prepare_index_data(config, msg="", error_msg="", selected_lib=None):
    series_list = []
    libraries = []
    all_libraries = []

    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    disabled_ids = get_disabled_library_ids(config)

    if config.get('KAVITA_API_KEY') and config.get('KAVITA_URL'):
        kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])

        if kavita.authenticate():
            all_libraries = kavita.get_libraries() or []

            # Dashboard = toutes les biblios. DISABLED_LIBRARIES ne borne que
            # le polling auto-sync (background_tasks), pas le batch ni le webhook.
            libraries = list(all_libraries)
            if selected_lib and not any(str(lib.get("id")) == str(selected_lib) for lib in libraries):
                selected_lib = None
            if all_libraries:
                series_list = kavita.get_all_series(library_id=selected_lib)

                if not selected_lib:
                    # Inventaire complet pour ne pas effacer le cache des séries
                    # temporairement hors sync (dénylist).
                    full_ids = {s['id'] for s in series_list}
                    cleaned = clean_orphaned_cache(full_ids)
                    if cleaned > 0:
                        logging.info(t.get("log_orphans_cleaned", "🧹 Nettoyage : {0} séries orphelines retirées du cache.").format(cleaned))
            else:
                error_msg = t.get('err_no_libraries', "Aucune bibliothèque trouvée dans Kavita.")
        else:
            err_key = {
                "localhost": "err_kavita_localhost",
                "http_401": "err_kavita_unauthorized",
                "timeout": "err_kavita_timeout",
                "dns": "err_kavita_dns",
                "connection": "err_kavita_connection",
                "ssl": "err_kavita_ssl",
            }.get(getattr(kavita, "last_auth_error", None), "err_kavita")
            error_msg = t.get(err_key, t.get('err_kavita', "Connexion à Kavita échouée."))
    else:
        error_msg = t.get('err_missing', "Données manquantes.")

    cached_info = get_all_cached_data()

    stats = {
        'total': len(cached_info),
        'completed': sum(1 for v in cached_info.values() if v.get('status') == 'COMPLETED'),
        'pending': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING'),
        'pending_review': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING_REVIEW'),
        'not_found': sum(1 for v in cached_info.values() if v.get('status') == 'NOT_FOUND'),
        'ignored': sum(1 for v in cached_info.values() if v.get('status') == 'IGNORED')
    }

    if libraries:
        for s in series_list:
            item_cache = cached_info.get(s['id'], {'status': 'PENDING', 'forced_id': '', 'alternative_title': ''})
            s['status'] = item_cache.get('status', 'PENDING')
            s['forced_id'] = item_cache.get('forced_id') or ''
            s['alternative_title'] = item_cache.get('alternative_title') or ''
            s['targeted_fields'] = item_cache.get('targeted_fields') or 'ALL'
            s['forced_provider'] = item_cache.get('forced_provider') or 'AUTO'
            s['publisher_pref'] = item_cache.get('publisher_pref') or 'GLOBAL'
            s['alt_title_langs'] = item_cache.get('alt_title_langs') or ''

    # Ne jamais injecter la vraie clé NI le sentinel « ******** » dans le HTML :
    # les navigateurs (autofill mot de passe) écrasent souvent ce champ, et un
    # saveConfig() sidebar renvoyait alors ******** / un mauvais secret / du vide,
    # ce qui faisait croire qu'un setup frais « n'écrivait pas » la config Kavita.
    # Champ toujours vide à l'affichage ; placeholder + flags has_* indiquent
    # qu'une clé est déjà enregistrée. POST vide = conserver (routes/config.py).
    safe_config = config.copy()
    has_kavita_api_key = bool((safe_config.get('KAVITA_API_KEY') or '').strip())
    has_deepl_api_key = bool((safe_config.get('DEEPL_API_KEY') or '').strip())
    has_azure_api_key = bool((safe_config.get('AZURE_API_KEY') or '').strip())
    safe_config['KAVITA_API_KEY'] = ''
    safe_config['DEEPL_API_KEY'] = ''
    safe_config['AZURE_API_KEY'] = ''

    scrapers_with_keys = [
        s for s in ScraperRegistry.get_all(scope="series")
        if getattr(s, 'needs_api_key', False)
    ]
    scraper_has_api_key = {}
    for s in scrapers_with_keys:
        key_name = f"{s.id}_API_KEY"
        scraper_has_api_key[s.id] = bool((safe_config.get(key_name) or '').strip())
        safe_config[key_name] = ''

    manga_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Manga")]
    comic_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Comic")]
    book_providers = [{"id": s.id, "display_name": s.localized_display_name} for s in ScraperRegistry.get_by_type("Book")]

    magic_scrapers = [
        {"id": s.id, "display_name": s.localized_display_name, "supported_types": list(s.supported_types)}
        for s in ScraperRegistry.get_all(scope="series")
        if getattr(s, 'has_direct_id_support', False)
    ]

    from services.scraper_manager import get_pending_core_updates
    pending_core_updates = get_pending_core_updates()

    # BF97 / #30 — virtual list above this size (light Jinja rows below).
    _VIRTUAL_SERIES_THRESHOLD = 120
    series_index_payload = [
        {
            "id": s["id"],
            "name": s.get("name") or "",
            "searchTitle": (s.get("name") or "").lower(),
            "libraryId": s.get("libraryId"),
            "status": s.get("status") or "PENDING",
            "forced_id": s.get("forced_id") or "",
            "alternative_title": s.get("alternative_title") or s.get("name") or "",
            "forced_provider": s.get("forced_provider") or "AUTO",
            "targeted_fields": s.get("targeted_fields") or "ALL",
            "publisher_pref": s.get("publisher_pref") or "GLOBAL",
            "alt_title_langs": s.get("alt_title_langs") or "",
        }
        for s in series_list
    ]
    use_virtual_series_list = len(series_list) >= _VIRTUAL_SERIES_THRESHOLD

    return render_template('index.html', config=safe_config, app_version=get_current_version(), msg=msg, error_msg=error_msg,
                           series_list=series_list, libraries=libraries, selected_lib=selected_lib,
                           all_libraries=all_libraries, disabled_library_ids=disabled_ids,
                           t=t, stats=stats,
                           lifetime=get_lifetime_stats(),
                           kavita_ui_url=get_kavita_ui_url(config),
                           kavita_plus_url=get_kavita_plus_url(config),
                           manga_providers=manga_providers,
                           comic_providers=comic_providers,
                           book_providers=book_providers,
                           magic_scrapers=magic_scrapers,
                           scrapers_with_keys=scrapers_with_keys,
                           has_kavita_api_key=has_kavita_api_key,
                           has_deepl_api_key=has_deepl_api_key,
                           has_azure_api_key=has_azure_api_key,
                           scraper_has_api_key=scraper_has_api_key,
                           match_accept_threshold=get_match_accept_threshold(config),
                           pending_core_updates=pending_core_updates,
                           series_index_payload=series_index_payload,
                           use_virtual_series_list=use_virtual_series_list)


@pages_bp.route('/', methods=['GET'])
def index():
    config = load_config()
    selected_lib = request.args.get('library_id')
    return _prepare_index_data(config, msg="", error_msg="", selected_lib=selected_lib)


@pages_bp.route('/stats')
def stats():
    config = load_config()
    cached_data = get_all_cached_data()
    total = len(cached_data)
    completed = sum(1 for v in cached_data.values() if v.get('status') == 'COMPLETED')
    pending = sum(1 for v in cached_data.values() if v.get('status') == 'PENDING')
    pending_review = sum(1 for v in cached_data.values() if v.get('status') == 'PENDING_REVIEW')
    not_found = sum(1 for v in cached_data.values() if v.get('status') == 'NOT_FOUND')
    ignored = sum(1 for v in cached_data.values() if v.get('status') == 'IGNORED')

    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    playful_enabled = bool(config.get('ENABLE_PLAYFUL_STATS', True))
    lifetime = get_lifetime_stats()
    playful = None
    if playful_enabled:
        playful = compute_playful_stats(
            cached_data,
            get_provider_stats(),
            lifetime,
            translations_dict=t,
        )
        mr_achievements = playful.get("mr_achievements") or evaluate_from_lifetime(lifetime, t)
    else:
        # Ancre #mr-achievements (lien recap MR) reste valide même sans stats playful.
        mr_achievements = evaluate_from_lifetime(lifetime, t)

    return render_template(
        'stats.html',
        config=config,
        t=t,
        total=total,
        completed=completed,
        pending=pending,
        pending_review=pending_review,
        not_found=not_found,
        ignored=ignored,
        playful_enabled=playful_enabled,
        playful=playful,
        mr_achievements=mr_achievements,
    )


@pages_bp.route('/diagnostics')
def diagnostics():
    """Page premium de diagnostic (préflight Internet/Kavita + probes scrapers)."""
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    return render_template(
        'diagnostics.html',
        config=config,
        t=t,
        app_version=get_current_version(),
        scrapers=list_scrapers_inventory(config),
        active_tab="diagnostics",
    )
