"""
Production settings must import cleanly when the required environment
variables are present. Catches a typo on the laptop instead of on the server.
"""

import importlib


def test_production_settings_import(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
    monkeypatch.setenv("SENTRY_DSN", "")

    from config.settings import base, production

    importlib.reload(base)
    importlib.reload(production)

    assert production.DEBUG is False
    assert production.SECURE_SSL_REDIRECT is True
    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True
    assert production.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert production.USE_X_FORWARDED_HOST is True
    assert production.ALLOWED_HOSTS == ["example.com"]
