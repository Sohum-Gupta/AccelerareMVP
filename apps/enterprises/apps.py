from django.apps import AppConfig


class EnterprisesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.enterprises"
    label = "enterprises"
    # The site and the staff admin say "organization"; the code says "enterprise".
    verbose_name = "Organizations"
