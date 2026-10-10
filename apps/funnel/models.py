"""
Funnel events: what happened, and when, with nothing that says to whom.

Each row is one step someone took (signed up, verified their email, got a
licence, and so on). There is deliberately no link to an account or a person:
counting accounts would lose everyone who is later erased and shift the rates,
and a log of events is not personal data unless it points at a person. The
attributes are coarse (country, channel, tier) for the same reason.

All writes go through services.py; the models only describe the shape.
"""

from django.db import models


class FunnelEvent(models.Model):
    class Kind(models.TextChoices):
        SIGNED_UP = "signed_up", "Signed up"
        EMAIL_VERIFIED = "email_verified", "Verified their email"
        LICENCE_GRANTED = "licence_granted", "Got a licence"
        LICENCE_UPGRADED = "licence_upgraded", "Upgraded a licence"
        SURVEY_STARTED = "survey_started", "Started the survey"
        PAGE_LOCKED = "page_locked", "Finished a page"
        SURVEY_SUBMITTED = "survey_submitted", "Submitted the survey"

    class Channel(models.TextChoices):
        DIRECT = "direct", "Signed up directly"
        INVITE = "invite", "Enterprise invite"  # Milestone 3
        CODE = "code", "Enterprise join code"  # Milestone 3

    kind = models.CharField(max_length=30, choices=Kind)
    occurred_at = models.DateTimeField(auto_now_add=True)
    # Two-letter country of the phone number at sign-up; blank when unknown.
    country = models.CharField(max_length=2, blank=True)
    channel = models.CharField(max_length=10, choices=Channel, default=Channel.DIRECT)
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=20, blank=True)  # licence source: manual or purchase
    page = models.PositiveSmallIntegerField(null=True, blank=True)  # for "finished a page"

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["kind", "occurred_at"], name="funnel_kind_time")]

    def __str__(self):
        return f"{self.get_kind_display()} at {self.occurred_at:%Y-%m-%d %H:%M}"
