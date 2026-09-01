"""
API d'enrichissement par tome et par album (issue #27).

Six routes : l'aperçu, qui n'écrit rien ; l'écriture d'une série, qui reçoit les
cases cochées ; la remise à zéro d'une série ; la passe de bibliothèque ; l'état
et l'annulation, communes aux deux écritures.

Les deux écritures rendent un démarrage, pas un résultat : elles tournent dans un
thread dédié et diffusent leur progression par `volume_enrich_progress`. Aucune
ne peut plus occuper le worker eventlet unique pendant des minutes.

Toutes sont coupées quand `VOLUME_ENRICHMENT_ENABLED` est éteint — l'interface
les masque déjà, mais un onglet resté ouvert ne doit pas relancer une écriture
en arrière-plan sur toute une bibliothèque.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from config_manager import load_config
from db_manager import (
    clear_volume_unit_states,
    get_volume_unit_states,
)
from kavita_api import KavitaAPI
from secure_logging import safe_exc_str
from services.volume_enrichment.index_cache import forget_series
from services.volume_enrichment.job import (
    build_series_plan,
    cancel_volume_enrich,
    get_volume_enrich_state,
    start_series_volume_enrich,
    start_volume_enrich,
)
from translations import translations

volume_enrichment_bp = Blueprint("volume_enrichment", __name__)


def _t():
    config = load_config()
    return translations.get(config.get("UI_LANG", "fr"), translations["fr"])


def _api() -> KavitaAPI:
    config = load_config()
    return KavitaAPI(config.get("KAVITA_URL"), config.get("KAVITA_API_KEY"))


def volume_enrichment_enabled(config: dict = None) -> bool:
    """Éteint par défaut : la fonctionnalité écrit dans Kavita tome par tome,
    elle ne doit pas s'activer toute seule à la mise à jour."""
    cfg = config if config is not None else load_config()
    return bool(cfg.get("VOLUME_ENRICHMENT_ENABLED", False))


#: Routes que la garde laisse passer même quand la fonctionnalité est éteinte.
#: La garde existe pour qu'un onglet resté ouvert ne puisse pas se mettre à
#: écrire dans une bibliothèque ; or ces deux-là ne peuvent rien écrire — l'une
#: lit un état, l'autre arrête une écriture. Les bloquer avait une conséquence
#: concrète : éteindre l'interrupteur pendant une passe rendait cette passe
#: impossible à voir et à arrêter, puisque les boutons disparaissent en même
#: temps que l'API. La garde protège les écritures, pas le droit de reprendre la
#: main sur ce qui tourne déjà.
_REACHABLE_WHILE_DISABLED = frozenset(
    {"volume_enrichment.volume_enrich_status", "volume_enrichment.volume_enrich_cancel"}
)


@volume_enrichment_bp.before_request
def _guard_disabled():
    if volume_enrichment_enabled():
        return None
    if request.endpoint in _REACHABLE_WHILE_DISABLED:
        return None
    t = _t()
    return jsonify(
        {
            "success": False,
            "error": t.get("vol_err_disabled", "Enrichissement par tome désactivé."),
            "disabled": True,
        }
    ), 403


def _force_flag(payload: dict, config: dict) -> bool:
    """`force` de la requête, sinon l'interrupteur persistant de la sidebar."""
    if "force" in payload:
        return bool(payload.get("force"))
    return bool(config.get("VOLUME_FORCE_OVERWRITE", False))


@volume_enrichment_bp.route("/api/series/<int:series_id>/volume-enrich/preview", methods=["POST"])
def volume_enrich_preview(series_id):
    """Ce qui serait écrit, sans rien écrire.

    Le plan est bâti par `services.volume_enrichment.job` : l'écriture, passée en
    tâche de fond, doit bâtir exactement le même — sinon l'utilisateur validerait
    un aperçu et écrirait autre chose. C'est aussi ce chemin qui garnit la
    mémoïsation de l'index dont l'écriture qui suit va se servir.
    """
    t = _t()
    payload = request.get_json(silent=True) or {}
    config = load_config()
    try:
        plan = build_series_plan(
            _api(),
            series_id,
            force=_force_flag(payload, config),
            experimental=bool(config.get("VOLUME_ENRICH_EXPERIMENTAL", False)),
            config=config,
        )
        plan["states"] = {
            str(cid): state.get("status")
            for cid, state in (get_volume_unit_states(series_id) or {}).items()
        }
        return jsonify({"success": True, "plan": plan})
    except Exception as e:
        logging.error("volume-enrich preview failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("vol_err_generic", str(e))}), 500


@volume_enrichment_bp.route("/api/series/<int:series_id>/volume-enrich/apply", methods=["POST"])
def volume_enrich_apply(series_id):
    """Lance l'écriture de la série en tâche de fond, cases cochées comprises.

    Cette route faisait tout le travail dans le greenlet de la requête :
    reconstruction du plan — donc réinterrogation du fournisseur, alors que
    l'aperçu venait de le faire —, puis par tome une lecture, une écriture et un
    téléversement de couverture. Sur l'unique worker eventlet qui sert toute
    l'application, la requête durait des minutes, le bouton restait sur
    « Écriture en cours… » sans rien dire, et rien ne permettait d'arrêter. Elle
    ne rend donc plus le résultat mais le démarrage : la progression arrive par
    `volume_enrich_progress`, comme pour la passe de bibliothèque, et
    `/api/volume-enrich/cancel` sait l'arrêter.
    """
    t = _t()
    payload = request.get_json(silent=True) or {}
    config = load_config()

    selection = None
    raw_selection = payload.get("selection")
    if isinstance(raw_selection, dict):
        selection = {}
        for key, fields in raw_selection.items():
            try:
                chapter_id = int(key)
            except (TypeError, ValueError):
                continue
            selection[chapter_id] = [str(f) for f in (fields or [])] if fields else None

    result = start_series_volume_enrich(
        series_id,
        selection=selection,
        force=_force_flag(payload, config),
        with_credits=bool(config.get("VOLUME_ENRICH_CREDITS", False)),
    )
    if result.get("success"):
        return jsonify({"success": True, "started": True, "series_id": series_id})

    if result.get("series_busy"):
        # La série est déjà en cours d'écriture : double-clic sur « Appliquer »,
        # passe de bibliothèque qui la traverse, ou enrichissement série lancé
        # depuis sa ligne. Sans ce refus, les crédits étaient récupérés deux fois
        # et la couverture téléversée deux fois.
        return jsonify(
            {
                "success": False,
                "busy": True,
                "series_busy": True,
                "error": t.get(
                    "vol_err_series_busy", "Cette série est déjà en cours d'écriture."
                ),
            }
        ), 409
    if result.get("busy"):
        # L'état de progression est global : une passe de bibliothèque en cours
        # interdit l'écriture d'une série, et réciproquement.
        return jsonify(
            {
                **result,
                "success": False,
                "busy": True,
                "error": t.get("vol_err_busy", "Une passe est déjà en cours."),
            }
        ), 409
    logging.error("volume-enrich apply failed: %s", result.get("error"))
    return jsonify(
        {
            "success": False,
            **result,
            "error": result.get("error") or t.get("vol_err_generic", "Écriture non démarrée."),
        }
    ), 500


@volume_enrichment_bp.route("/api/series/<int:series_id>/volume-enrich/reset", methods=["POST"])
def volume_enrich_reset(series_id):
    """Rend une série à la reprise en effaçant son état par unité.

    Seule sortie de secours quand une série a été fermée à tort — jusqu'ici
    `clear_volume_unit_states` n'était exposée par aucune route, et une série
    marquée traitée pendant une indisponibilité de Kavita ne pouvait plus revenir
    dans une passe sans repartir de zéro sur toute la bibliothèque.

    L'index mémoïsé part avec : remettre une série à la reprise, c'est demander à
    la refaire pour de bon, et la refaire à partir de l'index d'il y a dix
    minutes serait une remise à zéro en trompe-l'œil.
    """
    t = _t()
    payload = request.get_json(silent=True) or {}
    try:
        if payload.get("workshop"):
            from services.workshop import reset_workshop

            chapter_id = payload.get("chapter_id")
            result = reset_workshop(
                _api(),
                series_id,
                int(chapter_id) if chapter_id not in (None, "") else None,
            )
            return jsonify(
                {
                    "success": True,
                    "series_id": series_id,
                    "reset": True,
                    "workshop": True,
                    "index_forgotten": result.get("index_forgotten", 0),
                    "payload": result.get("payload"),
                }
            )
        clear_volume_unit_states(series_id)
        forgotten = forget_series(series_id)
        return jsonify(
            {
                "success": True,
                "series_id": series_id,
                "reset": True,
                "index_forgotten": forgotten,
            }
        )
    except Exception as e:
        logging.error("volume-enrich reset failed: %s", safe_exc_str(e))
        return jsonify({"success": False, "error": t.get("vol_err_generic", str(e))}), 500


@volume_enrichment_bp.route("/api/libraries/<library_id>/volume-enrich", methods=["POST"])
def volume_enrich_library(library_id):
    """Passe de bibliothèque, en thread dédié — reprend là où elle en était."""
    payload = request.get_json(silent=True) or {}
    config = load_config()
    series_ids = []
    for raw in payload.get("series_ids") or []:
        try:
            series_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    result = start_volume_enrich(
        library_id,
        series_ids or None,
        force=_force_flag(payload, config),
        with_credits=bool(config.get("VOLUME_ENRICH_CREDITS", False)),
        resume=payload.get("resume", True) is not False,
    )
    if not result.get("success"):
        t = _t()
        if not result.get("busy"):
            # `start_volume_enrich` échoue de deux façons : une passe tourne
            # déjà, ou le thread n'a pas démarré (conteneur à court de threads).
            # Le second cas répondait « Une passe est déjà en cours » avec un
            # 409, en écrasant la raison réelle : l'utilisateur cherchait une
            # passe fantôme, que ni `/status` ni Annuler ne montraient.
            return jsonify(
                {
                    "success": False,
                    **result,
                    "error": result.get("error")
                    or t.get("vol_err_generic", "Passe non démarrée."),
                }
            ), 500
        return jsonify(
            {**result, "error": t.get("vol_err_busy", "Une passe est déjà en cours.")}
        ), 409
    return jsonify(result)


@volume_enrichment_bp.route("/api/volume-enrich/status", methods=["GET"])
def volume_enrich_status():
    return jsonify({"success": True, **get_volume_enrich_state()})


@volume_enrichment_bp.route("/api/volume-enrich/cancel", methods=["POST"])
def volume_enrich_cancel():
    result = cancel_volume_enrich()
    if not result.get("success"):
        # Symétrique du démarrage, qui rend 409 quand une passe tourne déjà :
        # annuler ce qui ne tourne pas est le même genre de conflit d'état, et un
        # 200 obligeait l'appelant à lire le corps pour s'en apercevoir.
        t = _t()
        return jsonify(
            {**result, "error": t.get("vol_err_idle", "Aucune passe en cours.")}
        ), 409
    return jsonify(result)
