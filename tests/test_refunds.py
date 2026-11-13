"""
Milestone 4b, PR 4: refunds.

The rules (the founder's, 2026-11-13). Only a licence that has not been used
can be refunded, within 30 days of the payment. Staff do it with one button in
the Django admin, which takes the licence back and refunds through Stripe
together, or does neither. For an organization, only licences still in its
stock. Only superusers refund.

The builder's calls. "Not used" means the survey was never started on it. An
upgrade is refunded on its own (the tier goes back down), and the original
purchase only after any upgrade on top. A payment for which nothing was given
can always be refunded whole. A refund made in Stripe's own dashboard is
noticed: what was sold is taken back if those rules allow, and otherwise the
payment is marked "needs attention" and nothing is taken from anyone.

Stripe is played by tests/payments.FakeStripe throughout.
"""

import json
from datetime import timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.payments import services, stripe_api
from apps.payments.models import Purchase, Refund
from apps.responses import services as surveys
from apps.responses.signals import GROUP_NAME

from . import payments
from .orgs import new_member, org_with_admin, run_together
from .test_checkout import buy, buy_stock, submit_survey_on, upgrade
from .test_enterprise_services import refusal
from .test_profile import verified_account
from .test_response_context import fresh, published_survey
from .test_seat_pools import row as stock_line
from .test_verification import PASSWORD

CAROL = "carol@example.com"


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


def bought(stripe, account, tier=2):
    """A personal licence, paid for. Returns (the purchase, the licence)."""
    buy(account, tier)
    purchase = services.fulfil(stripe.pay())
    return purchase, purchase.entitlement


def upgraded(stripe, account, licence, tier):
    upgrade(account, licence, tier)
    return services.fulfil(stripe.pay())


def bought_stock(stripe, admin, tier=2, quantity=3):
    buy_stock(admin, tier, quantity)
    return services.fulfil(stripe.pay())


def aged(purchase, days):
    """Pretend the payment was made this many days ago."""
    when = timezone.now() - timedelta(days=days)
    Purchase.objects.filter(pk=purchase.pk).update(paid_at=when, given_at=when)
    return fresh(purchase)


def refund_message(purchase, refunded_cents):
    """The body of Stripe's "money went back for this charge" message."""
    found = {
        "id": "ch_test_1",
        "object": "charge",
        "payment_intent": purchase.stripe_payment_intent_id,
        "amount": purchase.amount_cents,
        "amount_refunded": refunded_cents,
    }
    return json.dumps({"id": "evt_r", "type": "charge.refunded", "data": {"object": found}})


def outside_refund(purchase, refunded_cents):
    """Stripe says this much has gone back in all, as after a refund in its dashboard."""
    return services.record_outside_refund(
        {
            "payment_intent": purchase.stripe_payment_intent_id,
            "amount_cents": purchase.amount_cents,
            "refunded_cents": refunded_cents,
        }
    )


def said(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


# --- a personal licence ------------------------------------------------------------------


@pytest.mark.django_db
class TestRefundingAPersonalLicence:
    def test_an_unused_one_is_withdrawn_and_the_money_goes_back_together(self, stripe, carol, root):
        purchase, licence = bought(stripe, carol, tier=2)
        made = services.refund(purchase, root)
        assert (made.amount_cents, made.quantity, made.made_by) == (200, 1, root)
        assert made.stripe_refund_id == "re_test_1"
        assert stripe.refunds == [
            {
                "payment_intent": purchase.stripe_payment_intent_id,
                "amount_cents": 200,
                "key": f"refund-{purchase.pk}-after-0",
            }
        ]
        now = fresh(purchase)
        assert (now.status, now.refunded_cents, now.refunded_quantity) == ("refunded", 200, 1)
        assert not fresh(licence).is_active and not licences.has_survey_access(carol)

    def test_one_whose_survey_was_started_is_refused_and_nothing_changes(self, stripe, carol, root):
        published_survey()
        purchase, licence = bought(stripe, carol)
        surveys.start_response(carol)
        assert refusal(lambda: services.refund(purchase, root)) == services.STARTED
        assert fresh(licence).is_active and stripe.refunds == []
        assert fresh(purchase).status == "paid" and not Refund.objects.exists()

    def test_one_whose_survey_was_submitted_is_refused(self, stripe, carol, root):
        purchase, licence = bought(stripe, carol)
        submit_survey_on(licence, carol)
        assert refusal(lambda: services.refund(purchase, root)) == services.STARTED
        assert stripe.refunds == []

    def test_after_thirty_days_it_is_refused(self, stripe, carol, root):
        purchase, licence = bought(stripe, carol)
        assert services.refund_preview(aged(purchase, 29))["can"] is True
        late = aged(purchase, 31)
        assert "more than 30 days old" in refusal(lambda: services.refund(late, root))
        assert fresh(licence).is_active and stripe.refunds == []

    def test_if_stripe_refuses_nothing_is_taken_back(self, stripe, carol, root, caplog):
        purchase, licence = bought(stripe, carol)
        stripe.fail = stripe_api.StripeFailed("APIConnectionError (no code)")
        assert refusal(lambda: services.refund(purchase, root)) == services.STRIPE_REFUSED
        assert fresh(licence).is_active and fresh(purchase).status == "paid"
        assert not Refund.objects.exists()
        assert f"Stripe refused the refund of payment {purchase.pk}" in caplog.text
        assert CAROL not in caplog.text

    def test_it_cannot_be_refunded_twice(self, stripe, carol, root):
        purchase, _ = bought(stripe, carol)
        services.refund(purchase, root)
        assert "already been refunded in full" in refusal(lambda: services.refund(purchase, root))
        assert len(stripe.refunds) == 1 and Refund.objects.count() == 1

    @pytest.mark.parametrize("status", ["pending", "failed"])
    def test_a_payment_that_was_never_completed_has_nothing_to_refund(self, stripe, carol, status):
        buy(carol)
        Purchase.objects.update(status=status)
        said_ = refusal(lambda: services.refund(Purchase.objects.get(), None))
        assert said_ == "This payment was never completed, so there is nothing to refund."

    def test_a_licence_that_went_with_its_account_is_refunded_all_the_same(
        self, stripe, carol, root
    ):
        purchase, _ = bought(stripe, carol)
        erasure.erase_account(carol)
        services.refund(purchase, root)
        assert fresh(purchase).status == "refunded" and stripe.refunds[0]["amount_cents"] == 200

    def test_a_personal_licence_is_refunded_whole(self, stripe, carol, root):
        purchase, _ = bought(stripe, carol)
        refusal(lambda: services.refund(purchase, root, quantity=2))
        services.refund(purchase, root, quantity=1)
        assert fresh(purchase).status == "refunded"


@pytest.mark.django_db(transaction=True)
def test_two_staff_refunding_at_the_same_moment_send_the_money_back_once(monkeypatch, settings):
    stripe = payments.install(monkeypatch, settings)
    carol = verified_account(CAROL)
    purchase, licence = bought(stripe, carol)
    results = run_together(
        lambda: services.refund(purchase, None), lambda: services.refund(purchase, None)
    )
    assert sum(isinstance(result, services.Refused) for result in results) == 1, results
    assert len(stripe.refunds) == 1 and Refund.objects.count() == 1
    assert fresh(purchase).refunded_cents == 200 and not fresh(licence).is_active


# --- an upgrade ----------------------------------------------------------------------------


@pytest.mark.django_db
class TestRefundingAnUpgrade:
    def test_the_tier_goes_back_down_and_the_difference_is_refunded(self, stripe, carol, root):
        original, licence = bought(stripe, carol, tier=1)
        paid_upgrade = upgraded(stripe, carol, licence, 3)
        made = services.refund(paid_upgrade, root)
        assert made.amount_cents == 200 and fresh(licence).tier == 1 and fresh(licence).is_active
        assert fresh(paid_upgrade).status == "refunded" and fresh(original).status == "paid"

    def test_the_original_purchase_waits_for_the_upgrade_on_top_of_it(self, stripe, carol, root):
        original, licence = bought(stripe, carol, tier=1)
        paid_upgrade = upgraded(stripe, carol, licence, 2)
        assert refusal(lambda: services.refund(original, root)) == services.UPGRADE_ON_TOP
        assert fresh(licence).is_active and stripe.refunds == []
        services.refund(paid_upgrade, root)
        services.refund(original, root)
        assert not fresh(licence).is_active
        assert [refund["amount_cents"] for refund in stripe.refunds] == [100, 100]

    def test_an_upgrade_made_after_the_survey_was_taken_is_not_refunded(self, stripe, carol, root):
        _, licence = bought(stripe, carol, tier=1)
        submit_survey_on(licence, carol)
        paid_upgrade = upgraded(stripe, carol, licence, 2)
        assert refusal(lambda: services.refund(paid_upgrade, root)) == services.STARTED
        assert fresh(licence).tier == 2

    def test_an_upgrade_under_a_later_one_cannot_be_undone_first(self, stripe, carol, root):
        _, licence = bought(stripe, carol, tier=1)
        first = upgraded(stripe, carol, licence, 2)
        second = upgraded(stripe, carol, licence, 3)
        assert "is Tier 3 now, not the Tier 2" in refusal(lambda: services.refund(first, root))
        services.refund(second, root)
        services.refund(first, root)
        assert fresh(licence).tier == 1


# --- an organization's stock ---------------------------------------------------------------


@pytest.mark.django_db
class TestRefundingAStockPurchase:
    def test_some_of_it_can_be_refunded_and_then_the_rest(self, stripe, acme, root):
        enterprise, admin = acme
        purchase = bought_stock(stripe, admin, quantity=3)
        made = services.refund(purchase, root, quantity=2)
        assert (made.amount_cents, made.quantity) == (400, 2)
        now = fresh(purchase)
        assert (now.status, now.refunded_cents, now.refunded_quantity) == ("part_refunded", 400, 2)
        assert orgs.seats_bought(enterprise)[2] == 1 and orgs.people_limit(enterprise) == 26
        services.refund(purchase, root)  # no number: everything not refunded yet
        assert fresh(purchase).status == "refunded" and orgs.seats_bought(enterprise)[2] == 0
        assert [refund["key"] for refund in stripe.refunds] == [
            f"refund-{purchase.pk}-after-0",
            f"refund-{purchase.pk}-after-400",
        ]

    def test_only_licences_still_in_the_stock_can_be_refunded(self, stripe, acme, root):
        enterprise, admin = acme
        purchase = bought_stock(stripe, admin, quantity=3)
        licences.assign_seat(admin, new_member(enterprise, "bob@example.com"), 2)  # one given
        orgs.invite_by_email(admin, CAROL, tier=2)  # one set aside
        assert services.refund_preview(purchase)["most"] == 1
        said_ = refusal(lambda: services.refund(purchase, root, quantity=2))
        assert said_.startswith("Only 1 Tier 2 licence(s) are still in the stock")
        assert orgs.seats_bought(enterprise)[2] == 3 and stripe.refunds == []
        services.refund(purchase, root, quantity=1)
        assert stock_line(enterprise, 2)["left"] == 0 and orgs.seats_bought(enterprise)[2] == 2

    @pytest.mark.parametrize("quantity", [0, -1, 4, "2", 2.0, True])
    def test_a_number_that_will_not_do_is_refused(self, stripe, acme, root, quantity):
        purchase = bought_stock(stripe, acme[1], quantity=3)
        refusal(lambda: services.refund(purchase, root, quantity=quantity))
        assert stripe.refunds == [] and orgs.seats_bought(acme[0])[2] == 3

    def test_if_stripe_refuses_the_stock_is_left_as_it_was(self, stripe, acme, root):
        purchase = bought_stock(stripe, acme[1], quantity=3)
        stripe.fail = stripe_api.StripeFailed("APIConnectionError (no code)")
        refusal(lambda: services.refund(purchase, root, quantity=2))
        assert orgs.seats_bought(acme[0])[2] == 3 and fresh(purchase).status == "paid"


# --- money that came in for nothing --------------------------------------------------------


@pytest.mark.django_db
class TestRefundingAPaymentThatGaveNothing:
    def test_it_is_refunded_whole_with_nothing_to_take_back_and_is_then_dealt_with(
        self, stripe, carol, root
    ):
        buy(carol, tier=3)
        purchase = services.fulfil(stripe.pay(charged=100))  # the wrong amount: nothing given
        assert purchase.needs_attention and purchase.given_at is None
        preview = services.refund_preview(purchase)
        assert preview["can"] and "Nothing was given" in preview["gives_back"]
        made = services.refund(aged_without_giving(purchase, 90), root)
        assert (made.amount_cents, made.quantity) == (300, 0)
        now = fresh(purchase)
        assert now.status == "refunded" and not now.needs_attention
        assert not Entitlement.objects.exists()


def aged_without_giving(purchase, days):
    Purchase.objects.filter(pk=purchase.pk).update(paid_at=timezone.now() - timedelta(days=days))
    return fresh(purchase)


# --- a refund made in Stripe's dashboard ---------------------------------------------------


@pytest.mark.django_db
class TestARefundMadeInStripesDashboard:
    def test_an_unused_licence_is_withdrawn_when_stripe_says_the_money_went_back(
        self, stripe, carol
    ):
        purchase, licence = bought(stripe, carol)
        now = outside_refund(aged(purchase, 60), 200)  # the 30 days are for the button only
        assert now.status == "refunded" and not now.needs_attention
        assert not fresh(licence).is_active
        made = Refund.objects.get()
        assert (made.amount_cents, made.quantity) == (200, 1)
        assert made.stripe_refund_id is None and made.made_by is None
        assert stripe.refunds == []  # the site sent no money back itself

    def test_a_used_licence_is_kept_and_the_payment_is_marked(self, stripe, carol, caplog):
        purchase, licence = bought(stripe, carol)
        submit_survey_on(licence, carol)
        now = outside_refund(purchase, 200)
        assert fresh(licence).is_active
        assert now.status == "refunded" and now.needs_attention
        assert "$2.00 was refunded in Stripe's dashboard" in now.note
        assert "has been started" in now.note and CAROL not in now.note
        assert Refund.objects.get().quantity == 0
        assert f"Payment {purchase.pk} needs attention" in caplog.text

    def test_our_own_refund_arriving_as_a_message_changes_nothing_more(self, stripe, carol, root):
        purchase, _ = bought(stripe, carol)
        services.refund(purchase, root)
        for _ in range(2):
            outside_refund(purchase, 200)
        assert Refund.objects.count() == 1 and fresh(purchase).refunded_cents == 200

    def test_the_same_message_twice_is_recorded_once(self, stripe, carol):
        purchase, _ = bought(stripe, carol)
        for _ in range(2):
            outside_refund(purchase, 200)
        assert Refund.objects.count() == 1

    def test_part_of_a_stock_purchase_comes_out_of_the_stock(self, stripe, acme):
        enterprise, admin = acme
        purchase = bought_stock(stripe, admin, quantity=3)
        now = outside_refund(purchase, 400)
        assert (now.status, now.refunded_quantity) == ("part_refunded", 2)
        assert orgs.seats_bought(enterprise)[2] == 1 and not now.needs_attention
        now = outside_refund(purchase, 600)  # Stripe's number is the total so far
        assert now.status == "refunded" and orgs.seats_bought(enterprise)[2] == 0
        assert [refund.amount_cents for refund in Refund.objects.all()] == [400, 200]

    def test_licences_already_given_out_are_left_with_their_members(self, stripe, acme):
        enterprise, admin = acme
        purchase = bought_stock(stripe, admin, quantity=1)
        given = licences.assign_seat(admin, new_member(enterprise, "bob@example.com"), 2)
        now = outside_refund(purchase, 200)
        assert fresh(given).is_active and orgs.seats_bought(enterprise)[2] == 1
        assert now.needs_attention and "nothing was taken back" in now.note

    def test_an_amount_that_is_not_a_whole_number_of_licences_takes_nothing_back(
        self, stripe, acme
    ):
        purchase = bought_stock(stripe, acme[1], quantity=3)
        now = outside_refund(purchase, 250)
        assert orgs.seats_bought(acme[0])[2] == 3 and now.refunded_cents == 250
        assert now.needs_attention and "not a whole number of licences" in now.note

    def test_a_charge_that_is_not_ours_is_nothing_to_us(self, stripe, carol):
        bought(stripe, carol)
        unknown = {"payment_intent": "pi_someone_elses", "amount_cents": 1, "refunded_cents": 1}
        assert services.record_outside_refund(unknown) is None
        assert services.record_outside_refund({**unknown, "payment_intent": ""}) is None
        assert not Refund.objects.exists()

    def test_stripes_signed_message_does_all_of_this(self, client, stripe, carol):
        purchase, licence = bought(stripe, carol)
        body = refund_message(purchase, 200)
        assert payments.post_webhook(client, body).status_code == 200
        assert not fresh(licence).is_active and fresh(purchase).status == "refunded"
        forged = payments.post_webhook(client, body, signature="t=1,v1=abc")
        assert forged.status_code == 400


# --- the Refund button in the admin --------------------------------------------------------


@pytest.mark.django_db
class TestTheRefundButton:
    def page(self, purchase):
        return f"/admin/payments/purchase/{purchase.pk}/refund/"

    def test_a_superuser_sees_the_button_on_a_payment(self, client, stripe, carol, root):
        purchase, _ = bought(stripe, carol)
        text = client.get(f"/admin/payments/purchase/{purchase.pk}/change/").content.decode()
        assert f'<a href="{self.page(purchase)}">Refund…</a>' in text

    def test_the_page_says_what_will_happen_and_changes_nothing(self, client, stripe, carol, root):
        purchase, licence = bought(stripe, carol)
        page = client.get(self.page(purchase))
        text = " ".join(page.content.decode().split())
        assert page.status_code == 200
        assert f"Payment {purchase.pk}: 1 x Tier 2, $2.00 paid." in text
        assert "The licence is withdrawn." in text and "$2.00 goes back to the card" in text
        assert "Yes, refund through Stripe" in text and CAROL not in text
        assert fresh(licence).is_active and stripe.refunds == []

    def test_confirming_refunds_and_the_history_says_who_and_what(
        self, client, stripe, carol, root
    ):
        purchase, licence = bought(stripe, carol)
        answer = client.post(self.page(purchase), {"quantity": "1"})
        assert answer.status_code == 302
        assert answer["Location"] == f"/admin/payments/purchase/{purchase.pk}/change/"
        assert said(answer) == ["Refunded $2.00 through Stripe; the licence was withdrawn."]
        assert not fresh(licence).is_active and len(stripe.refunds) == 1
        entry = LogEntry.objects.get()
        assert entry.user == root and entry.object_repr == f"Payment {purchase.pk}"
        assert "Refunded $2.00 through Stripe" in entry.get_change_message()
        assert CAROL not in entry.get_change_message() + entry.object_repr

    def test_a_stock_purchase_asks_how_many(self, client, stripe, acme, root):
        enterprise, admin = acme
        purchase = bought_stock(stripe, admin, quantity=3)
        licences.assign_seat(admin, new_member(enterprise, "bob@example.com"), 2)
        text = " ".join(client.get(self.page(purchase)).content.decode().split())
        assert "How many licences to refund" in text and 'max="2"' in text
        assert "$2.00 goes back to the card for each licence refunded" in text
        too_many = client.post(self.page(purchase), {"quantity": "3"})
        assert too_many.status_code == 200 and stripe.refunds == []
        answer = client.post(self.page(purchase), {"quantity": "2"})
        assert said(answer) == ["Refunded $4.00 through Stripe; took back 2 licence(s)."]
        assert orgs.seats_bought(enterprise)[2] == 1

    def test_a_payment_that_cannot_be_refunded_says_why_and_has_no_button(
        self, client, stripe, carol, root
    ):
        purchase, licence = bought(stripe, carol)
        submit_survey_on(licence, carol)
        text = " ".join(client.get(self.page(purchase)).content.decode().split())
        assert "This payment cannot be refunded here." in text and services.STARTED in text
        assert "Yes, refund through Stripe" not in text
        client.post(self.page(purchase), {"quantity": "1"})  # typed by hand anyway
        assert stripe.refunds == [] and fresh(licence).is_active

    def test_a_refusal_at_the_last_moment_is_a_message_not_a_crash(
        self, client, stripe, carol, root
    ):
        purchase, licence = bought(stripe, carol)
        stripe.fail = stripe_api.StripeFailed("APIConnectionError (no code)")
        answer = client.post(self.page(purchase), {"quantity": "1"})
        assert answer.status_code == 302 and said(answer) == [services.STRIPE_REFUSED]
        assert fresh(licence).is_active and not LogEntry.objects.exists()

    def test_support_staff_have_no_button_and_cannot_open_the_page(
        self, client, stripe, carol, support
    ):
        purchase, licence = bought(stripe, carol)
        text = client.get(f"/admin/payments/purchase/{purchase.pk}/change/").content.decode()
        assert "Refund…" not in text
        assert client.get(self.page(purchase)).status_code == 403
        assert client.post(self.page(purchase), {"quantity": "1"}).status_code == 403
        assert fresh(licence).is_active and stripe.refunds == []

    def test_someone_who_is_not_staff_is_sent_to_the_admin_login(self, client, stripe, carol):
        purchase, _ = bought(stripe, carol)
        client.force_login(carol)
        answer = client.post(self.page(purchase), {"quantity": "1"})
        assert answer.status_code == 302 and "/admin/login/" in answer["Location"]
        assert stripe.refunds == []
