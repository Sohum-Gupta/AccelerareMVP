"""
Identity: who is this?

Person is the human. Account is one login. ContactPoint is one email or phone
on one account, with a date it was proven. Today a person has one account;
Milestone 5 can link a second account to the same person, and that is why the
two are separate tables from the start.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models, transaction

from .services import normalise_email


class Person(models.Model):
    """
    The human behind one or more accounts. It carries nothing itself; it is the
    thing responses, entitlements and repeat detection point at.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    # Set by a Milestone 5 merge: this person's accounts now belong to another
    # person. Cleared by unmerge. Nullable because most people are never merged.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from"
    )

    def __str__(self):
        return f"Person {self.pk}"


class AccountManager(BaseUserManager):
    """
    Django's createsuperuser command and our own services call these two
    methods. The default manager expects a username, so we replace it.

    Every account made here also gets its own Person and a primary, unverified
    email ContactPoint, so the rest of the code can rely on both existing.
    A phone is the sign-up form's job (createsuperuser has none).
    """

    use_in_migrations = True

    def _create(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        typed = email.strip()  # kept for display; the login name below is normalised
        email = self.normalize_email(typed)
        with transaction.atomic():
            person = Person.objects.create()
            account = self.model(email=email, person=person, **extra_fields)
            account.set_password(password)  # hashes; None gives an unusable password
            account.save(using=self._db)
            ContactPoint.objects.create(
                account=account,
                kind=ContactPoint.Kind.EMAIL,
                value_normalised=normalise_email(email),
                value_display=typed,
                is_primary=True,
            )
        return account

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create(email, password, **extra_fields)


class Account(AbstractBaseUser, PermissionsMixin):
    """One login. `email` is the login name and always equals the primary email ContactPoint."""

    # AbstractBaseUser supplies `password` and `last_login`.
    # PermissionsMixin supplies `is_superuser`, `groups` and `user_permissions`.
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # may log into /admin/
    created_at = models.DateTimeField(auto_now_add=True)
    # Nullable only because accounts existed before Person did; the 0003 data
    # migration fills it in. A later PR makes it required once every row has one.
    # PROTECT: a person cannot be deleted while a login still points at it.
    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.PROTECT, related_name="accounts"
    )

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # createsuperuser prompts for USERNAME_FIELD + these

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email


class ContactPoint(models.Model):
    """
    One email or phone on one account.

    `verified_at` is null until the owner proves it (a clicked link for email;
    SMS later for phone). Only verified contact points ever take part in
    password reset, login or matching, and a verified value belongs to exactly
    one account: that is the rule that stops anyone claiming your address.
    """

    class Kind(models.TextChoices):
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone"

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="contact_points")
    kind = models.CharField(max_length=5, choices=Kind.choices)
    # The comparison form: lowercased email, or a phone in +E.164. Matching
    # and the uniqueness rules read this column only.
    value_normalised = models.CharField(max_length=254)
    # As the person typed it, for display.
    value_display = models.CharField(max_length=254)
    verified_at = models.DateTimeField(null=True, blank=True)
    # The primary email is the login name and where mail goes by default; the
    # primary phone is simply the account's phone.
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "-is_primary", "created_at"]
        constraints = [
            # Rule 1: a verified value has one owner. Unverified copies on other
            # accounts are fine; only the proof is exclusive.
            models.UniqueConstraint(
                fields=["kind", "value_normalised"],
                condition=models.Q(verified_at__isnull=False),
                name="contactpoint_one_owner_per_verified_value",
            ),
            # Rule 2: an account cannot list the same value twice.
            models.UniqueConstraint(
                fields=["account", "kind", "value_normalised"],
                name="contactpoint_no_duplicate_on_account",
            ),
            # Rule 3: at most one primary email and one primary phone per account.
            models.UniqueConstraint(
                fields=["account", "kind"],
                condition=models.Q(is_primary=True),
                name="contactpoint_one_primary_per_kind",
            ),
        ]

    def __str__(self):
        return self.value_display
