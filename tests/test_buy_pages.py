"""
Milestone 4b, PR 3: the pages where things are bought.

A person's own page, /buy/, lists the three tiers with today's prices and the
licences they hold that can be moved up. An organization's admin has
/organizations/<slug>/licences/buy/. Every button posts a tier (and a number,
for an organization) and nothing else: the price is the server's. Each ends by
sending the person to Stripe's payment page. With no Stripe key the pages say
buying online is not open yet.

Stripe is played by tests/payments.FakeStripe. Keeping one organization's buy
page from another is in tests/test_tenant_isolation.py.
"""

import pytest
from django.contrib.messages import get_messages

from apps.accounts import services as accounts
from apps.accounts.models import ContactPoint
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.payments import services
from apps.payments.models import Price, Purchase

from . import payments
from .orgs import new_member, org_with_admin
from .test_checkout import submit_survey_on
from .test_profile import verified_account
from .test_response_context import grant, grant_personal

CAROL = "carol@example.com"
BUY = "/buy/"
ACME_BUY = "/organizations/acme/licences/buy/"


@pytest.fixture
def stripe(monkeypatch, settings):
    return payments.install(monkeypatch, settings)


@pytest.fixture
def carol(client, db):
    account = verified_account(CAROL)
    client.force_login(account)
    return account


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def admin(client, acme):
    client.force_login(acme[1].account)
    return acme[1]


def html(client, address):
    page = client.get(address)
    assert page.status_code == 200, f"{address} answered {page.status_code}"
    return " ".join(page.content.decode().split())


def said(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


# --- a person's own page ----------------------------------------------------------------


@pytest.mark.django_db
class TestThePersonalBuyPage:
    def test_it_lists_the_three_tiers_with_todays_prices_and_a_button_each(
        self, client, stripe, carol
    ):
        Price.objects.filter(tier=3).update(amount_cents=1250)
        page = client.get(BUY)
        assert page.context["tiers"] == [
            {"tier": 1, "price": "$1.00"},
            {"tier": 2, "price": "$2.00"},
            {"tier": 3, "price": "$12.50"},
        ]
        text = " ".join(page.content.decode().split())
        for tier, price in ((1, "$1.00"), (2, "$2.00"), (3, "$12.50")):
            assert f"Buy for {price}" in text
            assert f'<input type="hidden" name="tier" value="{tier}">' in text
        assert text.count('action="/buy/personal/"') == 3
        assert "data-closed" not in text
        assert "Accelerare never sees or keeps your card details." in text

    def test_no_price_is_sent_by_the_browser(self, client, stripe, carol):
        """The form carries a tier and nothing else; a made-up amount is ignored."""
        text = html(client, BUY)
        assert 'name="amount"' not in text and 'name="price"' not in text
        client.post("/buy/personal/", {"tier": "3", "amount": "1", "amount_cents": "1"})
        assert Purchase.objects.get().amount_cents == 300
        assert stripe.asked()["unit_amount_cents"] == 300

    def test_the_button_sends_the_person_to_stripes_page(self, client, stripe, carol):
        answer = client.post("/buy/personal/", {"tier": "2"})
        assert answer.status_code == 302
        assert answer["Location"] == f"https://stripe.test/pay/{stripe.last}"
        purchase = Purchase.objects.get()
        assert (purchase.kind, purchase.tier, purchase.buyer) == ("personal", 2, carol)

    @pytest.mark.parametrize("typed", ["", "0", "4", "two", "2.5"])
    def test_anything_but_a_tier_comes_back_with_a_message(self, client, stripe, carol, typed):
        answer = client.post("/buy/personal/", {"tier": typed})
        assert answer.status_code == 302 and answer["Location"] == BUY
        assert said(answer) == [services.CHOOSE_A_TIER]
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_with_no_key_it_says_buying_is_not_open_and_has_no_buttons(self, client, carol):
        page = client.get(BUY)
        text = " ".join(page.content.decode().split())
        assert page.context["open"] is False and services.NOT_OPEN in text
        assert "<button" not in text.split("<main")[1]
        assert "$1.00" in text  # the prices are still shown
        answer = client.post("/buy/personal/", {"tier": "1"})
        assert said(answer) == [services.NOT_OPEN] and not Purchase.objects.exists()

    def test_it_needs_a_login_and_a_verified_email(self, client, stripe, db):
        assert "/accounts/login/" in client.get(BUY)["Location"]
        assert "/accounts/login/" in client.post("/buy/personal/", {"tier": "1"})["Location"]
        carol = verified_account(CAROL)
        ContactPoint.objects.filter(account=carol).update(verified_at=None)
        client.force_login(carol)
        assert client.get(BUY)["Location"] == "/accounts/profile/"
        assert client.post("/buy/personal/", {"tier": "1"})["Location"] == "/accounts/profile/"
        assert not Purchase.objects.exists()

    def test_the_buttons_take_a_post_only(self, client, stripe, carol):
        licence = grant_personal(carol, 1)
        assert client.get("/buy/personal/").status_code == 405
        assert client.get(f"/buy/upgrade/{licence.pk}/").status_code == 405
        assert client.post(BUY, {"tier": "1"}).status_code == 405

    def test_if_stripe_cannot_be_reached_it_says_nothing_was_charged(self, client, stripe, carol):
        stripe.fail = payments.stripe_api.StripeFailed("APIConnectionError (no code)")
        answer = client.post("/buy/personal/", {"tier": "1"})
        assert answer["Location"] == BUY and said(answer) == [services.COULD_NOT_START]


@pytest.mark.django_db
class TestUpgradingOnThePersonalPage:
    def test_each_licence_is_listed_with_the_upgrades_on_offer(self, client, stripe, carol):
        unused = grant_personal(carol, 1)
        started = grant_personal(carol, 2)
        submit_survey_on(started, carol)
        top = grant_personal(carol, 3)
        page = client.get(BUY)
        assert page.context["licences"] == [
            {
                "id": unused.pk,
                "tier": 1,
                "state": "unused",
                "upgrades": [{"tier": 2, "cost": "$1.00"}, {"tier": 3, "cost": "$2.00"}],
            },
            {
                "id": started.pk,
                "tier": 2,
                "state": "submitted",
                "upgrades": [{"tier": 3, "cost": "$1.00"}],
            },
            {"id": top.pk, "tier": 3, "state": "unused", "upgrades": []},
        ]
        text = " ".join(page.content.decode().split())
        assert "Upgrade to Tier 2 for $1.00" in text and "Upgrade to Tier 3 for $2.00" in text
        assert "Not used yet" in text and "Survey submitted" in text
        assert "This is the highest level." in text
        assert f'action="/buy/upgrade/{unused.pk}/"' in text

    def test_someone_with_no_licence_sees_no_such_section(self, client, stripe, carol):
        assert "Your licences" not in html(client, BUY)

    def test_a_withdrawn_licence_and_one_held_through_an_organization_are_not_listed(
        self, client, stripe, carol, acme
    ):
        gone = grant_personal(carol, 1)
        licences.revoke(gone)
        grant(new_member(acme[0], "dan@example.com"), 1)
        member = orgs.Membership.objects.create(account=carol, enterprise=acme[0])
        grant(member, 1)
        assert client.get(BUY).context["licences"] == []

    def test_the_button_sends_the_person_to_stripe_for_the_difference(self, client, stripe, carol):
        licence = grant_personal(carol, 1)
        answer = client.post(f"/buy/upgrade/{licence.pk}/", {"tier": "3", "amount": "1"})
        assert answer["Location"] == f"https://stripe.test/pay/{stripe.last}"
        purchase = Purchase.objects.get()
        assert (purchase.kind, purchase.from_tier, purchase.tier) == ("upgrade", 1, 3)
        assert purchase.amount_cents == 200 and purchase.entitlement == licence

    def test_a_refusal_comes_back_with_a_message(self, client, stripe, carol):
        licence = grant_personal(carol, 2)
        answer = client.post(f"/buy/upgrade/{licence.pk}/", {"tier": "1"})
        assert answer["Location"] == BUY and "already Tier 2" in said(answer)[0]
        assert not Purchase.objects.exists()

    def test_someone_elses_licence_is_not_found(self, client, stripe, carol, acme):
        theirs = grant_personal(verified_account("dan@example.com"), 1)
        through_an_organization = grant(new_member(acme[0], "erin@example.com"), 1)
        for licence in (theirs, through_an_organization):
            assert client.post(f"/buy/upgrade/{licence.pk}/", {"tier": "3"}).status_code == 404
        assert client.post("/buy/upgrade/999999/", {"tier": "3"}).status_code == 404
        assert not Purchase.objects.exists() and stripe.pages == {}


# --- an organization's admin ----------------------------------------------------------------


@pytest.mark.django_db
class TestTheOrganizationBuyPage:
    def test_it_offers_each_tier_with_its_price_and_asks_how_many(self, client, stripe, admin):
        text = html(client, ACME_BUY)
        for tier, price in ((1, "$1.00"), (2, "$2.00"), (3, "$3.00")):
            assert f'<option value="{tier}">Tier {tier} licence, {price} each</option>' in text
        assert 'name="quantity"' in text and "Continue to payment" in text
        assert "a numbered invoice" in text and "bring in one more person" in text

    def test_the_form_sends_the_admin_to_stripe_for_the_number_times_the_price(
        self, client, stripe, acme, admin
    ):
        answer = client.post(ACME_BUY, {"tier": "2", "quantity": "3", "amount": "1"})
        assert answer.status_code == 302
        assert answer["Location"] == f"https://stripe.test/pay/{stripe.last}"
        purchase = Purchase.objects.get()
        assert (purchase.kind, purchase.enterprise, purchase.buyer) == (
            "stock",
            acme[0],
            admin.account,
        )
        assert (purchase.tier, purchase.quantity, purchase.amount_cents) == (2, 3, 600)

    @pytest.mark.parametrize(
        "data, said_on_the_page",
        [
            ({"tier": "2", "quantity": "0"}, "Buy from 1 to 1,000 licences at a time."),
            ({"tier": "2", "quantity": "1001"}, "Buy from 1 to 1,000 licences at a time."),
            ({"tier": "2", "quantity": "three"}, "Enter a whole number."),
            ({"tier": "2"}, "Enter how many licences to buy."),
            ({"tier": "4", "quantity": "2"}, "Choose a tier from the list."),
            ({"quantity": "2"}, "Choose a tier."),
        ],
    )
    def test_something_that_will_not_do_is_asked_for_again(
        self, client, stripe, admin, data, said_on_the_page
    ):
        page = client.post(ACME_BUY, data)
        assert page.status_code == 200 and said_on_the_page in page.content.decode()
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_with_no_key_it_says_buying_is_not_open_and_has_no_form(self, client, admin):
        text = html(client, ACME_BUY)
        assert services.NOT_OPEN in text and "Continue to payment" not in text
        page = client.post(ACME_BUY, {"tier": "2", "quantity": "3"})
        assert page.status_code == 200 and not Purchase.objects.exists()

    def test_a_member_who_is_not_an_admin_cannot_open_it(self, client, stripe, acme):
        member = new_member(acme[0], "member@example.com")
        client.force_login(member.account)
        assert client.get(ACME_BUY).status_code == 404
        assert client.post(ACME_BUY, {"tier": "2", "quantity": "3"}).status_code == 404
        assert not Purchase.objects.exists()

    def test_the_whole_journey_ends_with_the_licences_in_the_stock(
        self, client, stripe, acme, admin
    ):
        client.post(ACME_BUY, {"tier": "2", "quantity": "3"})
        stripe.pay()
        landed = client.get("/buy/done/", {"session_id": stripe.last}, follow=True)
        text = " ".join(landed.content.decode().split())
        assert landed.redirect_chain[-1][0] == "/organizations/acme/licences/"
        assert "3 Tier 2 licences have been added to Acme" in text
        assert "3 of 3 Tier 2 licences left" in text
        assert orgs.people_limit(acme[0]) == 28


# --- the links that lead there -------------------------------------------------------------


@pytest.mark.django_db
class TestTheLinksToBuying:
    def test_my_surveys_offers_to_buy_when_there_is_no_licence(self, client, stripe, carol):
        text = html(client, "/survey/history/")
        assert "Taking the survey needs a licence." in text
        assert '<a href="/buy/"' in text and "Buy a licence" in text
        assert "by hand" not in text

    def test_the_start_page_offers_to_buy_when_there_is_no_licence(self, client, stripe, carol):
        text = html(client, "/survey/start/")
        assert "You need a licence to take the survey" in text and '<a href="/buy/"' in text
        assert "by hand" not in text

    def test_for_an_organization_it_says_to_ask_an_admin_and_offers_nothing_to_buy(
        self, client, stripe, carol, acme
    ):
        orgs.Membership.objects.create(account=carol, enterprise=acme[0])
        text = html(client, "/survey/start/acme/")
        assert "Ask one of its admins for one." in text and '<a href="/buy/"' not in text
        assert "by hand" not in text
        assert "needs a licence from it. Ask one of its admins" in html(client, "/survey/history/")

    def test_a_personal_result_below_the_top_tier_offers_the_upgrade(self, client, stripe, carol):
        low = submit_survey_on(grant_personal(carol, 1), carol)
        top = submit_survey_on(grant_personal(carol, 3), carol)
        assert "data-upgrade" in html(client, f"/survey/{low.pk}/result/")
        assert "data-upgrade" not in html(client, f"/survey/{top.pk}/result/")

    def test_an_admins_pages_link_to_buying_for_the_stock(self, client, stripe, admin):
        for address in ("/organizations/acme/", "/organizations/acme/licences/"):
            text = html(client, address)
            assert f'<a href="{ACME_BUY}">Buy licences</a>' in text
            assert "Contact Accelerare to buy" not in text

    def test_the_whole_personal_journey_ends_with_a_licence_to_start_on(
        self, client, stripe, carol
    ):
        accounts.set_full_name(carol, "Carol Example")
        client.post("/buy/personal/", {"tier": "2"})
        stripe.pay()
        landed = client.get("/buy/done/", {"session_id": stripe.last}, follow=True)
        text = " ".join(landed.content.decode().split())
        assert landed.redirect_chain[-1][0] == "/survey/history/"
        assert "Thank you. Your Tier 2 licence is ready." in text
        assert "You have 1 unused licence" in text and "Start" in text
