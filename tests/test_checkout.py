"""
Milestone 4b, PR 2: starting a purchase, and giving what was paid for.

The rules (the founder's, 2026-11-13). A person buys one personal licence at a
tier, or pays the difference to raise one they hold. An organization's admin
buys a number of licences of one tier into its stock. The amount is the
server's, read from the database. What was paid for is given exactly once,
whether the page the person returns to or Stripe's own message arrives first,
and whatever else happens the payment record is kept.

Stripe is played by tests/payments.FakeStripe throughout.
"""

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import ContactPoint
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.payments import services, stripe_api
from apps.payments.models import Price, Purchase
from apps.responses.models import Response
from apps.survey.services import current_version

from . import payments
from .orgs import new_member, org_with_admin, run_together
from .test_enterprise_services import refusal
from .test_profile import verified_account
from .test_response_context import fresh, grant, grant_personal
from .test_seat_pools import row as stock_line
from .test_seat_services import events
from .test_verification import fake_request

CAROL = "carol@example.com"
DONE = "/buy/done/"


@pytest.fixture
def stripe(monkeypatch, settings):
    return payments.install(monkeypatch, settings)


@pytest.fixture
def carol(db):
    return verified_account(CAROL)


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


def buy(account, tier=2):
    return services.start_personal(account, tier, request=fake_request())


def upgrade(account, licence, tier):
    return services.start_upgrade(account, licence, tier, request=fake_request())


def buy_stock(admin, tier=2, quantity=3):
    return services.start_stock(admin, tier, quantity, request=fake_request())


def said(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def submit_survey_on(licence, account):
    """The person takes the survey on a personal licence and submits it."""
    return Response.objects.create(
        account=account,
        survey_version=current_version(),
        entitlement=licence,
        status="submitted",
        submitted_at=timezone.now(),
    )


def personal_licences(account):
    return list(Entitlement.objects.filter(person=account.person))


# --- starting ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStartingAPersonalPurchase:
    def test_it_writes_a_pending_row_and_opens_a_page_for_the_servers_price(self, stripe, carol):
        address = buy(carol, tier=2)
        purchase = Purchase.objects.get()
        assert address == f"https://stripe.test/pay/{stripe.last}"
        assert (purchase.kind, purchase.status, purchase.buyer) == ("personal", "pending", carol)
        assert (purchase.tier, purchase.quantity, purchase.amount_cents) == (2, 1, 200)
        assert purchase.stripe_session_id == stripe.last and purchase.entitlement is None
        asked = stripe.asked()
        assert asked["reference"] == purchase.pk and asked["description"] == "Tier 2 licence"
        assert (asked["unit_amount_cents"], asked["quantity"], asked["currency"]) == (200, 1, "usd")
        assert asked["email"] == CAROL and asked["invoice"] is False
        assert asked["success_url"] == (
            "http://testserver/buy/done/?session_id={CHECKOUT_SESSION_ID}"
        )
        assert asked["cancel_url"] == f"http://testserver/buy/cancelled/?purchase={purchase.pk}"
        assert personal_licences(carol) == [] and events() == []  # nothing is given yet

    def test_the_price_is_todays_whatever_it_was_before(self, stripe, carol):
        Price.objects.filter(tier=2).update(amount_cents=1250)
        buy(carol, tier=2)
        assert Purchase.objects.get().amount_cents == 1250
        assert stripe.asked()["unit_amount_cents"] == 1250

    @pytest.mark.parametrize("tier", [0, 4, "2", 2.0, True, None])
    def test_anything_but_a_tier_is_refused_before_stripe_is_asked(self, stripe, carol, tier):
        assert refusal(lambda: buy(carol, tier)) == services.CHOOSE_A_TIER
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_an_account_that_has_not_verified_its_email_cannot_buy(self, stripe, carol):
        ContactPoint.objects.filter(account=carol).update(verified_at=None)
        assert refusal(lambda: buy(carol)) == "Verify your email address before buying."
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_an_erased_or_switched_off_account_cannot_buy(self, stripe, carol):
        carol.is_active = False
        carol.save()
        assert refusal(lambda: buy(carol)) == "This account cannot buy a licence."

    def test_with_no_key_buying_is_not_open(self, carol, settings):
        assert services.is_open() is False
        assert refusal(lambda: buy(carol)) == services.NOT_OPEN
        assert not Purchase.objects.exists()

    def test_if_the_page_cannot_be_opened_the_row_says_so_and_nothing_is_charged(
        self, stripe, carol, caplog
    ):
        stripe.fail = stripe_api.StripeFailed("APIConnectionError (no code)")
        assert refusal(lambda: buy(carol)) == services.COULD_NOT_START
        purchase = Purchase.objects.get()
        assert purchase.status == "failed" and purchase.stripe_session_id is None
        assert "Could not open a payment page" in caplog.text and CAROL not in caplog.text

    def test_someone_may_buy_a_second_licence_while_holding_an_unused_one(self, stripe, carol):
        grant_personal(carol, 1)
        buy(carol, tier=1)
        assert Purchase.objects.count() == 1


@pytest.mark.django_db
class TestStartingAnUpgrade:
    def test_it_charges_the_difference_between_the_two_prices(self, stripe, carol):
        licence = grant_personal(carol, 1)
        upgrade(carol, licence, 3)
        purchase = Purchase.objects.get()
        assert (purchase.kind, purchase.from_tier, purchase.tier) == ("upgrade", 1, 3)
        assert purchase.amount_cents == 200 and purchase.entitlement == licence
        assert stripe.asked()["description"] == "Upgrade from Tier 1 to Tier 3"
        assert stripe.asked()["unit_amount_cents"] == 200
        assert fresh(licence).tier == 1  # not until it is paid

    def test_the_tiers_on_offer_and_what_each_costs(self, carol):
        assert services.upgrades_for(grant_personal(carol, 1)) == {2: 100, 3: 200}
        assert services.upgrades_for(grant_personal(carol, 2)) == {3: 100}
        assert services.upgrades_for(grant_personal(carol, 3)) == {}

    def test_a_difference_too_small_for_stripe_to_charge_is_not_offered(self, stripe, carol):
        Price.objects.filter(tier=2).update(amount_cents=120)  # 20 cents above Tier 1
        licence = grant_personal(carol, 1)
        assert services.upgrades_for(licence) == {3: 200}
        assert refusal(lambda: upgrade(carol, licence, 2)) == (
            "That upgrade is not available at the moment."
        )

    def test_a_licence_can_be_upgraded_after_its_survey_is_submitted(self, stripe, carol):
        licence = grant_personal(carol, 1)
        submit_survey_on(licence, carol)
        upgrade(carol, licence, 2)
        assert Purchase.objects.get().kind == "upgrade"

    def test_the_same_or_a_lower_tier_is_refused(self, stripe, carol):
        licence = grant_personal(carol, 2)
        for tier in (1, 2):
            assert "already Tier 2" in refusal(lambda tier=tier: upgrade(carol, licence, tier))
        assert not Purchase.objects.exists()

    def test_someone_elses_licence_is_not_found(self, stripe, carol):
        theirs = grant_personal(verified_account("dan@example.com"), 1)
        with pytest.raises(services.NotFound):
            upgrade(carol, theirs, 2)
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_a_licence_held_through_an_organization_cannot_be_upgraded_by_paying(
        self, stripe, acme
    ):
        member = new_member(acme[0], CAROL)
        licence = grant(member, 1)
        assert services.upgrades_for(licence) == {}
        with pytest.raises(services.NotFound):
            upgrade(member.account, licence, 2)

    def test_a_withdrawn_licence_cannot_be_upgraded(self, stripe, carol):
        licence = grant_personal(carol, 1)
        licences.revoke(licence)
        assert services.upgrades_for(fresh(licence)) == {}
        assert "withdrawn" in refusal(lambda: upgrade(carol, licence, 2))


@pytest.mark.django_db
class TestStartingAStockPurchase:
    def test_it_writes_a_pending_row_for_the_number_times_the_price(self, stripe, acme):
        enterprise, admin = acme
        buy_stock(admin, tier=2, quantity=3)
        purchase = Purchase.objects.get()
        assert (purchase.kind, purchase.enterprise, purchase.buyer) == (
            "stock",
            enterprise,
            admin.account,
        )
        assert (purchase.tier, purchase.quantity) == (2, 3)
        assert (purchase.unit_amount_cents, purchase.amount_cents) == (200, 600)
        asked = stripe.asked()
        assert (asked["unit_amount_cents"], asked["quantity"]) == (200, 3)
        assert asked["description"] == "Tier 2 licence for Acme"
        assert asked["invoice"] is True  # an organization also gets a numbered invoice
        assert orgs.seats_bought(enterprise)[2] == 0  # not until it is paid

    @pytest.mark.parametrize("quantity", [0, -1, 1001, "3", 2.0, True, None])
    def test_a_number_that_will_not_do_is_refused(self, stripe, acme, quantity):
        refusal(lambda: buy_stock(acme[1], quantity=quantity))
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_up_to_a_thousand_at_a_time(self, stripe, acme):
        buy_stock(acme[1], quantity=1000)
        assert Purchase.objects.get().amount_cents == 200_000

    def test_only_an_active_admin_of_that_organization_can(self, stripe, acme):
        enterprise, _ = acme
        member = new_member(enterprise, "member@example.com")
        former = new_member(enterprise, "former@example.com", active=False)
        _, outsider = org_with_admin("Other")
        outsider.enterprise_id = enterprise.pk  # forged; read again, not trusted
        for who in (member, former, outsider):
            assert refusal(lambda who=who: buy_stock(who)) == (
                "Only an admin of this organization can do that."
            )
        assert not Purchase.objects.exists() and stripe.pages == {}

    def test_a_stock_cannot_be_bought_past_the_most_allowed(self, stripe, acme):
        orgs.set_seat_pool(acme[0], 2, orgs.MAX_SEATS - 2)
        refusal(lambda: buy_stock(acme[1], quantity=3))
        buy_stock(acme[1], quantity=2)


# --- giving what was paid for ---------------------------------------------------------------


@pytest.mark.django_db
class TestGivingWhatWasPaidFor:
    def test_a_paid_personal_purchase_gives_the_licence(self, stripe, carol):
        buy(carol, tier=2)
        purchase = services.fulfil(stripe.pay())
        (licence,) = personal_licences(carol)
        assert (licence.tier, licence.source, licence.granted_by) == (2, "purchase", None)
        assert purchase.status == "paid" and purchase.entitlement == licence
        assert purchase.paid_at is not None and not purchase.needs_attention
        assert purchase.stripe_payment_intent_id == f"pi_{stripe.last}"
        assert events() == [("licence_granted", 2, "purchase")]
        assert licences.has_survey_access(carol)

    def test_a_paid_upgrade_raises_the_tier_in_place(self, stripe, carol):
        licence = grant_personal(carol, 1)
        submit_survey_on(licence, carol)
        upgrade(carol, licence, 3)
        purchase = services.fulfil(stripe.pay())
        assert fresh(licence).tier == 3 and purchase.status == "paid"
        assert len(personal_licences(carol)) == 1  # the same licence, not a new one
        assert events()[-1][:2] == ("licence_upgraded", 3)

    def test_a_paid_stock_purchase_adds_to_the_stock_and_the_people_limit(self, stripe, acme):
        enterprise, admin = acme
        buy_stock(admin, tier=2, quantity=3)
        purchase = services.fulfil(stripe.pay())
        assert purchase.status == "paid" and purchase.stripe_invoice_id == f"in_{stripe.last}"
        assert stock_line(enterprise, 2)["bought"] == 3 and stock_line(enterprise, 2)["left"] == 3
        assert orgs.people_limit(enterprise) == 28
        assert not Entitlement.objects.exists()  # licences are given to members later, by hand

    def test_giving_twice_gives_once(self, stripe, carol, acme):
        buy(carol)
        paid = stripe.pay()
        for _ in range(3):
            services.fulfil(paid)
        assert len(personal_licences(carol)) == 1
        buy_stock(acme[1], quantity=3)
        paid = stripe.pay()
        for _ in range(3):
            services.fulfil(paid)
        assert orgs.seats_bought(acme[0])[2] == 3

    def test_an_unpaid_page_gives_nothing_and_stays_pending(self, stripe, carol):
        buy(carol)
        purchase = services.fulfil(stripe.get_checkout(stripe.last))
        assert purchase.status == "pending" and personal_licences(carol) == []
        services.fulfil(stripe.pay())  # and it can still be paid afterwards
        assert len(personal_licences(carol)) == 1

    def test_a_page_we_never_opened_is_nothing_to_us(self, stripe, carol):
        unknown = {**stripe_api._checkout({"id": "cs_someone_elses", "payment_status": "paid"})}
        assert services.fulfil(unknown) is None
        assert services.fulfil({**unknown, "id": ""}) is None
        assert not Entitlement.objects.exists()

    def test_a_different_amount_gives_nothing_and_is_marked(self, stripe, carol, caplog):
        buy(carol, tier=3)
        purchase = services.fulfil(stripe.pay(charged=100))
        assert purchase.status == "paid" and purchase.needs_attention
        assert "different amount" in purchase.note and personal_licences(carol) == []
        assert f"Payment {purchase.pk} needs attention" in caplog.text
        assert CAROL not in caplog.text and CAROL not in purchase.note

    def test_an_upgrade_whose_licence_changed_meanwhile_is_marked_and_changes_nothing(
        self, stripe, carol
    ):
        licence = grant_personal(carol, 1)
        upgrade(carol, licence, 2)
        first = stripe.last
        upgrade(carol, licence, 3)  # two payment pages open for one licence
        services.fulfil(stripe.pay())  # the second is paid: Tier 3
        late = services.fulfil(stripe.pay(first))  # then the first: it started from Tier 1
        assert fresh(licence).tier == 3
        assert late.status == "paid" and late.needs_attention
        assert "was Tier 3, not Tier 1" in late.note and "Refund it." in late.note

    def test_an_upgrade_of_a_licence_withdrawn_meanwhile_is_marked(self, stripe, carol):
        licence = grant_personal(carol, 1)
        upgrade(carol, licence, 2)
        licences.revoke(licence)
        purchase = services.fulfil(stripe.pay())
        assert purchase.needs_attention and "withdrawn" in purchase.note
        assert fresh(licence).tier == 1

    def test_a_payment_from_an_account_erased_meanwhile_is_kept_and_marked(self, stripe, carol):
        buy(carol)
        erasure.erase_account(carol)
        purchase = services.fulfil(stripe.pay())
        assert purchase.buyer is None and purchase.status == "paid" and purchase.needs_attention
        assert "no longer exists" in purchase.note and not Entitlement.objects.exists()

    def test_a_stock_that_would_pass_the_most_allowed_is_marked_and_not_added(self, stripe, acme):
        enterprise, admin = acme
        buy_stock(admin, quantity=3)
        orgs.set_seat_pool(enterprise, 2, orgs.MAX_SEATS)  # staff typed it meanwhile
        purchase = services.fulfil(stripe.pay())
        assert purchase.needs_attention and orgs.seats_bought(enterprise)[2] == orgs.MAX_SEATS

    def test_if_giving_is_refused_half_way_what_it_wrote_is_undone_and_the_money_is_recorded(
        self, stripe, carol, monkeypatch
    ):
        def half_done(purchase):
            licences.grant_individual(carol.person, 1, "purchase")
            raise services.Refused("it could not be finished.")

        buy(carol)
        monkeypatch.setattr(services, "_give", half_done)
        purchase = services.fulfil(stripe.pay())
        assert personal_licences(carol) == [] and events() == []
        assert purchase.status == "paid" and purchase.needs_attention
        assert purchase.note == "Paid, but nothing was given: it could not be finished. Refund it."

    def test_the_admin_who_bought_can_leave_and_the_organization_still_gets_its_licences(
        self, stripe, acme
    ):
        enterprise, admin = acme
        second = new_member(enterprise, "second@example.com", role="admin")
        buy_stock(admin, quantity=2)
        orgs.deactivate_membership(admin, by=second)
        purchase = services.fulfil(stripe.pay())
        assert not purchase.needs_attention and orgs.seats_bought(enterprise)[2] == 2


@pytest.mark.django_db(transaction=True)
def test_the_return_page_and_stripes_message_at_the_same_moment_give_one_licence(
    monkeypatch, settings
):
    stripe = payments.install(monkeypatch, settings)
    carol = verified_account(CAROL)
    buy(carol)
    paid = stripe.pay()
    results = run_together(*[lambda: services.fulfil(paid) for _ in range(3)])
    assert all(isinstance(result, Purchase) for result in results), results
    assert Entitlement.objects.filter(person=carol.person).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_stock_purchase_confirmed_twice_at_once_is_added_once(monkeypatch, settings):
    stripe = payments.install(monkeypatch, settings)
    enterprise, admin = org_with_admin("Acme")
    buy_stock(admin, quantity=5)
    paid = stripe.pay()
    run_together(lambda: services.fulfil(paid), lambda: services.fulfil(paid))
    assert orgs.seats_bought(enterprise)[2] == 5


# --- the page the person comes back to ------------------------------------------------------


@pytest.mark.django_db
class TestComingBackFromStripe:
    @pytest.fixture
    def logged_in(self, client, carol):
        client.force_login(carol)
        return carol

    def back(self, client, session_id):
        return client.get(DONE, {"session_id": session_id})

    def test_a_paid_purchase_gives_the_licence_and_says_thank_you(self, client, stripe, logged_in):
        buy(logged_in, tier=2)
        stripe.pay()
        answer = self.back(client, stripe.last)
        assert answer.status_code == 302 and answer["Location"] == "/survey/history/"
        assert said(answer) == ["Thank you. Your Tier 2 licence is ready."]
        assert len(personal_licences(logged_in)) == 1

    def test_coming_back_twice_gives_one_licence_and_no_second_thank_you(
        self, client, stripe, logged_in
    ):
        buy(logged_in)
        stripe.pay()
        self.back(client, stripe.last)
        again = self.back(client, stripe.last)
        assert again.status_code == 302 and len(personal_licences(logged_in)) == 1

    def test_an_upgrade_says_the_new_tier(self, client, stripe, logged_in):
        upgrade(logged_in, grant_personal(logged_in, 1), 3)
        stripe.pay()
        assert said(self.back(client, stripe.last)) == ["Thank you. Your licence is now Tier 3."]

    def test_a_stock_purchase_lands_on_the_organizations_licences_page(self, client, stripe, acme):
        enterprise, admin = acme
        client.force_login(admin.account)
        buy_stock(admin, quantity=3)
        stripe.pay()
        answer = self.back(client, stripe.last)
        assert answer["Location"] == "/organizations/acme/licences/"
        assert said(answer) == ["Thank you. 3 Tier 2 licences have been added to Acme's stock."]
        assert orgs.seats_bought(enterprise)[2] == 3

    def test_not_paid_yet_says_it_is_being_confirmed(self, client, stripe, logged_in):
        buy(logged_in)
        answer = self.back(client, stripe.last)
        assert "being confirmed" in said(answer)[0] and personal_licences(logged_in) == []

    def test_if_stripe_cannot_be_asked_it_says_the_same_and_the_message_finishes_it(
        self, client, stripe, logged_in
    ):
        buy(logged_in)
        paid = stripe.pay()
        stripe.fail = stripe_api.StripeFailed("APIConnectionError (no code)")
        assert "being confirmed" in said(self.back(client, stripe.last))[0]
        stripe.fail = None
        assert payments.post_webhook(client, payments.paid_message(paid)).status_code == 200
        assert len(personal_licences(logged_in)) == 1

    def test_a_payment_that_could_not_be_finished_says_so_calmly(self, client, stripe, logged_in):
        buy(logged_in)
        stripe.pay(charged=1)
        (text,) = said(self.back(client, stripe.last))
        assert "we could not finish our side" in text and "refund you" in text

    def test_someone_elses_payment_page_is_not_found(self, client, stripe, logged_in):
        dan = verified_account("dan@example.com")
        buy(dan)
        stripe.pay()
        assert self.back(client, stripe.last).status_code == 404
        assert personal_licences(dan) == []  # and it was not given by the attempt
        for missing in ("cs_never_existed", ""):
            assert self.back(client, missing).status_code == 404
        assert client.get(DONE).status_code == 404

    def test_logged_out_it_asks_for_a_login_first(self, client, stripe, carol):
        buy(carol)
        answer = client.get(DONE, {"session_id": stripe.last})
        assert answer.status_code == 302 and "/accounts/login/" in answer["Location"]

    def test_coming_back_without_paying_says_nothing_was_charged(self, client, stripe, logged_in):
        buy(logged_in)
        purchase = Purchase.objects.get()
        answer = client.get("/buy/cancelled/", {"purchase": purchase.pk})
        assert answer["Location"] == "/survey/history/"
        assert said(answer) == ["Nothing was charged. You can buy whenever you like."]
        assert fresh(purchase).status == "pending"
        for odd in ({"purchase": "abc"}, {"purchase": "999999"}, {}):
            assert client.get("/buy/cancelled/", odd)["Location"] == "/survey/history/"

    def test_cancelling_a_stock_purchase_goes_back_to_the_organization(self, client, stripe, acme):
        client.force_login(acme[1].account)
        buy_stock(acme[1])
        answer = client.get("/buy/cancelled/", {"purchase": Purchase.objects.get().pk})
        assert answer["Location"] == "/organizations/acme/licences/"


# --- the messages Stripe sends ---------------------------------------------------------------


@pytest.mark.django_db
class TestStripesMessages:
    def test_a_signed_paid_message_gives_the_licence_with_nobody_logged_in(
        self, client, stripe, carol
    ):
        buy(carol, tier=3)
        answer = payments.post_webhook(client, payments.paid_message(stripe.pay()))
        assert answer.status_code == 200 and answer.content == b"ok"
        assert [licence.tier for licence in personal_licences(carol)] == [3]

    def test_the_same_message_twice_gives_once(self, client, stripe, carol):
        buy(carol)
        body = payments.paid_message(stripe.pay())
        for _ in range(2):
            assert payments.post_webhook(client, body).status_code == 200
        assert len(personal_licences(carol)) == 1

    def test_a_message_with_a_bad_signature_or_none_gives_nothing(self, client, stripe, carol):
        buy(carol)
        body = payments.paid_message(stripe.pay())
        forged = payments.signed(body, secret="whsec_someone_elses")
        for signature in (forged, "nonsense", ""):
            answer = payments.post_webhook(client, body, signature=signature)
            assert answer.status_code == 400
        assert (
            client.post(
                "/payments/stripe/webhook/", data=body, content_type="application/json"
            ).status_code
            == 400
        )
        assert personal_licences(carol) == [] and Purchase.objects.get().status == "pending"

    def test_a_message_altered_on_the_way_gives_nothing(self, client, stripe, carol):
        buy(carol)
        unpaid = payments.paid_message(stripe.get_checkout(stripe.last))
        altered = unpaid.replace('"unpaid"', '"paid"')
        answer = payments.post_webhook(client, altered, signature=payments.signed(unpaid))
        assert answer.status_code == 400 and personal_licences(carol) == []

    def test_a_kind_of_message_the_site_does_not_use_is_answered_fine_and_ignored(
        self, client, stripe, carol
    ):
        buy(carol)
        body = payments.paid_message(stripe.pay()).replace(
            "checkout.session.completed", "customer.created"
        )
        assert payments.post_webhook(client, body).status_code == 200
        assert personal_licences(carol) == []

    def test_a_message_about_a_page_we_never_opened_is_answered_fine(self, client, stripe):
        body = payments.paid_message(
            {**stripe_api._checkout({"id": "cs_other", "payment_status": "paid"})}
        )
        assert payments.post_webhook(client, body).status_code == 200

    def test_without_the_secret_it_says_not_set_up_and_gives_nothing(
        self, client, stripe, carol, settings
    ):
        buy(carol)
        body = payments.paid_message(stripe.pay())
        settings.STRIPE_WEBHOOK_SECRET = ""
        answer = payments.post_webhook(client, body)
        assert answer.status_code == 503 and personal_licences(carol) == []

    def test_it_takes_a_post_only_and_needs_no_form_token(self, stripe, carol):
        strict = Client(enforce_csrf_checks=True)
        assert strict.get("/payments/stripe/webhook/").status_code == 405
        buy(carol)
        answer = payments.post_webhook(strict, payments.paid_message(stripe.pay()))
        assert answer.status_code == 200 and len(personal_licences(carol)) == 1

    def test_if_handling_fails_stripe_is_told_so_and_can_send_it_again(
        self, client, stripe, carol, monkeypatch
    ):
        buy(carol)
        body = payments.paid_message(stripe.pay())
        give, attempts = services._give, []

        def fails_the_first_time(purchase):
            attempts.append(purchase.pk)
            if len(attempts) == 1:
                raise RuntimeError("something nobody planned for")
            return give(purchase)

        monkeypatch.setattr(services, "_give", fails_the_first_time)
        client.raise_request_exception = False
        assert payments.post_webhook(client, body).status_code == 500
        assert Purchase.objects.get().status == "pending"  # nothing half done
        assert personal_licences(carol) == []
        assert payments.post_webhook(client, body).status_code == 200  # Stripe sends it again
        assert len(personal_licences(carol)) == 1 and Purchase.objects.get().status == "paid"
