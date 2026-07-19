import json
import os
import secrets

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

def load_config():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    config = {
        "KAVITA_URL": "", 
        "KAVITA_API_KEY": "", 
        "DEEPL_API_KEY": "", 
        "TARGET_LANG": "FR", 
        "UI_LANG": "fr", 
        "PROVIDER_1": "MANGABAKA", 
        "PROVIDER_2": "NAUTILJON", 
        "PROVIDER_3": "ANILIST", 
        "SMART_COMPLETION": False,
        "AUTO_SYNC_INTERVAL": 0, 
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
        "ADMIN_PASSWORD": "", 
        "SECRET_KEY": secrets.token_hex(24),
        "WEBHOOK_TOKEN": secrets.token_urlsafe(16)
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except json.JSONDecodeError:
            pass
            
    # Si la config chargée n'a pas de clés secrètes, on les génère et on sauvegarde
    needs_save = False
    if not config.get("SECRET_KEY"):
        config["SECRET_KEY"] = secrets.token_hex(24)
        needs_save = True
    if not config.get("WEBHOOK_TOKEN"):
        config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)
        needs_save = True
        
    if needs_save:
        save_config(config)

    config["KAVITA_URL"] = os.getenv("KAVITA_URL", config.get("KAVITA_URL", ""))
    config["KAVITA_API_KEY"] = os.getenv("KAVITA_API_KEY", config.get("KAVITA_API_KEY", ""))
    config["DEEPL_API_KEY"] = os.getenv("DEEPL_API_KEY", config.get("DEEPL_API_KEY", ""))
    config["TARGET_LANG"] = os.getenv("TARGET_LANG", config.get("TARGET_LANG", "FR"))
    config["UI_LANG"] = os.getenv("UI_LANG", config.get("UI_LANG", "fr"))
    
    config["PROVIDER_1"] = os.getenv("PROVIDER_1", config.get("PROVIDER_1", "MANGABAKA"))
    config["PROVIDER_2"] = os.getenv("PROVIDER_2", config.get("PROVIDER_2", "NAUTILJON"))
    config["PROVIDER_3"] = os.getenv("PROVIDER_3", config.get("PROVIDER_3", "ANILIST"))
    
    try:
        config["AUTO_SYNC_INTERVAL"] = int(os.getenv("AUTO_SYNC_INTERVAL", config.get("AUTO_SYNC_INTERVAL", 0)))
    except ValueError:
        config["AUTO_SYNC_INTERVAL"] = 0
        
    config["AUTO_COVER"] = str(os.getenv("AUTO_COVER", config.get("AUTO_COVER", "False"))).lower() == "true"
    config["AUTO_READING_DIR"] = str(os.getenv("AUTO_READING_DIR", config.get("AUTO_READING_DIR", "False"))).lower() == "true"
    config["SMART_COMPLETION"] = str(os.getenv("SMART_COMPLETION", config.get("SMART_COMPLETION", "False"))).lower() == "true"
    
    config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", config.get("ADMIN_PASSWORD", ""))
    
    return config

def save_config(data):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)