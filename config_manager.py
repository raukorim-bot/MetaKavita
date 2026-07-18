import json
import os

CONFIG_FILE = "config.json"

def load_config():
    # Ajout de AUTO_SYNC_INTERVAL (par défaut 0 = désactivé)
    config = {"KAVITA_URL": "", "KAVITA_API_KEY": "", "DEEPL_API_KEY": "", "TARGET_LANG": "FR", "UI_LANG": "fr", "PROVIDER": "ANILIST", "AUTO_SYNC_INTERVAL": 0, "AUTO_COVER": False}
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except json.JSONDecodeError:
            pass
            
    config["KAVITA_URL"] = os.getenv("KAVITA_URL", config.get("KAVITA_URL", ""))
    config["KAVITA_API_KEY"] = os.getenv("KAVITA_API_KEY", config.get("KAVITA_API_KEY", ""))
    config["DEEPL_API_KEY"] = os.getenv("DEEPL_API_KEY", config.get("DEEPL_API_KEY", ""))
    config["TARGET_LANG"] = os.getenv("TARGET_LANG", config.get("TARGET_LANG", "FR"))
    config["UI_LANG"] = os.getenv("UI_LANG", config.get("UI_LANG", "fr"))
    config["PROVIDER"] = os.getenv("PROVIDER", config.get("PROVIDER", "ANILIST"))
    
    # On force la conversion en entier pour éviter les bugs
    try:
        config["AUTO_SYNC_INTERVAL"] = int(os.getenv("AUTO_SYNC_INTERVAL", config.get("AUTO_SYNC_INTERVAL", 0)))
    except ValueError:
        config["AUTO_SYNC_INTERVAL"] = 0
        config["AUTO_COVER"] = str(os.getenv("AUTO_COVER", config.get("AUTO_COVER", "False"))).lower() == "true"
    
    return config

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
