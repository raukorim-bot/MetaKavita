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
        "COMICVINE_API_KEY": "",
        "GOOGLEBOOKS_API_KEY": "",
        "SMART_COMPLETION": False,
        "AUTO_SYNC_INTERVAL": 0, 
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
        "ADMIN_PASSWORD": "", 
        "SECRET_KEY": "",     # 👈 Initialisé à vide pour forcer la détection
        "WEBHOOK_TOKEN": ""   # 👈 Initialisé à vide pour forcer la détection
    }
    
    file_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                config.update(file_config)
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

    if "ADMIN_PASSWORD" in file_config:
        config["ADMIN_PASSWORD"] = file_config["ADMIN_PASSWORD"]
    else:
        config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", config.get("ADMIN_PASSWORD", ""))

    for key in [
        "TRANSLATION_PROVIDER", "KAVITA_URL", "KAVITA_API_KEY", "DEEPL_API_KEY", "AZURE_API_KEY", "AZURE_REGION", 
        "TARGET_LANG", "UI_LANG", "PROVIDER_1", "PROVIDER_2", "PROVIDER_3", "COMICVINE_API_KEY",
        "GOOGLEBOOKS_API_KEY"
    ]:
        if key in file_config:
            config[key] = file_config[key]
        else:
            config[key] = os.getenv(key, config.get(key, ""))
            
    if "AUTO_SYNC_INTERVAL" in file_config:
        config["AUTO_SYNC_INTERVAL"] = file_config["AUTO_SYNC_INTERVAL"]
    else:
        try:
            config["AUTO_SYNC_INTERVAL"] = int(os.getenv("AUTO_SYNC_INTERVAL", config.get("AUTO_SYNC_INTERVAL", 0)))
        except ValueError:
            config["AUTO_SYNC_INTERVAL"] = 0
            
    for bool_key in ["AUTO_COVER", "AUTO_READING_DIR", "SMART_COMPLETION"]:
        if bool_key in file_config:
            config[bool_key] = file_config[bool_key]
        else:
            config[bool_key] = str(os.getenv(bool_key, config.get(bool_key, "False"))).lower() == "true"
            
    return config

def save_config(data):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)