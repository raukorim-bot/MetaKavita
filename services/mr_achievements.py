"""
Hauts-faits Manual Review — moteur partagé pour /stats (lifetime).

Aligné sur le catalogue session JS (`static/js/manual_review.js`).
Les titres `session_only` (ex. pause café) sont exclus du lifetime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


ACCENT_HEX = {
    "teal": "#2dd4bf",
    "sky": "#38bdf8",
    "coral": "#fb7185",
    "amber": "#fbbf24",
    "lime": "#a3e635",
    "violet": "#a78bfa",
}


def lifetime_bag_from_stats(lifetime: Optional[dict]) -> Dict[str, Any]:
    """Mappe get_lifetime_stats() → bag d'évaluation (même forme que la session JS)."""
    life = lifetime or {}
    reviews = int(life.get("manual_reviews") or 0)
    return {
        "done": reviews,
        "skipped": int(life.get("manual_skips") or 0),
        "top1": int(life.get("manual_top1_accepts") or 0),
        "edits": int(life.get("manual_field_edits") or 0),
        "purged": int(life.get("manual_purges") or 0),
        "researches": int(life.get("manual_researches") or 0),
        "fusions": int(life.get("manual_fusions") or 0),
        "weak_picks": int(life.get("manual_weak_picks") or 0),
        "score_sum": float(life.get("manual_score_sum") or 0),
        "score_n": reviews,
        "super_used": int(life.get("manual_super_confirms") or 0) > 0,
    }


def _avg(bag: dict) -> float:
    n = int(bag.get("score_n") or 0)
    if n <= 0:
        return 0.0
    return float(bag.get("score_sum") or 0) / n


def _catalog() -> List[dict]:
    """Catalogue : priority desc, test(bag), flavor(bag), progress(bag)|None."""

    def flavor_purge(s):
        return ("mr_ach_purge_master_flavor", {"0": s.get("purged") or 0})

    def flavor_spectator(s):
        return ("mr_ach_spectator_flavor", {"0": s.get("skipped") or 0})

    def flavor_super(s):
        return ("mr_ach_super_marathon_flavor", {"0": s.get("done") or 0})

    def flavor_alchemist(s):
        return ("mr_ach_alchemist_flavor", {"0": s.get("fusions") or 0})

    def flavor_nugget(s):
        return ("mr_ach_nugget_flavor", {"0": s.get("weak_picks") or 0})

    def flavor_relancer(s):
        return ("mr_ach_relancer_flavor", {"0": s.get("researches") or 0})

    def flavor_oracle(s):
        return ("mr_ach_oracle_flavor", {"0": s.get("top1") or 0, "1": s.get("done") or 0})

    def flavor_rebel(s):
        return ("mr_ach_rebel_flavor", {"0": s.get("done") or 0})

    def flavor_sculptor(s):
        return ("mr_ach_sculptor_flavor", {"0": s.get("edits") or 0})

    def flavor_lightning(s):
        return ("mr_ach_lightning_flavor", {"0": s.get("done") or 0})

    def flavor_gourmet(s):
        return ("mr_ach_gourmet_flavor", {"0": f"{_avg(s):.2f}", "1": s.get("score_n") or 0})

    def flavor_sprinter(s):
        return ("mr_ach_sprinter_flavor", {"0": s.get("done") or 0})

    def flavor_balanced(s):
        return ("mr_ach_balanced_flavor", {"0": s.get("done") or 0, "1": s.get("skipped") or 0})

    def flavor_warmup(_s):
        return ("mr_ach_warmup_flavor", {})

    def flavor_curator(s):
        return ("mr_ach_curator_flavor", {"0": s.get("done") or 0, "1": s.get("skipped") or 0})

    return [
        {
            "id": "purge_master",
            "priority": 100,
            "accent": "coral",
            "mono": "VD",
            "title_key": "mr_ach_purge_master_title",
            "session_only": False,
            "test": lambda s: int(s.get("purged") or 0) > 0,
            "flavor": flavor_purge,
            "progress": lambda s: min(1.0, float(s.get("purged") or 0)),
            "hint_key": "mr_ach_hint_purge",
        },
        {
            "id": "spectator",
            "priority": 95,
            "accent": "coral",
            "mono": "SP",
            "title_key": "mr_ach_spectator_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) == 0 and int(s.get("skipped") or 0) > 0,
            "flavor": flavor_spectator,
            "progress": lambda s: min(1.0, float(s.get("skipped") or 0) / 3.0),
            "hint_key": "mr_ach_hint_spectator",
        },
        {
            "id": "empty_session",
            "priority": 90,
            "accent": "amber",
            "mono": "☕",
            "title_key": "mr_ach_empty_session_title",
            "session_only": True,
            "test": lambda s: (
                int(s.get("done") or 0)
                + int(s.get("skipped") or 0)
                + int(s.get("purged") or 0)
                + int(s.get("researches") or 0)
            ) == 0,
            "flavor": lambda _s: ("mr_ach_empty_session_flavor", {}),
            "progress": lambda _s: 0.0,
            "hint_key": "mr_ach_hint_empty",
        },
        {
            "id": "super_marathon",
            "priority": 88,
            "accent": "amber",
            "mono": "SR",
            "title_key": "mr_ach_super_marathon_title",
            "session_only": False,
            "test": lambda s: bool(s.get("super_used")) and int(s.get("done") or 0) >= 1,
            "flavor": flavor_super,
            "progress": lambda s: 1.0 if s.get("super_used") else 0.0,
            "hint_key": "mr_ach_hint_super",
        },
        {
            "id": "alchemist",
            "priority": 85,
            "accent": "violet",
            "mono": "AL",
            "title_key": "mr_ach_alchemist_title",
            "session_only": False,
            "test": lambda s: int(s.get("fusions") or 0) >= 1,
            "flavor": flavor_alchemist,
            "progress": lambda s: min(1.0, float(s.get("fusions") or 0)),
            "hint_key": "mr_ach_hint_alchemist",
        },
        {
            "id": "nugget",
            "priority": 82,
            "accent": "amber",
            "mono": "★",
            "title_key": "mr_ach_nugget_title",
            "session_only": False,
            "test": lambda s: int(s.get("weak_picks") or 0) >= 1,
            "flavor": flavor_nugget,
            "progress": lambda s: min(1.0, float(s.get("weak_picks") or 0)),
            "hint_key": "mr_ach_hint_nugget",
        },
        {
            "id": "relancer",
            "priority": 80,
            "accent": "sky",
            "mono": "↻",
            "title_key": "mr_ach_relancer_title",
            "session_only": False,
            "test": lambda s: int(s.get("researches") or 0) >= 1,
            "flavor": flavor_relancer,
            "progress": lambda s: min(1.0, float(s.get("researches") or 0)),
            "hint_key": "mr_ach_hint_relancer",
        },
        {
            "id": "oracle",
            "priority": 75,
            "accent": "teal",
            "mono": "T1",
            "title_key": "mr_ach_oracle_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 3
            and (float(s.get("top1") or 0) / max(1, int(s.get("done") or 0))) >= 0.8,
            "flavor": flavor_oracle,
            "progress": lambda s: (
                min(1.0, float(s.get("done") or 0) / 3.0)
                if int(s.get("done") or 0) < 3
                else min(
                    1.0,
                    (float(s.get("top1") or 0) / max(1, int(s.get("done") or 0))) / 0.8,
                )
            ),
            "hint_key": "mr_ach_hint_oracle",
        },
        {
            "id": "rebel",
            "priority": 72,
            "accent": "coral",
            "mono": "≠",
            "title_key": "mr_ach_rebel_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 2 and int(s.get("top1") or 0) == 0,
            "flavor": flavor_rebel,
            "progress": lambda s: min(1.0, float(s.get("done") or 0) / 2.0)
            if int(s.get("top1") or 0) == 0
            else 0.0,
            "hint_key": "mr_ach_hint_rebel",
        },
        {
            "id": "sculptor",
            "priority": 68,
            "accent": "violet",
            "mono": "✎",
            "title_key": "mr_ach_sculptor_title",
            "session_only": False,
            "test": lambda s: int(s.get("edits") or 0) >= 5 and int(s.get("done") or 0) >= 1,
            "flavor": flavor_sculptor,
            "progress": lambda s: min(1.0, float(s.get("edits") or 0) / 5.0),
            "hint_key": "mr_ach_hint_sculptor",
        },
        {
            "id": "lightning",
            "priority": 65,
            "accent": "lime",
            "mono": "⚡",
            "title_key": "mr_ach_lightning_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 3 and int(s.get("edits") or 0) == 0,
            "flavor": flavor_lightning,
            "progress": lambda s: (
                min(1.0, float(s.get("done") or 0) / 3.0)
                if int(s.get("edits") or 0) == 0
                else 0.0
            ),
            "hint_key": "mr_ach_hint_lightning",
        },
        {
            "id": "gourmet",
            "priority": 62,
            "accent": "teal",
            "mono": "◆",
            "title_key": "mr_ach_gourmet_title",
            "session_only": False,
            "test": lambda s: int(s.get("score_n") or 0) >= 3 and _avg(s) >= 0.85,
            "flavor": flavor_gourmet,
            "progress": lambda s: (
                min(1.0, float(s.get("score_n") or 0) / 3.0)
                if int(s.get("score_n") or 0) < 3
                else min(1.0, _avg(s) / 0.85)
            ),
            "hint_key": "mr_ach_hint_gourmet",
        },
        {
            "id": "sprinter",
            "priority": 58,
            "accent": "lime",
            "mono": "≫",
            "title_key": "mr_ach_sprinter_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 10,
            "flavor": flavor_sprinter,
            "progress": lambda s: min(1.0, float(s.get("done") or 0) / 10.0),
            "hint_key": "mr_ach_hint_sprinter",
        },
        {
            "id": "balanced",
            "priority": 55,
            "accent": "sky",
            "mono": "≈",
            "title_key": "mr_ach_balanced_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 2 and int(s.get("skipped") or 0) >= 2,
            "flavor": flavor_balanced,
            "progress": lambda s: min(
                1.0,
                min(float(s.get("done") or 0), float(s.get("skipped") or 0)) / 2.0,
            ),
            "hint_key": "mr_ach_hint_balanced",
        },
        {
            "id": "warmup",
            "priority": 40,
            "accent": "teal",
            "mono": "1",
            "title_key": "mr_ach_warmup_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) == 1,
            "flavor": flavor_warmup,
            "progress": lambda s: 1.0 if int(s.get("done") or 0) >= 1 else 0.0,
            "hint_key": "mr_ach_hint_warmup",
        },
        {
            "id": "curator",
            "priority": 10,
            "accent": "teal",
            "mono": "★",
            "title_key": "mr_ach_curator_title",
            "session_only": False,
            "test": lambda s: int(s.get("done") or 0) >= 1,
            "flavor": flavor_curator,
            "progress": lambda s: min(1.0, float(s.get("done") or 0)),
            "hint_key": "mr_ach_hint_curator",
        },
    ]


def _format_flavor(t: dict, key: str, params: dict, fallback: str = "") -> str:
    raw = (t or {}).get(key) or fallback or key
    out = str(raw)
    for k, v in (params or {}).items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out


def _card(entry: dict, bag: dict, t: dict, unlocked: bool) -> dict:
    flavor_key, params = entry["flavor"](bag)
    title = (t or {}).get(entry["title_key"]) or entry["id"]
    flavor = _format_flavor(t, flavor_key, params)
    hint = (t or {}).get(entry.get("hint_key") or "") or ""
    try:
        progress = float(entry["progress"](bag))
    except Exception:
        progress = 1.0 if unlocked else 0.0
    progress = max(0.0, min(1.0, progress))
    accent = entry.get("accent") or "teal"
    return {
        "id": entry["id"],
        "title": title,
        "title_key": entry["title_key"],
        "flavor": flavor,
        "hint": hint,
        "accent": accent,
        "accent_hex": ACCENT_HEX.get(accent, ACCENT_HEX["teal"]),
        "mono": entry.get("mono") or "★",
        "unlocked": unlocked,
        "progress": round(progress, 3),
        "priority": entry.get("priority") or 0,
    }


def evaluate(bag: Optional[dict], translations_dict: Optional[dict] = None) -> dict:
    """
    Évalue les hauts-faits pour un bag session/lifetime.

    Retourne unlocked (tri priorité desc), locked (même ordre catalogue),
    hero (= premier unlocked), counts.
    """
    s = bag or {}
    t = translations_dict or {}
    unlocked: List[dict] = []
    locked: List[dict] = []
    for entry in _catalog():
        if entry.get("session_only"):
            continue
        try:
            ok = bool(entry["test"](s))
        except Exception:
            ok = False
        card = _card(entry, s, t, ok)
        if ok:
            unlocked.append(card)
        else:
            locked.append(card)

    unlocked.sort(key=lambda c: c.get("priority") or 0, reverse=True)
    total = len(unlocked) + len(locked)
    return {
        "unlocked": unlocked,
        "locked": locked,
        "hero": unlocked[0] if unlocked else None,
        "unlocked_count": len(unlocked),
        "total": total,
    }


def evaluate_from_lifetime(lifetime: Optional[dict], translations_dict: Optional[dict] = None) -> dict:
    return evaluate(lifetime_bag_from_stats(lifetime), translations_dict)
