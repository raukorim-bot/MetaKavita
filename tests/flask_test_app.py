"""Shared Flask test helpers (importable; not a pytest conftest plugin)."""
import importlib


def get_series_bp():
    """Import ``series_bp`` with a reload filet if the module was partially polluted.

    Dashboard / override fixtures all need this Blueprint. A broken
    ``sys.modules['routes.series']`` (missing ``series_bp``) used to cascade into
    setup errors; reload once from disk when the attribute is absent.
    """
    import routes.series as series_mod

    bp = getattr(series_mod, "series_bp", None)
    if bp is not None:
        return bp
    series_mod = importlib.reload(series_mod)
    bp = getattr(series_mod, "series_bp", None)
    if bp is None:
        raise ImportError(
            "routes.series has no series_bp after reload — check for sys.modules pollution"
        )
    return bp
