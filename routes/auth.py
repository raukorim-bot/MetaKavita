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

from flask import Blueprint, request, render_template, session, redirect, url_for, jsonify

import auth_manager
from config_manager import load_config
from translations import translations

auth_bp = Blueprint('auth', __name__)


def _t():
    """(dictionnaire de traduction, config) pour la langue configurée."""
    config = load_config()
    return translations.get(config.get('UI_LANG', 'fr'), translations['fr']), config


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Création du compte au premier démarrage.

    Accessible UNIQUEMENT tant qu'aucun compte n'existe. Sans ce garde-fou,
    l'écran resterait un moyen non authentifié de créer un second compte — donc
    un contournement complet de l'authentification.

    Sur une instance qui tournait avec l'ancien `ADMIN_PASSWORD`, cet écran exige
    en plus ce mot de passe comme preuve de propriété : voir
    `auth_manager.legacy_proof_required`.
    """
    t, config = _t()

    if not auth_manager.setup_required():
        return redirect(url_for('auth.login'))

    legacy_required = auth_manager.legacy_proof_required()

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        confirm = request.form.get('password_confirm', '')

        # Le verrouillage est consulté d'abord et vaut aussi pour cet écran :
        # depuis qu'il vérifie un secret, il est devenu une cible de force brute
        # au même titre que /login.
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
        else:
            ok, err_key = auth_manager.create_user(username, password)
            if ok:
                # L'ancien mot de passe en clair n'est jamais repris : il est
                # supprimé maintenant qu'un vrai compte existe (choix du
                # mainteneur — réinitialisation forcée, cf. issue #15).
                auth_manager.purge_legacy_admin_password()

                user = auth_manager.verify_credentials(username, password)
                if user:
                    # Le compte est créé : plus rien ne justifie de garder le
                    # propriétaire à distance du verrou déclenché par une rafale.
                    auth_manager.clear_failed_attempts()
                    auth_manager.login_session(user)
                    auth_manager.record_login(user['id'])
                    return redirect(url_for('pages.index'))
                error = t.get('setup_err_generic')
            else:
                error = t.get(err_key, t.get('setup_err_generic'))

    return render_template(
        'setup.html',
        error=error,
        t=t,
        config=config,
        min_password_length=auth_manager.MIN_PASSWORD_LENGTH,
        legacy_required=legacy_required,
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
