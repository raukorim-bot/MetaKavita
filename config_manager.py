import json
import os

CONFIG_FILE = "config.json"

def load_config():
    config = {"KAVITA_URL": "", "KAVITA_API_KEY": "", "DEEPL_API_KEY": "", "TARGET_LANG": "FR", "UI_LANG": "fr", "PROVIDER": "ANILIST"}
    
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
    
    return config

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
