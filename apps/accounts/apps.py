from allauth.account.apps import AccountConfig as AllauthBaseConfig
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    # This module now holds more than one AppConfig subclass, so Django needs
    # telling which one is ours; without this it falls back to a plain config
    # and ready() never runs (no signals, no verification).
    default = True
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        from . import signals  # noqa: F401  (connects the receivers)


class AllauthAccountConfig(AllauthBaseConfig):
    """
    allauth's "account" app calls its admin section "Accounts" too, which put
    two sections of that name in the sidebar. This renames allauth's; its app
    name stays "allauth.account", which is how allauth finds itself.
    """

    default = False  # never mistaken for apps.accounts
    verbose_name = "Login (allauth)"
