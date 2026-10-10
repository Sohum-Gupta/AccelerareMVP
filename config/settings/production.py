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
# Sentry; we only want tracebacks and request context. Even so, the SDK would
# attach the request body (up to 10 KB) and every frame's local variables, which
# can hold answers, emails or the private survey wording, so both are off: an
# event carries the URL and the traceback, not the data.
sentry_sdk.init(
    dsn=env("SENTRY_DSN", default=""),
    send_default_pii=False,
    max_request_body_size="never",
    include_local_variables=False,
)

# Email. Django 6.1 configures senders through MAILERS; the SMTP backend takes
# its connection details as OPTIONS. base.py's console mailer is replaced here
# so the server really sends mail. All values are required: a missing one stops
# the app at startup instead of failing the first time someone resets a password.
# The credentials are Amazon SES SMTP credentials (a send-only IAM user), never
# a mailbox password.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("EMAIL_HOST"),
            "port": env.int("EMAIL_PORT", default=587),
            "username": env("EMAIL_HOST_USER"),
            "password": env("EMAIL_HOST_PASSWORD"),
            "use_tls": True,  # STARTTLS on port 587: encrypts the login and the message
            "timeout": 10,  # seconds; do not let a dead mail server hang a request
        },
    },
}

# The "From" address recipients see.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
