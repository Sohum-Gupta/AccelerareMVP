"""
Prices and payments in the staff admin.

Prices: three rows, one per tier. A superuser changes the amount, typed in
dollars; nobody adds or deletes a row. Support staff can look.

Payments: the record of every purchase, read-only for everyone. Nothing here
is typed: a payment is made by a person on Stripe's page, and changed only by
the services. Its refunds are listed under it. Support staff can look.

A payment's label is "Payment 12", never the buyer, so no admin history line
can keep someone's email.
"""

from decimal import Decimal

from django import forms
from django.contrib import admin

from apps.enterprises.admin import ReadOnlyAdmin

from . import services
from .models import MAX_PRICE_CENTS, MIN_PRICE_CENTS, Price, Purchase, Refund


class PriceForm(forms.ModelForm):
    """The price typed in dollars ("2.50"); the database keeps whole cents."""

    dollars = forms.DecimalField(
        label="Price in US dollars",
        max_digits=8,
        decimal_places=2,
        min_value=Decimal(MIN_PRICE_CENTS) / 100,
        max_value=Decimal(MAX_PRICE_CENTS) / 100,
        help_text="What one licence of this tier costs, for example 2.50. People who have "
        "already been sent to the payment page pay the price they were shown.",
    )

    class Meta:
        model = Price
        fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            cents = Decimal(self.instance.amount_cents)
            self.fields["dollars"].initial = (cents / 100).quantize(Decimal("0.01"))

    def save(self, commit=True):
        self.instance.amount_cents = int(self.cleaned_data["dollars"] * 100)
        return super().save(commit)


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    form = PriceForm
    list_display = ("__str__", "price", "updated_at")
    readonly_fields = ("tier", "updated_at")
    fields = ("tier", "dollars", "updated_at")
    ordering = ("tier",)

    @admin.display(description="Price")
    def price(self, price):
        return services.dollars(price.amount_cents)

    # Three rows, for good: one per tier.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    fields = ("created_at", "amount", "quantity", "stripe_refund_id", "made_by")
    readonly_fields = fields
    verbose_name_plural = "Refunds of this payment"

    @admin.display(description="Amount")
    def amount(self, refund):
        return services.dollars(refund.amount_cents)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class NeedsAttentionFilter(admin.SimpleListFilter):
    """Payments where money moved and the site could not finish its side."""

    title = "needs attention"
    parameter_name = "attention"

    def lookups(self, request, model_admin):
        return [("yes", "Needs attention")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(needs_attention=True)
        return queryset


@admin.register(Purchase)
class PurchaseAdmin(ReadOnlyAdmin):
    list_display = (
        "__str__",
        "kind",
        "what",
        "amount",
        "status",
        "enterprise",
        "needs_attention",
        "created_at",
        "paid_at",
    )
    list_filter = (NeedsAttentionFilter, "status", "kind")
    search_fields = ("stripe_session_id", "stripe_payment_intent_id", "enterprise__name")
    list_select_related = ("enterprise",)
    inlines = [RefundInline]

    @admin.display(description="What")
    def what(self, purchase):
        if purchase.kind == Purchase.Kind.UPGRADE:
            return f"Tier {purchase.from_tier} to Tier {purchase.tier}"
        return f"{purchase.quantity} x Tier {purchase.tier}"

    @admin.display(description="Amount")
    def amount(self, purchase):
        text = services.dollars(purchase.amount_cents)
        if purchase.refunded_cents:
            text += f" ({services.dollars(purchase.refunded_cents)} refunded)"
        return text
