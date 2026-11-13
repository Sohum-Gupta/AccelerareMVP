"""
Settings for the test suite (pytest reads this through pyproject.toml).

The same as local.py, with one change: passwords are hashed with a fast,
weak hasher. The real one, Argon2, is slow on purpose, so that stolen
passwords are hard to crack. Almost every test makes an account, so the suite
paid that cost hundreds of times and it was most of the running time.

This file is never used to run the site: manage.py uses local.py and the
server uses production.py, and both keep Argon2. One test
(tests/test_allauth_setup.py) puts the real hashers back and checks that a new
password is hashed with Argon2; another (tests/test_settings.py) checks that
the fast hasher is here and nowhere else.
"""

from .local import *

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
