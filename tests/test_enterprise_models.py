"""
Milestone 3, PR 2: the four organization tables and their database rules, the
read-only staff pages, and what erasing an account does to its memberships.

The rules about who may do what (roles, codes, invites, the people limit) live
in the services, which arrive in the next PRs; these tests cover what the
database itself refuses.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts import erasure, services
from apps.accounts.models import Account
from apps.enterprises.models import Enterprise, Invite, JoinCode, Membership
from apps.responses.signals import GROUP_NAME

from .orgs import add_member, make_enterprise
from .test_erasure import complete
from .test_profile import verified_account
from .test_verification import PASSWORD

SOON = timedelta(days=14)


@pytest.fixture
def bob(db):
    account = verified_account("bob@example.com")
    services.set_full_name(account, "Bob Example")
    return account


@pytest.fixture
def acme(db):
    return make_enterprise("Acme")


def make_invite(enterprise, **extra):
    values = {
        "email": "carol@example.com",
        "token": "token-" + str(Invite.objects.count()),
        "expires_at": timezone.now() + SOON,
        **extra,
    }
    return Invite.objects.create(enterprise=enterprise, **values)


def make_code(enterprise, **extra):
    values = {
        "code": f"ABCDE{JoinCode.objects.count():05d}",
        "max_uses": 5,
        "expires_at": timezone.now() + SOON,
        **extra,
    }
    return JoinCode.objects.create(enterprise=enterprise, **values)


def refused(make):
    """True if the database refuses the write (run in its own savepoint)."""
    try:
        with transaction.atomic():
            make()
    except IntegrityError:
        return True
    return False


# --- the database rules --------------------------------------------------------


@pytest.mark.django_db
class TestEnterprise:
    def test_starts_with_a_limit_of_25_people(self, acme):
        assert acme.people_limit == 25

    def test_two_may_share_a_name_but_not_a_slug(self, acme):
        twin = make_enterprise("Acme")
        assert twin.name == acme.name and twin.slug != acme.slug
        assert refused(lambda: Enterprise.objects.create(name="Other", slug=acme.slug))


@pytest.mark.django_db
class TestMembership:
    def test_is_a_member_and_active_by_default(self, acme, bob):
        membership = add_member(acme, bob)
        assert membership.role == "member" and membership.is_active and not membership.is_admin
        assert list(bob.memberships.all()) == [membership]
        assert list(acme.memberships.all()) == [membership]

    def test_one_per_account_and_organization(self, acme, bob):
        add_member(acme, bob)
        assert refused(lambda: add_member(acme, bob, role="admin"))
        add_member(make_enterprise("Other"), bob)  # a second organization is fine

    def test_a_deactivated_one_says_when_and_an_active_one_has_no_such_date(self, acme, bob):
        assert refused(lambda: add_member(acme, bob, status="deactivated"))
        assert refused(lambda: add_member(acme, bob, deactivated_at=timezone.now()))
        assert not add_member(acme, bob, active=False).is_active

    def test_a_deactivated_one_is_never_an_admin(self, acme, bob):
        assert refused(lambda: add_member(acme, bob, role="admin", active=False))

    def test_the_role_is_member_or_admin(self, acme, bob):
        assert refused(lambda: add_member(acme, bob, role="owner"))

    def test_nobody_joins_two_ways_at_once(self, acme, bob):
        invite, code = make_invite(acme), make_code(acme)
        assert refused(
            lambda: add_member(acme, bob, joined_via_invite=invite, joined_via_code=code)
        )
        assert add_member(acme, bob, joined_via_code=code).joined_via_invite is None

    def test_cannot_vanish_with_its_account_or_organization(self, acme, bob):
        add_member(acme, bob)
        with pytest.raises(ProtectedError):
            bob.delete()
        with pytest.raises(ProtectedError):
            acme.delete()


@pytest.mark.django_db
class TestInvite:
    def test_tokens_are_unique(self, acme):
        make_invite(acme, token="same")
        assert refused(lambda: make_invite(acme, token="same"))

    def test_the_tier_is_empty_or_1_to_3(self, acme):
        assert make_invite(acme).tier is None
        make_invite(acme, tier=3)
        assert refused(lambda: make_invite(acme, tier=0))
        assert refused(lambda: make_invite(acme, tier=4))

    def test_cannot_be_both_accepted_and_revoked(self, acme):
        now = timezone.now()
        assert refused(lambda: make_invite(acme, accepted_at=now, revoked_at=now))


@pytest.mark.django_db
class TestJoinCode:
    def test_codes_are_unique(self, acme):
        make_code(acme, code="ABCDEFGHJK")
        assert refused(lambda: make_code(acme, code="ABCDEFGHJK"))

    def test_uses_never_pass_the_cap(self, acme):
        code = make_code(acme, max_uses=2, uses=2)
        code.uses = 3
        assert refused(code.save)

    def test_needs_at_least_one_use(self, acme):
        assert refused(lambda: make_code(acme, max_uses=0))

    def test_the_tier_is_empty_or_1_to_3(self, acme):
        make_code(acme, tier=1)
        assert refused(lambda: make_code(acme, tier=4))


# --- labels --------------------------------------------------------------------


@pytest.mark.django_db
def test_no_label_holds_an_email_a_name_a_token_or_a_code(acme, bob):
    # The admin history stores str(object); it must not keep anyone's identity,
    # or a working way into an organization.
    invite = make_invite(acme, email="bob@example.com", token="secret-token", created_by=bob)
    code = make_code(acme, code="ABCDEFGHJK", created_by=bob)
    membership = add_member(acme, bob, joined_via_invite=invite)
    labels = " ".join(str(thing) for thing in (acme, membership, invite, code))
    for private in ("bob@example.com", "Bob Example", "secret-token", "ABCDEFGHJK"):
        assert private not in labels
    assert str(membership) == f"Membership {membership.pk} in Acme"


# --- erasure -------------------------------------------------------------------


@pytest.mark.django_db
class TestErasure:
    def test_an_account_with_no_completed_survey_is_deleted_with_its_memberships(self, acme, bob):
        other = make_enterprise("Other", created_by=bob)
        invite = make_invite(acme, created_by=bob)
        code = make_code(acme, created_by=bob)
        add_member(acme, bob)
        add_member(other, bob, role="admin")

        plan = erasure.plan_erasure(bob)
        assert plan.action == erasure.DELETE and "2 organization(s)" in plan.summary
        erasure.erase_account(bob)

        assert not Account.objects.filter(pk=bob.pk).exists()
        assert not Membership.objects.exists()
        # The organizations and what the account made in them stay, with no author.
        for thing in (other, invite, code):
            thing.refresh_from_db()
            assert thing.created_by is None
        assert Enterprise.objects.count() == 2

    def test_an_account_with_a_completed_survey_keeps_its_membership_deactivated(self, acme, bob):
        membership = add_member(acme, bob)
        complete(bob)

        plan = erasure.plan_erasure(bob)
        assert plan.action == erasure.ANONYMISE and "Erased member" in plan.summary
        erasure.erase_account(bob)

        membership.refresh_from_db()
        assert membership.status == "deactivated" and membership.deactivated_at is not None
        assert membership.account.anonymised_at is not None
        assert membership.account.full_name == ""
        assert "bob@example.com" not in membership.account.email

    def test_the_historical_total_still_counts_the_former_member(self, acme, bob):
        add_member(acme, bob)
        add_member(acme, verified_account("carol@example.com"))
        complete(bob)
        erasure.erase_account(bob)
        # Two views of an organization: who is in it now, and everyone who ever was.
        assert acme.memberships.filter(status="active").count() == 1
        assert acme.memberships.count() == 2

    def test_a_membership_deactivated_earlier_keeps_its_own_date(self, acme, bob):
        long_ago = timezone.now() - timedelta(days=90)
        membership = add_member(acme, bob, active=False, deactivated_at=long_ago)
        complete(bob)
        erasure.erase_account(bob)
        membership.refresh_from_db()
        assert membership.deactivated_at == long_ago

    def test_an_erased_admin_stops_being_one(self, acme, bob):
        membership = add_member(acme, bob, role="admin")
        complete(bob)
        erasure.erase_account(bob)
        membership.refresh_from_db()
        assert not membership.is_active and not membership.is_admin

    def test_the_only_admin_cannot_be_erased_while_others_are_still_members(self, acme, bob):
        add_member(acme, bob, role="admin")
        add_member(acme, verified_account("carol@example.com"))
        for check in (erasure.plan_erasure, erasure.erase_account):
            with pytest.raises(ValidationError) as caught:
                check(bob)
            assert " ".join(caught.value.messages) == (
                "This account is the only admin of Acme, which still has other members. "
                "Make another member an admin there first, then erase."
            )
        assert Account.objects.get(pk=bob.pk).email == "bob@example.com"

    def test_once_there_is_another_admin_the_erasure_goes_ahead(self, acme, bob):
        add_member(acme, bob, role="admin")
        add_member(acme, verified_account("carol@example.com"), role="admin")
        assert erasure.erase_account(bob).action == erasure.DELETE
        assert acme.memberships.filter(role="admin", status="active").count() == 1

    def test_an_admin_alone_in_an_organization_can_be_erased(self, acme, bob):
        add_member(acme, bob, role="admin")
        add_member(acme, verified_account("left@example.com"), active=False)
        assert erasure.erase_account(bob).action == erasure.DELETE
        assert Enterprise.objects.filter(pk=acme.pk).exists()

    def test_an_ordinary_member_is_never_blocked(self, acme, bob):
        add_member(acme, verified_account("admin@example.com"), role="admin")
        add_member(acme, bob)
        assert erasure.plan_erasure(bob).action == erasure.DELETE

    def test_the_erase_page_gives_the_reason_in_plain_words(self, client, acme, bob):
        root = Account.objects.create_superuser("root@example.com", PASSWORD)
        client.force_login(root)
        add_member(acme, bob, role="admin")
        add_member(acme, verified_account("carol@example.com"))
        page = client.get(f"/admin/accounts/account/{bob.pk}/erase/", follow=True)
        assert "only admin of Acme" in page.content.decode()
        assert Account.objects.filter(pk=bob.pk, anonymised_at__isnull=True).exists()

    def test_nothing_changes_if_it_fails_halfway(self, acme, bob, monkeypatch):
        membership = add_member(acme, bob)
        complete(bob)

        def boom(account):
            raise RuntimeError("boom")

        monkeypatch.setattr(erasure, "_end_sessions", lambda account: None)
        monkeypatch.setattr(Account, "set_unusable_password", boom)
        with pytest.raises(RuntimeError):
            erasure.erase_account(bob)
        membership.refresh_from_db()
        assert membership.is_active


# --- the staff admin -----------------------------------------------------------

PAGES = ("enterprise", "membership", "invite", "joincode")


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def things(acme, bob):
    invite = make_invite(acme, token="secret-token")
    code = make_code(acme, code="ABCDEFGHJK")
    membership = add_member(acme, bob, joined_via_code=code)
    return {"enterprise": acme, "membership": membership, "invite": invite, "joincode": code}


@pytest.mark.django_db
class TestAdmin:
    def test_a_superuser_can_look_at_all_four(self, client, root, things):
        for page in PAGES:
            assert client.get(f"/admin/enterprises/{page}/").status_code == 200
            detail = f"/admin/enterprises/{page}/{things[page].pk}/change/"
            assert client.get(detail).status_code == 200

    def test_the_section_is_called_organizations(self, client, root):
        html = client.get("/admin/").content.decode()
        assert "Organizations" in html

    def test_nothing_can_be_added_changed_or_deleted_there(self, client, root, things):
        for page in PAGES:
            pk = things[page].pk
            assert client.get(f"/admin/enterprises/{page}/add/").status_code == 403
            assert client.post(f"/admin/enterprises/{page}/{pk}/change/", {}).status_code == 403
            assert client.get(f"/admin/enterprises/{page}/{pk}/delete/").status_code == 403
        assert Membership.objects.count() == 1

    def test_the_invite_link_secret_is_never_shown(self, client, root, things):
        listing = client.get("/admin/enterprises/invite/").content.decode()
        detail = client.get(
            f"/admin/enterprises/invite/{things['invite'].pk}/change/"
        ).content.decode()
        assert "secret-token" not in listing and "secret-token" not in detail

    def test_a_working_code_is_not_on_the_list_page(self, client, root, things):
        assert "ABCDEFGHJK" not in client.get("/admin/enterprises/joincode/").content.decode()

    def test_support_staff_see_memberships_only_for_now(self, client, things):
        # They need memberships to grant one a licence (PR 5). Their view of the
        # rest arrives with the staff tools (PR 12).
        support = Account.objects.create_user("support@example.com", PASSWORD)
        support.is_staff = True
        support.save()
        support.groups.add(Group.objects.get(name=GROUP_NAME))
        client.force_login(support)
        assert client.get("/admin/enterprises/membership/").status_code == 200
        for page in ("enterprise", "invite", "joincode"):
            assert client.get(f"/admin/enterprises/{page}/").status_code == 403
        pk = things["membership"].pk
        assert client.post(f"/admin/enterprises/membership/{pk}/change/", {}).status_code == 403
