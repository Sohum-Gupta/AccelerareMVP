"""
Settings for the test suite (pytest reads this through pyproject.toml).

The same as local.py, with two changes. Stripe's keys are blanked (see the
bottom of the file). And passwords are hashed with a fast, weak hasher. The real one, Argon2, is slow on purpose, so that stolen
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

# The tests never talk to Stripe. A laptop's .env may hold a real test key
# (local.py reads it); these lines make sure no test can pick it up. A test
# that needs a key sets a made-up one, and tests/conftest.py stops any test
# from reaching Stripe's servers whatever the settings say.
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""
STRIPE_AUTOMATIC_TAX = False
