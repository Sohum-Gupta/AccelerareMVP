"""
Milestone 5, PR 3: the audit log.

The rule. Who did what, and when, is kept in one place: every action of staff
in the Django admin, and what an organization's admins do on the site
(invites, join codes, members, licences, buying stock). A row holds numbers
and plain facts, never a name, an email address or an answer. It is written
in the same transaction as the action, so an undone action leaves no row.
Superusers read it in the Django admin; nobody can change it there.
"""

import json

import pytest
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.urls import reverse

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise
from apps.entitlements import services as licences
from apps.payments import services as buying
from apps.responses.signals import GROUP_NAME

from . import payments
from .orgs import new_member, org_with_admin
from .test_enterprise_services import refusal
from .test_profile import verified_account
from .test_verification import fake_request

PASSWORD = "correct horse battery staple"
BOB = "bob@example.com"
CAROL = "carol@example.com"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with three Tier 2 licences bought"""
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 3)
    orgs.set_seat_pool(enterprise, 3, 1)
    return enterprise, admin


@pytest.fixture
def bob(acme):
    return new_member(acme[0], BOB)


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


def rows(action=None):
    """The audit rows, oldest first, optionally of one action."""
    found = AuditLog.objects.order_by("id")
    return list(found.filter(action=action) if action else found)


def only(action):
    """The one row of this action."""
    (row,) = rows(action)
    return row


def is_about(row, actor, target, **detail):
    """True if the row says this account did it to this thing, with these facts."""
    return (
        row.actor_id == actor.pk
        and row.target_type == target._meta.label_lower
        and row.target_id == str(target.pk)
        and all(row.detail.get(key) == value for key, value in detail.items())
    )


# --- writing a row ----------------------------------------------------------------------------


@pytest.mark.django_db
class TestRecord:
    def test_a_row_keeps_who_what_and_the_number_of_the_thing(self, acme):
        enterprise, admin = acme
        row = audit.record(admin.account, "something.done", enterprise, tier=2, sent=True)
        assert row.actor == admin.account and row.action == "something.done"
        assert (row.target_type, row.target_id) == ("enterprises.enterprise", str(enterprise.pk))
        assert row.detail == {"tier": 2, "sent": True} and row.at is not None

    def test_the_actor_may_be_given_as_a_number_or_left_out(self, acme):
        assert audit.record(acme[1].account_id, "x.y").actor == acme[1].account
        nobody = audit.record(None, "x.y")
        assert nobody.actor is None and (nobody.target_type, nobody.target_id) == ("", "")

    def test_anything_shaped_like_an_email_address_is_removed_before_it_is_stored(self, db):
        row = audit.record(None, "x.y", note=f"sent to {CAROL} today", list=[CAROL, 3])
        assert row.detail == {"note": "sent to [removed] today", "list": ["[removed]", 3]}

    def test_a_row_written_inside_something_that_is_undone_does_not_exist(self, db):
        with pytest.raises(RuntimeError), transaction.atomic():
            audit.record(None, "x.y")
            raise RuntimeError("the action failed after all")
        assert rows() == []

    def test_the_row_stays_with_no_actor_when_the_account_is_deleted(self, db):
        carol = verified_account(CAROL)
        row = audit.record(carol, "x.y")
        carol.delete()
        row.refresh_from_db()
        assert row.actor is None and row.action == "x.y"


# --- what an organization's admin does --------------------------------------------------------


@pytest.mark.django_db
class TestOrganizationAdmins:
    def test_creating_an_organization(self, db):
        enterprise, admin = org_with_admin("Acme")
        assert is_about(only("organization.created"), admin.account, enterprise)

    def test_staff_creating_one_is_left_to_the_admins_own_history(self, db):
        staff = Account.objects.create_superuser("root@example.com", PASSWORD)
        orgs.create_enterprise(verified_account(CAROL), "Acme", staff=staff)
        assert rows("organization.created") == []

    def test_an_invite_and_what_becomes_of_it(self, acme):
        enterprise, admin = acme
        invite, _ = orgs.invite_by_email(admin, CAROL, 2, request=fake_request())
        orgs.resend_invite(invite, admin, request=fake_request())
        orgs.move_invite(invite, "dave@example.com", admin, request=fake_request())
        orgs.revoke_invite(invite, admin)
        made, again, moved, withdrawn = rows()[-4:]
        assert [row.action for row in (made, again, moved, withdrawn)] == [
            "invite.created",
            "invite.emailed_again",
            "invite.moved",
            "invite.withdrawn",
        ]
        assert is_about(made, admin.account, invite, organization=enterprise.pk, tier=2)
        assert is_about(again, admin.account, invite, sent=True)
        assert is_about(moved, admin.account, invite) and is_about(withdrawn, admin.account, invite)

    def test_an_email_the_mail_server_refused_is_recorded_as_not_sent(self, acme, monkeypatch):
        invite, _ = orgs.invite_by_email(acme[1], CAROL, request=fake_request())
        monkeypatch.setattr(orgs, "send_invite_email", lambda invite, request: False)
        orgs.resend_invite(invite, acme[1], request=fake_request())
        assert only("invite.emailed_again").detail["sent"] is False

    def test_withdrawing_twice_is_one_row(self, acme):
        invite, _ = orgs.invite_by_email(acme[1], CAROL)
        orgs.revoke_invite(invite, acme[1])
        orgs.revoke_invite(invite, acme[1])
        assert len(rows("invite.withdrawn")) == 1

    def test_a_join_code_made_and_revoked(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 3, tier=2)
        orgs.revoke_code(code, admin)
        orgs.revoke_code(code, admin)
        made = only("join_code.created")
        assert is_about(made, admin.account, code, organization=enterprise.pk, tier=2, max_uses=3)
        assert is_about(only("join_code.revoked"), admin.account, code)

    def test_members_deactivated_reactivated_and_made_admin(self, acme, bob):
        enterprise, admin = acme
        orgs.set_role(bob, "admin", admin)
        orgs.set_role(bob, "admin", admin)  # no change, so no second row
        orgs.deactivate_membership(bob, admin)
        orgs.deactivate_membership(bob, admin)  # already off
        orgs.reactivate_membership(bob, admin)
        role, off, on = rows()[-3:]
        assert [row.action for row in (role, off, on)] == [
            "member.role_changed",
            "member.deactivated",
            "member.reactivated",
        ]
        assert is_about(role, admin.account, bob, organization=enterprise.pk, role="admin")
        assert is_about(off, admin.account, bob, draft_deleted=False)
        assert is_about(on, admin.account, bob)

    def test_staff_acting_from_the_django_admin_write_no_row_here(self, acme, bob):
        """`by` is empty then; the admin's own history line is what gets copied."""
        before = len(rows())
        orgs.deactivate_membership(bob)
        orgs.reactivate_membership(bob)
        orgs.revoke_code(orgs.create_code(acme[1], 1))
        assert [row.action for row in rows()[before:]] == ["join_code.created"]

    def test_a_licence_given_moved_to_another_tier_and_taken_back(self, acme, bob):
        enterprise, admin = acme
        licence = licences.assign_seat(admin, bob, 2)
        licences.change_seat_tier(admin, licence, 2)  # no change, so no row
        licences.change_seat_tier(admin, licence, 3)
        licences.take_back_seat(admin, licence)
        given, changed, back = rows()[-3:]
        assert [row.action for row in (given, changed, back)] == [
            "licence.given",
            "licence.tier_changed",
            "licence.taken_back",
        ]
        assert is_about(
            given, admin.account, licence, organization=enterprise.pk, membership=bob.pk, tier=2
        )
        assert is_about(changed, admin.account, licence, from_tier=2, to_tier=3)
        assert is_about(back, admin.account, licence, tier=3, draft_deleted=False)

    def test_buying_stock_is_recorded_when_started_and_when_paid(self, acme, monkeypatch, settings):
        enterprise, admin = acme
        stripe = payments.install(monkeypatch, settings)
        buying.start_stock(admin, 2, 5, request=fake_request())
        purchase = buying.fulfil(stripe.pay())
        buying.fulfil(stripe.pay())  # Stripe says so twice; one row
        started, paid = only("stock_purchase.started"), only("stock_purchase.paid")
        facts = {"organization": enterprise.pk, "tier": 2, "quantity": 5}
        assert is_about(started, admin.account, purchase, **facts)
        assert is_about(paid, admin.account, purchase, added_to_stock=True, **facts)

    def test_a_person_buying_for_themselves_is_not_an_organization_admins_action(
        self, db, monkeypatch, settings
    ):
        stripe = payments.install(monkeypatch, settings)
        buying.start_personal(verified_account(CAROL), 2, request=fake_request())
        buying.fulfil(stripe.pay())
        assert rows() == []

    def test_a_refused_action_leaves_no_row(self, acme, bob):
        admin = acme[1]
        before = len(rows())
        assert "no Tier 1" in refusal(lambda: orgs.invite_by_email(admin, CAROL, 1))
        assert refusal(lambda: licences.assign_seat(bob, bob, 2))  # not an admin
        assert refusal(lambda: orgs.deactivate_membership(admin, admin))  # the last admin
        assert len(rows()) == before

    def test_no_row_holds_a_name_or_an_address(self, acme, bob):
        """Everything above in one go, then every stored value is searched."""
        admin = acme[1]
        Account.objects.filter(pk=bob.account_id).update(full_name="Bob Builder")
        invite, _ = orgs.invite_by_email(admin, CAROL, 2, request=fake_request())
        orgs.move_invite(invite, "dave@example.com", admin, request=fake_request())
        orgs.create_code(admin, 1)
        licences.assign_seat(admin, bob, 2)
        orgs.deactivate_membership(bob, admin)
        stored = json.dumps(
            [[row.action, row.target_type, row.target_id, row.detail] for row in rows()]
        ).lower()
        assert len(rows()) >= 6
        for private in ("@", "bob", "carol", "dave", "builder", "acme", invite.token.lower()):
            assert private not in stored
        # Nor did anything have to be removed on the way in: nothing was passed.
        assert "removed" not in stored and "email" not in stored and "address" not in stored


# --- the action and its record are saved together ---------------------------------------------


@pytest.fixture
def log_is_broken(monkeypatch):
    """From here on, nothing can be written to the audit log."""

    def refuse(*args, **kwargs):
        raise RuntimeError("the audit log cannot be written")

    monkeypatch.setattr(audit, "record", refuse)


@pytest.mark.django_db
class TestSavedTogether:
    """If the record cannot be written, the action does not happen either."""

    def test_no_licence_is_given(self, acme, bob, log_is_broken):
        with pytest.raises(RuntimeError):
            licences.assign_seat(acme[1], bob, 2)
        assert not bob.entitlements.exists()

    def test_no_licence_is_taken_back_or_moved_to_another_tier(self, acme, bob, monkeypatch):
        licence = licences.assign_seat(acme[1], bob, 2)
        monkeypatch.setattr(audit, "record", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            licences.take_back_seat(acme[1], licence)
        with pytest.raises(ZeroDivisionError):
            licences.change_seat_tier(acme[1], licence, 3)
        licence.refresh_from_db()
        assert licence.revoked_at is None and licence.tier == 2

    def test_no_invite_or_join_code_is_made(self, acme, log_is_broken):
        enterprise, admin = acme
        with pytest.raises(RuntimeError):
            orgs.invite_by_email(admin, CAROL, 2)
        with pytest.raises(RuntimeError):
            orgs.create_code(admin, 2, tier=2)
        assert not enterprise.invites.exists() and not enterprise.join_codes.exists()

    def test_no_invite_is_withdrawn_or_moved(self, acme, monkeypatch):
        invite, _ = orgs.invite_by_email(acme[1], CAROL)
        monkeypatch.setattr(audit, "record", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            orgs.revoke_invite(invite, acme[1])
        with pytest.raises(ZeroDivisionError):
            orgs.move_invite(invite, "dave@example.com", acme[1], request=fake_request())
        invite.refresh_from_db()
        assert invite.revoked_at is None and invite.email == CAROL

    def test_no_member_is_deactivated_or_made_admin(self, acme, bob, log_is_broken):
        with pytest.raises(RuntimeError):
            orgs.deactivate_membership(bob, acme[1])
        with pytest.raises(RuntimeError):
            orgs.set_role(bob, "admin", acme[1])
        bob.refresh_from_db()
        assert bob.is_active and bob.role == "member"

    def test_no_organization_is_created(self, db, log_is_broken):
        carol = verified_account(CAROL)
        with pytest.raises(RuntimeError):
            orgs.create_enterprise(carol, "Acme")
        assert not Enterprise.objects.exists()

    def test_a_stock_payment_is_not_marked_as_dealt_with(self, acme, monkeypatch, settings):
        """It stays pending, so Stripe's next message, or the next look, gives it."""
        enterprise, admin = acme
        stripe = payments.install(monkeypatch, settings)
        buying.start_stock(admin, 2, 5, request=fake_request())
        real = audit.record
        monkeypatch.setattr(audit, "record", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            buying.fulfil(stripe.pay())
        assert orgs.seats_bought(enterprise)[2] == 3  # the five were not added
        monkeypatch.setattr(audit, "record", real)
        assert buying.fulfil(stripe.pay()).status == "paid"
        assert orgs.seats_bought(enterprise)[2] == 8

    def test_no_account_is_erased(self, root, log_is_broken):
        carol = verified_account(CAROL)
        with pytest.raises(RuntimeError):
            erasure.erase_account(carol, by=root)
        assert Account.objects.filter(pk=carol.pk, anonymised_at__isnull=True).exists()

    def test_no_admin_history_line_is_written_without_its_copy(self, root, monkeypatch):
        monkeypatch.setattr(audit, "copy_admin_line", lambda entry: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            LogEntry.objects.log_actions(
                root.pk, Group.objects.filter(name=GROUP_NAME), ADDITION, single_object=True
            )
        assert not LogEntry.objects.exists()


# --- erasing an account -----------------------------------------------------------------------


@pytest.mark.django_db
class TestErasure:
    def test_erasing_writes_a_row_that_says_who_did_it_and_no_more(self, root):
        carol = verified_account(CAROL)
        number = carol.pk
        erasure.erase_account(carol, by=root)
        row = only("account.erased")
        assert row.actor == root and row.detail == {"results_kept": False}
        assert (row.target_type, row.target_id) == ("accounts.account", str(number))
        assert "carol" not in json.dumps(row.detail)

    def test_an_erased_admins_rows_stay_with_the_actor_emptied(self, acme):
        enterprise, admin = acme
        account = admin.account
        orgs.create_code(admin, 1)
        assert erasure.erase_account(account).action == erasure.DELETE
        made = only("join_code.created")
        assert made.actor is None and made.detail["organization"] == enterprise.pk

    def test_an_erasure_that_is_refused_leaves_no_row(self, root):
        with pytest.raises(Exception, match="own account"):
            erasure.erase_account(root, by=root)
        assert rows("account.erased") == []


# --- the Django admin's history is copied -----------------------------------------------------


@pytest.mark.django_db
class TestAdminHistory:
    def test_adding_changing_and_deleting_in_the_admin_are_each_copied(self, client, root):
        client.post(reverse("admin:auth_group_add"), {"name": "Night shift"})
        group = Group.objects.get(name="Night shift")
        client.post(reverse("admin:auth_group_change", args=[group.pk]), {"name": "Day shift"})
        client.post(reverse("admin:auth_group_delete", args=[group.pk]), {"post": "yes"})
        added, changed, deleted = rows()
        assert [row.action for row in (added, changed, deleted)] == [
            "admin.added",
            "admin.changed",
            "admin.deleted",
        ]
        for row in (added, changed, deleted):
            assert row.actor == root
            assert (row.target_type, row.target_id) == ("auth.group", str(group.pk))
        assert changed.detail["message"] == "Changed: Name"

    def test_each_copy_points_at_its_history_line_and_has_its_time(self, client, root):
        client.post(reverse("admin:auth_group_add"), {"name": "Night shift"})
        line, row = LogEntry.objects.get(), only("admin.added")
        assert row.detail["history_line"] == line.pk and row.at == line.action_time

    def test_several_rows_deleted_at_once_are_each_copied(self, client, root):
        """Django writes these lines in one bulk insert, which sends no signal."""
        groups = [Group.objects.create(name=name) for name in ("One", "Two", "Three")]
        client.post(
            reverse("admin:auth_group_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [group.pk for group in groups],
                "post": "yes",
            },
        )
        assert not Group.objects.filter(name__in=["One", "Two", "Three"]).exists()
        copied = rows("admin.deleted")
        assert sorted(row.target_id for row in copied) == sorted(str(g.pk) for g in groups)
        assert all(row.actor == root for row in copied)
        assert LogEntry.objects.count() == 3

    def test_a_line_written_by_one_of_this_projects_admin_pages_is_copied_as_it_is(
        self, acme, root
    ):
        enterprise, _ = acme
        LogEntry.objects.log_actions(
            root.pk,
            Enterprise.objects.filter(pk=enterprise.pk),
            CHANGE,
            "Licence stock changed: Tier 2 from 3 to 5",
            single_object=True,
        )
        row = only("admin.changed")
        assert row.detail["message"] == "Licence stock changed: Tier 2 from 3 to 5"
        assert (row.target_type, row.target_id) == ("enterprises.enterprise", str(enterprise.pk))

    def test_the_label_of_the_object_is_never_copied(self, root):
        """A history line's label can be a person's email address; so can an inline's."""
        carol = verified_account(CAROL)
        LogEntry.objects.create(
            user=root,
            content_type=ContentType.objects.get_for_model(Account),
            object_id=str(carol.pk),
            object_repr=CAROL,
            action_flag=CHANGE,
            change_message=json.dumps(
                [
                    {"changed": {"fields": ["Full name"]}},
                    {"added": {"name": "contact point", "object": CAROL}},
                    {"changed": {"name": "membership", "object": "Carol", "fields": ["Role"]}},
                ]
            ),
        )
        row = only("admin.changed")
        assert row.detail["message"] == (
            "Changed: Full name. Added contact point. Changed membership: Role"
        )
        assert "carol" not in json.dumps([row.target_id, row.detail]).lower()

    def test_an_address_typed_into_a_reason_is_removed_from_the_copy(self, root):
        LogEntry.objects.create(
            user=root,
            content_type=ContentType.objects.get_for_model(Account),
            object_id="7",
            object_repr="Account #7",
            action_flag=CHANGE,
            change_message=f"Erased. Asked for by {CAROL} on the phone",
        )
        assert only("admin.changed").detail["message"] == (
            "Erased. Asked for by [removed] on the phone"
        )

    def test_erasing_from_the_admin_is_in_the_log_with_who_did_it(self, client, root):
        carol = verified_account(CAROL)
        number = carol.pk
        client.post(
            reverse("admin:accounts_account_erase", args=[number]),
            {"email": CAROL, "reason": "deletion request, ticket 123"},
        )
        assert not Account.objects.filter(pk=number).exists()
        erased = only("account.erased")
        assert erased.actor == root and erased.target_id == str(number)
        line = only("admin.deleted")
        assert line.actor == root and line.detail["message"] == (
            "Erased. deletion request, ticket 123"
        )

    def test_a_history_line_that_is_undone_leaves_no_copy(self, root):
        with pytest.raises(RuntimeError), transaction.atomic():
            LogEntry.objects.log_actions(
                root.pk, Group.objects.filter(name=GROUP_NAME), ADDITION, single_object=True
            )
            raise RuntimeError("the admin page failed after all")
        assert rows() == [] and not LogEntry.objects.exists()


# --- reading it -------------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminPage:
    def test_a_superuser_reads_who_did_what_by_number(self, client, acme, bob, root):
        admin = acme[1]
        licence = licences.assign_seat(admin, bob, 2)
        page = client.get(reverse("admin:audit_auditlog_changelist")).content.decode()
        assert "licence.given" in page and f"entitlements.entitlement #{licence.pk}" in page
        assert f"Account #{admin.account_id}</a>" in page
        assert reverse("admin:accounts_account_change", args=[admin.account_id]) in page
        assert admin.account.email not in page and BOB not in page

    def test_searching_a_number_finds_what_was_done_to_that_thing(self, client, acme, bob, root):
        licence = licences.assign_seat(acme[1], bob, 2)
        orgs.create_code(acme[1], 1)
        address = reverse("admin:audit_auditlog_changelist")
        page = client.get(address, {"q": str(licence.pk)}).content.decode()
        assert "licence.given" in page

    def test_nothing_can_be_added_changed_or_deleted(self, client, acme, root):
        row = rows()[0]
        assert client.get(reverse("admin:audit_auditlog_add")).status_code == 403
        change = reverse("admin:audit_auditlog_change", args=[row.pk])
        assert client.get(change).status_code == 200  # opens, read-only
        client.post(change, {"action": "changed.by.hand"})
        assert client.post(reverse("admin:audit_auditlog_delete", args=[row.pk])).status_code == 403
        client.post(
            reverse("admin:audit_auditlog_changelist"),
            {"action": "delete_selected", "_selected_action": [row.pk], "post": "yes"},
        )
        row.refresh_from_db()
        assert row.action == "organization.created"

    def test_support_staff_cannot_open_it_or_see_it_listed(self, client, acme, support):
        assert client.get(reverse("admin:audit_auditlog_changelist")).status_code == 403
        row = rows()[0]
        assert client.get(reverse("admin:audit_auditlog_change", args=[row.pk])).status_code == 403
        assert "Audit log" not in client.get(reverse("admin:index")).content.decode()

    def test_support_staff_cannot_be_let_in_by_a_permission_given_by_mistake(
        self, client, acme, support
    ):
        from django.contrib.auth.models import Permission

        support.user_permissions.add(Permission.objects.get(codename="view_auditlog"))
        assert client.get(reverse("admin:audit_auditlog_changelist")).status_code == 403

    def test_the_audit_log_is_on_no_page_of_the_site_itself(self):
        """It has no pages of its own: only the Django admin shows it."""
        from pathlib import Path

        from django.conf import settings

        app = Path(settings.BASE_DIR) / "apps" / "audit"
        assert not (app / "views.py").exists() and not (app / "urls.py").exists()
        templates = Path(settings.BASE_DIR) / "templates"
        for path in templates.rglob("*.html"):
            if "admin" not in path.parts:  # the Django admin's own pages may name it
                assert "audit" not in path.read_text().lower(), path
