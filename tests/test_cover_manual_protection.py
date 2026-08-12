"""
C65 — Protection des couvertures choisies à la main.

La provenance vit dans une colonne dédiée (`cover_manual`), plus dans
`targeted_fields` : le granulaire de l'utilisateur ne bouge plus, la cartouche
🔒 du dashboard reflète un état réel, et l'échappatoire de masse est
l'interrupteur `COVER_FORCE_OVERWRITE` (aucun clic série par série).

Le verrou Kavita ne peut pas jouer ce rôle : `upload_series_cover` pose
`lockCover` sur TOUS les uploads (sinon un scan Kavita régénère la vignette
depuis les fichiers), il ne distingue donc pas un choix manuel d'un upload
automatique.
"""

import db_manager
from services import kavita_payload


def _t():
    return {
        "log_sending": "[{0}] send",
        "log_success": "[{0}] ok",
        "log_cover_upload": "[{0}] cover up",
        "log_cover_success": "[{0}] cover ok",
        "log_cover_fail": "[{0}] cover fail {1}",
    }


class FakeKavita:
    def __init__(self):
        self.uploads = []

    def update_series_external_ids(self, *a, **k):
        return True, "ok"

    def update_series_metadata(self, meta):
        return True, "Succès", True

    def update_series_general(self, series_id, localized_name=None, format_val=None):
        return True, "Succès", True

    def upload_series_cover(self, series_id, cover_url):
        self.uploads.append((series_id, cover_url))
        return True, "ok"


def _apply(mocker, series_id, *, config, force_cover_upload=False):
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    mocker.patch("services.kavita_payload._schedule_seal_retry")

    built = {
        "metadata": {"seriesId": series_id, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": "https://cdn.example/provider.jpg",
        "external_ids": {},
    }
    if force_cover_upload:
        built["force_cover_upload"] = True

    kavita = FakeKavita()
    ok, msg, _ = kavita_payload.apply_kavita_payload(
        kavita, series_id, f"Series {series_id}", built, ["summary", "cover"], config, ["ANILIST"], _t(),
    )
    assert ok is True, msg
    return kavita


def test_auto_cover_skips_a_manual_cover(mocker, isolated_db):
    """AUTO_COVER seul n'écrase pas un choix manuel."""
    db_manager.set_cover_manual(7001, True)

    kavita = _apply(mocker, 7001, config={"AUTO_COVER": True})

    assert kavita.uploads == []
    assert db_manager.is_cover_manual(7001) is True


def test_auto_cover_uploads_when_no_manual_choice(mocker, isolated_db):
    """Sans marqueur de provenance, AUTO_COVER travaille normalement."""
    kavita = _apply(mocker, 7002, config={"AUTO_COVER": True})

    assert len(kavita.uploads) == 1
    # Un upload automatique n'est pas un choix manuel : rien à protéger.
    assert db_manager.is_cover_manual(7002) is False


def test_force_overwrite_switch_bypasses_protection_and_clears_the_flag(mocker, isolated_db):
    """Échappatoire de masse : un run entier réécrit les couvertures sans clic."""
    db_manager.set_cover_manual(7003, True)

    kavita = _apply(mocker, 7003, config={"AUTO_COVER": True, "COVER_FORCE_OVERWRITE": True})

    assert len(kavita.uploads) == 1
    # La couverture vient désormais du provider : plus rien à protéger, donc la
    # cartouche disparaît du dashboard.
    assert db_manager.is_cover_manual(7003) is False


def test_explicit_pick_wins_over_protection_and_marks_provenance(mocker, isolated_db):
    """Un choix explicite (cover pick MR) passe même sans AUTO_COVER."""
    kavita = _apply(mocker, 7004, config={"AUTO_COVER": False}, force_cover_upload=True)

    assert len(kavita.uploads) == 1
    assert db_manager.is_cover_manual(7004) is True


def test_protection_never_touches_targeted_fields(mocker, isolated_db):
    """Le granulaire de l'utilisateur reste ce qu'il a coché."""
    from models import SeriesOverride

    db_manager.save_series_override(
        SeriesOverride(series_id=7005, targeted_fields="summary,cover"), purge_pending=False
    )

    _apply(mocker, 7005, config={"AUTO_COVER": False}, force_cover_upload=True)

    cached = db_manager.get_all_cached_data()[7005]
    assert cached["targeted_fields"] == "summary,cover"
    assert cached["cover_manual"] is True


def test_marking_provenance_preserves_status(isolated_db):
    """IGNORED / COMPLETED ne doivent pas retomber sur PENDING."""
    db_manager.update_status(7006, "IGNORED")

    db_manager.set_cover_manual(7006, True)

    cached = db_manager.get_all_cached_data()[7006]
    assert cached["status"] == "IGNORED"
    assert cached["cover_manual"] is True
