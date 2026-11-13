"""
Milestone 4, PR 3: the organization admin's Licences page,
/organizations/<slug>/licences/, and the "Licences" box on the dashboard.

The page shows the organization's stock tier by tier ("1 of 2 Tier 2 licences
left") and each member with the licences they hold and whether the survey on
each is not started, in progress or submitted. Its buttons give a member a
licence, change a licence's tier and take one back; taking back asks first,
and warns when an unfinished survey will be deleted with it.

The rules themselves are tested at the services (tests/test_seat_services.py).
This file is about the page: that each button calls the service, that what the
service refuses is said in plain words, and that the page only offers what
would work. Who may open the page is in tests/test_tenant_isolation.py.
"""

import pytest

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.responses.models import Response

from .orgs import new_member, org_with_admin
from .test_response_context import fresh, grant
from .test_seat_pools import row as stock_line
from .test_seat_pools import take_survey

ACME = "/organizations/acme/"
LICENCES = "/organizations/acme/licences/"
MEMBERS = "/organizations/acme/members/"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with two Tier 2 licences and one Tier 3 bought"""
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 2)
    orgs.set_seat_pool(enterprise, 3, 1)
    return enterprise, admin


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    accounts.set_full_name(acme[1].account, "Alice Example")
    client.force_login(acme[1].account)
    return acme[1]


@pytest.fixture
def bob(acme):
    """Bob, an ordinary member of Acme (not logged in)."""
    member = new_member(acme[0], "bob@example.com")
    accounts.set_full_name(member.account, "Bob Example")
    return member


def html(client, address=LICENCES):
    page = client.get(address)
    assert page.status_code == 200, f"{address} answered {page.status_code}"
    return page.content.decode()


def after(client, address, data=None):
    """Send a form and return the page the person lands on, as (address, text)."""
    page = client.post(address, data or {}, follow=True)
    assert page.status_code == 200
    return page.redirect_chain[-1][0], page.content.decode()


def shown(client, membership):
    """What the Licences page gave its template for one member."""
    rows = client.get(LICENCES).context["rows"]
    return next(row for row in rows if row["id"] == membership.pk)


def one_licence(client, membership):
    """The only licence the page shows for a member."""
    (licence,) = shown(client, membership)["licences"]
    return licence


def give(membership):
    return f"{LICENCES}members/{membership.pk}/give/"


def change(licence):
    return f"{LICENCES}{licence.pk}/tier/"


def take_back(licence):
    return f"{LICENCES}{licence.pk}/take-back/"


def held(membership):
    """The licences a membership holds now (not taken back)."""
    return list(Entitlement.objects.filter(membership=membership, revoked_at__isnull=True))


# --- what the page shows -------------------------------------------------------------


@pytest.mark.django_db
class TestThePage:
    def test_it_shows_the_stock_tier_by_tier(self, client, acme, admin, bob):
        text = html(client)
        assert "2 of 2 Tier 2 licences left" in " ".join(text.split())
        assert "1 of 1 Tier 3 licence left" in " ".join(text.split())
        assert "Tier 1 licence" not in text  # none bought: no line
        licences.assign_seat(admin, bob, 2)
        assert "1 of 2 Tier 2 licences left" in " ".join(html(client).split())

    def test_with_nothing_bought_it_says_so_and_offers_nothing(self, client, admin, bob):
        for tier in (2, 3):
            orgs.set_seat_pool(admin.enterprise, tier, 0)
        text = html(client)
        assert "Acme has no licences in stock yet" in text
        assert "/give/" not in text
        assert client.get(LICENCES).context["stock"] == []

    def test_every_active_member_is_listed_the_admin_too(self, client, admin, bob):
        text = html(client)
        assert "Alice Example" in text and "(you)" in text
        assert "Bob Example" in text and "bob@example.com" in text
        assert shown(client, admin)["is_you"] and not shown(client, bob)["is_you"]
        assert shown(client, bob) == {
            "id": bob.pk,
            "name": "Bob Example",
            "email": "bob@example.com",
            "erased": False,
            "active": True,
            "is_you": False,
            "can_give": True,
            "licences": [],
            "promised": None,
        }
        assert "No licence" in text and give(bob) in text and give(admin) in text

    def test_only_tiers_with_one_left_are_offered(self, client, acme, admin, bob):
        assert client.get(LICENCES).context["give_tiers"] == [2, 3]
        licences.assign_seat(admin, admin, 3)
        page = client.get(LICENCES)
        assert page.context["give_tiers"] == [2]
        text = page.content.decode()
        assert '<option value="2">' in text and '<option value="3">' not in text

    def test_with_none_left_to_give_it_says_so(self, client, acme, admin, bob):
        carol = new_member(acme[0], "carol@example.com")
        dan = new_member(acme[0], "dan@example.com")
        for member, tier in ((bob, 2), (carol, 2), (dan, 3)):
            licences.assign_seat(admin, member, tier)
        text = html(client)
        assert "There are no licences left to give." in text
        assert "/give/" not in text  # the admin could be given one, but there is none
        assert "0 of 2 Tier 2 licences left" in " ".join(text.split())

    def test_a_stock_lowered_below_what_is_given_says_how_many_are_given(
        self, client, acme, admin, bob
    ):
        licences.assign_seat(admin, bob, 2)
        licences.assign_seat(admin, admin, 2)
        orgs.set_seat_pool(acme[0], 2, 1)
        text = " ".join(html(client).split())
        assert "2 of 1 Tier 2 licence given." in text
        assert "No more can be given at this tier" in text
        assert len(held(bob)) == 1 and len(held(admin)) == 1  # nobody lost theirs

    def test_an_unused_licence_can_be_changed_or_taken_back_but_not_doubled(
        self, client, admin, bob
    ):
        licence = licences.assign_seat(admin, bob, 2)
        assert one_licence(client, bob) == {
            "id": licence.pk,
            "tier": 2,
            "state": "unused",
            "from_stock": True,
            "can_take_back": True,
            "move_to": [3],
        }
        assert not shown(client, bob)["can_give"]
        text = html(client)
        assert "Not used yet" in text
        assert change(licence) in text and take_back(licence) in text
        assert give(bob) not in text

    def test_a_licence_whose_survey_is_in_progress_says_so(self, client, admin, bob):
        licence = licences.assign_seat(admin, bob, 2)
        take_survey(licence)
        facts = one_licence(client, bob)
        assert facts["state"] == "in_progress" and facts["can_take_back"]
        assert facts["move_to"] == [3]
        assert not shown(client, bob)["can_give"]
        assert "Survey in progress" in html(client)

    def test_a_submitted_licence_is_spent_it_can_only_go_up(self, client, admin, bob):
        licence = licences.assign_seat(admin, bob, 2)
        take_survey(licence, submitted=True)
        orgs.set_seat_pool(admin.enterprise, 1, 4)
        facts = one_licence(client, bob)
        assert facts["state"] == "submitted" and not facts["can_take_back"]
        assert facts["move_to"] == [3]  # not down to Tier 1, though it has some left
        text = html(client)
        assert "Survey submitted" in text and take_back(licence) not in text
        # A retake needs another licence, and they can now be given one.
        assert shown(client, bob)["can_give"] and give(bob) in text
        assert "1 of 2 Tier 2 licences left" in " ".join(text.split())

    def test_a_licence_staff_granted_is_shown_without_buttons(self, client, admin, bob):
        licence = grant(bob, 1)
        assert one_licence(client, bob) == {
            "id": licence.pk,
            "tier": 1,
            "state": "unused",
            "from_stock": False,
            "can_take_back": False,
            "move_to": [],
        }
        text = html(client)
        assert "Granted by Accelerare, not from your stock." in text
        assert change(licence) not in text and take_back(licence) not in text
        # They have a licence they have not used, so they are not offered another.
        assert give(bob) not in text
        assert "2 of 2 Tier 2 licences left" in " ".join(text.split())  # outside the stock

    def test_a_licence_that_was_taken_back_is_not_shown(self, client, admin, bob):
        licence = licences.assign_seat(admin, bob, 2)
        licences.take_back_seat(admin, licence)
        assert shown(client, bob)["licences"] == []
        assert shown(client, bob)["can_give"]

    def test_a_member_who_left_is_listed_only_while_they_hold_a_licence(
        self, client, acme, admin, bob
    ):
        carol = new_member(acme[0], "carol@example.com")
        licence = licences.assign_seat(admin, bob, 2)
        for member in (bob, carol):
            orgs.deactivate_membership(member, by=admin)
        rows = client.get(LICENCES).context["rows"]
        assert [row["id"] for row in rows] == [admin.pk, bob.pk]
        facts = shown(client, bob)
        assert not facts["active"] and not facts["can_give"]
        assert facts["licences"][0]["can_take_back"]
        text = html(client)
        assert "(no longer a member)" in text and take_back(licence) in text
        assert give(bob) not in text
        after(client, take_back(licence))
        assert [row["id"] for row in client.get(LICENCES).context["rows"]] == [admin.pk]

    def test_an_erased_member_who_used_a_licence_has_no_name(self, client, admin, bob):
        licence = licences.assign_seat(admin, bob, 2)
        take_survey(licence, submitted=True)
        erasure.erase_account(bob.account)
        facts = shown(client, bob)
        assert facts["erased"] and facts["name"] == "Erased member" and facts["email"] == ""
        text = html(client)
        assert "Erased member" in text
        assert "Bob Example" not in text and "bob@example.com" not in text
        # The licence was used, so it still counts.
        assert stock_line(admin.enterprise, 2)["given"] == 1


# --- giving --------------------------------------------------------------------------


@pytest.mark.django_db
class TestGiving:
    def test_the_button_gives_the_member_a_licence_from_the_stock(self, client, admin, bob):
        landed, text = after(client, give(bob), {"tier": "2"})
        assert landed == LICENCES
        (licence,) = held(bob)
        assert (licence.tier, licence.source, licence.granted_by) == (2, "seat", admin.account)
        assert "Bob Example now has a Tier 2 licence." in text
        assert "1 of 2 Tier 2 licences left" in " ".join(text.split())

    def test_an_admin_can_give_one_to_themselves(self, client, admin):
        _, text = after(client, give(admin), {"tier": "3"})
        assert "You now have a Tier 3 licence." in text
        assert [licence.tier for licence in held(admin)] == [3]

    def test_a_member_with_no_name_is_called_the_member(self, client, acme, admin):
        nameless = new_member(acme[0], "nameless@example.com")
        _, text = after(client, give(nameless), {"tier": "2"})
        assert "The member now has a Tier 2 licence." in text

    def test_with_none_left_it_is_refused_in_plain_words(self, client, acme, admin, bob):
        licences.assign_seat(admin, admin, 3)
        landed, text = after(client, give(bob), {"tier": "3"})
        assert landed == LICENCES
        assert "There are no Tier 3 licences left to give." in text
        assert held(bob) == []

    def test_a_second_unused_licence_is_refused(self, client, admin, bob):
        licences.assign_seat(admin, bob, 2)
        _, text = after(client, give(bob), {"tier": "2"})
        assert "They already have a licence they have not used." in text
        assert len(held(bob)) == 1

    def test_a_deactivated_member_is_refused(self, client, admin, bob):
        orgs.deactivate_membership(bob, by=admin)
        _, text = after(client, give(bob), {"tier": "2"})
        assert "This member has been deactivated." in text
        assert held(bob) == []

    @pytest.mark.parametrize("typed", ["", "0", "4", "2.0", "two", "-1", "True"])
    def test_anything_but_a_tier_is_refused(self, client, admin, bob, typed):
        _, text = after(client, give(bob), {"tier": typed})
        assert "Choose a tier from the list." in text
        assert held(bob) == []

    def test_it_only_answers_a_form(self, client, admin, bob):
        assert client.get(give(bob)).status_code == 405
        assert client.post(f"{LICENCES}members/999999/give/", {"tier": "2"}).status_code == 404
        assert held(bob) == []


# --- changing the tier ---------------------------------------------------------------


@pytest.mark.django_db
class TestChangingTheTier:
    @pytest.fixture
    def licence(self, admin, bob):
        return licences.assign_seat(admin, bob, 2)

    def test_the_button_moves_the_licence_between_the_two_stocks(self, client, admin, bob, licence):
        landed, text = after(client, change(licence), {"tier": "3"})
        assert landed == LICENCES and "The licence is now Tier 3." in text
        assert fresh(licence).tier == 3
        text = " ".join(text.split())
        assert "2 of 2 Tier 2 licences left" in text and "0 of 1 Tier 3 licence left" in text

    def test_a_tier_with_none_left_is_refused(self, client, admin, bob, licence):
        licences.assign_seat(admin, admin, 3)
        _, text = after(client, change(licence), {"tier": "3"})
        assert "There are no Tier 3 licences left to give." in text
        assert fresh(licence).tier == 2

    def test_after_the_survey_is_submitted_only_up(self, client, admin, bob, licence):
        take_survey(licence, submitted=True)
        orgs.set_seat_pool(admin.enterprise, 1, 4)
        _, text = after(client, change(licence), {"tier": "1"})
        assert "so its tier can only go up" in text and fresh(licence).tier == 2
        _, text = after(client, change(licence), {"tier": "3"})
        assert "The licence is now Tier 3." in text and fresh(licence).tier == 3

    def test_a_licence_staff_granted_is_not_the_admins_to_change(self, client, admin, bob):
        manual = grant(bob, 1)
        _, text = after(client, change(manual), {"tier": "2"})
        assert "granted by Accelerare" in text and fresh(manual).tier == 1

    @pytest.mark.parametrize("typed", ["", "0", "4", "2.0", "two"])
    def test_anything_but_a_tier_is_refused(self, client, admin, licence, typed):
        _, text = after(client, change(licence), {"tier": typed})
        assert "Choose a tier from the list." in text
        assert fresh(licence).tier == 2

    def test_it_only_answers_a_form(self, client, admin, licence):
        assert client.get(change(licence)).status_code == 405
        assert client.post(f"{LICENCES}999999/tier/", {"tier": "3"}).status_code == 404
        assert fresh(licence).tier == 2


# --- taking back ---------------------------------------------------------------------


@pytest.mark.django_db
class TestTakingBack:
    @pytest.fixture
    def licence(self, admin, bob):
        return licences.assign_seat(admin, bob, 2)

    def test_it_asks_first_and_opening_the_page_changes_nothing(self, client, admin, bob, licence):
        text = html(client, take_back(licence))
        assert "Take back this licence?" in text
        assert "the Tier 2 licence you gave Bob Example" in text
        assert "They have not started the survey on it" in text
        assert "will be deleted" not in text
        assert fresh(licence).revoked_at is None

    def test_confirming_puts_it_back_in_the_stock(self, client, admin, bob, licence):
        landed, text = after(client, take_back(licence))
        assert landed == LICENCES
        assert "The Tier 2 licence is back in your stock." in text
        assert "was deleted" not in text
        assert fresh(licence).revoked_at is not None  # kept as a record, not deleted
        assert "2 of 2 Tier 2 licences left" in " ".join(text.split())
        assert shown(client, bob)["licences"] == [] and shown(client, bob)["can_give"]

    def test_it_warns_when_an_unfinished_survey_will_be_deleted(self, client, admin, bob, licence):
        draft = take_survey(licence)
        text = html(client, take_back(licence))
        assert "They have started the survey on this licence." in text
        assert "Their unfinished survey will be deleted" in text
        assert Response.objects.filter(pk=draft.pk).exists()  # only a warning so far
        _, text = after(client, take_back(licence))
        assert "The unfinished survey on it was deleted." in text
        assert not Response.objects.filter(pk=draft.pk).exists()
        assert fresh(licence).revoked_at is not None

    def test_a_submitted_one_cannot_be_taken_back(self, client, admin, bob, licence):
        survey = take_survey(licence, submitted=True)
        refusal = "The survey on this licence has been submitted, so it cannot be taken back."
        asked = client.get(take_back(licence), follow=True)
        assert asked.redirect_chain[-1][0] == LICENCES and refusal in asked.content.decode()
        _, text = after(client, take_back(licence))
        assert refusal in text
        assert fresh(licence).revoked_at is None
        assert Response.objects.filter(pk=survey.pk).exists()

    def test_a_licence_staff_granted_cannot_be_taken_back(self, client, admin, bob):
        manual = grant(bob, 1)
        asked = client.get(take_back(manual), follow=True)
        assert "granted by Accelerare" in asked.content.decode()
        assert asked.redirect_chain[-1][0] == LICENCES
        _, text = after(client, take_back(manual))
        assert "granted by Accelerare" in text and fresh(manual).revoked_at is None

    def test_one_already_taken_back_says_so(self, client, admin, bob, licence):
        licences.take_back_seat(admin, licence)
        when = fresh(licence).revoked_at
        asked = client.get(take_back(licence), follow=True)
        assert "That licence has already been taken back." in asked.content.decode()
        _, text = after(client, take_back(licence))
        assert "That licence has already been taken back." in text
        assert fresh(licence).revoked_at == when

    def test_a_member_with_no_name_is_called_this_member(self, client, acme, admin):
        nameless = new_member(acme[0], "nameless@example.com")
        licence = licences.assign_seat(admin, nameless, 2)
        assert "the Tier 2 licence you gave this member." in html(client, take_back(licence))

    def test_an_unknown_licence_is_not_found(self, client, admin):
        assert client.get(f"{LICENCES}999999/take-back/").status_code == 404
        assert client.post(f"{LICENCES}999999/take-back/").status_code == 404


# --- the dashboard and the members page ----------------------------------------------


@pytest.mark.django_db
class TestTheDashboardBox:
    def test_an_admin_sees_the_stock_and_the_way_to_the_page(self, client, admin, bob):
        licences.assign_seat(admin, bob, 2)
        text = html(client, ACME)
        assert "Licences" in text and f'href="{LICENCES}"' in text
        text = " ".join(text.split())
        assert "1 of 2 Tier 2 licences left" in text and "1 of 1 Tier 3 licence left" in text

    def test_with_nothing_bought_it_says_so(self, client, admin):
        for tier in (2, 3):
            orgs.set_seat_pool(admin.enterprise, tier, 0)
        text = html(client, ACME)
        assert "Acme has none in stock yet" in text and f'href="{LICENCES}"' in text

    def test_a_member_sees_no_box(self, client, acme, bob):
        client.force_login(bob.account)
        text = html(client, ACME)
        assert LICENCES not in text and "licences left" not in text

    def test_the_members_page_links_to_it(self, client, admin):
        assert f'href="{LICENCES}"' in html(client, MEMBERS)
