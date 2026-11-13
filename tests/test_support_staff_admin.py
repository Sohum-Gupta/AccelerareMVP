"""
T-19, points 5 and 6: two things in the Django admin's Accounts pages.

Point 5. An account's page used to show how its password is stored: the
hashing method, its settings and part of the hash. Nontechnical staff read
that as a fault or a leak. The page now says only whether a password is set,
and a superuser gets a "Set a new password" button.

Point 6. Making a colleague Support staff took two steps (the "staff" tick and
the Support staff group), and doing only one gave them an admin with nothing
in it. Two actions on the Accounts list now do both, ask first, and leave a
history line saying who did it. Only superusers have them.
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import Account
from apps.audit.models import AuditLog
from apps.responses.signals import GROUP_NAME

from .test_profile import verified_account

PASSWORD = "correct horse battery staple"
LIST = reverse("admin:accounts_account_changelist")


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def support(db):
    account = verified_account("support@example.com")
    services.make_support_staff(account)
    return account


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


def fresh(account):
    return Account.objects.get(pk=account.pk)


def in_group(account):
    return account.groups.filter(name=GROUP_NAME).exists()


def act(client, action, *accounts, confirmed=True):
    data = {"action": action, "_selected_action": [account.pk for account in accounts]}
    if confirmed:
        data["confirmed"] = "yes"
    return client.post(LIST, data, follow=True)


def said(response):
    return " | ".join(str(message) for message in response.context["messages"])


def page_of(client, account):
    return client.get(reverse("admin:accounts_account_change", args=[account.pk])).content.decode()


# --- point 5: the password block ---------------------------------------------------------------


@pytest.mark.django_db
class TestThePasswordLine:
    def test_the_page_says_a_password_is_set_and_shows_nothing_about_how_it_is_stored(
        self, client, root, bob
    ):
        page = page_of(client, bob)
        assert "A password is set. Nobody can see it, staff included." in page
        stored = bob.password  # "<method>$<settings and salt>$<hash>"
        parts = stored.split("$")
        for secret in (stored, parts[-1], parts[-2], "Raw passwords are not stored"):
            assert secret not in page
        for word in ("algorithm", "iterations", "salt", "hash"):
            assert word not in page.lower()

    def test_an_account_with_no_password_says_so(self, client, root, bob):
        bob.set_unusable_password()
        bob.save()
        assert "No password is set" in page_of(client, bob)

    def test_a_superuser_gets_a_button_to_set_a_new_one_and_it_works(self, client, root, bob):
        address = reverse("admin:auth_user_password_change", args=[bob.pk])
        assert f'href="{address}"' in page_of(client, bob) and "Set a new password…" in page_of(
            client, bob
        )
        new = "another made-up long password"
        client.post(address, {"password1": new, "password2": new})
        assert fresh(bob).check_password(new)

    def test_support_staff_see_the_line_and_no_button_and_cannot_set_one(
        self, client, support, bob
    ):
        client.force_login(support)
        page = page_of(client, bob)
        assert "A password is set." in page and "Set a new password" not in page
        address = reverse("admin:auth_user_password_change", args=[bob.pk])
        new = "another made-up long password"
        assert client.post(address, {"password1": new, "password2": new}).status_code == 403
        assert not fresh(bob).check_password(new)

    def test_an_erased_account_has_no_button(self, client, root, bob):
        from apps.accounts import erasure
        from apps.entitlements import services as licences

        from .test_matching import take

        licences.grant_individual(bob.person, 1, "manual")
        take(bob)
        erasure.erase_account(bob, by=root)
        page = page_of(client, bob)
        assert "No password is set" in page and "Set a new password" not in page


# --- point 6: Support staff --------------------------------------------------------------------


@pytest.mark.django_db
class TestTheServices:
    def test_making_support_staff_does_both_things(self, bob):
        assert services.make_support_staff(bob) is True
        assert fresh(bob).is_staff and in_group(bob) and services.is_support_staff(fresh(bob))
        assert not fresh(bob).is_superuser

    def test_doing_it_twice_changes_nothing_the_second_time(self, bob):
        services.make_support_staff(bob)
        assert services.make_support_staff(bob) is False

    def test_an_account_with_only_one_of_the_two_is_put_right(self, bob):
        """The half-done state the two-step way used to leave behind."""
        Account.objects.filter(pk=bob.pk).update(is_staff=True)
        assert not services.is_support_staff(fresh(bob))
        assert services.make_support_staff(bob) is True and in_group(bob)

    def test_taking_it_away_undoes_both(self, support):
        assert services.remove_support_staff(support) is True
        assert not fresh(support).is_staff and not in_group(support)
        assert services.remove_support_staff(support) is False

    def test_taking_it_away_clears_a_half_done_state_too(self, bob):
        bob.groups.add(Group.objects.get(name=GROUP_NAME))
        assert services.remove_support_staff(bob) is True and not in_group(bob)

    def test_an_erased_or_switched_off_account_is_refused(self, bob):
        Account.objects.filter(pk=bob.pk).update(is_active=False)
        with pytest.raises(ValidationError, match="erased or switched off"):
            services.make_support_staff(bob)
        assert not fresh(bob).is_staff and not in_group(bob)

    def test_a_superuser_is_left_alone_both_ways(self, root):
        with pytest.raises(ValidationError, match="already more"):
            services.make_support_staff(root)
        with pytest.raises(ValidationError, match="superuser"):
            services.remove_support_staff(root)
        assert fresh(root).is_staff and fresh(root).is_superuser and not in_group(root)

    def test_someone_made_support_staff_can_open_the_admin_and_sees_their_pages(self, client, bob):
        services.make_support_staff(bob)
        client.force_login(fresh(bob))
        index = client.get(reverse("admin:index")).content.decode()
        assert "Entitlements" in index and "Accounts" in index
        services.remove_support_staff(bob)
        assert client.get(reverse("admin:index")).status_code == 302  # sent to the login page


@pytest.mark.django_db
class TestTheActions:
    def test_the_action_asks_first_and_changes_nothing_until_confirmed(self, client, root, bob):
        response = act(client, "make_support_staff", bob, confirmed=False)
        page = response.content.decode()
        assert "Make these accounts Support staff?" in page and "bob@example.com" in page
        assert "Yes, make them Support staff" in page and "never the answers" in page
        assert f'name="_selected_action" value="{bob.pk}"' in page
        assert not fresh(bob).is_staff and not LogEntry.objects.exists()

    def test_confirmed_it_makes_them_support_staff_and_writes_the_history(self, client, root, bob):
        response = act(client, "make_support_staff", bob)
        assert services.is_support_staff(fresh(bob))
        assert "Made Support staff: 1 account(s)." in said(response)
        line = LogEntry.objects.get()
        assert line.user == root and line.object_id == str(bob.pk)
        assert line.change_message == "Made Support staff"
        copy = AuditLog.objects.get(action="admin.changed")
        assert copy.actor == root and copy.target_id == str(bob.pk)
        assert copy.detail["message"] == "Made Support staff"

    def test_taking_it_away_asks_first_then_does_it(self, client, root, support):
        page = act(client, "remove_support_staff", support, confirmed=False).content.decode()
        assert "Take these accounts off Support staff?" in page
        assert "no longer be able to log in to this admin" in page
        assert services.is_support_staff(fresh(support))
        response = act(client, "remove_support_staff", support)
        assert not fresh(support).is_staff and not in_group(support)
        assert "Taken off Support staff: 1 account(s)." in said(response)
        assert LogEntry.objects.get().change_message == "Taken off Support staff"

    def test_several_at_once_and_the_ones_refused_are_named_by_number(
        self, client, root, bob, support
    ):
        off = verified_account("carol@example.com")
        Account.objects.filter(pk=off.pk).update(is_active=False)
        response = act(client, "make_support_staff", bob, support, off, root)
        text = said(response)
        assert services.is_support_staff(fresh(bob))
        assert "Made Support staff: 1 account(s)." in text
        assert f"Account #{support.pk} was already Support staff." in text
        assert f"Account #{off.pk}: This account is erased or switched off." in text
        assert f"Account #{root.pk}: This account is a superuser" in text
        assert "@" not in text  # numbers, not addresses, in what is said
        assert LogEntry.objects.count() == 1

    def test_the_page_that_asks_warns_about_a_superuser_in_the_selection(self, client, root, bob):
        page = act(client, "make_support_staff", bob, root, confirmed=False).content.decode()
        assert "a superuser, so this will be refused" in page

    def test_support_staff_do_not_have_the_actions_and_cannot_force_them(
        self, client, support, bob
    ):
        client.force_login(support)
        listing = client.get(LIST).content.decode()
        assert "Make the selected accounts Support staff" not in listing
        assert "Take the selected accounts off Support staff" not in listing
        act(client, "make_support_staff", bob)
        assert not fresh(bob).is_staff and not in_group(bob)

    def test_a_superuser_sees_both_actions(self, client, root):
        listing = client.get(LIST).content.decode()
        assert "Make the selected accounts Support staff" in listing
        assert "Take the selected accounts off Support staff" in listing
