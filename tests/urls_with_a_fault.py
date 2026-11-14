"""The site's addresses plus one that always fails, for tests/test_error_pages.py."""

from django.urls import include, path


def fault(request):
    raise RuntimeError("a made-up fault, with a secret-looking word: hunter2")


urlpatterns = [path("a-fault/", fault), path("", include("config.urls"))]
