"""
Exports CSV de l'inventaire : une valeur ne doit pas devenir une formule.

Un titre de série qui commence par `=`, `+`, `-` ou `@` est interprété comme une
formule à l'ouverture du CSV dans Excel ou LibreOffice — jusqu'à l'appel système
(`=cmd|' /C calc'!A0`). Les valeurs textuelles sont donc neutralisées par une
apostrophe de tête, dans les trois exports CSV et sur toutes leurs colonnes.

Les exports TXT ne sont pas concernés : personne ne les ouvre dans un tableur, et
les préfixer rendrait les rapports illisibles.
"""

from __future__ import annotations

from services.library_audit.export_csv import (
    duplicates_to_csv,
    duplicates_to_txt,
    missing_volumes_to_csv,
    missing_volumes_to_txt,
    volume_report_to_csv,
    volume_report_to_txt,
)

_PAYLOAD = '=cmd|\' /C calc\'!A0'


def _cells(csv_text: str, line: int = 1):
    import csv
    import io

    rows = list(csv.reader(io.StringIO(csv_text)))
    return rows[line]


def test_le_rapport_de_serie_neutralise_les_formules():
    report = {
        "series_id": 7,
        "series_name": _PAYLOAD,
        "structure": "volumes",
        "stats": {"kavita_count": 1},
        "catalog": {"expected": 3, "provider": "ANILIST", "status": "ok"},
        "completion": {"state": "partial"},
        "missing_volumes": [2, 3],
        "primary": {"unit": "volumes", "count": 1, "expected": 3, "missing": [2, 3]},
        "units": [{"volume_number": 1, "name": "+Tome 1", "isbn": "-978"}],
    }

    cells = _cells(volume_report_to_csv(report))
    assert _PAYLOAD not in cells, "le nom de série sort tel quel : formule exécutable"
    assert "'" + _PAYLOAD in cells
    assert "'+Tome 1" in cells
    assert "'-978" in cells

    txt = volume_report_to_txt(report)
    assert _PAYLOAD in txt, "l'export TXT n'a pas à être préfixé"


def test_lexport_doublons_neutralise_les_formules():
    groups = [
        {
            "group_id": 1,
            "group_key": "k",
            "score": 0.99,
            "reasons": ["@titre"],
            "series_ids": [1],
            "names": [_PAYLOAD],
        }
    ]

    cells = _cells(duplicates_to_csv(groups, library_id=5))
    assert "'" + _PAYLOAD in cells
    assert "'@titre" in cells
    assert _PAYLOAD in duplicates_to_txt(groups, library_id=5)


def test_lexport_manquants_neutralise_les_formules():
    rows = [
        {
            "series_id": 3,
            "name": _PAYLOAD,
            "badge": "1/3",
            "reason": "=SUM(A1)",
            "missing_volumes": [2, 3],
            "unit": "volumes",
        }
    ]

    cells = _cells(missing_volumes_to_csv(rows, library_id=5))
    assert "'" + _PAYLOAD in cells
    assert "'=SUM(A1)" in cells
    assert _PAYLOAD in missing_volumes_to_txt(rows, library_id=5)


def test_les_valeurs_ordinaires_ne_sont_pas_touchees():
    """Un préfixe posé à tort rendrait chaque export bruyant."""
    report = {
        "series_id": 7,
        "series_name": "Berserk",
        "stats": {"kavita_count": 41},
        "catalog": {"expected": 42, "provider": "ANILIST", "status": "ok"},
        "primary": {"unit": "volumes", "count": 41, "expected": 42, "missing": [42]},
        "units": [{"volume_number": 1, "name": "Tome 1", "isbn": "9782723", "has_isbn": True}],
    }

    cells = _cells(volume_report_to_csv(report))
    assert "Berserk" in cells
    assert "Tome 1" in cells
    assert "9782723" in cells
    assert "41" in cells
    assert not any(c.startswith("'") for c in cells)
