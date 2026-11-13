from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.jobs"
    label = "jobs"
    verbose_name = "Background jobs"

    def ready(self):
        # Every app keeps the functions that do its jobs in a file called
        # job_handlers.py. Importing them here, once Django has started, is what
        # tells the queue which kinds of job exist.
        autodiscover_modules("job_handlers")
