"""
Milestone 3, PR 5: a licence belongs to a person or to a membership, never both.
A membership licence can only be used for that organization and a personal one
only personally; the two contexts never see each other's licences. Staff grant
both kinds from the same admin form. Erasing an account deals with the licences
of its memberships.
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.entitlements import services
from apps.entitlements.models import Entitlement
from apps.funnel.models import FunnelEvent
from apps.responses import services as responses
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.survey.services import current_version

from .orgs import new_member, org_with_admin
from .test_profile import verified_account
from .test_verification import PASSWORD

ADD = "/admin/entitlements/entitlement/add/"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def member(acme):
    return new_member(acme[0], "bob@example.com")


def grant(membership, tier=2):
    return services.grant_for_membership(membership, tier, "manual", None)


def use(licence, account, submitted=False):
    """An attempt on this licence, made directly (the pages arrive in later PRs)."""
    extra = {"status": "submitted", "submitted_at": timezone.now()} if submitted else {}
    return Response.objects.create(
        account=account, survey_version=current_version(), entitlement=licence, **extra
    )


# --- the database rule ---------------------------------------------------------


@pytest.mark.django_db
class TestExactlyOneOwner:
    def refused(self, **values):
        try:
            with transaction.atomic():
                Entitlement.objects.create(tier=1, source="manual", **values)
        except IntegrityError:
            return True
        return False

    def test_a_licence_has_a_person_or_a_membership(self, member):
        person = member.account.person
        assert not self.refused(person=person)
        assert not self.refused(membership=member)

    def test_never_both_and_never_neither(self, member):
        assert self.refused(person=member.account.person, membership=member)
        assert self.refused()


# --- granting ------------------------------------------------------------------


@pytest.mark.django_db
class TestGrantForMembership:
    def test_gives_the_membership_a_licence_and_the_person_none(self, acme, member):
        root = Account.objects.create_superuser("root@example.com", PASSWORD)
        licence = services.grant_for_membership(member, 3, "manual", root)
        assert licence.membership == member and licence.person is None
        assert (licence.tier, licence.source, licence.granted_by) == (3, "manual", root)
        assert licence.is_active and not licence.is_personal
        assert list(member.entitlements.all()) == [licence]
        assert not member.account.person.entitlements.exists()

    def test_the_label_names_no_person(self, member):
        assert str(grant(member)) == f"Tier 2 licence for membership {member.pk}"

    def test_the_funnel_counts_it_like_any_other_licence(self, member):
        FunnelEvent.objects.all().delete()
        services.grant_for_membership(member, 2, "manual", None)
        event = FunnelEvent.objects.get()
        assert (event.kind, event.tier, event.source) == ("licence_granted", 2, "manual")

    @pytest.mark.parametrize(("tier", "source"), [(0, "manual"), (4, "manual"), (1, "gift")])
    def test_a_bad_tier_or_source_is_refused(self, member, tier, source):
        with pytest.raises(ValidationError):
            services.grant_for_membership(member, tier, source, None)
        assert not Entitlement.objects.exists()

    def test_a_deactivated_membership_is_refused(self, acme, member):
        orgs.deactivate_membership(member, by=acme[1])
        member.refresh_from_db()
        with pytest.raises(ValidationError) as caught:
            grant(member)
        assert "deactivated" in caught.value.messages[0]
        assert not Entitlement.objects.exists()


# --- the two contexts never mix ------------------------------------------------


@pytest.mark.django_db
class TestContext:
    def test_a_membership_licence_gives_access_for_that_organization_only(self, member):
        account = member.account
        licence = grant(member)
        assert services.unused_licence(account, member) == licence
        assert services.has_survey_access(account, member)
        # ...and none personally.
        assert services.unused_licence(account) is None
        assert not services.has_survey_access(account)

    def test_a_personal_licence_gives_access_personally_only(self, member):
        account = member.account
        licence = services.grant_individual(account.person, 1, "manual", None)
        assert services.unused_licence(account) == licence
        assert services.has_survey_access(account)
        assert services.unused_licence(account, member) is None
        assert not services.has_survey_access(account, member)

    def test_one_organizations_licence_is_no_use_in_another(self, acme, member):
        other, _ = org_with_admin("Other")
        elsewhere = orgs.redeem_code(
            orgs.create_code(other.memberships.get(), 5).code, member.account
        )
        grant(member)
        assert not services.has_survey_access(member.account, elsewhere)
        assert services.has_survey_access(member.account, member)

    def test_nobody_can_use_someone_elses_membership(self, acme, member):
        grant(member)
        stranger = verified_account("stranger@example.com")
        colleague = new_member(acme[0], "colleague@example.com")
        for account in (stranger, colleague.account, acme[1].account):
            assert services.unused_licence(account, member) is None
            assert not services.has_survey_access(account, member)

    def test_the_oldest_unused_licence_of_the_context_comes_first(self, member):
        services.grant_individual(member.account.person, 1, "manual", None)
        older = grant(member, 1)
        grant(member, 3)
        assert services.unused_licence(member.account, member) == older

    def test_a_used_or_revoked_licence_is_not_unused(self, member):
        account = member.account
        used, revoked = grant(member), grant(member)
        use(used, account, submitted=True)
        services.revoke(revoked)
        assert services.unused_licence(account, member) is None
        assert not services.has_survey_access(account, member)

    def test_an_open_draft_on_an_active_licence_is_access(self, member):
        account = member.account
        licence = grant(member)
        use(licence, account)
        assert services.unused_licence(account, member) is None
        assert services.has_survey_access(account, member)
        assert not services.has_survey_access(account)  # the draft is the organization's
        services.revoke(licence)
        assert not services.has_survey_access(account, member)

    def test_a_deactivated_member_keeps_the_licence_but_cannot_use_it(self, acme, member):
        licence = grant(member)
        orgs.deactivate_membership(member, by=acme[1])
        member.refresh_from_db()
        assert not services.has_survey_access(member.account, member)
        licence.refresh_from_db()
        assert licence.is_active  # still theirs, waiting

        orgs.reactivate_membership(member, by=acme[1])
        member.refresh_from_db()
        assert services.unused_licence(member.account, member) == licence
        assert services.has_survey_access(member.account, member)

    def test_an_account_with_no_person_sees_no_licences_at_all(self, member):
        # A missing person must never read as "every licence without a person".
        grant(member)
        orphan = verified_account("orphan@example.com")
        Account.objects.filter(pk=orphan.pk).update(person=None)
        orphan.refresh_from_db()
        assert services.unused_licence(orphan) is None
        assert not services.has_survey_access(orphan)

    def test_the_personal_survey_cannot_be_started_on_an_organizations_licence(self, member):
        grant(member)
        with pytest.raises(responses.NoLicence):
            responses.start_response(member.account)
        assert not Response.objects.exists()

    def test_revoking_a_membership_licence_deletes_its_unfinished_attempt(self, member):
        licence = grant(member)
        use(licence, member.account)
        _, draft_deleted = services.revoke(licence)
        assert draft_deleted and not Response.objects.exists()


# --- erasure -------------------------------------------------------------------


@pytest.mark.django_db
class TestErasure:
    def test_a_deleted_account_takes_its_memberships_licences_with_it(self, acme, member):
        account = member.account
        use(grant(member), account)  # an unfinished attempt for the organization
        grant(member)  # and a spare
        plan = erasure.plan_erasure(account)
        assert plan.action == erasure.DELETE and "2 licence(s)" in plan.summary
        erasure.erase_account(account)
        assert not Entitlement.objects.exists() and not Response.objects.exists()
        assert not acme[0].memberships.filter(role="member").exists()

    def test_a_stripped_account_keeps_the_used_licence_and_loses_the_unused_one(self, member):
        account = member.account
        used, spare, drafted = grant(member), grant(member), grant(member)
        done = use(used, account, submitted=True)
        use(drafted, account)

        assert erasure.erase_account(account).action == erasure.ANONYMISE

        for licence in (used, spare, drafted):
            licence.refresh_from_db()
        assert used.revoked_at is None  # the completed survey keeps its licence
        assert spare.revoked_at is not None and drafted.revoked_at is not None
        assert list(Response.objects.all()) == [done]
        member.refresh_from_db()
        assert not member.is_active and used.membership == member

    def test_the_personal_licences_are_handled_as_before(self, member):
        account = member.account
        personal = services.grant_individual(account.person, 1, "manual", None)
        use(grant(member), account, submitted=True)
        erasure.erase_account(account)
        personal.refresh_from_db()
        assert personal.revoked_at is not None


# --- the staff admin -----------------------------------------------------------


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


def find_membership(client, term):
    return client.get(
        "/admin/autocomplete/",
        {
            "app_label": "entitlements",
            "model_name": "entitlement",
            "field_name": "membership",
            "term": term,
        },
    )


@pytest.mark.django_db
class TestAdmin:
    def test_the_form_grants_a_licence_to_a_membership_and_records_who(self, client, root, member):
        response = client.post(ADD, {"membership": member.pk, "tier": 2, "source": "manual"})
        assert response.status_code == 302
        licence = Entitlement.objects.get()
        assert licence.membership == member and licence.person is None
        assert licence.tier == 2 and licence.granted_by == root
        assert LogEntry.objects.filter(object_id=str(licence.pk), user=root).exists()

    def test_the_form_still_grants_a_personal_licence(self, client, root, member):
        account = member.account
        client.post(ADD, {"account": account.pk, "tier": 1, "source": "manual"})
        licence = Entitlement.objects.get()
        assert licence.person == account.person and licence.membership is None

    def test_it_wants_an_account_or_a_membership_not_both_and_not_neither(
        self, client, root, member
    ):
        both = {"account": member.account.pk, "membership": member.pk, "tier": 1}
        for data in (both, {"tier": 1}):
            page = client.post(ADD, {**data, "source": "manual"})
            assert page.status_code == 200
            assert "one of the two, not both" in page.content.decode()
        assert not Entitlement.objects.exists()

    def test_a_deactivated_membership_is_refused_on_the_form(self, client, root, acme, member):
        orgs.deactivate_membership(member, by=acme[1])
        page = client.post(ADD, {"membership": member.pk, "tier": 1, "source": "manual"})
        assert page.status_code == 200 and "deactivated" in page.content.decode()
        assert not Entitlement.objects.exists()

    def test_the_membership_is_searched_for_not_listed(self, client, root, member):
        page = client.get(ADD).content.decode()
        assert page.count("admin-autocomplete") >= 2
        assert "bob@example.com" not in page
        for term in ("bob@ex", "Acme"):
            found = find_membership(client, term).json()["results"]
            assert f"Membership {member.pk} in Acme" in [row["text"] for row in found]
        # The label says which organization, and nothing about the person.
        assert "bob" not in str(find_membership(client, "bob@ex").json())

    def test_support_staff_can_find_a_membership_and_grant_it_a_licence(
        self, client, support, member
    ):
        found = find_membership(client, "bob@ex")
        assert found.status_code == 200 and len(found.json()["results"]) == 1
        response = client.post(ADD, {"membership": member.pk, "tier": 1, "source": "manual"})
        assert response.status_code == 302
        assert Entitlement.objects.get().granted_by == support

    def test_the_list_says_what_each_licence_is_for_and_can_be_filtered(self, client, root, member):
        org_licence = grant(member)
        personal = services.grant_individual(member.account.person, 1, "manual", None)
        listing = client.get("/admin/entitlements/entitlement/").content.decode()
        assert "Acme" in listing and "Personal" in listing

        def ids(query):
            html = client.get(f"/admin/entitlements/entitlement/?{query}").content.decode()
            return {
                pk
                for pk in (org_licence.pk, personal.pk)
                if f'name="_selected_action" value="{pk}"' in html
            }

        assert ids("context=organization") == {org_licence.pk}
        assert ids("context=personal") == {personal.pk}
        assert ids("q=Acme") == {org_licence.pk}
        assert ids("q=bob@example.com") == {org_licence.pk, personal.pk}

    def test_a_membership_licence_page_shows_the_membership_and_only_the_tier_changes(
        self, client, root, member
    ):
        licence = grant(member, 1)
        url = f"/admin/entitlements/entitlement/{licence.pk}/change/"
        assert f"Membership {member.pk} in Acme" in client.get(url).content.decode()
        client.post(url, {"tier": 3, "source": "purchase", "membership": ""})
        licence.refresh_from_db()
        assert licence.tier == 3 and licence.source == "manual" and licence.membership == member

    def test_revoking_works_for_a_membership_licence(self, client, root, member):
        licence = grant(member)
        client.post(
            "/admin/entitlements/entitlement/",
            {"action": "revoke_selected", "_selected_action": [licence.pk]},
        )
        licence.refresh_from_db()
        assert licence.revoked_at is not None
