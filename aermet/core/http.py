"""
Shared HTTP helper — configures SSL/TLS for all outbound requests.

Handles machines with missing or outdated CA certificate bundles by
falling back to the certifi package.
"""

import requests

try:
    import certifi
    _CA_BUNDLE = certifi.where()
except ImportError:
    _CA_BUNDLE = True  # use requests/system default


def get(url, **kwargs):
    """requests.get() with SSL cert handling baked in."""
    kwargs.setdefault('verify', _CA_BUNDLE)
    return requests.get(url, **kwargs)
