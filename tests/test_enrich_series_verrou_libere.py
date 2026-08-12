"""
Le verrou « série en cours de traitement » doit toujours être relâché.

`_processing_series_ids.add(sid)` avait lieu avant le `try`, et `load_config()` /
`translations.get()` s'exécutaient dans l'intervalle. Si l'un des deux levait, le
`finally` qui relâche le verrou n'était jamais atteint : la série restait marquée
« en cours de traitement » jusqu'au redémarrage du conteneur, et tout sync
ultérieur la refusait avec « Déjà en cours de traitement » — sans que rien
n'explique pourquoi cette série précise ne repartait plus.

`load_config()` peut effectivement lever : le `except json.JSONDecodeError` ne
couvre que le JSON illisible. Un `config.json` syntaxiquement valide mais qui
n'est pas un objet (une liste, une chaîne — un début de restauration de
sauvegarde, un montage tronqué) traverse `json.load` puis casse sur
`config.update`.
"""

from __future__ import annotations

import json

import pytest

import services.enrichment_engine as ee


def test_un_config_json_qui_nest_pas_un_objet_fait_lever_load_config(tmp_path, monkeypatch):
    import config_manager

    broken = tmp_path / "config.json"
    broken.write_text(json.dumps(["KAVITA_URL", "http://kavita"]), encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(broken))

    with pytest.raises(Exception):
        config_manager.load_config()


def test_un_echec_de_configuration_ne_bloque_pas_la_serie(monkeypatch):
    def _boom():
        raise ValueError("config.json illisible")

    monkeypatch.setattr(ee, "load_config", _boom)
    ee._processing_series_ids.discard(4242)

    ok, message, providers = ee.enrich_series(4242, "Berserk")

    assert ok is False
    assert message
    assert providers == []
    assert 4242 not in ee._processing_series_ids, (
        "la série reste marquée « en cours de traitement » : tout sync ultérieur "
        "sera refusé jusqu'au redémarrage"
    )


def test_la_serie_reste_synchronisable_apres_lechec(monkeypatch):
    """Preuve du symptôme : sans libération, le second appel n'atteint même plus
    la configuration."""
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise ValueError("config.json illisible")

    monkeypatch.setattr(ee, "load_config", _boom)
    ee._processing_series_ids.discard(4243)

    ee.enrich_series(4243, "Pluto")
    ee.enrich_series(4243, "Pluto")

    assert calls["n"] == 2, "le second sync a été refusé sans même relire la configuration"
