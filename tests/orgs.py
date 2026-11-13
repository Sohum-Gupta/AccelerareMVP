"""
Helpers for the organization tests: made-up organizations and members.

Not a test file. Tests import these so each one reads as its own story without
repeating how an organization is put together.
"""

from django.utils import timezone
from django.utils.text import slugify

from apps.enterprises.models import Enterprise, Membership


def make_enterprise(name="Acme", **extra):
    """An organization with a slug made from its name (numbered if the name is taken)."""
    base = slugify(name)
    slug, n = base, 1
    while Enterprise.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return Enterprise.objects.create(name=name, slug=slug, **extra)


def add_member(enterprise, account, role="member", active=True, **extra):
    """Put an account straight into an organization, skipping invites and codes."""
    if not active:
        extra = {"status": "deactivated", "deactivated_at": timezone.now(), **extra}
    return Membership.objects.create(enterprise=enterprise, account=account, role=role, **extra)
