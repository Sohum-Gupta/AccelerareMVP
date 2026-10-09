from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("admin/", admin.site.urls),
    # All of allauth's account pages. allauth links between them by name, so
    # mounting a subset risks a missing name at run time. Pages we replace
    # (signup, login) are shadowed by our own views under the same names.
    path("accounts/", include("allauth.account.urls")),
]
