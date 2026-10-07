"""
Settings shared by every environment.

Nothing in this file is specific to a laptop or a server. Anything that differs
between environments (secret key, database, allowed hosts) is read from
environment variables through django-environ. local.py and production.py import
this file and override what they need.
"""

from pathlib import Path

import environ

# BASE_DIR is the repository root: this file is config/settings/base.py, so
# three .parent hops up gets there.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Secrets and environment-specific values. env("X") raises if X is missing,
# which is what we want: a missing secret should fail loudly at startup.
SECRET_KEY = env("SECRET_KEY")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# env.db() parses a URL like postgres://user:pass@host:5432/dbname into the
# dict Django expects, including ENGINE = django.db.backends.postgresql.
DATABASES = {"default": env.db("DATABASE_URL")}

DEBUG = False


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files from the app itself, so gunicorn needs no
    # help from Caddy or S3. It must sit directly after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# Stored in UTC; rendered in the viewer's timezone later (see 03-tech-stack.md).

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"

# Where `collectstatic` gathers files for WhiteNoise to serve. Git-ignored.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Where our own source files live (Tailwind input and output).
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # Compresses files and adds a content hash to each filename so browsers
        # can cache them forever and still pick up changes after a deploy.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Email
# Django 6.1 uses MAILERS, not EMAIL_BACKEND. Console backend prints emails to
# the terminal; production.py will swap in SMTP later.

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
