"""
Non-régression : `load_config()` relit tout `config.json`, un appelant modifie
quelques clés en mémoire, puis `save_config()` réécrit le fichier ENTIER. Sans
verrou, deux cycles lire-modifier-écrire concurrents (ex: deux cases à cocher
de la sidebar changées coup sur coup — voir static/js/config.js::saveConfig(),
qui envoie un POST /save-config indépendant par case — ou une régénération de
jeton webhook en même temps qu'un autre changement) peuvent s'entrelacer : le
second cycle relit le fichier AVANT que le premier n'ait écrit, puis écrase le
fichier entier à partir de cet état périmé, faisant disparaître silencieusement
le changement du premier (perte de mise à jour classique).

`config_manager.CONFIG_LOCK` (RLock) doit englober tout le cycle
lire-modifier-écrire (pas seulement l'écriture) pour éliminer cette course.
"""
import threading
import time


def test_concurrent_read_modify_write_cycles_do_not_lose_either_change(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config_test.json"))

    entered_event = threading.Event()
    release_event = threading.Event()

    def slow_cycle_sets_auto_cover():
        with config_manager.CONFIG_LOCK:
            config = config_manager.load_config()
            entered_event.set()
            # Simule un cycle lent (ex: boucle sur plusieurs clés de formulaire)
            # pendant lequel un second cycle concurrent pourrait s'immiscer.
            release_event.wait(timeout=2)
            config["AUTO_COVER"] = True
            config_manager.save_config(config)

    first_thread = threading.Thread(target=slow_cycle_sets_auto_cover)
    first_thread.start()
    assert entered_event.wait(timeout=2), "Le premier cycle n'a pas démarré à temps"

    def fast_cycle_sets_smart_completion():
        with config_manager.CONFIG_LOCK:
            config = config_manager.load_config()
            config["SMART_COMPLETION"] = True
            config_manager.save_config(config)

    second_thread = threading.Thread(target=fast_cycle_sets_smart_completion)
    second_thread.start()

    # Tant que le premier cycle tient le verrou, le second doit rester bloqué en
    # attente — la preuve que les deux cycles sont bien mutuellement exclusifs.
    time.sleep(0.2)
    assert second_thread.is_alive(), "Le second cycle n'aurait pas dû pouvoir s'exécuter pendant que le premier tient CONFIG_LOCK"

    release_event.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    final_config = config_manager.load_config()
    assert final_config["AUTO_COVER"] is True, "Le changement du premier cycle a été perdu"
    assert final_config["SMART_COMPLETION"] is True, "Le changement du second cycle a été perdu"


def test_load_config_generating_secret_key_does_not_deadlock_on_reentry(tmp_path, monkeypatch):
    """load_config() appelle save_config() en interne (génération de SECRET_KEY/
    WEBHOOK_TOKEN au premier démarrage) alors qu'il tient déjà CONFIG_LOCK :
    ça ne doit pas se bloquer soi-même (CONFIG_LOCK doit être un RLock).

    Exécuté dans un thread à part avec un join(timeout=...) plutôt qu'un appel
    direct : si CONFIG_LOCK était régressé vers un Lock non ré-entrant, l'appel
    interne à save_config() se bloquerait indéfiniment sur lui-même — le thread
    séparé transforme ce risque de hang infini en échec de test propre.
    """
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config_test.json"))

    result = {}

    def run():
        result["config"] = config_manager.load_config()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=3)

    assert not t.is_alive(), "load_config() s'est bloqué indéfiniment (CONFIG_LOCK n'est plus ré-entrant ?)"
    assert result["config"]["SECRET_KEY"]
    assert result["config"]["WEBHOOK_TOKEN"]
