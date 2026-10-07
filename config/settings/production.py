"""
Settings for the server.

Everything here assumes the app runs behind Caddy, which terminates TLS and
forwards plain HTTP to gunicorn on port 8000. Environment variables come from
the container's environment, never from a .env file in the image.
"""

import sentry_sdk

from .base import *
from .base import env

DEBUG = False

# Caddy sets X-Forwarded-Proto: https on every request it forwards. Without
# these two settings Django would think every request is plain HTTP and
# SECURE_SSL_REDIRECT would redirect forever.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# HTTPS hardening. Cookies are only sent over HTTPS, HTTP is redirected, and
# browsers are told to remember that for a year (HSTS).
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Error tracking. send_default_pii=False keeps user emails and IPs out of
# Sentry; we only want tracebacks and request context.
sentry_sdk.init(
    dsn=env("SENTRY_DSN", default=""),
    send_default_pii=False,
)
