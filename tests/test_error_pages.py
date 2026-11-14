"""
Milestone 7, PR 1: the pages a visitor sees when something is not there, not
allowed, or broken.

Before this, Django's own bare pages were shown ("Not Found", "Server Error
(500)"). Now each is a calm page in the site's look with a way back. None says
anything about the visitor, the address they asked for or what went wrong
inside, and the "something went wrong" page is fixed text that cannot itself fail.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from apps.accounts import services as accounts

from .test_profile import verified_account

TEMPLATES = Path(settings.BASE_DIR) / "templates"
# What no error page may ever show.
NEVER = ("Traceback", "Django", "DEBUG", "RuntimeError", "hunter2", "@", "settings")


def text_of(answer):
    return answer.content.decode()


@pytest.mark.django_db
class TestNotFound:
    def test_an_unknown_address_gets_the_sites_own_page(self, client):
        answer = client.get("/no/such/page/")
        page = text_of(answer)
        assert answer.status_code == 404
        assert "<h1>Page not found</h1>" in page and "Accelerare" in page
        assert 'href="/"' in page and "Go to the start page" in page

    def test_it_says_nothing_about_the_address_or_the_visitor(self, client):
        client.force_login(verified_account("bob@example.com"))
        page = text_of(client.get("/no/such/page/with-a-marker-9f3a/"))
        assert "marker-9f3a" not in page and "bob" not in page
        for word in NEVER:
            assert word not in page, word

    def test_it_is_the_same_page_to_the_byte_for_everyone(self, client):
        logged_out = client.get("/no/such/page/").content
        client.force_login(verified_account("bob@example.com"))
        assert client.get("/no/such/page/").content == logged_out
        assert client.get("/another/missing/page/").content == logged_out
        # No form and no security token: either would differ from load to load.
        assert b"<form" not in logged_out and b"csrfmiddlewaretoken" not in logged_out

    def test_an_organization_that_is_not_yours_looks_the_same(self, client):
        from .orgs import org_with_admin

        org_with_admin("Acme")
        client.force_login(verified_account("stranger@example.com"))
        theirs = client.get("/organizations/acme/")
        missing = client.get("/organizations/no-such-place/")
        assert theirs.status_code == missing.status_code == 404
        assert theirs.content == missing.content
        assert b"<h1>Page not found</h1>" in theirs.content and b"Acme" not in theirs.content


@pytest.mark.django_db
class TestNotAllowed:
    def test_a_page_this_account_may_not_open(self, client):
        support = verified_account("support@example.com")
        accounts.make_support_staff(support)
        client.force_login(support)
        answer = client.get(reverse("admin:audit_auditlog_changelist"))
        page = text_of(answer)
        assert answer.status_code == 403
        assert "<h1>Not allowed</h1>" in page and "Go to the start page" in page
        for word in NEVER:
            assert word not in page, word

    def test_a_form_without_the_security_token(self, db):
        strict = Client(enforce_csrf_checks=True)
        answer = strict.post(reverse("account_login"), {"login": "x", "password": "y"})
        page = text_of(answer)
        assert answer.status_code == 403
        assert "<h1>Please try again</h1>" in page and "nothing was changed" in page
        assert "CSRF" not in page and "Referer" not in page
        for word in NEVER:
            assert word not in page, word


class TestSomethingWentWrong:
    @pytest.fixture
    def broken(self, client, settings):
        settings.ROOT_URLCONF = "tests.urls_with_a_fault"
        client.raise_request_exception = False
        return client

    @pytest.mark.django_db
    def test_a_fault_gets_a_calm_page_and_no_detail(self, broken):
        answer = broken.get("/a-fault/")
        page = text_of(answer)
        assert answer.status_code == 500
        assert "<h1>Something went wrong</h1>" in page and "Accelerare" in page
        assert "Anything you had already saved is still saved" in page
        for word in NEVER:
            assert word not in page, word

    @pytest.mark.django_db
    def test_it_is_the_same_for_someone_logged_in(self, broken):
        logged_out = broken.get("/a-fault/").content
        broken.force_login(verified_account("bob@example.com"))
        assert broken.get("/a-fault/").content == logged_out

    def test_the_page_needs_no_database(self):
        """This test may not touch the database at all; rendering the page must not try."""
        assert "Something went wrong" in render_to_string("500.html")

    def test_the_page_is_fixed_text_that_cannot_fail(self):
        source = (TEMPLATES / "500.html").read_text()
        assert "{%" not in source and "{{" not in source
        # Nothing to fetch: no stylesheet, script or image of ours.
        assert "<link" not in source and "<script" not in source and "<img" not in source


def test_the_other_three_pages_carry_nothing_personal_or_changing():
    """No account menu, no form, no token: the same bytes for every visitor."""
    for name in ("errors/base.html", "404.html", "403.html", "403_csrf.html"):
        source = (TEMPLATES / name).read_text()
        for tag in ("csrf_token", "user.", "request.", "messages", "<form", "exception", "reason"):
            assert tag not in source, f"{name} uses {tag}"
    # The shared layout stands alone: the site's main layout draws the account menu.
    assert "{% extends" not in (TEMPLATES / "errors/base.html").read_text()
