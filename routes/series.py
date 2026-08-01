"""
Blueprint des actions par série : overrides manuels, ignorer/inclure, recherche
et application de couvertures.

⚠️ Endpoints réels : 'series.save_override', 'series.toggle_ignore',
'series.get_series_covers', 'series.apply_series_cover'.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from flask import Blueprint, request, jsonify

from config_manager import load_config
from db_manager import get_all_cached_data, update_status, save_series_override
from kavita_api import KavitaAPI
from models import SeriesOverride
from scrapers import ScraperRegistry
from scrapers.utils import library_type_for_scraper
from services.enrichment_engine import ALL_TARGETED_FIELDS
from secure_logging import safe_exc_str

series_bp = Blueprint('series', __name__)


@series_bp.route('/save-override', methods=['POST'])
def save_override():
    series_id = request.form.get('series_id')
    forced_id = request.form.get('forced_id', '').strip()
    alt_title = request.form.get('alternative_title', '').strip()
    forced_provider = request.form.get('forced_provider', 'AUTO').strip()
    targeted_fields = request.form.get('targeted_fields', 'ALL').strip()
    publisher_pref = request.form.get('publisher_pref', 'GLOBAL').strip()
    alt_title_langs = request.form.get('alt_title_langs', '').strip()

    save_series_override(SeriesOverride(
        series_id=int(series_id),
        forced_id=forced_id,
        alternative_title=alt_title,
        forced_provider=forced_provider,
        targeted_fields=targeted_fields,
        publisher_pref=publisher_pref,
        alt_title_langs=alt_title_langs,
    ))
    return "OK", 200


@series_bp.route('/toggle-ignore', methods=['POST'])
def toggle_ignore():
    series_id = request.form.get('series_id')
    current_status = request.form.get('current_status')
    if not series_id: return jsonify(success=False)

    new_status = 'IGNORED' if current_status != 'IGNORED' else 'PENDING'
    update_status(int(series_id), new_status)
    # Une série ignorée ne doit plus apparaître dans la file de review.
    if new_status == 'IGNORED':
        try:
            from db_manager import delete_pending_by_series
            from services.manual_review import emit_pending_count
            deleted = delete_pending_by_series(int(series_id))
            if deleted:
                emit_pending_count()
        except Exception as e:
            logging.debug("ignore-series orphan purge failed: %s", safe_exc_str(e))
    return jsonify(success=True, new_status=new_status)


@series_bp.route('/api/series/<int:series_id>/covers', methods=['GET'])
def get_series_covers(series_id):
    series_name = request.args.get('series_name')
    cache_data = get_all_cached_data().get(series_id, {})
    search_query = cache_data.get('forced_id') or cache_data.get('alternative_title') or series_name

    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

    library_type = kavita.get_library_type_for_series(series_id)
    target_scrapers = ScraperRegistry.get_by_type(library_type)

    if not target_scrapers:
        target_scrapers = ScraperRegistry.get_by_type("Manga")

    script_root = request.script_root or ""
    covers = []

    def fetch_single_scraper(scraper):
        """Fonction exécutée en parallèle pour chaque scraper."""
        try:
            fetch_lt = library_type_for_scraper(scraper, library_type)
            s_covers = scraper.fetch_covers(search_query, library_type=fetch_lt)
            results = []
            if s_covers:
                for c in s_covers:
                    if getattr(scraper, 'requires_proxy', False):
                        c['display_url'] = f"{script_root}/api/proxy-image?url={quote(c['url'])}"
                    else:
                        c['display_url'] = c['url']
                    results.append(c)
            return results
        except Exception as e:
            logging.error(f"[Covers] Erreur sur le scraper {scraper.id} : {e}")
            return []

    # Lancement en parallèle de tous les scrapers disponibles
    with ThreadPoolExecutor(max_workers=min(len(target_scrapers), 8)) as executor:
        futures = [executor.submit(fetch_single_scraper, scraper) for scraper in target_scrapers]
        for future in as_completed(futures):
            res = future.result()
            if res:
                covers.extend(res)

    return jsonify({"success": True, "covers": covers[:20]})


@series_bp.route('/api/series/<int:series_id>/update-cover', methods=['POST'])
def apply_series_cover(series_id):
    cover_url = request.json.get('cover_url')
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))

    success, msg = kavita.upload_series_cover(series_id, cover_url)

    if success:
        # Protège le choix manuel : on retire 'cover' des champs ciblés de cette
        # série pour qu'un futur scraping (webhook, auto-sync, force-sync, batch)
        # ne réécrase pas silencieusement la couverture avec celle du fournisseur.
        cache_data = get_all_cached_data().get(int(series_id), {})
        override = SeriesOverride.from_cache_dict(series_id, cache_data)
        original_status = cache_data.get('status') or 'PENDING'

        current_fields = override.targeted_fields
        if current_fields == 'ALL':
            all_fields = list(ALL_TARGETED_FIELDS)
        else:
            all_fields = current_fields.split(',')

        remaining_fields = [f for f in all_fields if f != 'cover']
        override.targeted_fields = ",".join(remaining_fields) if remaining_fields else "NONE"

        save_series_override(override)
        # save_series_override() force TOUJOURS status='PENDING' (voir db_manager.py) :
        # c'est le comportement voulu pour /save-override (l'utilisateur fournit un
        # meilleur indice pour relancer la recherche), mais ici on ne fait QUE protéger
        # la couverture. Sans cette restauration, choisir une couverture manuelle
        # ré-ouvrait silencieusement une série IGNORED (elle repasserait dans la file
        # du prochain auto-sync) ou COMPLETED/NOT_FOUND (fausse les stats et expose la
        # série à un re-scraping inutile, voire à l'écrasement d'autres champs si un
        # force_update survient entre-temps).
        update_status(int(series_id), original_status)
        logging.info(f"🔒 [Couverture Manuelle] Champ 'cover' verrouillé pour la série {series_id} (protégé contre les futurs scrapings automatiques).")

    return jsonify({"success": success, "msg": msg})


@series_bp.route('/api/series/<int:series_id>/seal-locks', methods=['POST'])
def seal_series_locks(series_id):
    """Rescelle les verrous Kavita (après NEEDS_RELOCK) sans re-scraper."""
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    if not kavita.authenticate():
        return jsonify(success=False, error="Auth Kavita échouée"), 502

    ok, msg = kavita.seal_series_locks(series_id)
    if not ok:
        return jsonify(success=False, error=msg), 502

    update_status(int(series_id), 'COMPLETED')
    try:
        from services.kavita_payload import _emit_series_status
        cache = get_all_cached_data().get(int(series_id), {})
        _emit_series_status(series_id, 'COMPLETED', cache.get('alternative_title') or '')
    except Exception as e:
        logging.debug("seal-locks status emit failed: %s", safe_exc_str(e))
    return jsonify(success=True, status='COMPLETED', message=msg)


@series_bp.route('/api/series/seal-locks-pending', methods=['POST'])
def seal_all_needs_relock():
    """Rescelle toutes les séries en statut NEEDS_RELOCK."""
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    if not kavita.authenticate():
        return jsonify(success=False, error="Auth Kavita échouée"), 502

    cached = get_all_cached_data()
    targets = [sid for sid, row in cached.items() if (row or {}).get('status') == 'NEEDS_RELOCK']
    sealed = []
    failed = []
    from services.kavita_payload import _emit_series_status
    for sid in targets:
        ok, msg = kavita.seal_series_locks(sid)
        if ok:
            update_status(int(sid), 'COMPLETED')
            _emit_series_status(sid, 'COMPLETED')
            sealed.append(int(sid))
        else:
            failed.append({"series_id": int(sid), "error": msg})
    return jsonify(
        success=True,
        sealed_count=len(sealed),
        failed_count=len(failed),
        sealed=sealed,
        failed=failed,
    )
