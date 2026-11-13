"""
Milestone 3, PR 12: the staff tools for organizations in the Django admin.

Staff create an organization for a customer, set its people limit, and run
actions on memberships, invites and join codes. Every action calls services.py
(so its rules hold for staff too), asks "are you sure?" first, and leaves a
history line that says who did it and holds nobody's email. Support staff can
look at everything and deactivate a membership; the rest is for superusers.
"""

from datetime import timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.enterprises import services
from apps.enterprises.models import Enterprise, Invite
from apps.entitlements import services as licences
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.survey.services import current_version

from .orgs import new_member, org_with_admin
from .test_enterprise_services import expire, refusal, spend_places
from .test_erasure import complete
from .test_profile import verified_account
from .test_verification import PASSWORD

ORGANIZATIONS = "/admin/enterprises/enterprise/"
MEMBERSHIPS = "/admin/enterprises/membership/"
INVITES = "/admin/enterprises/invite/"
CODES = "/admin/enterprises/joincode/"
PAGES = (ORGANIZATIONS, MEMBERSHIPS, INVITES, CODES)


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def support(client, db):
    account = Account.objects.create_user("support@example.com", PASSWORD)
    account.is_staff = True
    account.save()
    account.groups.add(Group.objects.get(name=GROUP_NAME))
    client.force_login(account)
    return account


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def member(acme):
    return new_member(acme[0], "bob@example.com")


@pytest.fixture
def invite(acme):
    return services.invite_by_email(acme[1], "carol@example.com")[0]


@pytest.fixture
def code(acme):
    return services.create_code(acme[1], 5)


def run(client, page, action, *rows, confirm=True):
    """Pick an action for some rows on a list page; `confirm` presses the page's button too."""
    data = {"action": action, "_selected_action": [row.pk for row in rows]}
    if confirm:
        data["confirm"] = "yes"
    else:
        data["index"] = "0"  # what the list page's own Go button sends
    return client.post(page, data, follow=True)


def said(response):
    """The messages shown at the top of the next page."""
    return " | ".join(str(message) for message in response.context["messages"])


def history(row):
    """The row's history lines, as (who, what)."""
    entries = LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(row), object_id=str(row.pk)
    )
    return [(entry.user, entry.get_change_message()) for entry in entries]


def draft_for(membership):
    """A licence for the membership and an unfinished attempt on it."""
    licence = licences.grant_for_membership(membership, 2, "manual", None)
    Response.objects.create(
        account=membership.account,
        survey_version=current_version(),
        entitlement=licence,
        membership=membership,
    )
    return licence


# --- organizations -----------------------------------------------------------------


@pytest.mark.django_db
class TestOrganizations:
    ADD = ORGANIZATIONS + "add/"

    def test_staff_create_one_for_a_customer_with_a_first_admin(self, client, root):
        customer = verified_account("customer@example.com")
        response = client.post(self.ADD, {"name": "  Acme   Ltd ", "account": customer.pk})
        assert response.status_code == 302
        acme = Enterprise.objects.get()
        assert (acme.name, acme.slug, acme.created_by) == ("Acme Ltd", "acme-ltd", root)
        first = acme.memberships.get()
        assert first.account == customer and first.is_admin and first.is_active
        assert [who for who, _ in history(acme)] == [root]

    def test_the_customer_needs_no_verified_email_and_the_cap_of_three_does_not_apply(
        self, client, root
    ):
        customer = verified_account("customer@example.com")
        for name in ("One", "Two", "Three"):
            services.create_enterprise(customer, name)
        assert "limit" in refusal(lambda: services.create_enterprise(customer, "Four"))
        client.post(self.ADD, {"name": "Four", "account": customer.pk})
        unverified = Account.objects.create_user("new@example.com", PASSWORD)
        client.post(self.ADD, {"name": "Five", "account": unverified.pk})
        assert Enterprise.objects.count() == 5
        assert Enterprise.objects.get(name="Five").memberships.get().account == unverified

    def test_the_first_admin_is_searched_for_not_listed(self, client, root):
        verified_account("customer@example.com")
        page = client.get(self.ADD).content.decode()
        assert "admin-autocomplete" in page and "customer@example.com" not in page
        found = client.get(
            "/admin/autocomplete/",
            {
                "app_label": "enterprises",
                "model_name": "enterprise",
                "field_name": "created_by",
                "term": "customer@ex",
            },
        )
        assert [row["text"] for row in found.json()["results"]] == ["customer@example.com"]

    def test_a_name_that_will_not_do_is_an_error_on_the_form(self, client, root):
        customer = verified_account("customer@example.com")
        page = client.post(self.ADD, {"name": " A ", "account": customer.pk})
        assert page.status_code == 200
        assert "Enter the organization" in page.content.decode()
        assert not Enterprise.objects.exists()

    def test_an_erased_or_switched_off_account_cannot_be_given_one(self, client, root):
        erased = verified_account("gone@example.com")
        complete(erased)
        erasure.erase_account(erased)
        off = verified_account("off@example.com")
        Account.objects.filter(pk=off.pk).update(is_active=False)
        for account in (erased, off):
            page = client.post(self.ADD, {"name": "Acme", "account": account.pk})
            assert page.status_code == 200
            assert "cannot have an organization" in page.content.decode()
        assert not Enterprise.objects.exists()

    def test_a_refusal_at_the_last_moment_is_a_message_not_a_crash(self, client, root, monkeypatch):
        customer = verified_account("customer@example.com")

        def refuse(*args, **kwargs):
            raise services.Refused("This account cannot have an organization.")

        monkeypatch.setattr(services, "create_enterprise", refuse)
        response = client.post(self.ADD, {"name": "Acme", "account": customer.pk}, follow=True)
        assert response.status_code == 200
        assert "cannot have an organization" in said(response)
        assert not Enterprise.objects.exists() and not LogEntry.objects.exists()

    def test_only_the_people_limit_can_be_changed(self, client, root, acme):
        enterprise, _ = acme
        url = f"{ORGANIZATIONS}{enterprise.pk}/change/"
        page = client.get(url).content.decode()
        assert 'name="people_limit"' in page
        assert 'name="name"' not in page and 'name="slug"' not in page
        response = client.post(url, {"people_limit": 40, "name": "Hacked", "slug": "hacked"})
        assert response.status_code == 302
        enterprise.refresh_from_db()
        assert (enterprise.people_limit, enterprise.name, enterprise.slug) == (40, "Acme", "acme")
        assert history(enterprise) == [(root, "Changed People limit.")]

    def test_a_lower_people_limit_refuses_the_next_invite_and_a_higher_one_lets_it_in(
        self, client, root, acme
    ):
        enterprise, admin = acme
        spend_places(enterprise, 3)
        url = f"{ORGANIZATIONS}{enterprise.pk}/change/"
        client.post(url, {"people_limit": 3})
        assert "no places left" in refusal(
            lambda: services.invite_by_email(admin, "dave@example.com")
        )
        client.post(url, {"people_limit": 4})
        assert services.invite_by_email(admin, "dave@example.com")[0].pk

    def test_its_page_counts_members_and_places(self, client, root, acme, member, code):
        enterprise, admin = acme
        new_member(enterprise, "left@example.com", active=False)
        services.invite_by_email(admin, "carol@example.com")
        services.redeem_code(code.code, verified_account("dave@example.com"))
        page = client.get(f"{ORGANIZATIONS}{enterprise.pk}/change/").content.decode()
        assert "23 of 25 left (1 invite(s) sent, 1 join(s) by code" in page
        listing = client.get(ORGANIZATIONS).content.decode()
        assert '<td class="field-members_now">3</td>' in listing  # admin, bob, dave
        assert enterprise.memberships.count() == 4  # "members ever" counts the one who left

    def test_it_is_found_by_name_or_slug_and_cannot_be_deleted(self, client, root, acme):
        org_with_admin("Other")
        for term in ("Acm", "acme"):
            listing = client.get(ORGANIZATIONS, {"q": term}).content.decode()
            assert "Acme" in listing and "Other" not in listing
        assert client.get(f"{ORGANIZATIONS}{acme[0].pk}/delete/").status_code == 403


# --- memberships -------------------------------------------------------------------


@pytest.mark.django_db
class TestMemberships:
    def test_every_action_asks_first_and_changes_nothing_until_confirmed(
        self, client, root, acme, member
    ):
        draft_for(member)
        for action in ("deactivate_selected", "reactivate_selected", "make_admin", "make_member"):
            page = run(client, MEMBERSHIPS, action, member, confirm=False)
            html = page.content.decode()
            assert page.status_code == 200 and 'name="confirm" value="yes"' in html
            assert f"Membership {member.pk} in Acme" in html
        member.refresh_from_db()
        assert member.is_active and not member.is_admin
        assert member.responses.count() == 1 and not history(member)

    def test_the_deactivate_page_warns_about_an_unfinished_attempt(self, client, root, member):
        page = run(client, MEMBERSHIPS, "deactivate_selected", member, confirm=False)
        assert "it will be deleted" not in page.content.decode()
        draft_for(member)
        page = run(client, MEMBERSHIPS, "deactivate_selected", member, confirm=False)
        assert "unfinished survey attempt for the organization: it will be deleted" in (
            page.content.decode()
        )

    def test_deactivating_deletes_the_draft_keeps_the_licence_and_says_who(
        self, client, root, member
    ):
        licence = draft_for(member)
        response = run(client, MEMBERSHIPS, "deactivate_selected", member)
        member.refresh_from_db()
        licence.refresh_from_db()
        assert not member.is_active and not member.responses.exists()
        assert licence.revoked_at is None
        assert "Deactivated 1 membership(s)." in said(response)
        assert "Deleted 1 unfinished survey attempt(s)." in said(response)
        assert history(member) == [
            (root, "Deactivated; the unfinished survey attempt for the organization was deleted")
        ]

    def test_a_submitted_survey_survives_deactivation(self, client, root, member):
        licence = licences.grant_for_membership(member, 1, "manual", None)
        Response.objects.create(
            account=member.account,
            survey_version=current_version(),
            entitlement=licence,
            membership=member,
            status="submitted",
            submitted_at=timezone.now(),
        )
        run(client, MEMBERSHIPS, "deactivate_selected", member)
        assert member.responses.filter(status="submitted").count() == 1
        assert history(member) == [(root, "Deactivated")]

    def test_the_only_admin_cannot_be_deactivated_or_made_a_member(
        self, client, root, acme, member
    ):
        _, admin = acme
        for action in ("deactivate_selected", "make_member"):
            response = run(client, MEMBERSHIPS, action, admin, member)
            assert f"Membership {admin.pk} in Acme: An organization needs at least one admin" in (
                said(response)
            )
            admin.refresh_from_db()
            assert admin.is_active and admin.is_admin and not history(admin)
        # The other selected row still went through.
        member.refresh_from_db()
        assert not member.is_active

    def test_reactivating_brings_someone_back_as_a_member(self, client, root, acme):
        left = new_member(acme[0], "left@example.com", active=False)
        response = run(client, MEMBERSHIPS, "reactivate_selected", left)
        left.refresh_from_db()
        assert left.is_active and not left.is_admin
        assert "Reactivated 1 membership(s)." in said(response)
        assert history(left) == [(root, "Reactivated")]

    def test_an_erased_member_cannot_be_reactivated(self, client, root, member):
        complete(member.account)
        erasure.erase_account(member.account)
        response = run(client, MEMBERSHIPS, "reactivate_selected", member)
        assert "was erased" in said(response) and "Nothing was reactivated." in said(response)
        member.refresh_from_db()
        assert not member.is_active

    def test_making_an_admin_and_a_member_again(self, client, root, acme, member):
        _, admin = acme
        response = run(client, MEMBERSHIPS, "make_admin", member)
        member.refresh_from_db()
        assert member.is_admin and "Changed 1 membership(s)." in said(response)
        # Now there are two admins, so the first can step back.
        run(client, MEMBERSHIPS, "make_member", admin)
        admin.refresh_from_db()
        assert not admin.is_admin
        assert history(member) == [(root, "Made an admin")]
        assert history(admin) == [(root, "Made an ordinary member")]

    def test_a_deactivated_member_cannot_be_made_an_admin(self, client, root, acme):
        left = new_member(acme[0], "left@example.com", active=False)
        response = run(client, MEMBERSHIPS, "make_admin", left)
        assert "Reactivate this member" in said(response)
        left.refresh_from_db()
        assert not left.is_admin

    def test_a_row_already_as_asked_is_left_alone_and_gets_no_history(
        self, client, root, acme, member
    ):
        _, admin = acme
        for action, row, nothing in (
            ("reactivate_selected", member, "Nothing was reactivated."),
            ("make_member", member, "Nothing was changed."),
            ("make_admin", admin, "Nothing was changed."),
        ):
            assert nothing in said(run(client, MEMBERSHIPS, action, row))
        services.deactivate_membership(member)
        response = run(client, MEMBERSHIPS, "deactivate_selected", member)
        assert "Nothing was deactivated." in said(response)
        assert not history(member) and not history(admin)

    def test_no_history_line_or_message_holds_an_email_or_a_name(self, client, root, acme, member):
        draft_for(member)
        shown = [
            said(run(client, MEMBERSHIPS, action, member, acme[1]))
            for action in (
                "make_admin",
                "make_member",
                "deactivate_selected",
                "reactivate_selected",
            )
        ]
        entries = LogEntry.objects.all()
        assert entries.count() >= 4
        kept = " ".join(f"{e.object_repr} {e.change_message}" for e in entries) + " ".join(shown)
        for secret in ("bob@", "admin@", "example.com", "Bob", "Example"):
            assert secret not in kept

    def test_a_membership_is_still_never_edited_added_or_deleted_by_hand(
        self, client, root, member
    ):
        url = f"{MEMBERSHIPS}{member.pk}/change/"
        assert client.get(url).status_code == 200
        assert client.post(url, {"role": "admin"}).status_code == 403
        assert client.get(MEMBERSHIPS + "add/").status_code == 403
        assert "delete_selected" not in client.get(MEMBERSHIPS).content.decode()


# --- invites and join codes --------------------------------------------------------


@pytest.mark.django_db
class TestInvites:
    def test_withdrawing_asks_first_then_stops_the_invite_and_says_who(
        self, client, root, acme, invite
    ):
        page = run(client, INVITES, "withdraw_selected", invite, confirm=False)
        assert f"Invite {invite.pk} to Acme" in page.content.decode()
        invite.refresh_from_db()
        assert invite.revoked_at is None
        response = run(client, INVITES, "withdraw_selected", invite)
        invite.refresh_from_db()
        assert invite.revoked_at is not None
        assert "Withdrew 1 invite(s)." in said(response)
        assert history(invite) == [(root, "Withdrawn")]
        # It still counts towards the people limit.
        assert services.places_left(acme[0]) == 24

    def test_an_accepted_invite_cannot_be_withdrawn(self, client, root, invite):
        services.accept_invite(invite.token, verified_account("carol@example.com"))
        response = run(client, INVITES, "withdraw_selected", invite)
        assert f"Invite {invite.pk}: That invite has already been accepted." in said(response)
        invite.refresh_from_db()
        assert invite.revoked_at is None and not history(invite)

    def test_withdrawing_twice_changes_nothing(self, client, root, invite):
        run(client, INVITES, "withdraw_selected", invite)
        first = Invite.objects.get(pk=invite.pk).revoked_at
        response = run(client, INVITES, "withdraw_selected", invite)
        assert "Nothing was withdrawn." in said(response)
        assert Invite.objects.get(pk=invite.pk).revoked_at == first
        assert len(history(invite)) == 1

    def test_the_list_says_where_each_invite_stands(self, client, root, acme, invite):
        _, admin = acme

        def state(row):
            html = client.get(INVITES).content.decode()
            start = html.index(f'name="_selected_action" value="{row.pk}"')
            cell = html.index('class="field-state">', start) + len('class="field-state">')
            return html[cell : html.index("<", cell)]

        assert state(invite) == "Waiting"
        expired = services.invite_by_email(admin, "dave@example.com")[0]
        expire(expired)
        assert state(expired) == "Expired"
        accepted = services.invite_by_email(admin, "erin@example.com")[0]
        services.accept_invite(accepted.token, verified_account("erin@example.com"))
        assert state(accepted) == "Accepted"
        services.revoke_invite(invite)
        assert state(invite) == "Withdrawn"
        Invite.objects.filter(pk=expired.pk).update(
            email="", expires_at=timezone.now() + timedelta(days=1)
        )
        assert state(expired) == "Address removed"

    def test_the_link_secret_is_not_on_the_confirmation_page_or_in_the_history(
        self, client, root, invite
    ):
        page = run(client, INVITES, "withdraw_selected", invite, confirm=False)
        assert invite.token not in page.content.decode()
        run(client, INVITES, "withdraw_selected", invite)
        entry = LogEntry.objects.get()
        assert invite.token not in entry.object_repr + entry.change_message
        assert "carol" not in entry.object_repr + entry.change_message


@pytest.mark.django_db
class TestJoinCodes:
    def test_switching_off_asks_first_then_stops_the_code_and_says_who(
        self, client, root, acme, code
    ):
        page = run(client, CODES, "switch_off_selected", code, confirm=False)
        html = page.content.decode()
        assert f"Join code {code.pk} for Acme" in html and code.code not in html
        response = run(client, CODES, "switch_off_selected", code)
        code.refresh_from_db()
        assert code.revoked_at is not None
        assert "Switched off 1 join code(s)." in said(response)
        assert history(code) == [(root, "Switched off")]
        assert "switched off" in refusal(
            lambda: services.redeem_code(code.code, verified_account("dave@example.com"))
        )

    def test_switching_off_twice_changes_nothing(self, client, root, code):
        run(client, CODES, "switch_off_selected", code)
        response = run(client, CODES, "switch_off_selected", code)
        assert "Nothing was switched off." in said(response)
        assert len(history(code)) == 1

    def test_the_list_says_where_each_code_stands_and_never_shows_a_code(
        self, client, root, acme, code
    ):
        _, admin = acme
        expired = services.create_code(admin, 5)
        expire(expired)
        used = services.create_code(admin, 1)
        services.redeem_code(used.code, verified_account("dave@example.com"))
        off = services.revoke_code(services.create_code(admin, 5))
        html = client.get(CODES).content.decode()
        for label in ("Working", "Expired", "Used up", "Switched off"):
            assert f'class="field-state">{label}<' in html
        for row in (code, expired, used, off):
            assert row.code not in html

    def test_a_superuser_can_read_the_code_on_its_own_page(self, client, root, code):
        assert code.code in client.get(f"{CODES}{code.pk}/change/").content.decode()


# --- support staff -----------------------------------------------------------------


@pytest.mark.django_db
class TestSupportStaff:
    def test_they_can_look_at_all_four(self, client, support, acme, member, invite, code):
        rows = {ORGANIZATIONS: acme[0], MEMBERSHIPS: member, INVITES: invite, CODES: code}
        for page, row in rows.items():
            assert client.get(page).status_code == 200
            assert client.get(f"{page}{row.pk}/change/").status_code == 200
            assert client.get(f"{page}{row.pk}/history/").status_code == 200

    def test_the_only_action_they_are_offered_is_deactivate(
        self, client, support, acme, member, invite, code
    ):
        html = client.get(MEMBERSHIPS).content.decode()
        assert 'value="deactivate_selected"' in html
        for action in ("reactivate_selected", "make_admin", "make_member"):
            assert f'value="{action}"' not in html
        assert 'value="withdraw_selected"' not in client.get(INVITES).content.decode()
        assert 'value="switch_off_selected"' not in client.get(CODES).content.decode()

    def test_they_can_deactivate_a_membership(self, client, support, member):
        draft_for(member)
        page = run(client, MEMBERSHIPS, "deactivate_selected", member, confirm=False)
        assert "it will be deleted" in page.content.decode()
        response = run(client, MEMBERSHIPS, "deactivate_selected", member)
        member.refresh_from_db()
        assert not member.is_active and "Deactivated 1 membership(s)." in said(response)
        assert [who for who, _ in history(member)] == [support]

    def test_posting_any_other_action_does_nothing(
        self, client, support, acme, member, invite, code
    ):
        left = new_member(acme[0], "left@example.com", active=False)
        run(client, MEMBERSHIPS, "reactivate_selected", left)
        run(client, MEMBERSHIPS, "make_admin", member)
        run(client, MEMBERSHIPS, "make_member", acme[1])
        run(client, INVITES, "withdraw_selected", invite)
        run(client, CODES, "switch_off_selected", code)
        for row in (left, member, acme[1], invite, code):
            row.refresh_from_db()
        assert not left.is_active and not member.is_admin and acme[1].is_admin
        assert invite.revoked_at is None and code.revoked_at is None
        assert not LogEntry.objects.exists()

    def test_they_cannot_create_an_organization_or_change_its_people_limit(
        self, client, support, acme
    ):
        enterprise, _ = acme
        customer = verified_account("customer@example.com")
        assert client.get(ORGANIZATIONS + "add/").status_code == 403
        add = client.post(ORGANIZATIONS + "add/", {"name": "Mine", "account": customer.pk})
        assert add.status_code == 403
        url = f"{ORGANIZATIONS}{enterprise.pk}/change/"
        assert 'name="people_limit"' not in client.get(url).content.decode()
        assert client.post(url, {"people_limit": 500}).status_code == 403
        enterprise.refresh_from_db()
        assert enterprise.people_limit == 25 and Enterprise.objects.count() == 1

    def test_they_never_see_a_join_code_or_an_invite_link_secret(
        self, client, support, invite, code
    ):
        for page, row, secret in ((CODES, code, code.code), (INVITES, invite, invite.token)):
            assert secret not in client.get(page).content.decode()
            assert secret not in client.get(f"{page}{row.pk}/change/").content.decode()

    def test_seeing_memberships_is_not_enough_to_deactivate_one(self, client, db, member):
        """Deactivating has its own permission; looking does not bring it along."""
        looker = Account.objects.create_user("looker@example.com", PASSWORD)
        looker.is_staff = True
        looker.save()
        looker.user_permissions.add(Permission.objects.get(codename="view_membership"))
        client.force_login(looker)
        html = client.get(MEMBERSHIPS).content.decode()
        assert 'value="deactivate_selected"' not in html
        run(client, MEMBERSHIPS, "deactivate_selected", member)
        member.refresh_from_db()
        assert member.is_active and not LogEntry.objects.exists()

    def test_staff_who_are_not_in_the_group_see_none_of_it(self, client, db, member):
        outsider = Account.objects.create_user("temp@example.com", PASSWORD)
        outsider.is_staff = True
        outsider.save()
        client.force_login(outsider)
        for page in PAGES:
            assert client.get(page).status_code == 403
        run(client, MEMBERSHIPS, "deactivate_selected", member)
        member.refresh_from_db()
        assert member.is_active
