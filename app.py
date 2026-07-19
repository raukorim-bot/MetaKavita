import threading
import time
import logging
import queue
import io
import os
import secrets
from flask import Flask, request, render_template, Response, jsonify, session, redirect, url_for
from flask_socketio import SocketIO
from flask_socketio import disconnect
from urllib.parse import urlparse
from config_manager import load_config, save_config
from kavita_api import KavitaAPI
from metadata_fetcher import fetch_metadata, translate_text, PROVIDERS_MAP, ALLOWED_PROXY_DOMAINS
from db_manager import init_db, update_status, get_all_cached_data, save_forced_overrides, reset_errors, clean_orphaned_cache
from translations import translations
from datetime import timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = load_config().get('SECRET_KEY', 'kavita-secret-key')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True, # Empêche les scripts JS (XSS) de lire le cookie
    SESSION_COOKIE_SAMESITE='Lax', # Empêche un site externe de forcer une action (CSRF)
    PERMANENT_SESSION_LIFETIME=timedelta(days=30)
)
socketio = SocketIO(app)

init_db()

class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        socketio.emit('log_update', {'data': log_entry})

ws_handler = WebSocketLogHandler()
ws_formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S')
ws_handler.setFormatter(ws_formatter)

# --- On s'assure que le dossier "data" existe pour les logs ---
if not os.path.exists("data"):
    os.makedirs("data")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data/metakavita.log", encoding='utf-8'), # <--- NOUVEAU CHEMIN
        logging.StreamHandler(),
        ws_handler
    ]
)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

@app.before_request
def require_login():
    # On laisse passer les assets statiques, le login et les webhooks internes
    if request.endpoint in ['login', 'static', 'webhook']:
        return
        
    config = load_config()
    admin_pwd = config.get('ADMIN_PASSWORD')
    
    # S'il y a un mot de passe, l'utilisateur doit avoir une session active
    if admin_pwd and not session.get('logged_in'):
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = load_config()
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])

    if not config.get('ADMIN_PASSWORD'):
        return redirect(url_for('index'))
        
    error = None
    if request.method == 'POST':
        
        # DÉBUT DE LA CORRECTION (Timing Attack Fix)
        user_input = request.form.get('password', '')
        real_password = config.get('ADMIN_PASSWORD', '')
        
        # On utilise compare_digest au lieu de "=="
        if secrets.compare_digest(user_input.encode('utf-8'), real_password.encode('utf-8')):
            session.permanent = True  # <--- Active le cookie longue durée
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            time.sleep(2)
            error = t.get('login_error')
        # FIN DE LA CORRECTION
            
    return render_template('login.html', error=error, t=t, config=config)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
    
sync_queue = queue.Queue()

@socketio.on('connect')
def handle_connect():
    config = load_config()
    # Si un mot de passe est requis mais que l'utilisateur n'est pas loggué
    if config.get('ADMIN_PASSWORD') and not session.get('logged_in'):
        logging.warning(f"🚨 [Sécurité] Connexion WebSocket rejetée (Non authentifié) IP: {request.remote_addr}")
        disconnect()

def worker():
    while True:
        item = sync_queue.get()
        if item is None: break
        series_id, series_name, force_update = item
        
        config = load_config()
        t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
        provider = config.get('PROVIDER', 'ANILIST')
        
        remaining = sync_queue.qsize()
        logging.info(t.get('log_worker_start').format(series_name, remaining))
        
        success, msg, used_providers = process_series_logic(series_id, series_name, force_update)
        
        # --- SÉCURITÉ ANTI-BAN DYNAMIQUE ---
        if used_providers:
            delays = {"MANGABAKA": 2.5, "NAUTILJON": 1.5, "ANILIST": 1.0}
            # Si on a dû taper plusieurs API (fusion), on met la sécurité maximale (2.5s)
            delay = 2.5 if len(used_providers) > 1 else delays.get(used_providers[0], 1.5)
            time.sleep(delay)
        else:
            time.sleep(0.02)
            
        sync_queue.task_done()
        
        if sync_queue.empty():
            logging.info(t.get('log_batch_finished'))

threading.Thread(target=worker, daemon=True).start()

# --- NOUVEAU : AUTO-SYNC (POLLING) ---
def auto_sync_worker():
    last_run = 0
    while True:
        config = load_config()
        interval = config.get('AUTO_SYNC_INTERVAL', 0)
        
        if interval > 0:
            current_time = time.time()
            # Si le temps écoulé dépasse l'intervalle configuré (en minutes)
            if current_time - last_run >= (interval * 60):
                last_run = current_time
                t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
                
                try:
                    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
                    if kavita.authenticate():
                        logging.info(t.get('log_auto_sync_start'))
                        all_series = kavita.get_all_series()
                        active_ids = {s['id'] for s in all_series}
                        clean_orphaned_cache(active_ids)
                        cached = get_all_cached_data()
                        
                        to_process = []
                        for s in all_series:
                            s_id = s['id']
                            # On ne traite que les séries inconnues ou explicitement PENDING
                            if s_id not in cached or cached[s_id].get('status') == 'PENDING':
                                to_process.append(s)
                        
                        if to_process:
                            logging.info(t.get('log_auto_sync_found').format(len(to_process)))
                            for s in to_process:
                                sync_queue.put((s['id'], s['name'], False))
                                
                except Exception as e:
                    logging.error(f"❌ [Auto-Sync] Erreur : {e}")
                    
        # On vérifie toutes les 30 secondes s'il faut se lancer
        time.sleep(30)

threading.Thread(target=auto_sync_worker, daemon=True).start()


def process_series_logic(series_id, series_name, force_update=False):
    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    try:
        kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
        
        if not kavita.authenticate():
            logging.error(t.get('log_auth_fail').format(series_name))
            return False, "Erreur Kavita.", []

        metadata = kavita.get_series_metadata(series_id)
        if not metadata:
            logging.error(t.get('log_meta_fail').format(series_name))
            return False, "Erreur de métadonnées.", []

        if metadata.get('summary') and not force_update:
            logging.info(t.get('log_skip').format(series_name))
            update_status(series_id, 'COMPLETED')
            return True, "Déjà à jour.", []

        cache_data = get_all_cached_data().get(int(series_id), {})
        search_query = cache_data.get('forced_id') or cache_data.get('alternative_title') or series_name

        # --- NOUVELLE LOGIQUE DE FALLBACK ET FUSION ---
        p1 = config.get("PROVIDER_1", "MANGABAKA")
        p2 = config.get("PROVIDER_2", "NAUTILJON")
        p3 = config.get("PROVIDER_3", "ANILIST")
        
        # On filtre "NONE" et on dédoublonne tout en gardant l'ordre
        raw_providers = [p for p in [p1, p2, p3] if p != "NONE"]
        providers_list = list(dict.fromkeys(raw_providers))
        
        smart_completion = config.get("SMART_COMPLETION", False)

        logging.info(t.get('log_scraping').format(series_name, " > ".join(providers_list), search_query))
        
        provider_data, used_providers = fetch_metadata(search_query, providers_list, smart_completion)

        if not provider_data:
            logging.warning(t.get('log_not_found').format(series_name, "API(s)"))
            update_status(series_id, 'NOT_FOUND')
            return False, "Introuvable.", used_providers

        # Extraction des infos de provenance pour le log final
        actual_provider = provider_data.pop('_provider_used', 'Inconnu')
        fusion_providers = provider_data.pop('_fusion_providers', [])
        
        msg_found = t.get('log_found').format(series_name) + f" (Base: {actual_provider})"
        if fusion_providers:
            msg_found += f" + 🧩 Fusion ({', '.join(fusion_providers)})"
        logging.info(msg_found)

        # --- MAPPAGE DES DONNÉES ---
        if provider_data.get('summary') and (not metadata.get('summary') or force_update):
            target_lang = config.get('TARGET_LANG', 'FR')
            metadata['summary'] = translate_text(provider_data['summary'], config.get('DEEPL_API_KEY'), target_lang)
            metadata['summaryLocked'] = True

        if provider_data.get('year'): 
            metadata['releaseYear'] = provider_data['year']
            metadata['releaseYearLocked'] = True

        status_map = {"RELEASING": 0, "HIATUS": 1, "FINISHED": 2, "CANCELLED": 3}
        if provider_data.get('status') in status_map:
            metadata['publicationStatus'] = status_map[provider_data['status']]
            metadata['publicationStatusLocked'] = True

        # --- CORRECTIONS KAVITA API (id: 0 et noms exacts) ---
        if provider_data.get('genres'): 
            metadata['genres'] = [{"id": 0, "title": g} for g in provider_data['genres']]
            metadata['genresLocked'] = True
            
        if provider_data.get('tags'): 
            metadata['tags'] = [{"id": 0, "title": t} for t in provider_data['tags'][:15]]
            metadata['tagsLocked'] = True
            
        if provider_data.get('characters'): 
            metadata['characters'] = [{"id": 0, "name": c['node']['name']['full']} for c in provider_data['characters']]
            metadata['charactersLocked'] = True

        if provider_data.get('alternative_titles'):
            metadata['localizedName'] = " / ".join(provider_data['alternative_titles'])
            metadata['localizedNameLocked'] = True

        # 1. Le Staff étendu
        writers, pencillers, colorists, translators, cover_artists = [], [], [], [], []
        for edge in provider_data.get('staff', []):
            role = edge.get('role', '').lower()
            name = edge.get('node', {}).get('name', {}).get('full', '')
            if not name: continue
            
            entry = {"id": 0, "name": name}
            
            if 'story' in role or 'original' in role or 'scénar' in role: writers.append(entry)
            if 'art' in role or 'illustration' in role or 'dessin' in role: pencillers.append(entry)
            if 'color' in role or 'couleur' in role: colorists.append(entry)
            if 'translat' in role or 'traduct' in role: translators.append(entry)
            if 'cover' in role or 'couverture' in role: cover_artists.append(entry)

        if writers: metadata['writers'] = writers; metadata['writersLocked'] = True
        if pencillers: metadata['pencillers'] = pencillers; metadata['pencillersLocked'] = True
        if colorists: metadata['colorists'] = colorists; metadata['coloristsLocked'] = True
        if translators: metadata['translators'] = translators; metadata['translatorsLocked'] = True
        if cover_artists: metadata['coverArtists'] = cover_artists; metadata['coverArtistsLocked'] = True

        # 2. Éditeur
        if provider_data.get('publisher'):
            metadata['publisher'] = provider_data['publisher']
            metadata['publisherLocked'] = True
            
        # 3. Classification d'âge
        if provider_data.get('age_rating'):
            rating_str = str(provider_data['age_rating']).lower()
            if rating_str == 'safe': metadata['ageRating'] = 1
            elif rating_str == 'suggestive': metadata['ageRating'] = 2
            elif rating_str == 'erotica': metadata['ageRating'] = 3
            elif rating_str == 'pornographic': metadata['ageRating'] = 4
            metadata['ageRatingLocked'] = True

        # 4. Sens de lecture (Format) - SEULEMENT SI L'OPTION EST COCHÉE !
        if config.get('AUTO_READING_DIR') and provider_data.get('format'):
            fmt = str(provider_data['format']).upper()
            if 'MANGA' in fmt or 'JP' in fmt:
                metadata['format'] = 2 # Droite à Gauche
            elif 'WEBTOON' in fmt or 'MANHWA' in fmt or 'KR' in fmt:
                metadata['format'] = 3 # Vertical
            elif 'COMIC' in fmt or 'BD' in fmt or 'US' in fmt or 'FR' in fmt:
                metadata['format'] = 1 # Gauche à Droite
            metadata['formatLocked'] = True
            
        # 5. Identifiants Externes (Sauvegarde en base de données Kavita)
        a_id = provider_data.get('anilist_id')
        m_id = provider_data.get('mal_id')
        mb_id = provider_data.get('mangabaka_id')
        
        if a_id or m_id or mb_id:
            id_success, id_msg = kavita.update_series_external_ids(
                series_id=series_id,
                anilist_id=a_id,
                mal_id=m_id,
                mangabaka_id=mb_id
            )
            if not id_success:
                logging.warning(f"[{series_name}] ⚠️ Impossible de sauvegarder les IDs externes : {id_msg}")

        # 6. Liens Web (Génération auto à partir des IDs + Scrapers)
        existing_links = metadata.get('webLinks', '')
        links_list = [link.strip() for link in existing_links.split(',')] if existing_links else []
        
        # Petite fonction interne pour éviter d'ajouter des liens en double
        def add_weblink(url):
            if url and url not in links_list:
                links_list.append(url)

        # On transforme les IDs en vrais liens pour forcer l'affichage des icônes dans Kavita !
        if a_id: 
            add_weblink(f"https://anilist.co/manga/{a_id}")
        if m_id: 
            add_weblink(f"https://myanimelist.net/manga/{m_id}")
        if mb_id:
            add_weblink(f"https://mangabaka.org/{mb_id}")
            
        # On ajoute le lien récupéré directement par les scrapers (ex: Nautiljon)
        if provider_data.get('url'):
            add_weblink(provider_data['url'])
            
        # On recolle le tout avec des virgules et on envoie à Kavita
        if links_list:
            metadata['webLinks'] = ",".join(links_list)
            metadata['webLinksLocked'] = True
        
        metadata['seriesId'] = int(series_id)
        metadata.pop('created', None)
        metadata.pop('lastModified', None)

        logging.info(t.get('log_sending').format(series_name))
        success, msg = kavita.update_series_metadata(metadata)
        
        if success:
            logging.info(t.get('log_success').format(series_name))
            
            # --- GESTION DE LA COUVERTURE AUTOMATIQUE ---
            if config.get('AUTO_COVER') and provider_data.get('cover_url'):
                logging.info(t.get('log_cover_upload').format(series_name))
                cover_success, cover_msg = kavita.upload_series_cover(series_id, provider_data['cover_url'])
                if not cover_success:
                    logging.warning(t.get('log_cover_fail').format(series_name, cover_msg))
                else:
                    logging.info(t.get('log_cover_success').format(series_name))
            # ------------------------------------------------------
            
            update_status(series_id, 'COMPLETED')
            return True, "Succès", used_providers
        else:
            logging.error(t.get('log_kavita_refused').format(series_name, msg))
            return False, f"Erreur: {msg}", used_providers

    except Exception as e:
        logging.error(t.get('log_crash').format(series_name, e))
        return False, "Erreur interne.", []

def prepare_index_data(config, msg="", error_msg="", selected_lib=None):
    series_list = []
    libraries = []
    
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    
    # 1. Vérification des identifiants
    if config.get('KAVITA_API_KEY') and config.get('KAVITA_URL'):
        kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
        
        # 2. On intercepte explicitement l'authentification
        if kavita.authenticate():
            libraries = kavita.get_libraries()
            if libraries:
                series_list = kavita.get_all_series(library_id=selected_lib)
                
                # Nettoyage auto du cache
                if not selected_lib:
                    active_ids = {s['id'] for s in series_list}
                    cleaned = clean_orphaned_cache(active_ids)
                    if cleaned > 0:
                        logging.info(f"🧹 Nettoyage : {cleaned} séries orphelines retirées du cache.")
            else:
                error_msg = "Aucune bibliothèque trouvée dans Kavita."
        else:
            # 3. L'authentification a échoué (ex: Clé API fausse ou révoquée)
            error_msg = t.get('err_kavita', "Connexion à Kavita échouée.")
    else:
        # Les champs sont vides
        error_msg = t.get('err_missing', "Données manquantes.")

    cached_info = get_all_cached_data()
    
    stats = {
        'total': len(cached_info),
        'completed': sum(1 for v in cached_info.values() if v.get('status') == 'COMPLETED'),
        'pending': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING'),
        'not_found': sum(1 for v in cached_info.values() if v.get('status') == 'NOT_FOUND'),
        'ignored': sum(1 for v in cached_info.values() if v.get('status') == 'IGNORED')
    }

    if libraries:
        for s in series_list:
            item_cache = cached_info.get(s['id'], {'status': 'PENDING', 'forced_id': '', 'alternative_title': ''})
            s['status'] = item_cache.get('status', 'PENDING')
            s['forced_id'] = item_cache.get('forced_id') or ''
            s['alternative_title'] = item_cache.get('alternative_title') or ''
            
    safe_config = config.copy()
    if safe_config.get('KAVITA_API_KEY'): safe_config['KAVITA_API_KEY'] = '********'
    if safe_config.get('DEEPL_API_KEY'): safe_config['DEEPL_API_KEY'] = '********'
            
    return render_template('index.html', config=safe_config, msg=msg, error_msg=error_msg, 
                           series_list=series_list, libraries=libraries, selected_lib=selected_lib, 
                           t=t, stats=stats, available_providers=list(PROVIDERS_MAP.keys()))
                           
@app.route('/', methods=['GET'])
def index():
    config = load_config()
    selected_lib = request.args.get('library_id') 
    return prepare_index_data(config, msg="", error_msg="", selected_lib=selected_lib)

@app.route('/save-config', methods=['POST'])
def save_config_ajax():
    config = load_config()
    
    config['KAVITA_URL'] = request.form.get('KAVITA_URL', '').strip().rstrip('/')
    
    # --- NOUVEAU : On enregistre seulement si on n'a pas renvoyé les étoiles ---
    kavita_key = request.form.get('KAVITA_API_KEY', '').strip()
    if kavita_key and kavita_key != '********':
        config['KAVITA_API_KEY'] = kavita_key
        
    deepl_key = request.form.get('DEEPL_API_KEY', '').strip()
    if deepl_key and deepl_key != '********':
        config['DEEPL_API_KEY'] = deepl_key
        
    config['TARGET_LANG'] = request.form.get('TARGET_LANG', 'FR').strip()
    config['UI_LANG'] = request.form.get('UI_LANG', 'fr').strip()
    config['PROVIDER_1'] = request.form.get('PROVIDER_1', 'MANGABAKA').strip()
    config['PROVIDER_2'] = request.form.get('PROVIDER_2', 'NAUTILJON').strip()
    config['PROVIDER_3'] = request.form.get('PROVIDER_3', 'ANILIST').strip()
    config['SMART_COMPLETION'] = request.form.get('SMART_COMPLETION') == 'true'
    
    try:
        config['AUTO_SYNC_INTERVAL'] = int(request.form.get('AUTO_SYNC_INTERVAL', 0))
    except ValueError:
        config['AUTO_SYNC_INTERVAL'] = 0
        
    config['AUTO_COVER'] = request.form.get('AUTO_COVER') == 'true'
    config['AUTO_READING_DIR'] = request.form.get('AUTO_READING_DIR') == 'true'
    
    save_config(config)
    return jsonify(success=True)

@app.route('/save-override', methods=['POST'])
def save_override():
    series_id = request.form.get('series_id')
    forced_id = request.form.get('forced_id', '').strip()
    alt_title = request.form.get('alternative_title', '').strip()
    save_forced_overrides(int(series_id), forced_id, alt_title)
    return "OK", 200

@app.route('/reset-errors', methods=['POST'])
def amnistie():
    reset_errors()
    return jsonify(success=True)

@app.route('/force-sync', methods=['POST'])
def force_sync():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    series_id = request.form.get('series_id')
    series_name = request.form.get('series_name')
    if not series_id or not series_name: return jsonify(success=False, msg=t.get('err_missing'))
    
    success, result_msg, _ = process_series_logic(series_id, series_name, force_update=True)
    return jsonify(success=success, msg=result_msg)

@app.route('/batch-sync', methods=['POST'])
def batch_sync():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    library_id = request.form.get('library_id')
    force_update = request.form.get('force_update') == 'true'
    selected_ids = request.form.getlist('selected_series')
    
    if not selected_ids:
        return jsonify(success=False, msg=t.get('err_no_sel'))
        
    config = load_config()
    all_series = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY')).get_all_series(library_id=library_id)
    
    cached = get_all_cached_data()
    series_to_process = [
        s for s in all_series 
        if str(s['id']) in selected_ids 
        and cached.get(s['id'], {}).get('status') != 'IGNORED'
    ]
    
    current_size = sync_queue.qsize()
    total_after_add = current_size + len(series_to_process)
    logging.info(t.get('log_batch_added').format(len(series_to_process), total_after_add))
    
    for s in series_to_process:
        sync_queue.put((s['id'], s['name'], force_update))
        
    msg_added = t.get('batch_added').replace('{}', str(len(series_to_process)))
    return jsonify(success=True, msg=msg_added)

@app.route('/stop-batch', methods=['POST'])
def stop_batch():
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    while not sync_queue.empty():
        try:
            sync_queue.get_nowait()
            sync_queue.task_done()
        except queue.Empty:
            break
    logging.info(t.get('log_batch_stopped'))
    return jsonify(success=True, msg=t.get('batch_stopped'))

@app.route('/export-errors', methods=['GET'])
def export_errors():
    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])
    all_series = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY')).get_all_series()
    cached = get_all_cached_data()
    
    error_lines = [f"{t.get('report_title')}\n", "="*50, "\n\n"]
    for s in all_series:
        if cached.get(s['id'], {}).get('status') == 'NOT_FOUND':
            error_lines.append(f"- {s['name']} ({t.get('report_item')} {s['id']})\n")
            
    return Response("".join(error_lines), mimetype="text/plain", headers={"Content-disposition": "attachment; filename=metakavita_erreurs.txt"})

@app.route('/webhook', methods=['POST'])
def webhook():
    config = load_config()
    token = request.args.get('token')
    
    # --- SÉCURITÉ ANTI-SPAM INFAILLIBLE ---
    if not token or not secrets.compare_digest(token, config.get('WEBHOOK_TOKEN', '')):
        logging.warning("🚨 [Sécurité] Tentative d'accès au webhook bloquée (Jeton invalide).")
        return "Unauthorized", 401
    # --------------------------------------

    payload = request.json
    series_id = payload.get("seriesId") or payload.get("SeriesId")
    series_name = payload.get("name") or payload.get("Name")
    if series_id and series_name: sync_queue.put((series_id, series_name, False))
    return "Event reçu", 200

@app.route('/stats')
def stats():
    config = load_config()
    cached_data = get_all_cached_data()
    total = len(cached_data)
    completed = sum(1 for v in cached_data.values() if v.get('status') == 'COMPLETED')
    pending = sum(1 for v in cached_data.values() if v.get('status') == 'PENDING')
    not_found = sum(1 for v in cached_data.values() if v.get('status') == 'NOT_FOUND')
    ignored = sum(1 for v in cached_data.values() if v.get('status') == 'IGNORED') # <-- AJOUTE CETTE LIGNE

    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    
    # N'oublie pas d'ajouter ignored=ignored à la fin du return :
    return render_template('stats.html', config=config, t=t, 
                           total=total, completed=completed, 
                           pending=pending, not_found=not_found, ignored=ignored)
                           
@app.route('/toggle-ignore', methods=['POST'])
def toggle_ignore():
    series_id = request.form.get('series_id')
    current_status = request.form.get('current_status')
    if not series_id: return jsonify(success=False)
        
    new_status = 'IGNORED' if current_status != 'IGNORED' else 'PENDING'
    update_status(int(series_id), new_status)
    return jsonify(success=True, new_status=new_status)

# --- PROXY POUR CONTOURNER L'ANTI-HOTLINK DE NAUTILJON ---
@app.route('/api/proxy-image')
def proxy_image():
    img_url = request.args.get('url')
    if not img_url: return "Missing URL", 400
    
    config = load_config()
    t = translations.get(config.get('UI_LANG', 'fr'), translations['fr'])

    # --- SÉCURITÉ ANTI-SSRF (Whitelisting Renforcé) ---
    try:
        parsed = urlparse(img_url)
        # .split(':')[0] pour ignorer les ports (ex: nautiljon.com:443)
        domain = parsed.netloc.lower().split(':')[0]
        
        # CORRECTION ICI : La parenthèse ferme TOUT à la fin
        is_safe = any(domain == d or domain.endswith('.' + d) for d in ALLOWED_PROXY_DOMAINS)
        
        if not is_safe:
            logging.warning(t.get('log_proxy_ssrf').format(domain))
            return "Domain not allowed", 403
    except Exception:
        return "Invalid URL", 400

    try:
        from curl_cffi import requests as cffi_requests
        from flask import send_file
        import io
        
        headers = {
            "Referer": "https://www.nautiljon.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = cffi_requests.get(img_url, headers=headers, impersonate="safari15_5", timeout=10)
        
        if res.status_code == 200:
            return send_file(io.BytesIO(res.content), mimetype='image/jpeg')
        else:
            print(f"[Proxy] Erreur téléchargement (Code {res.status_code}) : {img_url}")
            
    except Exception as e:
        print(f"[Proxy] Crash interne : {e}")
        
    return "Error", 500

# --- RECHERCHE MULTIPLE DE COUVERTURES (JUSQU'À 8 RÉSULTATS) ---
@app.route('/api/series/<int:series_id>/covers', methods=['GET'])
def get_series_covers(series_id):
    series_name = request.args.get('series_name')
    cache_data = get_all_cached_data().get(series_id, {})
    search_query = cache_data.get('forced_id') or cache_data.get('alternative_title') or series_name

    covers = []
    
    from scrapers import clean_title
    clean_sq = clean_title(search_query)

    # 1. Fouille sur AniList (Les 4 meilleurs résultats)
    try:
        import requests
        query = '''
        query ($search: String) {
          Page(page: 1, perPage: 4) {
            media(search: $search, type: MANGA) {
              title { romaji }
              coverImage { extraLarge }
            }
          }
        }
        '''
        res = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': {'search': clean_sq}}, timeout=10)
        if res.status_code == 200:
            results = res.json().get('data', {}).get('Page', {}).get('media', [])
            for m in results:
                if m.get('coverImage', {}).get('extraLarge'):
                    covers.append({
                        "provider": "AniList", 
                        "title": m.get('title', {}).get('romaji', 'Inconnu'),
                        "url": m['coverImage']['extraLarge']
                    })
    except Exception as e:
        logging.error(f"[Covers] Erreur AniList : {e}")

    # 2. Fouille sur Nautiljon (Les 4 meilleurs résultats de la page de recherche)
    try:
        from curl_cffi import requests as cffi_requests
        from bs4 import BeautifulSoup
        import re
        
        session = cffi_requests.Session(impersonate="safari15_5")
        session.headers.update({"Referer": "https://www.nautiljon.com/", "DNT": "1"})
        
        res_init = session.get("https://www.nautiljon.com/mangas/", timeout=10)
        soup_init = BeautifulSoup(res_init.text, 'html.parser')
        st_input = soup_init.find('input', {'name': 'st'})
        
        if st_input and st_input.get('value'):
            st = st_input['value']
            res_search = session.get("https://www.nautiljon.com/mangas/", params={"q": clean_sq, "st": st}, timeout=10)
            soup_search = BeautifulSoup(res_search.text, 'html.parser')
            
            # On prend les 4 premières lignes du tableau de recherche
            for tr in soup_search.select('table.search tr')[1:5]:
                a_tag = tr.find('a', href=re.compile(r'^/mangas/.*\.html$'))
                img_tag = tr.find('img')
                if a_tag and img_tag and img_tag.has_attr('src'):
                    thumb_url = img_tag['src']
                    if thumb_url.startswith('/'): thumb_url = "https://www.nautiljon.com" + thumb_url
                    
                    # On convertit l'URL de la miniature en URL HD
                    full_url = thumb_url.replace('/miniatures/', '/')
                    title = a_tag.text.strip()
                    
                    covers.append({
                        "provider": "Nautiljon",
                        "title": title,
                        "url": full_url
                    })
    except Exception as e:
        logging.error(f"[Covers] Erreur Nautiljon : {e}")
 # 3. Fouille sur MangaBaka (API V2 Finale)
    try:
        import requests
        res = requests.get("https://api.mangabaka.org/v2/series/search", params={"q": clean_sq}, timeout=10)
        
        if res.status_code == 200:
            json_res = res.json()
            results = json_res.get('data') if 'data' in json_res else json_res
            
            if isinstance(results, list):
                for m in results[:4]:  # On prend les 4 premiers résultats
                    cover_data = m.get('cover', {})
                    cover_url = None
                    if isinstance(cover_data, dict):
                        cover_url = cover_data.get('raw') or cover_data.get('original')
                    elif isinstance(cover_data, str):
                        cover_url = cover_data
                        
                    if cover_url:
                        # Recherche du titre dans la liste de dictionnaires
                        title = "Inconnu"
                        titles_list = m.get('titles', [])
                        if titles_list and isinstance(titles_list, list) and isinstance(titles_list[0], dict):
                            title = titles_list[0].get('title', 'Inconnu')
                            
                        covers.append({
                            "provider": "MangaBaka",
                            "title": title,
                            "url": cover_url
                        })
    except Exception as e:
        logging.error(f"[Covers] Erreur MangaBaka V2 : {e}")

    return jsonify({"success": True, "covers": covers})

@app.route('/api/series/<int:series_id>/update-cover', methods=['POST'])
def apply_series_cover(series_id):
    cover_url = request.json.get('cover_url')
    config = load_config()
    kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
    
    success, msg = kavita.upload_series_cover(series_id, cover_url)
    return jsonify({"success": success, "msg": msg})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5010, allow_unsafe_werkzeug=True, debug=False)
