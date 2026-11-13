"""
One person's attempt at the survey.

A Response is created when a licence is consumed (the one-to-one makes "one
licence, one attempt" a database rule), fills up as answers are saved, and
becomes immutable once submitted. `answers` is {"<question id>": value}; the
database id, not the position, so reordering questions later cannot corrupt old
answers. Everything is PROTECT: deleting an account, a survey version or a licence
is refused while a response points at it. Accounts are soft-deleted instead, and
a real erasure is a deliberate procedure that removes the responses first.

Context. An attempt is personal (`membership` is empty) or taken for one
organization (`membership` is the person's membership of it). The context is
never chosen separately: it is copied from the licence when the attempt starts
(services.start_response), so a response and its licence always agree, and the
licence decides who may see that the survey was taken. A person may have one
unfinished attempt per context: one personal, and one for each organization.

All writes go through services.py; the models only describe the shape and the
database rules. The service layer, not the model, enforces "locked pages stay
locked" and "submitted stays submitted".
"""

from django.db import models


class Response(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"

    class TookBeforeVia(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        COMPANY = "company", "Company"
        OTHER = "other", "Other"

    account = models.ForeignKey(
        "accounts.Account", on_delete=models.PROTECT, related_name="responses"
    )
    survey_version = models.ForeignKey(
        "survey.SurveyVersion", on_delete=models.PROTECT, related_name="responses"
    )
    # The reverse name is "response": Entitlement.objects.filter(response__isnull=True)
    # finds licences nobody has used yet.
    entitlement = models.OneToOneField(
        "entitlements.Entitlement", on_delete=models.PROTECT, related_name="response"
    )
    # Empty for a personal attempt; the membership for one taken for an
    # organization. Always the same as the licence's membership (the service
    # copies it). PROTECT: a membership is deactivated, never deleted, while a
    # response points at it.
    membership = models.ForeignKey(
        "enterprises.Membership",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="responses",
    )
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    answers = models.JSONField(default=dict, blank=True)
    # How many pages are locked (Next pressed). Page n is locked when this >= n.
    pages_completed = models.PositiveSmallIntegerField(default=0)
    # The self-report question; null means not answered yet. If yes, how they
    # took it; empty otherwise (a database rule, below).
    took_before = models.BooleanField(null=True, blank=True)
    took_before_via = models.CharField(max_length=20, choices=TookBeforeVia, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    possible_repeat = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            # A submitted response has a submit time and a draft has none.
            models.CheckConstraint(
                condition=(
                    models.Q(status="draft", submitted_at__isnull=True)
                    | models.Q(status="submitted", submitted_at__isnull=False)
                ),
                name="response_submitted_at_iff_submitted",
            ),
            # One open draft per account and context, so two tabs starting at
            # once cannot both create one. Two rules, because in SQL an empty
            # membership never counts as equal to another empty one: a single
            # rule on (account, membership) would let personal drafts pile up.
            models.UniqueConstraint(
                fields=["account"],
                condition=models.Q(status="draft", membership__isnull=True),
                name="response_one_open_personal_draft",
            ),
            models.UniqueConstraint(
                fields=["account", "membership"],
                condition=models.Q(status="draft", membership__isnull=False),
                name="response_one_open_draft_per_membership",
            ),
            # "How did you take it" is only an answer when "taken before" is yes.
            # (The null check matters: in SQL, NULL = true is NULL, and a check
            # constraint lets NULL through.)
            models.CheckConstraint(
                condition=(
                    models.Q(took_before_via="")
                    | models.Q(took_before__isnull=False, took_before=True)
                ),
                name="response_took_before_via_only_when_took_before",
            ),
        ]

    def __str__(self):
        return f"Response {self.pk} ({self.status})"
