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
