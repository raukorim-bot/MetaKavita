"""
Blueprint d'authentification : /setup, /login, /logout.

⚠️ Noms d'endpoints : ce blueprint est enregistré sous le nom 'auth', donc les
endpoints Flask réels sont 'auth.setup', 'auth.login' et 'auth.logout'. Ces noms
sont référencés dans les listes blanches de `auth_manager.py` (setup_gate /
login_gate) : les renommer déplace la frontière de sécurité. Voir DEVELOPER.md
section 11.C pour la checklist à suivre.

La logique d'authentification elle-même (hachage, stockage, verrouillage IP)
vit dans `auth_manager.py` ; ce module reste une couche HTTP fine.
"""

import logging
import os

from flask import Blueprint, request, render_template, session, redirect, url_for, jsonify

import auth_manager
from config_manager import (
    load_config,
    save_config,
    CONFIG_LOCK,
    target_lang_from_ui_lang,
)
from translations import translations

auth_bp = Blueprint('auth', __name__)

_PROVIDER_KEYS = (
    'PROVIDER_1', 'PROVIDER_2', 'PROVIDER_3',
    'COMIC_PROVIDER_1', 'COMIC_PROVIDER_2', 'COMIC_PROVIDER_3',
    'BOOK_PROVIDER_1', 'BOOK_PROVIDER_2', 'BOOK_PROVIDER_3',
)

# Defaults « click and go » appliqués au premier setup (Passer / champs absents).
_SETUP_BOOL_DEFAULTS = {
    'SMART_SCORING': True,
    'SMART_COMPLETION': True,
    'MANUAL_REVIEW_MODE': False,
    'AUTO_COVER': False,
    'TITLE_FALLBACK_TRANSLATION': False,
}
_SETUP_AUTO_SYNC_DEFAULT = 360  # 6 h


def _t(ui_lang=None):
    """(dictionnaire de traduction, config) pour la langue demandée ou configurée."""
    config = load_config()
    lang = (ui_lang or config.get('UI_LANG') or 'fr').strip().lower()
    if lang not in translations:
        lang = 'fr'
    return translations.get(lang, translations['fr']), config


def _normalize_root_path(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        return ''
    return '/' + raw.strip('/')


def _effective_root_path(config: dict) -> str:
    return _normalize_root_path(
        (os.environ.get('ROOT_PATH') or '').strip()
        or (config.get('ROOT_PATH') or '').strip()
    )


def _form_bool(key: str, default: bool) -> bool:
    if key not in request.form:
        return default
    return request.form.get(key, '').strip().lower() in ('true', '1', 'on', 'yes')


def _apply_secret(config: dict, form_key: str, config_key: str) -> None:
    val = request.form.get(form_key, '').strip()
    if val and val != '********':
        config[config_key] = val


def _apply_setup_config(config: dict) -> bool:
    """Merge le formulaire wizard dans config. Retourne True si ROOT_PATH change
    par rapport à la valeur effective actuelle (redémarrage conseillé)."""
    from scrapers import ScraperRegistry

    before_root = _effective_root_path(config)

    config['KAVITA_URL'] = request.form.get('KAVITA_URL', '').strip().rstrip('/')
    _apply_secret(config, 'KAVITA_API_KEY', 'KAVITA_API_KEY')

    new_root = _normalize_root_path(request.form.get('ROOT_PATH', ''))
    config['ROOT_PATH'] = new_root

    ui_lang = request.form.get('UI_LANG', 'fr').strip().lower()
    if ui_lang not in ('fr', 'en'):
        ui_lang = 'fr'
    config['UI_LANG'] = ui_lang

    target = request.form.get('TARGET_LANG', '').strip()
    if not target:
        target = target_lang_from_ui_lang(ui_lang)
    config['TARGET_LANG'] = target

    config['TRANSLATION_PROVIDER'] = request.form.get(
        'TRANSLATION_PROVIDER', 'GOOGLE'
    ).strip() or 'GOOGLE'
    _apply_secret(config, 'DEEPL_API_KEY', 'DEEPL_API_KEY')
    _apply_secret(config, 'AZURE_API_KEY', 'AZURE_API_KEY')
    config['AZURE_REGION'] = request.form.get('AZURE_REGION', '').strip()

    config['PUBLISHER_PREFERENCE'] = request.form.get(
        'PUBLISHER_PREFERENCE', 'LOCALIZED'
    ).strip() or 'LOCALIZED'
    loc_mode = request.form.get('LOCALIZED_TITLE_MODE', 'all').strip().lower()
    config['LOCALIZED_TITLE_MODE'] = loc_mode if loc_mode in ('all', 'prefer', 'none') else 'all'
    config['LOCALIZED_TITLE_LANGS'] = request.form.get('LOCALIZED_TITLE_LANGS', '').strip()
    config['TITLE_FALLBACK_TRANSLATION'] = _form_bool(
        'TITLE_FALLBACK_TRANSLATION', _SETUP_BOOL_DEFAULTS['TITLE_FALLBACK_TRANSLATION']
    )

    for key, default in _SETUP_BOOL_DEFAULTS.items():
        if key == 'TITLE_FALLBACK_TRANSLATION':
            continue
        config[key] = _form_bool(key, default)

    try:
        interval = int(request.form.get('AUTO_SYNC_INTERVAL', _SETUP_AUTO_SYNC_DEFAULT))
    except (TypeError, ValueError):
        interval = _SETUP_AUTO_SYNC_DEFAULT
    config['AUTO_SYNC_INTERVAL'] = max(0, interval)

    for s in ScraperRegistry.get_all(scope="series"):
        if getattr(s, 'needs_api_key', False):
            key_name = f"{s.id}_API_KEY"
            _apply_secret(config, key_name, key_name)

    for key in _PROVIDER_KEYS:
        if key in request.form:
            config[key] = request.form.get(key, 'NONE').strip() or 'NONE'

    # Env Docker inchangé : si ROOT_PATH est déjà fourni par l'env, la config
    # ne change pas l'effectif — pas de notice inutile.
    env_root = _normalize_root_path(os.environ.get('ROOT_PATH', ''))
    if env_root:
        return False
    return bool(new_root) and new_root != before_root


def _form_values_from_config(config: dict) -> dict:
    """Préremplit le wizard rerun depuis la config actuelle (hors secrets)."""
    fv = {}
    for key in (
        'KAVITA_URL', 'ROOT_PATH', 'UI_LANG', 'TARGET_LANG',
        'TRANSLATION_PROVIDER', 'AZURE_REGION', 'PUBLISHER_PREFERENCE',
        'LOCALIZED_TITLE_MODE', 'LOCALIZED_TITLE_LANGS',
        *_PROVIDER_KEYS,
    ):
        val = config.get(key)
        fv[key] = '' if val is None else str(val)
    for key, default in _SETUP_BOOL_DEFAULTS.items():
        fv[key] = 'true' if bool(config.get(key, default)) else 'false'
    try:
        fv['AUTO_SYNC_INTERVAL'] = str(int(config.get('AUTO_SYNC_INTERVAL', _SETUP_AUTO_SYNC_DEFAULT)))
    except (TypeError, ValueError):
        fv['AUTO_SYNC_INTERVAL'] = str(_SETUP_AUTO_SYNC_DEFAULT)
    return fv


def _form_values_from_request() -> dict:
    fv = {}
    for key in (
        'username', 'KAVITA_URL', 'ROOT_PATH', 'UI_LANG', 'TARGET_LANG',
        'TRANSLATION_PROVIDER', 'AZURE_REGION', 'PUBLISHER_PREFERENCE',
        'LOCALIZED_TITLE_MODE', 'LOCALIZED_TITLE_LANGS', 'AUTO_SYNC_INTERVAL',
        *_PROVIDER_KEYS,
    ):
        if key in request.form:
            fv[key] = request.form.get(key, '')
    for key, default in _SETUP_BOOL_DEFAULTS.items():
        fv[key] = 'true' if _form_bool(key, default) else 'false'
    return fv


def _setup_context(
    t,
    config,
    error=None,
    legacy_required=False,
    form_values=None,
    *,
    setup_rerun=False,
):
    from scrapers import ScraperRegistry

    scrapers_with_keys = [
        s for s in ScraperRegistry.get_all(scope="series")
        if getattr(s, 'needs_api_key', False)
    ]
    scraper_has_api_key = {
        s.id: bool((config.get(f'{s.id}_API_KEY') or '').strip())
        for s in scrapers_with_keys
    }
    manga_providers = [
        {"id": s.id, "display_name": s.localized_display_name}
        for s in ScraperRegistry.get_by_type("Manga")
    ]
    comic_providers = [
        {"id": s.id, "display_name": s.localized_display_name}
        for s in ScraperRegistry.get_by_type("Comic")
    ]
    book_providers = [
        {"id": s.id, "display_name": s.localized_display_name}
        for s in ScraperRegistry.get_by_type("Book")
    ]

    wizard_lang = request.args.get('lang') or request.form.get('UI_LANG') or config.get('UI_LANG', 'fr')
    wizard_lang = str(wizard_lang).strip().lower()
    if wizard_lang not in ('fr', 'en'):
        wizard_lang = 'fr'

    # Ne PAS passer csrf_token ici : ça écraserait le context processor
    # (ensure_csrf_token) avec une chaîne vide et casserait Finish en prod.
    return dict(
        error=error,
        t=t,
        config=config,
        min_password_length=auth_manager.MIN_PASSWORD_LENGTH,
        legacy_required=legacy_required,
        scrapers_with_keys=scrapers_with_keys,
        scraper_has_api_key=scraper_has_api_key,
        manga_providers=manga_providers,
        comic_providers=comic_providers,
        book_providers=book_providers,
        wizard_lang=wizard_lang,
        default_target_lang=target_lang_from_ui_lang(wizard_lang),
        setup_auto_sync_default=_SETUP_AUTO_SYNC_DEFAULT,
        form_values=form_values or {},
        resume_step=0,
        setup_rerun=setup_rerun,
        has_kavita_api_key=bool((config.get('KAVITA_API_KEY') or '').strip()),
        has_deepl_api_key=bool((config.get('DEEPL_API_KEY') or '').strip()),
        has_azure_api_key=bool((config.get('AZURE_API_KEY') or '').strip()),
        first_step=1 if setup_rerun else 0,
    )


def _persist_setup_config(t):
    """Applique le formulaire wizard et sauve. Retourne (ok, root_changed, error_msg)."""
    try:
        with CONFIG_LOCK:
            cfg = load_config()
            root_changed = _apply_setup_config(cfg)
            save_config(cfg)
        return True, root_changed, None
    except Exception as exc:
        logging.warning(
            t.get(
                "log_setup_config_fail",
                "[Setup] Échec persistance config : %s",
            ),
            exc,
        )
        return False, False, t.get('setup_err_config_save')


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Wizard first-run (compte + config) ou rejeu guidé (session requise, sans compte).

    - Aucun compte → first-run public (création du compte + config).
    - Compte existant + session → rerun (config seulement).
    - Compte existant sans session → /login (jamais de 2ᵉ compte ni config anonyme).
    """
    lang_arg = request.args.get('lang') or request.form.get('UI_LANG')
    t, config = _t(lang_arg)

    first_run = auth_manager.setup_required()
    setup_rerun = (not first_run) and auth_manager.is_authenticated()
    if not first_run and not setup_rerun:
        return redirect(url_for('auth.login'))

    legacy_required = first_run and auth_manager.legacy_proof_required()
    has_kavita_key = bool((config.get('KAVITA_API_KEY') or '').strip())

    error = None
    if request.method == 'POST':
        kavita_url = request.form.get('KAVITA_URL', '').strip()
        kavita_key = request.form.get('KAVITA_API_KEY', '').strip()
        kavita_ok = bool(kavita_url) and (bool(kavita_key) or (setup_rerun and has_kavita_key))

        if setup_rerun:
            locked, remaining = auth_manager.is_locked_out()
            if locked:
                minutes = max(1, (remaining + 59) // 60)
                auth_manager.log_lockout_reject(
                    username=session.get('username'),
                    remaining_seconds=remaining,
                )
                error = (t.get('login_err_locked') or '').replace('{}', str(minutes))
            elif not kavita_ok:
                error = t.get('setup_err_kavita_required')
            else:
                ok, root_changed, err = _persist_setup_config(t)
                if not ok:
                    error = err
                else:
                    if root_changed:
                        session['ui_banner'] = t.get(
                            'setup_restart_root_path',
                            'Redémarrez MetaKavita pour appliquer le sous-chemin (ROOT_PATH).',
                        )
                    session['ui_banner'] = session.get('ui_banner') or t.get(
                        'setup_rerun_saved',
                        'Configuration mise à jour.',
                    )
                    return redirect(url_for('pages.index'))
        else:
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            confirm = request.form.get('password_confirm', '')

            locked, remaining = auth_manager.is_locked_out()
            if locked:
                minutes = max(1, (remaining + 59) // 60)
                auth_manager.log_lockout_reject(username=username, remaining_seconds=remaining)
                error = (t.get('login_err_locked') or '').replace('{}', str(minutes))
            elif legacy_required and not auth_manager.verify_legacy_password(
                request.form.get('legacy_password', '')
            ):
                auth_manager.register_failed_attempt(username=username)
                error = t.get('setup_err_legacy_password')
            elif password != confirm:
                error = t.get('setup_err_password_mismatch')
            elif not kavita_ok:
                error = t.get('setup_err_kavita_required')
            else:
                # Config d'abord : si la persistance échoue, aucun compte orphelin.
                ok, root_changed, err = _persist_setup_config(t)
                if not ok:
                    error = err
                else:
                    created, err_key = auth_manager.create_user(username, password)
                    if created:
                        auth_manager.purge_legacy_admin_password()
                        user = auth_manager.verify_credentials(username, password)
                        if user:
                            auth_manager.clear_failed_attempts()
                            auth_manager.login_session(user)
                            auth_manager.record_login(user['id'])
                            if root_changed:
                                session['ui_banner'] = t.get(
                                    'setup_restart_root_path',
                                    'Redémarrez MetaKavita pour appliquer le sous-chemin (ROOT_PATH).',
                                )
                            return redirect(url_for('pages.index'))
                        error = t.get('setup_err_generic')
                    else:
                        error = t.get(err_key, t.get('setup_err_generic'))

    # Recharger t / config après erreur ou pour le GET
    t, config = _t(request.args.get('lang') or request.form.get('UI_LANG'))
    form_values = {}
    if error and request.method == 'POST':
        form_values = _form_values_from_request()
    elif setup_rerun:
        form_values = _form_values_from_config(config)

    resume_step = 1 if setup_rerun else 0
    if error and form_values:
        if error in (
            t.get('setup_err_kavita_required'),
            t.get('setup_err_config_save'),
        ):
            resume_step = 1
        elif not setup_rerun:
            resume_step = 0
    ctx = _setup_context(
        t,
        config,
        error=error,
        legacy_required=legacy_required,
        form_values=form_values,
        setup_rerun=setup_rerun,
    )
    ctx['resume_step'] = resume_step
    return render_template('setup.html', **ctx)


def _kavita_probe_fail_message(t, detail: str) -> str:
    """Message UI pour un code last_auth_error (aligné Config / diagnostics)."""
    err_map = {
        'missing': 'setup_kavita_test_missing',
        'localhost': 'err_kavita_localhost',
        'http_401': 'err_kavita_unauthorized',
        'timeout': 'err_kavita_timeout',
        'dns': 'err_kavita_dns',
        'connection': 'err_kavita_connection',
        'ssl': 'err_kavita_ssl',
    }
    key = err_map.get(detail)
    if key:
        return t.get(key) or t.get('err_kavita', 'Connexion à Kavita échouée.')
    return t.get(
        'setup_kavita_warn_libs',
        'Connexion Kavita échouée — les bibliothèques ne pourront pas être chargées '
        'tant que l’URL ou la clé ne seront pas corrigées (Config).',
    )


def _probe_target_is_link_local(url: str) -> bool:
    """True si l'URL visée est en lien-local ou pointe un service de metadata.

    Volontairement PAS `url_allowlist._is_blocked_host`, qui refuse aussi 10/8,
    172.16/12 et 192.168/16 : Kavita est auto-hébergé, il vit précisément sur ces
    plages, et les interdire ici rendrait le bouton « Tester » inutile pour
    l'installation normale. Le lien-local, lui, n'héberge jamais un Kavita — mais
    c'est là que répond le service de metadata d'un hébergeur cloud
    (169.254.169.254), la cible classique d'une sonde réseau détournée.
    """
    import ipaddress
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or '').lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in ('metadata.google.internal', 'metadata'):
        return True
    try:
        return ipaddress.ip_address(host.strip('[]')).is_link_local
    except ValueError:
        return False


def _kavita_probe_owner_proof_ok() -> bool:
    """Preuve de propriété exigée avant de laisser le serveur émettre un POST.

    Cette route est dans les deux listes blanches des gates : tant que
    `setup_required()` est vrai, elle est joignable sans session. Sur une
    installation neuve c'est nécessaire (le wizard doit pouvoir tester Kavita
    avant qu'un compte existe) et sans conséquence : le premier arrivé peut de
    toute façon revendiquer l'instance par `/setup`, donc la sonde ne lui apprend
    rien qu'il ne puisse obtenir ensuite.

    Le cas gênant est l'instance DÉJÀ EN SERVICE qui vient d'être mise à niveau :
    la table `users` est vide, donc `setup_required()` est vrai, et n'importe qui
    sur le réseau faisait émettre au serveur un POST vers l'URL de son choix en
    lisant le code d'erreur renvoyé (`dns` / `connection` / `timeout` / `ssl` /
    `http_401`), c'est-à-dire un balayage réseau précis depuis l'intérieur. Le
    mainteneur exige déjà l'ancien `ADMIN_PASSWORD` pour `POST /setup` : cette
    route demande la même preuve, et rien de plus.

    ⚠️ `templates/setup.html` n'envoie pas encore `legacy_password` avec le test
    Kavita : sur une instance mise à niveau, le bouton « Tester » affiche donc
    l'avertissement générique jusqu'à ce que ce champ soit joint au POST. Le test
    n'a jamais été bloquant pour terminer le wizard.
    """
    if auth_manager.is_authenticated():
        return True
    if not auth_manager.legacy_proof_required():
        return True

    locked, remaining = auth_manager.is_locked_out()
    if locked:
        auth_manager.log_lockout_reject(remaining_seconds=remaining)
        return False

    candidate = request.form.get('legacy_password', '')
    if auth_manager.verify_legacy_password(candidate):
        return True
    if candidate:
        # Même comptabilité que /setup : sans elle, cette route offrirait une
        # force brute illimitée sur la preuve de propriété.
        auth_manager.register_failed_attempt()
    logging.info(
        "[Setup] Test Kavita refusé : instance déjà en service (ADMIN_PASSWORD "
        "encore présent) et aucune preuve de propriété fournie."
    )
    return False


@auth_bp.route('/setup/test-kavita', methods=['POST'])
def setup_test_kavita():
    """Ping auth Kavita pendant le wizard — n'écrit pas la config."""
    if not auth_manager.setup_required() and not auth_manager.is_authenticated():
        return jsonify(ok=False, error='forbidden'), 403
    if not _kavita_probe_owner_proof_ok():
        return jsonify(ok=False, error='forbidden'), 403

    lang_arg = request.form.get('UI_LANG') or request.args.get('lang')
    t, config = _t(lang_arg)

    url = request.form.get('KAVITA_URL', '').strip().rstrip('/')
    submitted_key = request.form.get('KAVITA_API_KEY', '').strip()
    saved_key = (config.get('KAVITA_API_KEY') or '').strip()
    # Champ vide = clé déjà enregistrée (rerun / Config).
    key = submitted_key or (
        saved_key if auth_manager.is_authenticated() else ''
    )
    if not url or not key:
        return jsonify(
            ok=False,
            error='missing',
            message=t.get('setup_kavita_test_missing', 'URL et clé API requises.'),
        )
    if _probe_target_is_link_local(url):
        # Refus AVANT tout appel réseau : ni sortie vers le service de metadata,
        # ni code d'erreur qui dirait si quelque chose écoute là.
        return jsonify(
            ok=False,
            error='blocked',
            message=_kavita_probe_fail_message(t, 'blocked'),
        )

    try:
        from kavita_api import KavitaAPI

        probe = KavitaAPI(url, key)
        ok = bool(probe.authenticate())
        # Rerun : le navigateur autofill souvent le mot de passe MetaKavita
        # dans le seul champ type=password (clé API). Si la valeur tapée est
        # refusée mais la clé sauvée fonctionne, on la privilégie.
        used_saved_fallback = False
        if (
            not ok
            and submitted_key
            and saved_key
            and submitted_key != saved_key
            and auth_manager.is_authenticated()
            and getattr(probe, 'last_auth_error', None) == 'http_401'
        ):
            probe_saved = KavitaAPI(url, saved_key)
            if probe_saved.authenticate():
                ok = True
                used_saved_fallback = True
        if ok:
            msg = t.get('setup_kavita_test_ok', 'Connexion Kavita réussie.')
            if used_saved_fallback:
                msg = t.get(
                    'setup_kavita_test_ok_saved_key',
                    'Connexion OK avec la clé enregistrée '
                    '(le champ contenait probablement un mot de passe autofill — laissez-le vide).',
                )
            return jsonify(ok=True, message=msg, used_saved_key=used_saved_fallback)
        detail = getattr(probe, 'last_auth_error', None) or 'unknown'
        return jsonify(
            ok=False,
            error=detail,
            message=_kavita_probe_fail_message(t, detail),
        )
    except Exception as exc:
        logging.warning(
            t.get("log_setup_kavita_probe_fail", "[Setup] Test Kavita : %s"),
            exc,
        )
        return jsonify(
            ok=False,
            error='unknown',
            message=_kavita_probe_fail_message(t, 'unknown'),
        )


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    t, config = _t()

    # Aucun compte : l'utilisateur doit passer par le setup, pas par un
    # formulaire de connexion qu'aucun identifiant ne pourrait satisfaire.
    if auth_manager.setup_required():
        return redirect(url_for('auth.setup'))

    if auth_manager.is_authenticated():
        return redirect(url_for('pages.index'))

    error = None
    if request.method == 'POST':
        # Le verrouillage est vérifié AVANT toute vérification d'identifiants :
        # sinon chaque tentative continuerait de coûter un hachage complet, et
        # le verrou cesserait de protéger le CPU du worker unique.
        locked, remaining = auth_manager.is_locked_out()
        username = request.form.get('username', '')
        if locked:
            minutes = max(1, (remaining + 59) // 60)
            auth_manager.log_lockout_reject(username=username, remaining_seconds=remaining)
            error = (t.get('login_err_locked') or '').replace('{}', str(minutes))
        else:
            user = auth_manager.verify_credentials(
                username,
                request.form.get('password', ''),
            )
            if user:
                auth_manager.clear_failed_attempts()
                auth_manager.login_session(user)
                auth_manager.record_login(user['id'])
                return redirect(url_for('pages.index'))

            auth_manager.register_failed_attempt(username=username)
            # Message volontairement identique pour un utilisateur inconnu et un
            # mot de passe erroné : distinguer les deux revient à publier la
            # liste des comptes existants.
            error = t.get('login_error')

    return render_template('login.html', error=error, t=t, config=config)


@auth_bp.route('/account/password', methods=['POST'])
def change_password():
    """Changement de mot de passe depuis la modale Config (session active requise).

    Volontairement minimal : un formulaire à 3 champs et une route, pas un
    flux « mot de passe oublié » par e-mail — l'application est mono-compte et
    auto-hébergée (cf. `auth_manager.MIN_PASSWORD_LENGTH`). Comme le reste des
    routes protégées, l'authentification n'est pas revérifiée ici : elle est
    garantie par `auth_manager.login_gate` en amont.
    """
    t, _config = _t()

    locked, remaining = auth_manager.is_locked_out()
    if locked:
        minutes = max(1, (remaining + 59) // 60)
        auth_manager.log_lockout_reject(
            username=session.get("username"),
            remaining_seconds=remaining,
        )
        msg = (t.get('login_err_locked') or '').replace('{}', str(minutes))
        return jsonify(success=False, error=msg), 429

    data = request.get_json(silent=True) or request.form
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm = data.get('new_password_confirm', '')

    if new_password != confirm:
        return jsonify(success=False, error=t.get('account_err_mismatch')), 400

    ok, err_key = auth_manager.update_password(
        auth_manager.current_user_id(), current_password, new_password
    )
    if not ok:
        # Un mauvais mot de passe actuel compte comme un échec de connexion :
        # sans ça, un onglet resté ouvert deviendrait un oracle de brute-force
        # sans le verrouillage qui protège /login.
        if err_key == "account_err_wrong_current":
            auth_manager.register_failed_attempt(
                username=session.get("username"),
            )
        return jsonify(success=False, error=t.get(err_key, t.get('account_err_generic'))), 400

    auth_manager.clear_failed_attempts()
    return jsonify(success=True, message=t.get('account_pwd_changed'))


@auth_bp.route('/logout')
def logout():
    from flask import current_app

    session.clear()
    session.permanent = False

    response = redirect(url_for('auth.login'))
    cookie_name = current_app.config.get('SESSION_COOKIE_NAME', 'session')
    response.set_cookie(cookie_name, '', expires=0)

    return response
