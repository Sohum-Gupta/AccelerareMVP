"""
Possible duplicates: two accounts that look like the same person.

One row is one pair of accounts and what they have in common. Finding a pair
changes nothing for either account and tells neither of them: the row waits
for a superuser, who says "same person" (the two logins are linked and share
their personal licences) or "different people" (the pair is closed and never
raised again). A link can be undone.

`signals` holds only the names of the rules that found the pair ("same_phone",
"same_name"), never the phone number or the name itself. If either account is
deleted or erased, the row goes with it: it was about a person who is gone.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.db import models


class MatchCandidate(models.Model):
    class Status(models.TextChoices):
        FLAGGED = "flagged", "Waiting for a decision"
        CONFIRMED = "confirmed", "Same person: linked"
        REJECTED = "rejected", "Different people"
        UNLINKED = "unlinked", "Linked, then undone"

    # The pair, always with the lower account number first, so that one pair
    # can only ever be stored one way round (two database rules, below).
    account_a = models.ForeignKey("accounts.Account", on_delete=models.CASCADE, related_name="+")
    account_b = models.ForeignKey("accounts.Account", on_delete=models.CASCADE, related_name="+")
    # The names of the rules that found this pair (matching/rules.py).
    signals = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.FLAGGED)
    created_at = models.DateTimeField(auto_now_add=True)
    # Which superuser decided, and when. Empty while it waits.
    resolved_by = models.ForeignKey(
        "accounts.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Set when the two are linked: the person the second login had to itself
    # before, which is where undoing the link puts it back.
    old_person = models.ForeignKey(
        "accounts.Person", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        # Those waiting for a decision first (they have no decision date), newest first.
        ordering = [models.F("resolved_at").asc(nulls_first=True), "-created_at", "-id"]
        verbose_name = "possible duplicate"
        constraints = [
            models.UniqueConstraint(
                fields=["account_a", "account_b"], name="matchcandidate_one_row_per_pair"
            ),
            models.CheckConstraint(
                condition=models.Q(account_a__lt=models.F("account_b")),
                name="matchcandidate_lower_account_first",
            ),
        ]

    def __str__(self):
        # Numbers only: this label goes into the admin's history.
        return f"Possible duplicate {self.pk}: accounts {self.account_a_id} and {self.account_b_id}"
