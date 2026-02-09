import httpx
from ._legacy import (
    MOBILE_UA,
    DESKTOP_UA,
    TIMEOUT,
    MAX_RETRIES,
    _headers,
    _get_client,
    _close_clients,
    _client,
    _release_client,
    _rate_limit,
    _cached_trending,
    _request_with_retry,
)

NETWORK_EXCEPTIONS = (httpx.HTTPError, httpx.TimeoutException)
PARSE_EXCEPTIONS = (ValueError, IndexError, TypeError)

class ClientPool:
    """Context manager for clawkit HTTP client pool cleanup."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _close_clients()
        return False

    def close(self):
        _close_clients()


__all__ = [
    "MOBILE_UA",
    "DESKTOP_UA",
    "TIMEOUT",
    "MAX_RETRIES",
    "NETWORK_EXCEPTIONS",
    "PARSE_EXCEPTIONS",
    "ClientPool",
    "_headers",
    "_get_client",
    "_close_clients",
    "_client",
    "_release_client",
    "_rate_limit",
    "_cached_trending",
    "_request_with_retry",
]
