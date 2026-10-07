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
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_HOST_USER", "mailer@example.com")
    monkeypatch.setenv("EMAIL_HOST_PASSWORD", "app-password")
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "Accelerare <noreply@example.com>")

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

    mailer = production.MAILERS["default"]
    assert mailer["BACKEND"] == "django.core.mail.backends.smtp.EmailBackend"
    assert mailer["OPTIONS"]["host"] == "smtp.example.com"
    assert mailer["OPTIONS"]["port"] == 587  # default when EMAIL_PORT is unset
    assert mailer["OPTIONS"]["use_tls"] is True
    assert production.DEFAULT_FROM_EMAIL == "Accelerare <noreply@example.com>"


def test_production_requires_email_settings(monkeypatch):
    """A missing mail variable must stop startup, not fail on the first reset email."""
    import pytest
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("SECRET_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/db")
    monkeypatch.delenv("EMAIL_HOST", raising=False)

    from config.settings import base, production

    importlib.reload(base)
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(production)
