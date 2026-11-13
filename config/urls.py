from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views
from apps.enterprises import views as enterprise_views
from apps.entitlements import organization_views as licence_views
from apps.payments import views as payment_views
from apps.responses import organization_views

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health", views.health, name="health"),
    path("health/worker", views.worker_health, name="worker_health"),
    path("admin/", admin.site.urls),
    # Ours, before the include, so reverse("account_signup") finds this one.
    path("accounts/signup/", account_views.signup, name="account_signup"),
    path("accounts/profile/", account_views.profile, name="account_profile"),
    path("accounts/profile/name/", account_views.change_name, name="profile_change_name"),
    path("accounts/profile/email/add/", account_views.add_email, name="profile_add_email"),
    path(
        "accounts/profile/email/<int:pk>/resend/",
        account_views.resend_verification,
        name="profile_resend_verification",
    ),
    path(
        "accounts/profile/email/<int:pk>/primary/",
        account_views.make_primary,
        name="profile_make_primary",
    ),
    path(
        "accounts/profile/contact/<int:pk>/remove/",
        account_views.remove_contact,
        name="profile_remove_contact",
    ),
    path("accounts/profile/phone/", account_views.change_phone, name="profile_change_phone"),
    path(
        "accounts/profile/personal-email-prompt/dismiss/",
        account_views.dismiss_personal_email_prompt,
        name="profile_dismiss_prompt",
    ),
    # All of allauth's account pages. allauth links between them by name, so
    # mounting a subset risks a missing name at run time. Pages we replace
    # (signup, login) are shadowed by our own views under the same names.
    path("accounts/", include("allauth.account.urls")),
    path("survey/", include("apps.responses.urls")),
    # Buying: the pages Stripe sends a person back to, and Stripe's own messages.
    path("", include("apps.payments.urls")),
    # An organization's responses pages. They are served by the responses app
    # (the enterprises app may not import it), so they are listed here, before
    # the include, rather than in apps/enterprises/urls.py.
    path(
        "organizations/<slug:slug>/responses/",
        organization_views.table,
        name="organization_responses",
    ),
    path(
        "organizations/<slug:slug>/responses/export/",
        organization_views.export,
        name="organization_responses_export",
    ),
    path(
        "organizations/<slug:slug>/responses/<int:pk>/",
        organization_views.detail,
        name="organization_response",
    ),
    # An organization's Licences page and its buttons, served by the licences
    # app for the same reason.
    path(
        "organizations/<slug:slug>/licences/",
        licence_views.licences,
        name="organization_licences",
    ),
    # Buying licences into an organization's stock, served by the payments app.
    path(
        "organizations/<slug:slug>/licences/buy/",
        payment_views.buy_stock,
        name="organization_licences_buy",
    ),
    path(
        "organizations/<slug:slug>/licences/members/<int:pk>/give/",
        licence_views.give,
        name="organization_licence_give",
    ),
    path(
        "organizations/<slug:slug>/licences/<int:pk>/tier/",
        licence_views.change_tier,
        name="organization_licence_tier",
    ),
    path(
        "organizations/<slug:slug>/licences/<int:pk>/take-back/",
        licence_views.take_back,
        name="organization_licence_take_back",
    ),
    path("organizations/", include("apps.enterprises.urls")),
    # Joining an organization. Not under /organizations/: the person is not a member yet.
    path("join/code/", enterprise_views.join_code, name="join_code"),
    path("join/invite/<str:token>/", enterprise_views.join_invite, name="join_invite"),
]
