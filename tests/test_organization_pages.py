"""
Milestone 3, PR 8: the organization pages under /organizations/.

Anyone with a verified email can create an organization and becomes its admin.
The list shows the organizations an account belongs to. The dashboard shows a
member the organization's name and the way to their own surveys; an admin also
gets the members page: name, email, role, status, joined date and licence, with
buttons to deactivate, reactivate, make admin and make member.

Who may open which page, and what no page shows, is in
tests/test_tenant_isolation.py. This file is about what the pages do.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import pytest
from django.urls import reverse

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise, Membership
from apps.entitlements import services as licences
from apps.responses import services as surveys
from apps.responses.models import Response

from .orgs import new_member, org_with_admin
from .test_erasure import complete
from .test_profile import second_email, verified_account
from .test_response_context import acme, fresh, grant, member  # noqa: F401
from .test_verification import PASSWORD

LIST = "/organizations/"
NEW = "/organizations/new/"
ACME = "/organizations/acme/"
MEMBERS = "/organizations/acme/members/"


def html(client, address):
    page = client.get(address)
    assert page.status_code == 200, f"{address} answered {page.status_code}"
    return page.content.decode()


def action(membership, what):
    return f"{MEMBERS}{membership.pk}/{what}/"


def after(client, address, data=None):
    """Send a form and return the page the person lands on, as (address, text)."""
    page = client.post(address, data or {}, follow=True)
    assert page.status_code == 200
    return page.redirect_chain[-1][0], page.content.decode()


def row(client, membership):
    """What the members page gave its template for one member."""
    rows = client.get(MEMBERS).context["rows"]
    return next(r for r in rows if r["id"] == membership.pk)


def named(membership, name):
    accounts.set_full_name(membership.account, name)
    return membership


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    named(acme[1], "Alice Example")
    client.force_login(acme[1].account)
    return acme[1]


@pytest.fixture
def bob(member):
    """Bob, an ordinary member of Acme (not logged in)."""
    return named(member, "Bob Example")


# --- creating an organization ----------------------------------------------------


@pytest.mark.django_db
class TestCreating:
    @pytest.fixture
    def carol(self, client):
        account = verified_account("carol@example.com")
        client.force_login(account)
        return account

    def test_the_page_has_one_box(self, client, carol):
        assert 'name="name"' in html(client, NEW)

    def test_creating_makes_the_person_its_admin_and_opens_the_dashboard(self, client, carol):
        landed, text = after(client, NEW, {"name": "  Carol's   Bakery "})
        bakery = Enterprise.objects.get()
        assert bakery.name == "Carol's Bakery" and bakery.created_by == carol
        assert landed == f"/organizations/{bakery.slug}/"
        membership = Membership.objects.get()
        assert membership.account == carol and membership.is_admin and membership.is_active
        assert "has been created. You are its admin." in text
        assert "You are an admin of this organization." in text

    def test_a_second_organization_of_the_same_name_gets_its_own_address(self, client, carol):
        after(client, NEW, {"name": "Acme"})
        landed, _ = after(client, NEW, {"name": "Acme"})
        assert landed == "/organizations/acme-2/"
        assert "Acme" in html(client, "/organizations/acme/")

    def test_a_blank_name_is_asked_for_again(self, client, carol):
        page = client.post(NEW, {"name": "   "})
        assert page.status_code == 200
        assert "Enter the organization&#x27;s name." in page.content.decode()
        assert not Enterprise.objects.exists()

    def test_a_name_the_rules_refuse_shows_why(self, client, carol):
        for name, why in [("A", "Enter the organization&#x27;s name."), ("x" * 121, "at most 120")]:
            page = client.post(NEW, {"name": name})
            assert page.status_code == 200 and why in page.content.decode()
        assert not Enterprise.objects.exists()

    def test_the_fourth_is_refused_in_plain_words(self, client, carol):
        for name in ("One", "Two", "Three"):
            after(client, NEW, {"name": name})
        page = client.post(NEW, {"name": "Four"})
        assert page.status_code == 200
        assert "You have created 3 organizations, which is the limit." in page.content.decode()
        assert Enterprise.objects.count() == 3

    def test_a_name_is_shown_as_typed_never_run_as_markup(self, client, carol):
        _, text = after(client, NEW, {"name": "<b>Acme</b>"})
        assert "<b>Acme</b>" not in text and "&lt;b&gt;Acme&lt;/b&gt;" in text

    def test_an_unverified_account_is_sent_to_the_profile(self, client, db):
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        for address in (LIST, NEW):
            assert client.get(address).url == reverse("account_profile")
        assert client.post(NEW, {"name": "Acme"}).url == reverse("account_profile")
        assert not Enterprise.objects.exists()


# --- the list ----------------------------------------------------------------------


@pytest.mark.django_db
class TestTheList:
    def test_someone_in_no_organization_is_told_so_and_can_create_one(self, client, db):
        client.force_login(verified_account("carol@example.com"))
        text = html(client, LIST)
        assert "You are not in an organization yet." in text
        assert f'href="{NEW}"' in text

    def test_it_lists_each_organization_with_the_persons_role(self, client, admin):
        globex, _ = org_with_admin("Globex")
        Membership.objects.create(enterprise=globex, account=admin.account)
        rows = client.get(LIST).context["rows"]
        assert rows == [
            {"name": "Acme", "slug": "acme", "is_admin": True},
            {"name": "Globex", "slug": "globex", "is_admin": False},
        ]
        text = html(client, LIST)
        assert f'href="{ACME}"' in text and 'href="/organizations/globex/"' in text
        assert "You are an admin" in text and "You are a member" in text

    def test_an_organization_the_person_has_left_is_not_listed(self, client, acme, bob):
        orgs.deactivate_membership(bob, by=acme[1])
        client.force_login(bob.account)
        assert client.get(LIST).context["rows"] == []


# --- the dashboard -----------------------------------------------------------------


@pytest.mark.django_db
class TestTheDashboard:
    def test_a_member_sees_the_name_and_the_way_to_their_own_survey(self, client, bob):
        client.force_login(bob.account)
        text = html(client, ACME)
        assert "<h1>Acme</h1>" in text
        assert "You are a member of this organization." in text
        assert 'href="/survey/start/acme/"' in text and 'href="/survey/history/"' in text
        assert MEMBERS not in text and "Manage members" not in text

    def test_an_admin_also_gets_the_members_link_and_two_counts(self, client, acme, admin, bob):
        carol = new_member(acme[0], "carol@example.com")
        orgs.deactivate_membership(carol, by=admin)
        page = client.get(ACME)
        text = page.content.decode()
        assert "You are an admin of this organization." in text
        assert f'href="{MEMBERS}"' in text and 'href="/survey/start/acme/"' in text
        assert page.context["current_members"] == 2
        assert page.context["all_time_members"] == 3

    def test_an_erased_member_still_counts_in_the_total(self, client, admin, bob):
        complete(bob.account)
        erasure.erase_account(bob.account)
        page = client.get(ACME)
        assert page.context["current_members"] == 1
        assert page.context["all_time_members"] == 2


# --- the members page --------------------------------------------------------------


@pytest.mark.django_db
class TestTheMembersPage:
    def test_it_shows_name_email_role_status_joined_date_and_licence(self, client, admin, bob):
        grant(bob, 2)
        text = html(client, MEMBERS)
        joined = f"Joined {bob.joined_at.day} {bob.joined_at:%B %Y}"
        for words in (
            "Alice Example",
            "admin@acme.example.com",
            "Bob Example",
            "bob@example.com",
            "Admin",
            "Member",
            "Active",
            joined,
            "Licence: Tier 2",
            "No licence",
            "(you)",
        ):
            assert words in text, words
        assert "2 members now" in text and "2 in total" in text

    def test_the_admins_own_row_is_marked(self, client, admin, bob):
        assert row(client, admin)["is_you"] and not row(client, bob)["is_you"]

    def test_an_account_from_before_names_were_asked_for(self, client, acme, admin):
        nameless = new_member(acme[0], "old@example.com")
        assert row(client, nameless)["name"] == ""
        assert "No name yet" in html(client, MEMBERS)

    def test_someone_who_joined_by_code_shows_their_login_address(self, client, acme, admin):
        code = orgs.create_code(admin, 5)
        carol = verified_account("carol@example.com")
        second_email(carol, "carol@work.example.com")
        joined = orgs.redeem_code(code.code, carol)
        assert row(client, joined)["email"] == "carol@example.com"
        assert "carol@work.example.com" not in html(client, MEMBERS)

    def test_someone_who_joined_by_invite_shows_the_invited_address(self, client, acme, admin):
        """The founder's rule: the organization sees the address it invited."""
        carol = verified_account("carol@example.com")
        second_email(carol, "carol@work.example.com")
        invite, _ = orgs.invite_by_email(admin, "carol@work.example.com")
        joined = orgs.accept_invite(invite.token, carol)
        assert row(client, joined)["email"] == "carol@work.example.com"
        assert "carol@example.com" not in html(client, MEMBERS)

    def test_the_licence_is_the_highest_one_that_still_counts(self, client, admin, bob):
        low, high = grant(bob, 1), grant(bob, 3)
        assert row(client, bob)["tier"] == 3
        licences.revoke(high)
        assert row(client, bob)["tier"] == 1
        licences.revoke(low)
        assert row(client, bob)["tier"] is None

    def test_an_erased_member_has_no_name_no_address_and_no_buttons(self, client, admin, bob):
        complete(bob.account)
        erasure.erase_account(bob.account)
        erased = row(client, bob)
        assert erased["name"] == "Erased member" and erased["email"] == ""
        assert erased["erased"] and not erased["active"]
        text = html(client, MEMBERS)
        assert "Erased member" in text
        assert "Bob Example" not in text and "bob@example.com" not in text
        assert "erased.invalid" not in text
        assert action(bob, "reactivate") not in text and action(bob, "role") not in text

    def test_active_members_come_first(self, client, acme, admin, bob):
        carol = new_member(acme[0], "carol@example.com")
        orgs.deactivate_membership(bob, by=admin)
        ids = [r["id"] for r in client.get(MEMBERS).context["rows"]]
        assert ids == [admin.pk, carol.pk, bob.pk]
        assert "Deactivated on" in html(client, MEMBERS)

    def test_the_only_admin_has_no_buttons_and_is_told_why(self, client, admin, bob):
        text = html(client, MEMBERS)
        assert row(client, admin)["only_admin"]
        assert "The only admin." in text
        assert action(admin, "deactivate") not in text and action(admin, "role") not in text
        # Bob, a member, can be made an admin or deactivated.
        assert action(bob, "role") in text and action(bob, "deactivate") in text
        assert "Make admin" in text and "Make member" not in text

    def test_with_two_admins_either_can_be_changed(self, client, admin, bob):
        orgs.set_role(bob, "admin", by=admin)
        text = html(client, MEMBERS)
        assert "The only admin." not in text
        for membership in (admin, bob):
            assert action(membership, "role") in text
            assert action(membership, "deactivate") in text
        assert "Make member" in text and "Make admin" not in text

    def test_a_deactivated_member_can_only_be_reactivated(self, client, admin, bob):
        orgs.deactivate_membership(bob, by=admin)
        text = html(client, MEMBERS)
        assert action(bob, "reactivate") in text
        assert action(bob, "role") not in text and action(bob, "deactivate") not in text


# --- deactivating and reactivating -------------------------------------------------


@pytest.mark.django_db
class TestDeactivating:
    def test_it_asks_first_and_says_what_will_happen(self, client, admin, bob):
        text = html(client, action(bob, "deactivate"))
        assert "Deactivate Bob Example?" in text
        assert "unfinished survey for Acme, it is deleted" in text
        assert "A join code will not let them back in." in text
        assert f'href="{MEMBERS}"' in text  # Cancel
        assert fresh(bob).is_active

    def test_confirming_deactivates_the_member(self, client, admin, bob):
        landed, text = after(client, action(bob, "deactivate"))
        assert landed == MEMBERS
        assert "Bob Example has been deactivated." in text
        assert "was deleted" not in text
        assert not fresh(bob).is_active

    def test_it_says_when_an_unfinished_survey_was_deleted(self, client, admin, bob):
        grant(bob)
        surveys.start_response(bob.account, bob)
        _, text = after(client, action(bob, "deactivate"))
        assert "Their unfinished survey for Acme was deleted." in text
        assert not Response.objects.exists()

    def test_the_only_admin_is_refused_in_plain_words(self, client, admin, bob):
        landed, text = after(client, action(admin, "deactivate"))
        assert landed == MEMBERS
        assert "An organization needs at least one admin." in text
        assert fresh(admin).is_active and fresh(admin).is_admin

    def test_an_admin_can_leave_once_there_is_another(self, client, admin, bob):
        orgs.set_role(bob, "admin", by=admin)
        assert "Leave Acme?" in html(client, action(admin, "deactivate"))
        landed, text = after(client, action(admin, "deactivate"))
        assert landed == LIST
        assert "You are no longer a member of Acme." in text
        assert not fresh(admin).is_active
        assert client.get(ACME).status_code == 404

    def test_someone_already_deactivated_is_left_alone(self, client, admin, bob):
        orgs.deactivate_membership(bob, by=admin)
        before = fresh(bob).deactivated_at
        for send in (client.get, client.post):
            page = send(action(bob, "deactivate"), follow=True)
            assert page.redirect_chain[-1][0] == MEMBERS
            assert "Bob Example is already deactivated." in page.content.decode()
        assert fresh(bob).deactivated_at == before

    def test_reactivating_brings_them_back_as_a_member(self, client, admin, bob):
        orgs.set_role(bob, "admin", by=admin)
        orgs.deactivate_membership(bob, by=admin)
        landed, text = after(client, action(bob, "reactivate"))
        assert landed == MEMBERS and "Bob Example is a member again." in text
        assert fresh(bob).is_active and not fresh(bob).is_admin

    def test_an_erased_member_cannot_be_reactivated(self, client, admin, bob):
        complete(bob.account)
        erasure.erase_account(bob.account)
        _, text = after(client, action(bob, "reactivate"))
        assert "account was erased, so it cannot be reactivated" in text
        assert not fresh(bob).is_active

    def test_a_member_without_a_name_is_still_spoken_of(self, client, acme, admin):
        nameless = new_member(acme[0], "old@example.com")
        assert "Deactivate this member?" in html(client, action(nameless, "deactivate"))
        _, text = after(client, action(nameless, "deactivate"))
        assert "The member has been deactivated." in text


# --- roles -------------------------------------------------------------------------


@pytest.mark.django_db
class TestRoles:
    def test_make_admin_then_make_member(self, client, admin, bob):
        landed, text = after(client, action(bob, "role"), {"role": "admin"})
        assert landed == MEMBERS and "Bob Example is now an admin." in text
        assert fresh(bob).is_admin
        _, text = after(client, action(bob, "role"), {"role": "member"})
        assert "Bob Example is now a member, not an admin." in text
        assert not fresh(bob).is_admin

    def test_the_only_admin_cannot_be_made_a_member(self, client, admin, bob):
        _, text = after(client, action(admin, "role"), {"role": "member"})
        assert "An organization needs at least one admin." in text
        assert fresh(admin).is_admin

    def test_an_admin_who_steps_down_lands_on_the_dashboard(self, client, admin, bob):
        orgs.set_role(bob, "admin", by=admin)
        landed, text = after(client, action(admin, "role"), {"role": "member"})
        assert landed == ACME
        assert "You are no longer an admin of Acme." in text
        assert "You are a member of this organization." in text
        assert client.get(MEMBERS).status_code == 404

    def test_a_role_that_does_not_exist_is_refused(self, client, admin, bob):
        for data in ({"role": "owner"}, {}):
            _, text = after(client, action(bob, "role"), data)
            assert "The role must be member or admin." in text
        assert not fresh(bob).is_admin

    def test_a_deactivated_member_cannot_be_given_a_role(self, client, admin, bob):
        orgs.deactivate_membership(bob, by=admin)
        _, text = after(client, action(bob, "role"), {"role": "admin"})
        assert "Reactivate this member before changing their role." in text

    def test_the_buttons_are_post_only(self, client, admin, bob):
        for what in ("reactivate", "role"):
            assert client.get(action(bob, what)).status_code == 405

    def test_a_membership_that_does_not_exist_is_not_found(self, client, admin):
        for what in ("deactivate", "reactivate", "role"):
            assert client.post(f"{MEMBERS}999999/{what}/", {"role": "admin"}).status_code == 404


# --- the ways in -------------------------------------------------------------------


@pytest.mark.django_db
class TestTheWaysIn:
    def test_the_header_links_there_once_logged_in(self, client, db):
        assert f'href="{LIST}"' not in client.get("/accounts/login/").content.decode()
        client.force_login(verified_account("carol@example.com"))
        assert f'href="{LIST}"' in html(client, "/survey/history/")

    def test_the_profile_has_a_box_for_it(self, client, db):
        client.force_login(verified_account("carol@example.com"))
        text = html(client, reverse("account_profile"))
        assert f'href="{LIST}"' in text and "Your organizations" in text
