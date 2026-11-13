"""
The numbers at the top of the Django admin's first page (Milestone 6).

Staff open the admin many times a day. Its first page was only a list of
pages; now it starts with the handful of numbers that say how the site is
doing: accounts, organizations, surveys submitted, possible duplicates waiting
for a decision, and background jobs that failed or are waiting.

Two rules:

* Each number is a link to the list behind it, and that list shows the same
  number of rows. So every number is counted with exactly the filter its link
  puts on the list.
* A member of staff sees a number only if they may open that list, asked of
  the list's own admin page (`has_view_permission`), so a page that is for
  superusers only stays that way here. A number they may not see is not even
  counted.

This lives in the responses app because it is the one app that may import all
the others (tests/test_app_dependencies.py).
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account
from apps.enterprises.models import Enterprise
from apps.jobs import services as jobs
from apps.jobs.models import Job
from apps.matching.models import MatchCandidate

from .models import Response

# How far back "recently" goes for submitted surveys. The admin's own date
# filter has a "Past 7 days" choice, and the link uses it.
DAYS = 7


def _list(model, **filters):
    """The address of a model's list in the admin, with these filters on."""
    address = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    return f"{address}?{urlencode(filters)}" if filters else address


def _recent_days(now):
    """From midnight seven days ago to the coming midnight, as the admin's "Past 7 days" filter."""
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=DAYS), today + timedelta(days=1)


def numbers_for(request, now=None):
    """
    The lines to show this member of staff: a list of {"label", "number",
    "url", "warning"}. "warning" is a few plain words when the number needs
    attention, else empty. Empty list for someone who may open none of the lists.
    """
    now = now or timezone.now()

    def may_open(model):
        return admin.site.is_registered(model) and admin.site.get_model_admin(
            model
        ).has_view_permission(request)

    lines = []

    def add(label, number, url, warning=""):
        lines.append({"label": label, "number": number, "url": url, "warning": warning})

    if may_open(Account):
        add(
            "Accounts (not counting erased ones)",
            Account.objects.filter(anonymised_at__isnull=True).count(),
            _list(Account, anonymised_at__isempty=1),
        )
    if may_open(Enterprise):
        add("Organizations", Enterprise.objects.count(), _list(Enterprise))
    if may_open(Response):
        submitted = Response.objects.filter(status=Response.Status.SUBMITTED)
        since, until = _recent_days(now)
        add(
            f"Surveys submitted in the last {DAYS} days",
            submitted.filter(submitted_at__gte=since, submitted_at__lt=until).count(),
            # Only a submitted survey has a submit date, so the dates are filter enough.
            _list(Response, submitted_at__gte=str(since), submitted_at__lt=str(until)),
        )
        add(
            "Surveys submitted, all time",
            submitted.count(),
            _list(Response, status__exact=Response.Status.SUBMITTED),
        )
    if may_open(MatchCandidate):
        add(
            "Possible duplicates waiting for a decision",
            MatchCandidate.objects.filter(status=MatchCandidate.Status.FLAGGED).count(),
            _list(MatchCandidate, status__exact=MatchCandidate.Status.FLAGGED),
        )
    if may_open(Job):
        failed = Job.objects.filter(status=Job.Status.FAILED).count()
        add(
            "Background jobs that failed",
            failed,
            _list(Job, status__exact=Job.Status.FAILED),
            "open the list to see why, and to run them again" if failed else "",
        )
        add(
            "Background jobs waiting",
            Job.objects.filter(status=Job.Status.QUEUED).count(),
            _list(Job, status__exact=Job.Status.QUEUED),
            "the worker is not keeping up, or is not running"
            if jobs.waiting(now)["behind"]
            else "",
        )
    return lines
