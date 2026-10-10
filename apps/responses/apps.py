from django.apps import AppConfig


class ResponsesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.responses"
    label = "responses"

    def ready(self):
        from . import signals  # noqa: F401  (connects the receivers)
