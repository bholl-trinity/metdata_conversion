"""
Shared HTTP helper — configures SSL/TLS for all outbound requests.

Handles machines with missing or outdated CA certificate bundles by
falling back to the certifi package.  If SSL verification still fails
(e.g. outdated certifi or system CA store), retries with verification
disabled and warns the user.
"""

import requests
from requests.exceptions import SSLError

try:
    import certifi
    _CA_BUNDLE = certifi.where()
except ImportError:
    _CA_BUNDLE = True  # use requests/system default


def get(url, **kwargs):
    """requests.get() with SSL cert handling baked in."""
    kwargs.setdefault('verify', _CA_BUNDLE)
    try:
        return requests.get(url, **kwargs)
    except SSLError:
        print("  WARNING: SSL certificate verification failed.")
        print("  Retrying without certificate verification.")
        print("  Tip: install or update the 'certifi' package to fix this permanently:")
        print("       pip install --upgrade certifi")
        kwargs['verify'] = False
        return requests.get(url, **kwargs)
