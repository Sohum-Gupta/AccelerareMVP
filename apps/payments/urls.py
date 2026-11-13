from django.urls import path

from . import views

app_name = "payments"

# Mounted at the top of the site. The webhook's address is the one given to
# Stripe (docs/05-build-plan.md, Milestone 4b), so it must not move.
urlpatterns = [
    path("buy/done/", views.done, name="done"),
    path("buy/cancelled/", views.cancelled, name="cancelled"),
    path("payments/stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
