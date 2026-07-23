# Dans config_manager.py

import json
import os
import secrets

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

def load_config():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    config = {
        "TRANSLATION_PROVIDER": "GOOGLE", 
        "KAVITA_URL": "", 
        "KAVITA_API_KEY": "", 
        "DEEPL_API_KEY": "", 
        "AZURE_API_KEY": "", 
        "AZURE_REGION": "", 
        "TARGET_LANG": "FR", 
        "UI_LANG": "fr", 
        "PROVIDER_1": "MANGABAKA", 
        "PROVIDER_2": "KITSU", 
        "PROVIDER_3": "ANILIST",
        "SMART_COMPLETION": False,
        "AUTO_SYNC_INTERVAL": 0, 
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
        "ADMIN_PASSWORD": "", 
        "SECRET_KEY": "",
        "WEBHOOK_TOKEN": ""
    }
    
    file_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                config.update(file_config) # 👈 Charge magiquement TOUTES les clés API des scrapers
        except json.JSONDecodeError:
            pass
            
    needs_save = False
    if not config.get("SECRET_KEY"):
        config["SECRET_KEY"] = secrets.token_hex(24)
        needs_save = True
    if not config.get("WEBHOOK_TOKEN"):
        config["WEBHOOK_TOKEN"] = secrets.token_urlsafe(16)
        needs_save = True
        
    if needs_save:
        save_config(config)

    config["ADMIN_PASSWORD"] = file_config.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", config.get("ADMIN_PASSWORD", "")))

    # On a retiré les clés des scrapers d'ici !
    for key in [
        "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_API_KEY", "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION", 
        "TARGET_LANG", "UI_LANG", "PROVIDER_1", "PROVIDER_2", "PROVIDER_3"
    ]:
        config[key] = file_config.get(key, os.getenv(key, config.get(key, "")))
            
    # 👈 NOUVEAU : Récupération dynamique depuis Docker / OS des clés API (ex: HARDCOVER_API_KEY)
    for env_key, env_val in os.environ.items():
        if env_key.endswith("_API_KEY") and env_key not in config:
            config[env_key] = env_val

    if "AUTO_SYNC_INTERVAL" in file_config:
        config["AUTO_SYNC_INTERVAL"] = file_config["AUTO_SYNC_INTERVAL"]
    else:
        try:
            config["AUTO_SYNC_INTERVAL"] = int(os.getenv("AUTO_SYNC_INTERVAL", config.get("AUTO_SYNC_INTERVAL", 0)))
        except ValueError:
            config["AUTO_SYNC_INTERVAL"] = 0
            
    for bool_key in ["AUTO_COVER", "AUTO_READING_DIR", "SMART_COMPLETION"]:
        config[bool_key] = file_config.get(bool_key, str(os.getenv(bool_key, config.get(bool_key, "False"))).lower() == "true")
            
    return config

def save_config(data):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)