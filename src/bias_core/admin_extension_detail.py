from bias_core.api.admin import admin_extension_detail as _detail

for _name in dir(_detail):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_detail, _name)

__all__ = [_name for _name in globals() if not _name.startswith("__")]
