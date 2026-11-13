"""
Payments: what a licence costs, and the record of every payment.

A Price is what one licence of a tier costs today. Staff change it in the
admin; the amount is sent to Stripe with each purchase, so nothing has to be set
up in Stripe when a price changes.

A Purchase is one trip to Stripe's payment page: a personal licence, an upgrade
of one, or a number of licences for an organization's stock. The row is written
before the person is sent to Stripe, with the price the server read, and is
marked paid when Stripe confirms. A Refund is money sent back for one.

These rows are the accounting record, and they hold no personal identity: no
name, no email, no card detail. They keep amounts, dates, the tier and
Stripe's references. The three links a purchase has (who pressed Buy, the
licence, the organization) are emptied, never followed, when what they point at
is deleted, so erasing a person can never remove or change a payment.

Money is whole cents in an integer column, never a fraction.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.conf import settings
from django.db import models

TIER_1_TO_3 = models.Q(tier__gte=1, tier__lte=3)
# Stripe refuses a charge under 50 US cents; the top is a guard against a slip
# of the finger in the admin (10,000 dollars for one licence).
MIN_PRICE_CENTS = 50
MAX_PRICE_CENTS = 1_000_000


class Price(models.Model):
    """What one licence of a tier costs, in US cents. One row per tier."""

    tier = models.PositiveSmallIntegerField(unique=True)
    amount_cents = models.PositiveIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tier"]
        constraints = [
            models.CheckConstraint(condition=TIER_1_TO_3, name="price_tier_1_to_3"),
            models.CheckConstraint(
                condition=models.Q(
                    amount_cents__gte=MIN_PRICE_CENTS, amount_cents__lte=MAX_PRICE_CENTS
                ),
                name="price_amount_in_range",
            ),
        ]

    def __str__(self):
        return f"Price of a Tier {self.tier} licence"


class Purchase(models.Model):
    """One payment, from the moment the person is sent to Stripe's page."""

    class Kind(models.TextChoices):
        PERSONAL = "personal", "A personal licence"
        UPGRADE = "upgrade", "An upgrade of a personal licence"
        STOCK = "stock", "Licences for an organization's stock"

    class Status(models.TextChoices):
        PENDING = "pending", "Not paid (payment page opened)"
        PAID = "paid", "Paid"
        PART_REFUNDED = "part_refunded", "Partly refunded"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Could not be started"

    kind = models.CharField(max_length=10, choices=Kind)
    status = models.CharField(max_length=15, choices=Status, default=Status.PENDING)

    # Who pressed Buy. Needed to give a personal licence to the right person
    # when Stripe says "paid". Emptied if that account is ever deleted.
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # The licence that was bought (set when it is paid) or upgraded (set at the
    # start). Emptied if the licence is deleted with its account.
    entitlement = models.ForeignKey(
        "entitlements.Entitlement",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchases",
        verbose_name="licence",
    )
    # A stock purchase: whose stock. Organizations are never deleted.
    enterprise = models.ForeignKey(
        "enterprises.Enterprise",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchases",
        verbose_name="organization",
    )

    # What was sold: the tier, the tier an upgrade started from, and how many.
    tier = models.PositiveSmallIntegerField()
    from_tier = models.PositiveSmallIntegerField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    # For an upgrade, the unit amount is the difference between the two prices.
    unit_amount_cents = models.PositiveIntegerField()
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="usd")
    refunded_cents = models.PositiveIntegerField(default=0)
    refunded_quantity = models.PositiveIntegerField(default=0)

    # Stripe's references. The session is the visit to the payment page; the
    # payment intent is the charge itself, known once it is paid.
    stripe_session_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_invoice_id = models.CharField(max_length=255, blank=True)

    # Something staff must look at: money came in or went out and the site
    # could not finish its side. `note` says what, in plain words, naming nobody.
    needs_attention = models.BooleanField(default=False)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # When what was paid for was given. Empty on a paid row means the money
    # came in and nothing was given (see needs_attention): a refund of it has
    # nothing to take back.
    given_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "payment"
        constraints = [
            models.CheckConstraint(condition=TIER_1_TO_3, name="purchase_tier_1_to_3"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="purchase_at_least_one"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    amount_cents=models.F("unit_amount_cents") * models.F("quantity")
                ),
                name="purchase_amount_is_unit_times_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(refunded_cents__lte=models.F("amount_cents"))
                & models.Q(refunded_quantity__lte=models.F("quantity")),
                name="purchase_never_refunds_more_than_was_paid",
            ),
            # Only a stock purchase names an organization, and it always does.
            models.CheckConstraint(
                condition=(
                    models.Q(kind="stock", enterprise__isnull=False)
                    | (~models.Q(kind="stock") & models.Q(enterprise__isnull=True))
                ),
                name="purchase_organization_iff_stock",
            ),
            # Only an upgrade has a tier it started from, below the one bought.
            models.CheckConstraint(
                condition=(
                    # "is not null" is spelled out: a check that works out to
                    # "unknown" passes, and comparing with NULL is unknown.
                    models.Q(
                        kind="upgrade",
                        from_tier__isnull=False,
                        from_tier__gte=1,
                        from_tier__lt=models.F("tier"),
                    )
                    | (~models.Q(kind="upgrade") & models.Q(from_tier__isnull=True))
                ),
                name="purchase_from_tier_iff_upgrade",
            ),
            # Only a stock purchase is for more than one.
            models.CheckConstraint(
                condition=models.Q(kind="stock") | models.Q(quantity=1),
                name="purchase_one_unless_stock",
            ),
        ]

    @property
    def refundable_cents(self):
        return self.amount_cents - self.refunded_cents

    def __str__(self):
        # Never the buyer: Django's admin history keeps this as its label.
        return f"Payment {self.pk}"


class Refund(models.Model):
    """Money sent back for a purchase, in full or (for a stock purchase) in part."""

    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="refunds")
    amount_cents = models.PositiveIntegerField()
    # How many licences it took back; 0 when the money went back in Stripe's
    # dashboard and nothing could be taken back here.
    quantity = models.PositiveIntegerField(default=0)
    # Stripe's reference. Empty for a refund the site only heard about.
    stripe_refund_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    # The staff account that pressed Refund; empty if it was made in Stripe's dashboard.
    made_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_cents__gte=1), name="refund_is_for_something"
            ),
        ]

    def __str__(self):
        return f"Refund {self.pk}"
