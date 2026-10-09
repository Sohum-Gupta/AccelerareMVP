"""
Milestone 1, PR 7: the root admin, and the verified_email_required guard.
"""

import pytest
from allauth.account.models import EmailAddress
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.decorators import verified_email_required
from apps.accounts.models import Account, ContactPoint, Person

from .test_profile import second_email, verified_account
from .test_verification import PASSWORD


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


# --- the guard -----------------------------------------------------------------


@verified_email_required
def guarded(request):
    return HttpResponse("secret")


def call_guarded(client, account=None):
    from django.contrib.messages.storage.fallback import FallbackStorage

    request = RequestFactory().get("/guarded/")
    request.user = account
    request.session = client.session
    request._messages = FallbackStorage(request)
    return guarded(request)


@pytest.mark.django_db
def test_unverified_account_is_redirected_to_the_profile_and_sent_nothing(client, mailoutbox):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)  # as createsuperuser
    response = call_guarded(client, account)
    assert response.status_code == 302 and response.url == reverse("account_profile")
    assert mailoutbox == []


@pytest.mark.django_db
def test_anonymous_visitor_is_sent_to_login(client):
    from django.contrib.auth.models import AnonymousUser

    response = call_guarded(client, AnonymousUser())
    assert response.status_code == 302 and "/accounts/login/" in response.url


@pytest.mark.django_db
def test_verified_account_gets_through(client):
    response = call_guarded(client, verified_account())
    assert response.status_code == 200 and response.content == b"secret"


@pytest.mark.django_db
def test_profile_stays_open_to_an_unverified_account(client):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    assert client.get(reverse("account_profile")).status_code == 200


# --- the admin -----------------------------------------------------------------


@pytest.mark.django_db
def test_admin_pages_load(client, root):
    for model in ("account", "person", "contactpoint"):
        assert client.get(f"/admin/accounts/{model}/").status_code == 200


@pytest.mark.django_db
def test_admin_finds_an_account_by_email_and_by_phone(client, root):
    verified_account("bob@example.com")
    by_email = client.get("/admin/accounts/account/", {"q": "bob@example"}).content.decode()
    by_phone = client.get("/admin/accounts/account/", {"q": "+919876543210"}).content.decode()
    assert "bob@example.com" in by_email and "bob@example.com" in by_phone
    contacts = client.get("/admin/accounts/contactpoint/", {"q": "+919876543210"}).content.decode()
    assert "+919876543210" in contacts
    people = client.get("/admin/accounts/person/", {"q": "+919876543210"}).content.decode()
    assert "bob@example.com" in people


@pytest.mark.django_db
def test_admin_cannot_add_or_delete_contacts_or_edit_them_directly(client, root):
    contact = verified_account().contact_points.filter(kind="email").get()
    assert client.get("/admin/accounts/contactpoint/add/").status_code == 403
    assert client.post(f"/admin/accounts/contactpoint/{contact.pk}/delete/").status_code == 403
    client.post(f"/admin/accounts/contactpoint/{contact.pk}/change/", {"value_display": "x@y.com"})
    contact.refresh_from_db()
    assert contact.value_display == "bob@example.com"
    assert client.get("/admin/accounts/account/add/").status_code == 403


@pytest.mark.django_db
def test_admin_make_primary_changes_both_tables(client, root):
    account = verified_account()
    other = second_email(account, "other@example.com")
    client.post(
        "/admin/accounts/contactpoint/",
        {"action": "make_primary", "_selected_action": [other.pk]},
    )
    account.refresh_from_db()
    assert account.email == "other@example.com"
    assert EmailAddress.objects.get(user=account, primary=True).email == "other@example.com"
    other.refresh_from_db()
    assert other.is_primary


@pytest.mark.django_db
def test_admin_remove_goes_through_the_service_and_keeps_tables_in_step(client, root):
    account = verified_account()
    other = second_email(account, "other@example.com")
    primary = account.contact_points.get(kind="email", is_primary=True)
    client.post(
        "/admin/accounts/contactpoint/",
        {"action": "remove", "_selected_action": [other.pk, primary.pk]},
    )
    assert not ContactPoint.objects.filter(pk=other.pk).exists()
    assert not EmailAddress.objects.filter(user=account, email="other@example.com").exists()
    # the primary is refused by the service, so it is still on both sides
    assert ContactPoint.objects.filter(pk=primary.pk).exists()
    assert EmailAddress.objects.filter(user=account, email="bob@example.com").exists()


@pytest.mark.django_db
def test_admin_make_primary_of_an_unverified_email_is_refused(client, root):
    account = verified_account()
    unverified = second_email(account, "later@example.com", verified=False)
    client.post(
        "/admin/accounts/contactpoint/",
        {"action": "make_primary", "_selected_action": [unverified.pk]},
    )
    account.refresh_from_db()
    assert account.email == "bob@example.com"


@pytest.mark.django_db
def test_account_email_is_read_only_in_the_admin(client, root):
    account = verified_account()
    client.post(
        f"/admin/accounts/account/{account.pk}/change/",
        {"email": "hacked@example.com", "is_active": "on"},
    )
    account.refresh_from_db()
    assert account.email == "bob@example.com"
    assert Person.objects.filter(accounts=account).exists()
