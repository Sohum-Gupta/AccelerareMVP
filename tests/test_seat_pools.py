"""
Milestone 4, PR 1: the stock of licences an organization has bought (seat pools).

Staff record, per tier, how many licences an organization has bought. How many
have been given out is counted from the licences themselves, never stored. The
number of people an organization may bring in is its base number plus every
licence it has bought. Superusers and Support staff set the stock on the
"Licence stock" page of the Django admin; every change leaves a history line.

Giving a licence out of the stock arrives in PR 2, so these tests make a stock
licence by creating the row directly (`stock_licence`).
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Account
from apps.enterprises import services
from apps.enterprises.models import Enterprise, SeatPool
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.survey.services import current_version

from .orgs import locked_tables, new_member, org_with_admin
from .test_enterprise_services import refusal, spend_places
from .test_profile import verified_account
from .test_verification import PASSWORD

ORGANIZATIONS = "/admin/enterprises/enterprise/"
GRANT = "/admin/entitlements/entitlement/add/"
NOTHING = {1: 0, 2: 0, 3: 0}


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def member(acme):
    return new_member(acme[0], "bob@example.com")


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


def stock_licence(membership, tier=2):
    """A licence given out of the organization's stock."""
    return Entitlement.objects.create(membership=membership, tier=tier, source="seat")


def take_survey(licence, submitted=False):
    """An attempt on a membership's licence: unfinished, or submitted."""
    extra = {"status": "submitted", "submitted_at": timezone.now()} if submitted else {}
    return Response.objects.create(
        account=licence.membership.account,
        survey_version=current_version(),
        entitlement=licence,
        membership=licence.membership,
        **extra,
    )


def row(enterprise, tier):
    """One tier's line of the summary."""
    return next(line for line in services.seat_summary(enterprise) if line["tier"] == tier)


def stock_page(enterprise):
    return f"{ORGANIZATIONS}{enterprise.pk}/stock/"


def change_page(enterprise):
    return f"{ORGANIZATIONS}{enterprise.pk}/change/"


def said(response):
    """The messages shown at the top of the next page."""
    return " | ".join(str(message) for message in response.context["messages"])


def history(enterprise):
    """The organization's history lines, as (who, what)."""
    entries = LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(enterprise), object_id=str(enterprise.pk)
    )
    return [(entry.user, entry.get_change_message()) for entry in entries]


# --- recording what an organization has bought -------------------------------------


@pytest.mark.django_db
class TestSettingTheStock:
    def test_a_new_organization_has_bought_nothing(self, acme):
        assert services.seats_bought(acme[0]) == NOTHING
        assert not SeatPool.objects.exists()

    def test_the_number_is_the_total_so_setting_it_again_replaces_it(self, acme):
        enterprise, _ = acme
        pool = services.set_seat_pool(enterprise, 2, 10)
        assert (pool.enterprise, pool.tier, pool.seats) == (enterprise, 2, 10)
        services.set_seat_pool(enterprise, 2, 15)
        assert SeatPool.objects.count() == 1
        assert services.seats_bought(enterprise) == {1: 0, 2: 15, 3: 0}

    def test_each_tier_and_each_organization_has_its_own(self, acme):
        enterprise, _ = acme
        other, _ = org_with_admin("Other")
        services.set_seat_pool(enterprise, 1, 3)
        services.set_seat_pool(enterprise, 3, 4)
        services.set_seat_pool(other, 2, 7)
        assert services.seats_bought(enterprise) == {1: 3, 2: 0, 3: 4}
        assert services.seats_bought(other) == {1: 0, 2: 7, 3: 0}

    def test_it_can_be_set_back_to_nothing_and_up_to_the_most_allowed(self, acme):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 1, services.MAX_SEATS)
        assert services.seats_bought(enterprise)[1] == services.MAX_SEATS
        services.set_seat_pool(enterprise, 1, 0)
        assert services.seats_bought(enterprise) == NOTHING

    @pytest.mark.parametrize("tier", [0, 4, -1, "2", 2.0, True, None])
    def test_a_bad_tier_is_refused(self, acme, tier):
        message = refusal(lambda: services.set_seat_pool(acme[0], tier, 5))
        assert message == "The tier must be 1, 2 or 3."
        assert not SeatPool.objects.exists()

    @pytest.mark.parametrize("seats", [-1, services.MAX_SEATS + 1, "5", 2.5, True, None])
    def test_a_bad_number_is_refused_and_the_old_one_stays(self, acme, seats):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        message = refusal(lambda: services.set_seat_pool(enterprise, 2, seats))
        assert message == "Enter a whole number of licences from 0 to 1,000,000."
        assert services.seats_bought(enterprise)[2] == 10

    def test_it_takes_the_organizations_lock(self, acme):
        """So a change and someone joining or being given a licence take turns."""
        with CaptureQueriesContext(connection) as captured:
            services.set_seat_pool(acme[0], 2, 10)
        assert Enterprise._meta.db_table in locked_tables(captured.captured_queries)

    def test_the_database_keeps_one_row_per_organization_and_tier(self, acme):
        enterprise, _ = acme
        SeatPool.objects.create(enterprise=enterprise, tier=2, seats=1)
        with pytest.raises(IntegrityError), transaction.atomic():
            SeatPool.objects.create(enterprise=enterprise, tier=2, seats=5)
        assert SeatPool.objects.get().seats == 1

    @pytest.mark.parametrize("tier", [0, 4])
    def test_the_database_refuses_a_tier_outside_1_to_3(self, acme, tier):
        with pytest.raises(IntegrityError), transaction.atomic():
            SeatPool.objects.create(enterprise=acme[0], tier=tier, seats=5)
        assert not SeatPool.objects.exists()


# --- counting what has been given --------------------------------------------------


@pytest.mark.django_db
class TestCounting:
    def test_a_licence_from_the_stock_counts_against_its_tier(self, acme, member):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 5)
        stock_licence(member, 2)
        assert services.seats_given(enterprise) == {1: 0, 2: 1, 3: 0}
        assert row(enterprise, 2) == {"tier": 2, "bought": 5, "given": 1, "set_aside": 0, "left": 4}
        assert row(enterprise, 1) == {"tier": 1, "bought": 0, "given": 0, "set_aside": 0, "left": 0}

    def test_an_admin_holding_one_counts_like_any_member(self, acme):
        enterprise, admin = acme
        stock_licence(admin, 3)
        assert services.seats_given(enterprise) == {1: 0, 2: 0, 3: 1}

    @pytest.mark.parametrize("source", ["manual", "purchase"])
    def test_a_licence_staff_granted_by_hand_is_outside_the_stock(self, acme, member, source):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 5)
        licences.grant_for_membership(member, 2, source, None)
        licences.grant_individual(member.account.person, 2, source, None)
        assert services.seats_given(enterprise) == NOTHING
        assert row(enterprise, 2)["left"] == 5

    def test_one_that_was_taken_back_no_longer_counts(self, acme, member):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 5)
        licences.revoke(stock_licence(member, 2))
        assert services.seats_given(enterprise) == NOTHING
        assert row(enterprise, 2)["left"] == 5

    def test_one_being_used_counts_and_a_submitted_one_counts_for_good(self, acme, member):
        enterprise, admin = acme
        services.set_seat_pool(enterprise, 2, 5)
        take_survey(stock_licence(member, 2))
        take_survey(stock_licence(admin, 2), submitted=True)
        assert services.seats_given(enterprise) == {1: 0, 2: 2, 3: 0}
        assert row(enterprise, 2)["left"] == 3

    def test_a_second_licence_after_a_submitted_one_counts_too(self, acme, member):
        """A retake needs another licence: the spent one and the new one both count."""
        enterprise, _ = acme
        take_survey(stock_licence(member, 2), submitted=True)
        stock_licence(member, 2)
        stock_licence(member, 3)
        assert services.seats_given(enterprise) == {1: 0, 2: 2, 3: 1}

    def test_it_counts_under_the_tier_the_licence_has_now(self, acme, member):
        enterprise, _ = acme
        licence = stock_licence(member, 1)
        licences.change_tier(licence, 3)
        assert services.seats_given(enterprise) == {1: 0, 2: 0, 3: 1}

    def test_a_deactivated_members_unused_licence_still_counts(self, acme, member):
        """It stays with the membership until an admin takes it back."""
        enterprise, admin = acme
        stock_licence(member, 2)
        services.deactivate_membership(member, by=admin)
        assert services.seats_given(enterprise) == {1: 0, 2: 1, 3: 0}

    def test_another_organizations_licences_and_stock_do_not_count(self, acme, member):
        enterprise, _ = acme
        other, other_admin = org_with_admin("Other")
        services.set_seat_pool(other, 2, 9)
        stock_licence(other_admin, 2)
        stock_licence(new_member(other, "carol@example.com"), 1)
        assert services.seats_given(enterprise) == NOTHING
        assert services.seat_summary(enterprise) == [
            {"tier": tier, "bought": 0, "given": 0, "set_aside": 0, "left": 0} for tier in (1, 2, 3)
        ]
        assert row(other, 2) == {"tier": 2, "bought": 9, "given": 1, "set_aside": 0, "left": 8}

    def test_a_stock_lowered_below_what_is_given_takes_nothing_away(self, acme, member):
        enterprise, admin = acme
        services.set_seat_pool(enterprise, 2, 5)
        stock_licence(member, 2)
        stock_licence(admin, 2)
        services.set_seat_pool(enterprise, 2, 1)
        assert row(enterprise, 2) == {"tier": 2, "bought": 1, "given": 2, "set_aside": 0, "left": 0}
        assert Entitlement.objects.filter(revoked_at__isnull=True).count() == 2


# --- the people limit --------------------------------------------------------------


@pytest.mark.django_db
class TestPeopleLimit:
    def test_it_is_the_base_number_plus_every_licence_bought_at_any_tier(self, acme):
        enterprise, _ = acme
        assert services.people_limit(enterprise) == 25
        services.set_seat_pool(enterprise, 1, 2)
        services.set_seat_pool(enterprise, 3, 5)
        assert services.people_limit(enterprise) == 32
        assert services.places_left(enterprise) == 32

    def test_staff_changing_the_base_number_still_works(self, acme):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 5)
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=10)
        enterprise.refresh_from_db()
        assert services.people_limit(enterprise) == 15

    def test_the_26th_person_gets_in_by_code_once_a_licence_is_bought(self, acme):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        code = services.create_code(admin, 5)
        bob = verified_account("bob@example.com")
        message = refusal(lambda: services.redeem_code(code.code, bob))
        assert message == "Acme cannot take more people at the moment. Ask one of its admins."
        services.set_seat_pool(enterprise, 1, 1)
        assert services.redeem_code(code.code, bob).is_active
        assert services.places_left(enterprise) == 0
        carol = verified_account("carol@example.com")
        refusal(lambda: services.redeem_code(code.code, carol))

    def test_the_26th_person_can_be_invited_once_a_licence_is_bought(self, acme):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        message = refusal(lambda: services.invite_by_email(admin, "bob@example.com"))
        assert "no places left" in message
        services.set_seat_pool(enterprise, 3, 1)
        assert services.invite_by_email(admin, "bob@example.com")[0].pk
        assert services.places_left(enterprise) == 0

    def test_giving_licences_out_uses_no_places(self, acme, member):
        """Places follow what was bought, not what was given."""
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 5)
        stock_licence(member, 2)
        assert services.places_left(enterprise) == 30

    def test_a_licence_granted_by_hand_adds_no_place(self, acme, member):
        enterprise, _ = acme
        licences.grant_for_membership(member, 2, "manual", None)
        assert services.people_limit(enterprise) == 25

    def test_a_lowered_stock_lowers_the_limit_and_places_never_go_below_zero(self, acme):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        spend_places(enterprise, 30)
        assert services.places_left(enterprise) == 5
        services.set_seat_pool(enterprise, 2, 2)
        assert services.people_limit(enterprise) == 27
        assert services.places_left(enterprise) == 0

    def test_another_organizations_stock_gives_no_places(self, acme):
        other, _ = org_with_admin("Other")
        services.set_seat_pool(other, 2, 50)
        assert services.people_limit(acme[0]) == 25

    def test_the_organizations_own_pages_show_the_limit_in_effect(self, client, acme):
        enterprise, admin = acme
        services.set_seat_pool(enterprise, 2, 5)
        spend_places(enterprise, 3)
        client.force_login(admin.account)
        for page in ("", "codes/", "invites/"):
            response = client.get(f"/organizations/{enterprise.slug}/{page}")
            assert response.context["places"] == {"left": 27, "limit": 30}, page
            assert "27 of 30 places left" in response.content.decode(), page


# --- the source "from the organization's stock" ------------------------------------


@pytest.mark.django_db
class TestTheSeatSource:
    def test_staff_cannot_grant_one_from_the_stock_by_hand(self, member):
        """Those are given by the organization's admin, within the stock (PR 2)."""
        with pytest.raises(ValidationError):
            licences.grant_for_membership(member, 2, "seat", None)
        with pytest.raises(ValidationError):
            licences.grant_individual(member.account.person, 2, "seat", None)
        assert not Entitlement.objects.exists()

    def test_the_staff_grant_form_does_not_offer_it(self, client, root, member):
        page = client.get(GRANT).content.decode()
        assert 'value="manual"' in page and 'value="purchase"' in page
        assert 'value="seat"' not in page
        response = client.post(GRANT, {"membership": member.pk, "tier": 2, "source": "seat"})
        assert response.status_code == 200  # the form again, with an error
        assert not Entitlement.objects.exists()

    def test_staff_can_still_open_and_find_a_licence_from_the_stock(self, client, root, member):
        licence = stock_licence(member, 2)
        url = f"/admin/entitlements/entitlement/{licence.pk}/change/"
        assert "From the organization" in client.get(url).content.decode()
        assert client.get("/admin/entitlements/entitlement/").status_code == 200


# --- the "Licence stock" page in the Django admin ----------------------------------


@pytest.mark.django_db
class TestTheStockPage:
    def test_the_organizations_page_links_to_it_and_says_none_yet(self, client, root, acme):
        enterprise, _ = acme
        page = client.get(change_page(enterprise)).content.decode()
        assert stock_page(enterprise) in page and "Licence stock" in page
        assert "None yet" in page

    def test_it_has_one_box_per_tier_holding_the_total_so_far(self, client, root, acme, member):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        stock_licence(member, 2)
        response = client.get(stock_page(enterprise))
        assert response.status_code == 200
        form = response.context["form"]
        assert [(name, field.initial) for name, field in form.fields.items()] == [
            ("tier_1", 0),
            ("tier_2", 10),
            ("tier_3", 0),
        ]
        page = response.content.decode()
        assert "Tier 2 licences bought" in page
        assert "1 given to members, 0 set aside for invites and join codes, 9 left." in page
        assert "it can bring in 35 in total" in page

    def test_looking_at_it_changes_nothing(self, client, root, acme):
        client.get(stock_page(acme[0]))
        assert not SeatPool.objects.exists() and not LogEntry.objects.exists()

    def test_saving_sets_the_stock_and_the_history_says_who_and_what(self, client, root, acme):
        enterprise, _ = acme
        data = {"tier_1": 0, "tier_2": 10, "tier_3": 3}
        response = client.post(stock_page(enterprise), data, follow=True)
        assert response.redirect_chain == [(change_page(enterprise), 302)]
        assert services.seats_bought(enterprise) == {1: 0, 2: 10, 3: 3}
        text = "Licence stock changed: Tier 2 from 0 to 10; Tier 3 from 0 to 3"
        assert history(enterprise) == [(root, text)]
        assert text + "." in said(response)
        page = response.content.decode()
        assert (
            "Tier 2: 10 bought, 0 given, 0 set aside, 10 left; "
            "Tier 3: 3 bought, 0 given, 0 set aside, 3 left"
        ) in page
        assert "38 of 38 left" in page

    def test_only_the_tiers_that_changed_are_written_and_logged(self, client, root, acme):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        client.post(stock_page(enterprise), {"tier_1": 0, "tier_2": 10, "tier_3": 4})
        assert history(enterprise) == [(root, "Licence stock changed: Tier 3 from 0 to 4")]
        assert set(SeatPool.objects.values_list("tier", flat=True)) == {2, 3}

    def test_saving_the_same_numbers_changes_nothing_and_leaves_no_history(
        self, client, root, acme
    ):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        data = {"tier_1": 0, "tier_2": 10, "tier_3": 0}
        response = client.post(stock_page(enterprise), data, follow=True)
        assert "Nothing was changed." in said(response)
        assert not LogEntry.objects.exists()
        assert services.seats_bought(enterprise) == {1: 0, 2: 10, 3: 0}

    def test_lowering_it_below_what_is_given_warns_and_takes_nothing_away(
        self, client, root, acme, member
    ):
        enterprise, admin = acme
        services.set_seat_pool(enterprise, 2, 5)
        stock_licence(member, 2)
        stock_licence(admin, 2)
        data = {"tier_1": 0, "tier_2": 1, "tier_3": 0}
        response = client.post(stock_page(enterprise), data, follow=True)
        messages = said(response)
        assert "Tier 2: 2 are already given to members or set aside" in messages
        assert "Nobody loses a licence" in messages
        assert services.seats_bought(enterprise)[2] == 1
        assert Entitlement.objects.filter(revoked_at__isnull=True).count() == 2
        assert "Tier 2: 1 bought, 2 given, 0 set aside, 0 left" in response.content.decode()

    @pytest.mark.parametrize("typed", ["-1", "", "ten", "2.5", str(services.MAX_SEATS + 1)])
    def test_a_number_that_will_not_do_is_an_error_on_the_form(self, client, root, acme, typed):
        enterprise, _ = acme
        services.set_seat_pool(enterprise, 2, 10)
        data = {"tier_1": 4, "tier_2": typed, "tier_3": 0}
        response = client.post(stock_page(enterprise), data)
        assert response.status_code == 200
        assert response.context["form"].errors.keys() == {"tier_2"}
        # Nothing is saved, not even the tier that was typed correctly.
        assert services.seats_bought(enterprise) == {1: 0, 2: 10, 3: 0}
        assert not LogEntry.objects.exists()

    def test_an_organization_that_does_not_exist_is_not_found(self, client, root, acme):
        missing = acme[0].pk + 1000
        assert client.get(f"{ORGANIZATIONS}{missing}/stock/").status_code == 404
        data = {"tier_1": 1, "tier_2": 1, "tier_3": 1}
        assert client.post(f"{ORGANIZATIONS}{missing}/stock/", data).status_code == 404
        assert not SeatPool.objects.exists()

    def test_the_history_line_and_the_messages_name_nobody(self, client, root, acme, member):
        enterprise, admin = acme
        stock_licence(member, 2)
        data = {"tier_1": 0, "tier_2": 0, "tier_3": 7}
        response = client.post(stock_page(enterprise), data, follow=True)
        words = said(response) + " ".join(what for _, what in history(enterprise))
        for account in (root, admin.account, member.account):
            assert account.email not in words
        assert "Acme" not in words


# --- who may set the stock ---------------------------------------------------------


@pytest.mark.django_db
class TestWhoMaySetTheStock:
    DATA = {"tier_1": 0, "tier_2": 6, "tier_3": 0}

    def test_support_staff_see_the_link_and_can_set_it(self, client, support, acme):
        enterprise, _ = acme
        assert stock_page(enterprise) in client.get(change_page(enterprise)).content.decode()
        assert client.get(stock_page(enterprise)).status_code == 200
        response = client.post(stock_page(enterprise), self.DATA, follow=True)
        assert response.status_code == 200
        assert services.seats_bought(enterprise)[2] == 6
        assert history(enterprise) == [(support, "Licence stock changed: Tier 2 from 0 to 6")]

    def test_support_staff_still_cannot_change_the_base_number(self, client, support, acme):
        enterprise, _ = acme
        assert client.post(change_page(enterprise), {"people_limit": 500}).status_code == 403
        enterprise.refresh_from_db()
        assert enterprise.people_limit == 25

    def test_staff_who_may_only_look_at_organizations_get_no_link_and_no_page(
        self, client, db, acme
    ):
        enterprise, _ = acme
        looker = Account.objects.create_user("looker@example.com", PASSWORD)
        looker.is_staff = True
        looker.save()
        looker.user_permissions.add(Permission.objects.get(codename="view_enterprise"))
        client.force_login(looker)
        page = client.get(change_page(enterprise))
        assert page.status_code == 200
        assert stock_page(enterprise) not in page.content.decode()
        assert client.get(stock_page(enterprise)).status_code == 403
        assert client.post(stock_page(enterprise), self.DATA).status_code == 403
        assert not SeatPool.objects.exists() and not LogEntry.objects.exists()

    def test_staff_outside_the_group_cannot_open_or_post_it(self, client, db, acme):
        enterprise, _ = acme
        outsider = Account.objects.create_user("temp@example.com", PASSWORD)
        outsider.is_staff = True
        outsider.save()
        client.force_login(outsider)
        assert client.get(stock_page(enterprise)).status_code == 403
        assert client.post(stock_page(enterprise), self.DATA).status_code == 403
        assert not SeatPool.objects.exists()

    def test_the_organizations_own_admin_and_a_visitor_are_sent_to_the_staff_login(
        self, client, acme
    ):
        enterprise, admin = acme
        for login in (False, True):
            if login:
                client.force_login(admin.account)
            for response in (
                client.get(stock_page(enterprise)),
                client.post(stock_page(enterprise), self.DATA),
            ):
                assert response.status_code == 302
                assert response.url.startswith("/admin/login/")
        assert not SeatPool.objects.exists()
