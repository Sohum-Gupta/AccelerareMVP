from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("admin/", admin.site.urls),
    # Ours, before the include, so reverse("account_signup") finds this one.
    path("accounts/signup/", account_views.signup, name="account_signup"),
    path("accounts/profile/", account_views.profile, name="account_profile"),
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
]
