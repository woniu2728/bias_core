from __future__ import annotations


def build_site_extension(registry, ext_id: str, ext_path: str):
    return None


def load_site_extenders(registry):
    extenders = []
    import importlib.metadata
    try:
        for ep in importlib.metadata.entry_points(group="bias.extensions"):
            try:
                fn = ep.load()
                result = fn()
                if isinstance(result, (list, tuple)):
                    extenders.extend(result)
            except Exception:
                continue
    except Exception:
        pass
    return tuple(extenders)
