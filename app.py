from flask import Flask, request, render_template, Response, jsonify
from flask_socketio import SocketIO
import threading
import time
import logging
import queue
from config_manager import load_config, save_config
from kavita_api import KavitaAPI
from metadata_fetcher import fetch_metadata, translate_text
from db_manager import init_db, update_status, get_all_cached_data, save_forced_overrides, reset_errors
from translations import translations

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kavita-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

init_db()

class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        socketio.emit('log_update', {'data': log_entry})

ws_handler = WebSocketLogHandler()
ws_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("metakavita.log", encoding='utf-8'),
        logging.StreamHandler(),
        ws_handler
    ]
)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

sync_queue = queue.Queue()

def worker():
    while True:
        item = sync_queue.get()
        if item is None: break
        series_id, series_name, force_update = item
        
        # On réintègre le log qui indique combien il reste d'éléments dans la file
        remaining = sync_queue.qsize()
        logging.info(f"⏳ [{series_name}] Traitement lancé. Encore {remaining} série(s) dans la file d'attente.")
        
        success, msg, api_called = process_series_logic(series_id, series_name, force_update)
        if api_called:
            time.sleep(1.5)
        else:
            time.sleep(0.02)
        sync_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

def process_series_logic(series_id, series_name, force_update=False):
    logging.info(f"▶️ [{series_name}] Démarrage de l'analyse...")
    try:
        config = load_config()
        kavita = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY'))
        
        if not kavita.authenticate():
            logging.error(f"[{series_name}] ❌ Échec d'authentification à Kavita.")
            return False, "Erreur Kavita.", False

        metadata = kavita.get_series_metadata(series_id)
        if not metadata:
            logging.error(f"[{series_name}] ❌ Impossible de lire les métadonnées Kavita de cette série.")
            return False, "Erreur de métadonnées.", False

        if metadata.get('summary') and not force_update:
            logging.info(f"[{series_name}] ⏭️ Série déjà à jour, elle est ignorée.")
            update_status(series_id, 'COMPLETED')
            return True, "Déjà à jour.", False

        cache_data = get_all_cached_data().get(int(series_id), {})
        search_query = cache_data.get('forced_id') or cache_data.get('alternative_title') or series_name

        provider = config.get("PROVIDER", "ANILIST")
        logging.info(f"[{series_name}] 🔍 Scraping sur {provider} avec la requête : '{search_query}'")
        
        provider_data = fetch_metadata(search_query, provider)
        api_called = True 

        if not provider_data:
            logging.warning(f"[{series_name}] ⚠️ Aucun résultat trouvé sur {provider}.")
            update_status(series_id, 'NOT_FOUND')
            return False, "Introuvable.", api_called

        logging.info(f"[{series_name}] 📝 Données trouvées ! Formatage en cours...")

        if provider_data.get('summary') and (not metadata.get('summary') or force_update):
            target_lang = config.get('TARGET_LANG', 'FR')
            metadata['summary'] = translate_text(provider_data['summary'], config.get('DEEPL_API_KEY'), target_lang)
            metadata['summaryLocked'] = True

        if provider_data.get('year'): metadata['releaseYear'] = provider_data['year']; metadata['releaseYearLocked'] = True

        status_map = {"RELEASING": 0, "HIATUS": 1, "FINISHED": 2, "CANCELLED": 3}
        if provider_data.get('status') in status_map:
            metadata['publicationStatus'] = status_map[provider_data['status']]
            metadata['publicationStatusLocked'] = True

        if provider_data.get('genres'): metadata['genres'] = [{"title": g} for g in provider_data['genres']]; metadata['genresLocked'] = True
        if provider_data.get('tags'): metadata['tags'] = [{"title": t} for t in provider_data['tags'][:15]]; metadata['tagsLocked'] = True
        if provider_data.get('characters'): metadata['characters'] = [{"name": c['node']['name']['full']} for c in provider_data['characters']]; metadata['characterLocked'] = True

        if provider_data.get('alternative_titles'):
            metadata['localizedName'] = " / ".join(provider_data['alternative_titles'])
            metadata['localizedNameLocked'] = True

        writers, pencillers = [], []
        for edge in provider_data.get('staff', []):
            role = edge.get('role', '').lower()
            if 'story' in role or 'original' in role: writers.append({"name": edge['node']['name']['full']})
            if 'art' in role or 'illustration' in role: pencillers.append({"name": edge['node']['name']['full']})

        if writers: metadata['writers'] = writers; metadata['writerLocked'] = True
        if pencillers: metadata['pencillers'] = pencillers; metadata['pencillerLocked'] = True

        metadata['seriesId'] = int(series_id)
        metadata.pop('created', None); metadata.pop('lastModified', None)

        logging.info(f"[{series_name}] ⬆️ Envoi des données formatées à Kavita...")
        success, msg = kavita.update_series_metadata(metadata)
        if success:
            logging.info(f"[{series_name}] ✅ Enrichissement réussi avec succès !")
            update_status(series_id, 'COMPLETED')
            return True, "Succès", api_called
        else:
            logging.error(f"[{series_name}] ❌ Kavita a refusé la mise à jour : {msg}")
            return False, f"Erreur: {msg}", api_called

    except Exception as e:
        logging.error(f"[{series_name}] 💥 Crash inattendu durant le processus : {e}")
        return False, "Erreur interne.", False

def prepare_index_data(config, msg="", error_msg="", selected_lib=None):
    series_list = []
    libraries = []
    cached_info = get_all_cached_data()
    
    stats = {
        'total': len(cached_info),
        'completed': sum(1 for v in cached_info.values() if v.get('status') == 'COMPLETED'),
        'pending': sum(1 for v in cached_info.values() if v.get('status') == 'PENDING'),
        'not_found': sum(1 for v in cached_info.values() if v.get('status') == 'NOT_FOUND')
    }

    if config.get('KAVITA_API_KEY') and config.get('KAVITA_URL'):
        kavita = KavitaAPI(config['KAVITA_URL'], config['KAVITA_API_KEY'])
        libraries = kavita.get_libraries()
        if libraries:
            series_list = kavita.get_all_series(library_id=selected_lib)
            for s in series_list:
                item_cache = cached_info.get(s['id'], {'status': 'PENDING', 'forced_id': '', 'alternative_title': ''})
                s['status'] = item_cache.get('status', 'PENDING')
                s['forced_id'] = item_cache.get('forced_id') or ''
                s['alternative_title'] = item_cache.get('alternative_title') or ''
        else:
            error_msg = "Connexion à Kavita échouée."
            
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    
    return render_template('index.html', config=config, msg=msg, error_msg=error_msg, 
                           series_list=series_list, libraries=libraries, selected_lib=selected_lib, t=t, stats=stats)

@app.route('/', methods=['GET', 'POST'])
def index():
    config = load_config()
    msg = ""
    if request.method == 'POST':
        config['KAVITA_URL'] = request.form.get('KAVITA_URL', '').strip().rstrip('/')
        config['KAVITA_API_KEY'] = request.form.get('KAVITA_API_KEY', '').strip()
        config['DEEPL_API_KEY'] = request.form.get('DEEPL_API_KEY', '').strip()
        config['TARGET_LANG'] = request.form.get('TARGET_LANG', 'FR').strip()
        config['UI_LANG'] = request.form.get('UI_LANG', 'fr').strip()
        config['PROVIDER'] = request.form.get('PROVIDER', 'ANILIST').strip()
        save_config(config)
        t = translations.get(config['UI_LANG'], translations['fr'])
        msg = t.get('save_settings', 'Sauvegardé')
    selected_lib = request.args.get('library_id') 
    return prepare_index_data(config, msg=msg, selected_lib=selected_lib)

@app.route('/save-override', methods=['POST'])
def save_override():
    series_id = request.form.get('series_id')
    forced_id = request.form.get('forced_id', '').strip()
    alt_title = request.form.get('alternative_title', '').strip()
    save_forced_overrides(int(series_id), forced_id, alt_title)
    return "OK", 200

@app.route('/reset-errors', methods=['POST'])
def amnistie():
    library_id = request.form.get('library_id')
    reset_errors()
    return prepare_index_data(load_config(), msg="Erreurs réinitialisées", selected_lib=library_id)

@app.route('/force-sync', methods=['POST'])
def force_sync():
    series_id = request.form.get('series_id')
    series_name = request.form.get('series_name')
    if not series_id or not series_name: return jsonify(success=False, msg="Données manquantes")
    
    success, result_msg, _ = process_series_logic(series_id, series_name, force_update=True)
    return jsonify(success=success, msg=result_msg)

@app.route('/batch-sync', methods=['POST'])
def batch_sync():
    library_id = request.form.get('library_id')
    force_update = request.form.get('force_update') == 'true'
    selected_ids = request.form.getlist('selected_series')
    
    if not selected_ids:
        return jsonify(success=False, msg="Aucune série sélectionnée.")
        
    config = load_config()
    all_series = KavitaAPI(config.get('KAVITA_URL'), config.get('KAVITA_API_KEY')).get_all_series(library_id=library_id)
    series_to_process = [s for s in all_series if str(s['id']) in selected_ids]
    
    for s in series_to_process:
        sync_queue.put((s['id'], s['name'], force_update))
        
    return jsonify(success=True, msg=f"{len(series_to_process)} ajoutées !")

@app.route('/stop-batch', methods=['POST'])
def stop_batch():
    with sync_queue.mutex:
        sync_queue.queue.clear()
    logging.info("🛑 Le traitement par lots a été interrompu par l'utilisateur.")
    t = translations.get(load_config().get('UI_LANG', 'fr'), translations['fr'])
    return jsonify(success=True, msg=t.get('batch_stopped'))

@app.route('/export-errors', methods=['GET'])
def export_errors():
    all_series = KavitaAPI(load_config().get('KAVITA_URL'), load_config().get('KAVITA_API_KEY')).get_all_series()
    cached = get_all_cached_data()
    error_lines = ["Rapport des erreurs\n", "="*50, "\n\n"]
    for s in all_series:
        if cached.get(s['id'], {}).get('status') == 'NOT_FOUND':
            error_lines.append(f"- {s['name']} (ID Kavita: {s['id']})\n")
    return Response("".join(error_lines), mimetype="text/plain", headers={"Content-disposition": "attachment; filename=metakavita_erreurs.txt"})

@app.route('/webhook', methods=['POST'])
def webhook():
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
    ui_lang = config.get('UI_LANG', 'fr')
    t = translations.get(ui_lang, translations['fr'])
    return render_template('stats.html', config=config, t=t, 
                           total=total, completed=completed, 
                           pending=pending, not_found=not_found)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5010, allow_unsafe_werkzeug=True, debug=False)
