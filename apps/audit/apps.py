from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    label = "audit"
    verbose_name = "Audit log"

    def ready(self):
        from . import admin_history  # noqa: F401  (starts copying the admin's history lines)
