"""
The queue of background jobs in the staff admin.

Read-only: a job is made by the site and done by the worker. Staff look here
to see that the worker is keeping up (the line at the top says how long the
oldest job has waited) and to find a job that failed. A superuser can run a
failed job again and can queue a test job, which does nothing: if it shows as
done a few seconds later, the worker is alive.

Nothing here can show personal data: a job's payload holds numbers and plain
words only, and its error is only the kind of error.
"""

from django.contrib import admin, messages
from django.contrib.admin.options import ActionLocation
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from . import services
from .models import Job


def _minutes(waited):
    """A wait as people say it: "under a minute", "about 3 minutes"."""
    seconds = int(waited.total_seconds())
    if seconds < 60:
        return "under a minute"
    minutes = seconds // 60
    return "about 1 minute" if minutes == 1 else f"about {minutes:,} minutes"


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "status",
        "attempts",
        "created_at",
        "run_after",
        "finished_at",
        "last_error",
    )
    list_filter = ("status", "kind")
    search_fields = ("kind",)
    search_help_text = 'Search by the kind of job, for example "send_licence_email".'
    actions = ["run_again"]

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        actions = super().get_actions(request, action_location)
        if not request.user.is_superuser:
            actions.pop("run_again", None)
        return actions

    @admin.action(description="Run the selected failed jobs again")
    def run_again(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        again = sum(services.retry(failed) for failed in queryset)
        if again:
            self.message_user(
                request, f"{again} failed job(s) are back in the queue.", messages.SUCCESS
            )
        else:
            self.message_user(request, "None of those jobs had failed.", messages.WARNING)

    # --- the line at the top, and "Queue a test job" ---------------------------------

    def get_urls(self):
        custom = [
            path(
                "queue-a-test-job/",
                self.admin_site.admin_view(require_POST(self.queue_test_job)),
                name="jobs_job_test",
            ),
            path(
                "send-a-test-error/",
                self.admin_site.admin_view(self.send_test_error),
                name="jobs_job_test_error",
            ),
        ]
        return [*custom, *super().get_urls()]

    def changelist_view(self, request, extra_context=None):
        queue = services.waiting()
        if queue["count"] == 0:
            standing = "No job is waiting."
        else:
            standing = (
                f"{queue['count']:,} job(s) waiting; the oldest has waited "
                f"{_minutes(queue['oldest'])}."
            )
            if queue["behind"]:
                standing += " The worker is not keeping up, or is not running."
        extra_context = {
            **(extra_context or {}),
            "standing": standing,
            "behind": queue["behind"],
            "can_test": request.user.is_superuser,
            "test_url": reverse("admin:jobs_job_test"),
            "test_error_url": reverse("admin:jobs_job_test_error"),
        }
        return super().changelist_view(request, extra_context)

    def queue_test_job(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        queued = services.enqueue(services.TEST_KIND)
        self.message_user(
            request,
            f"{queued} is in the queue. Reload this page in a few seconds: if the worker is "
            'running, it will say "Done".',
            messages.SUCCESS,
        )
        return redirect("admin:jobs_job_changelist")

    def send_test_error(self, request):
        """
        "Send a test error": a page that says what will happen, and a button
        that fails on purpose. One press sends an error from the web site
        (this request) and one from the worker (a job that fails once), so a
        superuser can see both arrive in Sentry without SSH. The person who
        presses it sees the site's "Something went wrong" page: that is the
        test working.
        """
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method == "POST":
            services.send_test_error()
            raise services.DeliberateError(
                "A test error, sent on purpose from the Django admin. Nothing is wrong."
            )
        context = {
            **self.admin_site.each_context(request),
            "title": "Send a test error",
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/jobs/job/test_error.html", context)
