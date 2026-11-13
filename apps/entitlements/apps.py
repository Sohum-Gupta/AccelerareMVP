from django.apps import AppConfig


class EntitlementsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.entitlements"
    label = "entitlements"

    def ready(self):
        from . import signals  # noqa: F401  (connects the receiver)
