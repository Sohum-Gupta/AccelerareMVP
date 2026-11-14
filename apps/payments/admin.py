"""
Prices and payments in the staff admin.

Prices: three rows, one per tier. A superuser changes the amount, typed in
dollars; nobody adds or deletes a row. Support staff can look.

Payments: the record of every purchase, read-only for everyone. Nothing here
is typed: a payment is made by a person on Stripe's page, and changed only by
the services. Its refunds are listed under it. Support staff can look.

Refunding: a superuser opens a payment and presses "Refund…". A page says
exactly what will happen (what is taken back, how much money goes back) and
asks first. One button then takes back what was sold and refunds through
Stripe, together or not at all (services.refund), and writes a history line
saying who did it. Staff should refund here, not in Stripe's dashboard: a
refund made there is noticed, but the site can only take back what the rules
allow, and marks the payment "needs attention" otherwise.

A payment's label is "Payment 12", never the buyer, so no admin history line
can keep someone's email.
"""

from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.validators import MaxValueValidator
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.accounts.admin_links import link
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


class RefundForm(forms.Form):
    """The "Refund" page of a stock purchase: how many of its licences to refund."""

    quantity = forms.IntegerField(label="How many licences to refund", min_value=1)

    def __init__(self, *args, most, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["quantity"]
        field.max_value = most
        field.initial = most
        field.widget.attrs["max"] = most
        field.validators.append(MaxValueValidator(most))
        field.help_text = f"From 1 to {most}: the number still in the organization's stock."


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
        "buyer_link",
        "enterprise_link",
        "needs_attention",
        "created_at",
        "paid_at",
    )
    list_filter = (NeedsAttentionFilter, "status", "kind")
    # By Stripe's references, the organization, or the email of whoever pressed Buy.
    search_fields = (
        "stripe_session_id",
        "stripe_payment_intent_id",
        "enterprise__name",
        "buyer__email",
    )
    list_select_related = ("enterprise", "buyer")

    @admin.display(description="Bought by", ordering="buyer__email")
    def buyer_link(self, purchase):
        return link(purchase.buyer)

    @admin.display(description="Organization", ordering="enterprise__name")
    def enterprise_link(self, purchase):
        return link(purchase.enterprise)

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

    # --- the "Refund" page ---------------------------------------------------------

    def get_urls(self):
        custom = path(
            "<path:object_id>/refund/",
            self.admin_site.admin_view(self.refund_view),
            name="payments_purchase_refund",
        )
        return [custom, *super().get_urls()]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        # Superusers only: has_manage_permission is the model's "change"
        # permission, which Support staff do not hold.
        if self.has_manage_permission(request):
            extra_context["refund_url"] = reverse(
                "admin:payments_purchase_refund", args=[object_id]
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def refund_view(self, request, object_id):
        if not self.has_manage_permission(request):
            raise PermissionDenied
        purchase = get_object_or_404(Purchase.objects.select_related("enterprise"), pk=object_id)
        back = reverse("admin:payments_purchase_change", args=[purchase.pk])
        preview = services.refund_preview(purchase)
        is_stock = purchase.kind == Purchase.Kind.STOCK
        form = RefundForm(request.POST or None, most=max(preview["most"], 1))
        if request.method == "POST" and preview["can"] and form.is_valid():
            quantity = form.cleaned_data["quantity"] if is_stock else None
            try:
                made = services.refund(purchase, request.user, quantity)
            except services.Refused as error:
                self.message_user(request, str(error), messages.ERROR)
                return redirect(request.path)
            text = f"Refunded {services.dollars(made.amount_cents)} through Stripe"
            if made.quantity:
                text += (
                    f"; took back {made.quantity} licence(s)"
                    if is_stock
                    else "; "
                    + (
                        "the licence went back down a tier"
                        if purchase.kind == Purchase.Kind.UPGRADE
                        else "the licence was withdrawn"
                    )
                )
            # The payment's history says who refunded it and what happened.
            self.log_change(request, purchase, text)
            self.message_user(request, text + ".", messages.SUCCESS)
            return redirect(back)
        context = {
            **self.admin_site.each_context(request),
            "title": "Refund a payment",
            "opts": self.opts,
            "purchase": purchase,
            "what": self.what(purchase),
            "paid": services.dollars(purchase.amount_cents),
            "refunded": services.dollars(purchase.refunded_cents),
            "preview": preview,
            "unit": services.dollars(preview["unit"]),
            "whole": services.dollars(preview["unit"] * preview["most"]),
            "is_stock": is_stock,
            "form": form,
            "days": services.REFUND_DAYS,
        }
        return TemplateResponse(request, "admin/payments/purchase/refund.html", context)
