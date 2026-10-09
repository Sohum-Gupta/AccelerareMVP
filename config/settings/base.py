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
    # allauth: verification links, the login flow and rate limits. Only the
    # core and the "account" (email + password) parts; no social login yet.
    "allauth",
    "allauth.account",
    "apps.accounts",
]

# Must be set before the first migration runs; changing it later means
# dropping the database. Email is the login identifier.
AUTH_USER_MODEL = "accounts.Account"

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
    # Required by allauth: it keeps the current request available to code
    # that sends mail, so the adapter can build absolute links.
    "allauth.account.middleware.AccountMiddleware",
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


# Authentication
# Django's own backend first (admin login, tests), then allauth's, which
# resolves an email login through allauth's EmailAddress table so any verified
# email on an account can log in.

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# URL names rather than paths, so the pages can move. The login page is
# allauth's until PR 4 replaces it under the same name.
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# allauth. Email is the only login identifier; there is no username field on
# Account. Verification is mandatory: nobody logs in until they have clicked
# the link sent to the address they are logging in with.
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# One owner per verified address (the same rule as ContactPoint), and an
# account may hold several addresses rather than swapping one for another.
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_CHANGE_EMAIL = False
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Accelerare] "

# Argon2 first: new passwords use it, and an existing PBKDF2 hash is upgraded
# the next time its owner logs in. The others stay so old hashes still verify.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]


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


# Cache
# allauth counts login and reset attempts in the cache. The default in-memory
# cache is private to each gunicorn worker, so the limits would only apply per
# worker. A table in PostgreSQL is shared by all of them. The table is created
# by `manage.py createcachetable` (deploy.sh runs it; tests create it alone).

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    },
}


# Email
# Django 6.1 uses MAILERS, not EMAIL_BACKEND. Console backend prints emails to
# the terminal; production.py will swap in SMTP later.

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
