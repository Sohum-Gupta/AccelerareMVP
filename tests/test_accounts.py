import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

Account = get_user_model()


@pytest.mark.django_db
def test_create_user_hashes_password_and_normalises_email():
    account = Account.objects.create_user("Alice@Example.COM", "s3cret-pass")
    assert account.email == "Alice@example.com"  # domain lowercased, local part kept
    assert account.check_password("s3cret-pass")
    assert account.password != "s3cret-pass"
    assert account.is_active and not account.is_staff and not account.is_superuser


@pytest.mark.django_db
def test_create_user_without_password_is_unusable():
    account = Account.objects.create_user("bob@example.com")
    assert not account.has_usable_password()


@pytest.mark.django_db
def test_create_superuser_sets_flags():
    account = Account.objects.create_superuser("root@example.com", "s3cret-pass")
    assert account.is_staff and account.is_superuser


@pytest.mark.django_db
def test_email_is_unique():
    Account.objects.create_user("dup@example.com", "x")
    with pytest.raises(IntegrityError):
        Account.objects.create_user("dup@example.com", "y")


def test_email_is_required():
    with pytest.raises(ValueError):
        Account.objects.create_user("", "x")
