from . import _legacy as _legacy

__version__ = "3.3.1"

# Export all names (including internal helpers used by tests).
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

# Keep mutable cookie state patchable at package level.
_cookie_cache = _legacy._cookie_cache
_cookies_store = _legacy._cookies_store

def _get_cookies(platform: str):
    if platform in _cookie_cache:
        return _cookie_cache[platform]
    entry = _cookies_store.get(platform, {})
    if isinstance(entry, dict) and "cookies" in entry and isinstance(entry.get("cookies"), dict):
        cookies = entry["cookies"]
    else:
        cookies = entry if isinstance(entry, dict) else {}
    _cookie_cache[platform] = cookies
    return cookies

del _name
