"""
Settings for running on your own machine.

Loads .env from the repository root *before* importing base, because base reads
SECRET_KEY and DATABASE_URL at import time and would fail if they were not yet
in the environment.
"""

from pathlib import Path

import environ

environ.Env.read_env(Path(__file__).resolve().parent.parent.parent / ".env")

from .base import *

DEBUG = True

# Locally nothing runs collectstatic, so the hashed-manifest storage from
# base.py would fail every {% static %} lookup when DEBUG is off (as in tests).
# Use plain storage and let WhiteNoise serve straight from static/.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
