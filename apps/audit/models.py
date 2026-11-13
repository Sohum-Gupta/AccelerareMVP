"""
The audit log: who did what, and when.

One row for each thing a member of staff does in the Django admin and each
thing an organization's admin does on the site (invites, join codes, members,
licences, buying stock). It answers "who took that licence back, and when?"
long after the page that did it has moved on.

A row holds numbers and plain facts only: the number of the account that
acted, what kind of thing was acted on and its number, and a few details such
as a tier or a quantity. It never holds a name, an email address or an answer,
so erasing a person needs to change nothing here. If the account that acted is
deleted, the row stays and its actor is emptied.

Rows are only ever added, through services.py. Nothing edits or deletes one.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    # Who did it. Empty when the site did it by itself, or the account is gone.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # What was done, as "thing.what": "invite.created", "licence.taken_back".
    action = models.CharField(max_length=60)
    # What it was done to: the kind ("enterprises.invite") and its number. Kept
    # as plain values, not a link, so the row outlives the thing itself.
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    # A few plain facts about it: numbers and short words, never who.
    detail = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="audit_target"),
            models.Index(fields=["action", "at"], name="audit_action_time"),
        ]

    def __str__(self):
        about = f" {self.target_type} #{self.target_id}" if self.target_id else ""
        return f"{self.action}{about}"
