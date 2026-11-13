"""
Milestone 4b, PR 1: prices, the record of payments, and the file that talks to
Stripe.

What must hold. Three prices exist and only a superuser changes one. A payment
row cannot contradict itself (the database refuses). The rows hold no personal
identity and survive the erasure of whoever paid. An organization's stock can
be added to and taken from by a payment. And the one file that talks to Stripe
sends what it should, hands back plain values, and accepts a message only if
Stripe signed it. No test here, or anywhere, reaches Stripe's servers.
"""

import hashlib
import hmac
import importlib
import json
import time

import pytest
import stripe
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.payments import services, stripe_api
from apps.payments.models import Price, Purchase, Refund
from apps.responses.signals import GROUP_NAME

from .orgs import new_member, org_with_admin
from .test_enterprise_services import refusal
from .test_erasure import complete
from .test_profile import verified_account
from .test_response_context import fresh
from .test_seat_pools import row as stock_line
from .test_seat_services import ORGANIZATION, lock_order
from .test_verification import PASSWORD

SECRET = "whsec_made_up_for_tests"


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


def paid_personal(account, tier=1, **extra):
    """A paid personal purchase and the licence it bought, written straight in."""
    licence = licences.grant_individual(account.person, tier, "purchase")
    cents = services.prices()[tier]
    return Purchase.objects.create(
        kind="personal",
        status="paid",
        buyer=account,
        entitlement=licence,
        tier=tier,
        unit_amount_cents=cents,
        amount_cents=cents,
        stripe_session_id=f"cs_test_{account.pk}_{tier}",
        stripe_payment_intent_id=f"pi_test_{account.pk}_{tier}",
        **extra,
    )


def row(**changes):
    """The fields of a valid personal purchase, with some changed."""
    return {
        "kind": "personal",
        "tier": 2,
        "quantity": 1,
        "unit_amount_cents": 200,
        "amount_cents": 200,
        **changes,
    }


def refused_by_the_database(**changes):
    with pytest.raises(IntegrityError), transaction.atomic():
        Purchase.objects.create(**row(**changes))


# --- prices ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPrices:
    def test_the_three_tiers_start_at_one_two_and_three_dollars(self):
        assert services.prices() == {1: 100, 2: 200, 3: 300}
        assert [str(price) for price in Price.objects.all()] == [
            "Price of a Tier 1 licence",
            "Price of a Tier 2 licence",
            "Price of a Tier 3 licence",
        ]

    def test_running_the_migration_again_keeps_a_price_staff_changed(self):
        Price.objects.filter(tier=2).update(amount_cents=950)
        migration = importlib.import_module("apps.payments.migrations.0002_prices")
        from django.apps import apps as django_apps

        migration.create_prices(django_apps, None)
        assert services.prices() == {1: 100, 2: 950, 3: 300}

    @pytest.mark.parametrize(
        "cents, shown",
        [(100, "$1.00"), (250, "$2.50"), (5, "$0.05"), (123456, "$1,234.56"), (0, "$0.00")],
    )
    def test_an_amount_is_shown_in_dollars_and_cents(self, cents, shown):
        assert services.dollars(cents) == shown

    @pytest.mark.parametrize("bad", [{"tier": 4}, {"tier": 0}])
    def test_the_database_keeps_one_price_per_tier_from_1_to_3(self, bad):
        with pytest.raises(IntegrityError), transaction.atomic():
            Price.objects.create(amount_cents=100, **bad)
        with pytest.raises(IntegrityError), transaction.atomic():
            Price.objects.create(tier=1, amount_cents=100)

    @pytest.mark.parametrize("cents", [0, 49, 1_000_001])
    def test_the_database_refuses_a_price_stripe_could_not_charge(self, cents):
        with pytest.raises(IntegrityError), transaction.atomic():
            Price.objects.filter(tier=1).update(amount_cents=cents)


@pytest.mark.django_db
class TestPricesInTheAdmin:
    def page(self, tier=2):
        return f"/admin/payments/price/{Price.objects.get(tier=tier).pk}/change/"

    def test_a_superuser_changes_a_price_typed_in_dollars(self, client, root):
        assert 'value="2.00"' in client.get(self.page()).content.decode()
        answer = client.post(self.page(), {"dollars": "12.50"})
        assert answer.status_code == 302
        assert services.prices() == {1: 100, 2: 1250, 3: 300}
        assert "$12.50" in client.get("/admin/payments/price/").content.decode()
        assert LogEntry.objects.filter(user=root).count() == 1  # who changed it is on record

    @pytest.mark.parametrize("typed", ["0", "0.49", "-1", "10000.01", "1.999", "free", ""])
    def test_an_amount_that_will_not_do_is_asked_for_again(self, client, root, typed):
        answer = client.post(self.page(), {"dollars": typed})
        assert answer.status_code == 200 and services.prices()[2] == 200

    def test_nobody_adds_or_deletes_a_price(self, client, root):
        assert client.get("/admin/payments/price/add/").status_code == 403
        assert client.post(self.page() + "../delete/", {"post": "yes"}).status_code in (403, 404)
        assert Price.objects.count() == 3

    def test_support_staff_can_look_and_cannot_change(self, client, support):
        assert client.get("/admin/payments/price/").status_code == 200
        assert client.get(self.page()).status_code == 200
        client.post(self.page(), {"dollars": "0.50"})
        assert services.prices()[2] == 200


# --- the record of a payment -----------------------------------------------------------


@pytest.mark.django_db
class TestThePaymentRecord:
    def test_a_valid_row_of_each_kind_is_accepted(self):
        enterprise, _ = org_with_admin("Acme")
        Purchase.objects.create(**row())
        Purchase.objects.create(**row(kind="upgrade", from_tier=1, tier=3))
        Purchase.objects.create(
            **row(kind="stock", enterprise=enterprise, quantity=4, amount_cents=800)
        )
        assert Purchase.objects.filter(status="pending").count() == 3

    def test_its_label_names_nobody(self):
        purchase = paid_personal(verified_account("carol@example.com"))
        assert str(purchase) == f"Payment {purchase.pk}"
        refund = Refund.objects.create(purchase=purchase, amount_cents=100, quantity=1)
        assert str(refund) == f"Refund {refund.pk}"

    def test_no_column_could_hold_a_name_an_email_or_a_card(self):
        names = {field.name for field in Purchase._meta.fields} | {
            field.name for field in Refund._meta.fields
        }
        for word in ("email", "name", "card", "address", "phone"):
            assert not [name for name in names if word in name], word

    @pytest.mark.parametrize(
        "changes",
        [
            {"tier": 0},
            {"tier": 4},
            {"quantity": 0},
            {"amount_cents": 199},  # not the unit amount times the number
            {"quantity": 2, "amount_cents": 400},  # more than one, and not for a stock
            {"refunded_cents": 201},
            {"refunded_quantity": 2},
            {"kind": "stock"},  # a stock purchase with no organization
            {"from_tier": 1},  # a tier it started from, on something that is not an upgrade
            {"kind": "upgrade"},  # an upgrade from nothing
            {"kind": "upgrade", "from_tier": 2},  # an upgrade to the same tier
            {"kind": "upgrade", "from_tier": 3},  # an upgrade downwards
            {"kind": "upgrade", "from_tier": 0},
        ],
    )
    def test_the_database_refuses_a_row_that_contradicts_itself(self, changes):
        refused_by_the_database(**changes)

    def test_a_personal_purchase_cannot_name_an_organization(self):
        enterprise, _ = org_with_admin("Acme")
        refused_by_the_database(enterprise=enterprise)

    def test_one_row_per_visit_to_stripes_page_and_per_refund(self):
        Purchase.objects.create(**row(stripe_session_id="cs_1"))
        refused_by_the_database(stripe_session_id="cs_1")
        Purchase.objects.create(**row())  # not yet sent to Stripe: no id, and that is allowed twice
        first = Purchase.objects.create(**row())
        Refund.objects.create(purchase=first, amount_cents=1, stripe_refund_id="re_1")
        with pytest.raises(IntegrityError), transaction.atomic():
            Refund.objects.create(purchase=first, amount_cents=1, stripe_refund_id="re_1")
        with pytest.raises(IntegrityError), transaction.atomic():
            Refund.objects.create(purchase=first, amount_cents=0)


@pytest.mark.django_db
class TestPaymentsInTheAdmin:
    def test_a_superuser_sees_the_list_and_one_payment_and_can_type_nothing(self, client, root):
        purchase = paid_personal(verified_account("carol@example.com"))
        Refund.objects.create(purchase=purchase, amount_cents=40, quantity=0)
        Purchase.objects.filter(pk=purchase.pk).update(refunded_cents=40)
        listing = client.get("/admin/payments/purchase/").content.decode()
        assert f"Payment {purchase.pk}" in listing and "1 x Tier 1" in listing
        assert "$1.00 ($0.40 refunded)" in listing
        page = client.get(f"/admin/payments/purchase/{purchase.pk}/change/")
        text = page.content.decode()
        assert page.status_code == 200 and "Refunds of this payment" in text
        assert '<input type="text"' not in text and "<select" not in text.split("</nav>")[-1]
        assert client.post(f"/admin/payments/purchase/{purchase.pk}/change/", {}).status_code == 403
        assert client.get("/admin/payments/purchase/add/").status_code == 403
        assert client.get(f"/admin/payments/purchase/{purchase.pk}/delete/").status_code == 403

    def test_the_needs_attention_filter_finds_the_ones_staff_must_look_at(self, client, root):
        fine = paid_personal(verified_account("carol@example.com"))
        stuck = paid_personal(
            verified_account("dan@example.com"), needs_attention=True, note="Paid twice."
        )
        text = client.get("/admin/payments/purchase/?attention=yes").content.decode()
        assert f"Payment {stuck.pk}" in text and f"Payment {fine.pk}" not in text

    def test_it_is_found_by_stripes_reference_or_the_organizations_name(self, client, root):
        enterprise, _ = org_with_admin("Acme")
        stock = Purchase.objects.create(
            **row(kind="stock", enterprise=enterprise, quantity=2, amount_cents=400),
            stripe_payment_intent_id="pi_find_me",
        )
        other = Purchase.objects.create(**row())
        for typed in ("pi_find_me", "Acme"):
            text = client.get(f"/admin/payments/purchase/?q={typed}").content.decode()
            assert f"Payment {stock.pk}" in text and f"Payment {other.pk}" not in text

    def test_support_staff_can_look_at_payments(self, client, support):
        purchase = paid_personal(verified_account("carol@example.com"))
        assert client.get("/admin/payments/purchase/").status_code == 200
        assert client.get(f"/admin/payments/purchase/{purchase.pk}/change/").status_code == 200

    def test_staff_outside_the_group_see_none_of_it(self, client, db):
        account = Account.objects.create_user("clerk@example.com", PASSWORD)
        account.is_staff = True
        account.save()
        client.force_login(account)
        for address in ("/admin/payments/purchase/", "/admin/payments/price/"):
            assert client.get(address).status_code == 403


# --- erasing whoever paid --------------------------------------------------------------


@pytest.mark.django_db
class TestErasureLeavesThePaymentRecord:
    def test_deleting_the_account_empties_the_links_and_keeps_the_money(self):
        carol = verified_account("carol@example.com")
        purchase = paid_personal(carol, tier=2)
        Refund.objects.create(purchase=purchase, amount_cents=50, made_by=carol)
        assert erasure.plan_erasure(carol).action == erasure.DELETE
        erasure.erase_account(carol)
        kept = fresh(purchase)
        assert kept.buyer is None and kept.entitlement is None
        assert (kept.status, kept.tier, kept.amount_cents) == ("paid", 2, 200)
        assert kept.stripe_payment_intent_id == purchase.stripe_payment_intent_id
        assert Refund.objects.get().made_by is None and Refund.objects.get().amount_cents == 50

    def test_stripping_the_account_changes_nothing_in_the_record(self):
        carol = verified_account("carol@example.com")
        purchase = paid_personal(carol, tier=3)
        complete(carol)  # a submitted survey: the account is stripped, not deleted
        before = Purchase.objects.filter(pk=purchase.pk).values().get()
        erasure.erase_account(carol)
        assert Purchase.objects.filter(pk=purchase.pk).values().get() == before
        assert "carol" not in fresh(carol).email  # the identity went; the row did not need it

    def test_a_stock_purchase_survives_the_admin_who_made_it(self):
        enterprise, admin = org_with_admin("Acme")
        purchase = Purchase.objects.create(
            **row(kind="stock", enterprise=enterprise, quantity=3, amount_cents=600),
            buyer=admin.account,
            status="paid",
        )
        erasure.erase_account(admin.account)  # nobody else is active, so it goes ahead
        kept = fresh(purchase)
        assert kept.buyer is None and kept.enterprise == enterprise and kept.amount_cents == 600


# --- a payment adds to an organization's stock ------------------------------------------


@pytest.mark.django_db
class TestAddingToAndTakingFromTheStock:
    @pytest.fixture
    def acme(self):
        return org_with_admin("Acme")

    def test_adding_raises_the_stock_and_the_people_limit(self, acme):
        enterprise, _ = acme
        assert orgs.add_seats(enterprise, 2, 3).seats == 3
        assert orgs.add_seats(enterprise, 2, 4).seats == 7
        assert orgs.seats_bought(enterprise) == {1: 0, 2: 7, 3: 0}
        assert orgs.people_limit(enterprise) == 32

    def test_taking_lowers_it_again(self, acme):
        enterprise, _ = acme
        orgs.add_seats(enterprise, 2, 5)
        assert orgs.remove_seats(enterprise, 2, 2).seats == 3
        assert stock_line(enterprise, 2)["left"] == 3

    def test_only_what_is_still_in_the_stock_can_be_taken(self, acme):
        enterprise, admin = acme
        orgs.add_seats(enterprise, 2, 3)
        licences.assign_seat(admin, new_member(enterprise, "bob@example.com"), 2)  # one given
        orgs.invite_by_email(admin, "carol@example.com", tier=2)  # one set aside
        said = refusal(lambda: orgs.remove_seats(enterprise, 2, 2))
        assert said.startswith("Only 1 Tier 2 licence(s) are still in the stock")
        assert orgs.seats_bought(enterprise)[2] == 3
        assert orgs.remove_seats(enterprise, 2, 1).seats == 2

    def test_nothing_can_be_taken_from_a_tier_never_bought(self, acme):
        refusal(lambda: orgs.remove_seats(acme[0], 1, 1))

    @pytest.mark.parametrize("tier", [0, 4, "2", 2.0, True, None])
    def test_a_bad_tier_is_refused(self, acme, tier):
        refusal(lambda: orgs.add_seats(acme[0], tier, 1))
        refusal(lambda: orgs.remove_seats(acme[0], tier, 1))

    @pytest.mark.parametrize("quantity", [0, -1, "3", 1.0, True, None])
    def test_a_bad_number_is_refused(self, acme, quantity):
        refusal(lambda: orgs.add_seats(acme[0], 2, quantity))
        refusal(lambda: orgs.remove_seats(acme[0], 2, quantity))
        assert orgs.seats_bought(acme[0])[2] == 0

    def test_a_stock_cannot_pass_the_most_allowed(self, acme):
        orgs.set_seat_pool(acme[0], 2, orgs.MAX_SEATS)
        refusal(lambda: orgs.add_seats(acme[0], 2, 1))

    def test_both_take_the_organizations_lock(self, acme):
        for action in (orgs.add_seats, orgs.remove_seats):
            orgs.set_seat_pool(acme[0], 2, 5)
            with CaptureQueriesContext(connection) as queries:
                action(acme[0], 2, 1)
            assert lock_order(queries)[0] == ORGANIZATION


# --- the file that talks to Stripe ------------------------------------------------------


class FakeClient:
    """Stands in for Stripe's library: remembers what it was asked, answers like Stripe."""

    made = []

    class Answer:
        def __init__(self, values):
            self.values = values

        def to_dict(self):
            return self.values

    def __init__(self, key, **options):
        self.key, self.options = key, options
        self.calls = []
        FakeClient.made.append(self)
        sessions = type("Sessions", (), {"create": self.create, "retrieve": self.retrieve})
        refunds = type("Refunds", (), {"create": self.refund})
        self.v1 = type(
            "V1", (), {"checkout": type("Checkout", (), {"sessions": sessions}), "refunds": refunds}
        )

    def create(self, params=None, options=None):
        self.calls.append(("create", params, options))
        return self.Answer({"id": "cs_test_1", "url": "https://checkout.stripe.test/pay/cs_test_1"})

    def retrieve(self, session_id, params=None, options=None):
        self.calls.append(("retrieve", session_id, options))
        return self.Answer(
            {
                "id": session_id,
                "payment_status": "paid",
                "payment_intent": "pi_test_1",
                "invoice": {"id": "in_test_1"},
                "amount_subtotal": 600,
                "amount_total": 648,
                "currency": "USD",
            }
        )

    def refund(self, params=None, options=None):
        self.calls.append(("refund", params, options))
        return self.Answer({"id": "re_test_1"})


@pytest.fixture
def stripe_client(monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_made_up"
    FakeClient.made = []
    monkeypatch.setattr(stripe, "StripeClient", FakeClient)
    return FakeClient


def checkout(**changes):
    return stripe_api.create_checkout(
        **{
            "reference": 41,
            "description": "Tier 2 licence",
            "unit_amount_cents": 200,
            "quantity": 1,
            "currency": "usd",
            "email": "carol@example.com",
            "success_url": "https://site.test/buy/done/?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": "https://site.test/buy/cancelled/",
            **changes,
        }
    )


def signed(payload, secret=SECRET, at=None):
    """The header Stripe would send with this message."""
    at = int(at or time.time())
    digest = hmac.new(secret.encode(), f"{at}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


def message(kind="checkout.session.completed", **found):
    return json.dumps({"id": "evt_1", "type": kind, "data": {"object": found}})


class TestTalkingToStripe:
    def test_the_tests_are_run_with_no_key_whatever_the_laptop_has(self, settings):
        assert settings.STRIPE_SECRET_KEY == "" and settings.STRIPE_WEBHOOK_SECRET == ""
        assert settings.STRIPE_AUTOMATIC_TAX is False
        assert stripe_api.is_open() is False

    def test_without_a_key_nothing_is_sent(self):
        for call in (
            lambda: checkout(),
            lambda: stripe_api.get_checkout("cs_1"),
            lambda: stripe_api.refund_payment("pi_1", 100, key="k", reference=1),
        ):
            with pytest.raises(stripe_api.NotConfigured):
                call()

    def test_a_test_that_forgets_to_fake_stripe_fails_instead_of_reaching_it(self, settings):
        settings.STRIPE_SECRET_KEY = "sk_test_made_up"
        with pytest.raises(AssertionError, match="tried to reach Stripe"):
            checkout()

    def test_opening_a_payment_page_sends_our_amount_and_our_reference(self, stripe_client):
        made = checkout()
        assert made["id"] == "cs_test_1" and made["url"].startswith("https://checkout.stripe.test/")
        (client,) = stripe_client.made
        assert client.key == "sk_test_made_up" and stripe_api.is_open()
        ((name, params, _options),) = client.calls
        assert name == "create" and params["mode"] == "payment"
        assert params["line_items"] == [
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": 200,
                    "product_data": {"name": "Tier 2 licence"},
                },
            }
        ]
        assert params["client_reference_id"] == "41" and params["metadata"] == {"purchase": "41"}
        assert params["payment_intent_data"] == {"metadata": {"purchase": "41"}}
        assert params["customer_email"] == "carol@example.com"
        assert "{CHECKOUT_SESSION_ID}" in params["success_url"]
        assert "automatic_tax" not in params and "invoice_creation" not in params

    def test_it_never_waits_longer_than_the_web_server_allows(self, stripe_client):
        checkout()
        http = stripe_client.made[0].options["http_client"]
        assert http._timeout == stripe_api.TIMEOUT_SECONDS < 30

    def test_an_organizations_purchase_asks_for_a_numbered_invoice(self, stripe_client):
        checkout(invoice=True, quantity=3, description="Tier 2 licences for Acme")
        params = stripe_client.made[0].calls[0][1]
        assert params["invoice_creation"]["enabled"] is True
        assert params["line_items"][0]["quantity"] == 3

    def test_tax_is_one_setting_away(self, stripe_client, settings):
        settings.STRIPE_AUTOMATIC_TAX = True
        checkout()
        params = stripe_client.made[0].calls[0][1]
        assert params["automatic_tax"] == {"enabled": True}
        assert params["line_items"][0]["price_data"]["tax_behavior"] == "exclusive"

    def test_asking_about_a_payment_page_gives_plain_values(self, stripe_client):
        assert stripe_api.get_checkout("cs_test_9") == {
            "id": "cs_test_9",
            "url": "",
            "paid": True,
            "payment_intent": "pi_test_1",
            "invoice": "in_test_1",
            "amount_cents": 600,  # before tax, to compare with our own row
            "currency": "usd",
        }

    def test_a_refund_names_the_payment_the_amount_and_a_key_against_repeats(self, stripe_client):
        assert stripe_api.refund_payment("pi_1", 150, key="refund-7-0", reference=7) == "re_test_1"
        ((name, params, options),) = stripe_client.made[0].calls
        assert name == "refund" and options == {"idempotency_key": "refund-7-0"}
        assert params == {"payment_intent": "pi_1", "amount": 150, "metadata": {"purchase": "7"}}

    def test_a_failure_at_stripe_is_reported_without_what_was_sent(
        self, stripe_client, monkeypatch
    ):
        def refuse(self, params=None, options=None):
            raise stripe.InvalidRequestError(
                "No such customer: carol@example.com", param="x", code="resource_missing"
            )

        monkeypatch.setattr(FakeClient, "create", refuse)
        with pytest.raises(stripe_api.StripeFailed) as caught:
            checkout()
        assert str(caught.value) == "InvalidRequestError (resource_missing)"
        assert "carol" not in str(caught.value)


class TestAMessageFromStripe:
    @pytest.fixture(autouse=True)
    def secret(self, settings):
        settings.STRIPE_WEBHOOK_SECRET = SECRET

    def test_a_signed_message_is_read_as_plain_values(self):
        payload = message(id="cs_1", payment_status="paid", payment_intent="pi_1", currency="usd")
        event = stripe_api.read_event(payload.encode(), signed(payload))
        assert event["type"] == "checkout.session.completed"
        assert stripe_api.checkout_in(event) == {
            "id": "cs_1",
            "url": "",
            "paid": True,
            "payment_intent": "pi_1",
            "invoice": "",
            "amount_cents": None,
            "currency": "usd",
        }

    def test_a_refund_message_says_which_payment_and_how_much_has_gone_back(self):
        payload = message("charge.refunded", payment_intent="pi_1", amount=600, amount_refunded=200)
        event = stripe_api.read_event(payload.encode(), signed(payload))
        assert stripe_api.charge_in(event) == {
            "payment_intent": "pi_1",
            "amount_cents": 600,
            "refunded_cents": 200,
        }

    @pytest.mark.parametrize(
        "header",
        [None, "", "nonsense", "t=1,v1=abc", lambda p: signed(p, secret="whsec_someone_elses")],
    )
    def test_anything_not_signed_with_our_secret_is_refused(self, header):
        payload = message(id="cs_1", payment_status="paid")
        if callable(header):
            header = header(payload)
        with pytest.raises(stripe_api.BadSignature):
            stripe_api.read_event(payload.encode(), header)

    def test_a_message_changed_on_the_way_is_refused(self):
        payload = message(id="cs_1", payment_status="unpaid")
        header = signed(payload)
        with pytest.raises(stripe_api.BadSignature):
            stripe_api.read_event(payload.replace("unpaid", "paid").encode(), header)

    def test_an_old_message_sent_again_is_refused(self):
        payload = message(id="cs_1", payment_status="paid")
        with pytest.raises(stripe_api.BadSignature):
            stripe_api.read_event(payload.encode(), signed(payload, at=time.time() - 3600))

    def test_without_the_secret_no_message_can_be_checked(self, settings):
        settings.STRIPE_WEBHOOK_SECRET = ""
        payload = message(id="cs_1")
        with pytest.raises(stripe_api.NotConfigured):
            stripe_api.read_event(payload.encode(), signed(payload))


def test_production_settings_start_without_any_stripe_setting(monkeypatch):
    """The keys are optional, so a deploy before they exist cannot stop the site."""
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_AUTOMATIC_TAX"):
        monkeypatch.delenv(name, raising=False)
    from config.settings import base

    reloaded = importlib.reload(base)
    try:
        assert reloaded.STRIPE_SECRET_KEY == "" and reloaded.STRIPE_WEBHOOK_SECRET == ""
        assert reloaded.STRIPE_AUTOMATIC_TAX is False
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_from_the_environment")
        monkeypatch.setenv("STRIPE_AUTOMATIC_TAX", "true")
        reloaded = importlib.reload(base)
        assert reloaded.STRIPE_SECRET_KEY == "sk_test_from_the_environment"
        assert reloaded.STRIPE_AUTOMATIC_TAX is True
    finally:
        monkeypatch.undo()
        importlib.reload(base)
