"""
The custom user model.

Account is the login identity: one row per sign-in. Email is the identifier
instead of Django's default username. In Milestone 1 it gains a `person`
foreign key and a ContactPoint table for additional verified emails/phones.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class AccountManager(BaseUserManager):
    """
    Django's createsuperuser command and our own services call these two
    methods. The default manager expects a username, so we replace it.
    """

    use_in_migrations = True

    def _create(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        account = self.model(email=email, **extra_fields)
        account.set_password(password)  # hashes; None gives an unusable password
        account.save(using=self._db)
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
    # AbstractBaseUser supplies `password` and `last_login`.
    # PermissionsMixin supplies `is_superuser`, `groups` and `user_permissions`.
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # may log into /admin/
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # createsuperuser prompts for USERNAME_FIELD + these

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email
