"""
Helpers for the organization tests: made-up organizations and members.

Not a test file. Tests import these so each one reads as its own story without
repeating how an organization is put together.
"""

import threading

from django.db import connection
from django.utils import timezone
from django.utils.text import slugify

from apps.enterprises import services
from apps.enterprises.models import Enterprise, Membership

from .test_profile import verified_account


def make_enterprise(name="Acme", **extra):
    """A bare organization with nobody in it (numbered slug if the name is taken)."""
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


def org_with_admin(name="Acme", email=None):
    """An organization made the real way. Returns (enterprise, its admin's membership)."""
    email = email or f"admin@{slugify(name)}.example.com"
    enterprise = services.create_enterprise(verified_account(email), name)
    return enterprise, enterprise.memberships.get()


def new_member(enterprise, email, **extra):
    """A fresh verified account, put straight into the organization."""
    return add_member(enterprise, verified_account(email), **extra)


def run_together(*jobs):
    """
    Run each job in its own thread, all released at the same moment, and return
    what each returned (or the exception it raised), in order. Each thread gets
    its own database connection, as two web requests would; the test needs
    `@pytest.mark.django_db(transaction=True)` so the threads can see its data.
    """
    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)

    def run(index, job):
        try:
            barrier.wait(timeout=10)
            results[index] = job()
        except Exception as error:  # noqa: BLE001  (handed back to the test to assert on)
            results[index] = error
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def locked_tables(queries):
    """Which tables were read with FOR UPDATE in the captured SQL."""
    return {
        word.strip('"')
        for query in queries
        if "FOR UPDATE" in query["sql"]
        for word in query["sql"].split()
        if word.startswith('"') and "_" in word and "." not in word
    }
