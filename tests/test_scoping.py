"""
Milestone 3, PR 3: `scoping.for_member` and `scoping.for_admin`, the wall
between one organization and another. Every organization page will start with
one of them, so these are the first of the tenant isolation tests: a slug from
the address is never enough, only the account's own active membership is.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory

from apps.enterprises import scoping, services

from .orgs import add_member, new_member, org_with_admin


def request_from(account):
    request = RequestFactory().get("/organizations/anything/")
    request.user = account
    return request


def is_404(look_up, account, slug):
    try:
        look_up(request_from(account), slug)
    except Http404:
        return True
    return False


@pytest.fixture
def two_orgs(db):
    acme, acme_admin = org_with_admin("Acme")
    globex, globex_admin = org_with_admin("Globex")
    return {
        "acme": acme,
        "acme_admin": acme_admin,
        "acme_member": new_member(acme, "member@acme.example.com"),
        "globex": globex,
        "globex_admin": globex_admin,
        "globex_member": new_member(globex, "member@globex.example.com"),
    }


@pytest.mark.django_db
class TestForMember:
    def test_gives_the_accounts_own_membership(self, two_orgs):
        for who in ("acme_admin", "acme_member"):
            membership = two_orgs[who]
            found = scoping.for_member(request_from(membership.account), "acme")
            assert found == membership and found.enterprise == two_orgs["acme"]

    def test_another_organization_is_not_found(self, two_orgs):
        for who in ("globex_admin", "globex_member"):
            assert is_404(scoping.for_member, two_orgs[who].account, "acme")

    def test_a_slug_that_does_not_exist_looks_exactly_the_same(self, two_orgs):
        outsider = two_orgs["globex_admin"].account
        assert is_404(scoping.for_member, outsider, "no-such-organization")
        assert is_404(scoping.for_member, outsider, "acme")

    def test_a_deactivated_member_is_not_found(self, two_orgs):
        membership = two_orgs["acme_member"]
        services.deactivate_membership(membership, by=two_orgs["acme_admin"])
        assert is_404(scoping.for_member, membership.account, "acme")
        services.reactivate_membership(membership, by=two_orgs["acme_admin"])
        assert not is_404(scoping.for_member, membership.account, "acme")

    def test_a_visitor_who_is_not_logged_in_is_not_found(self, two_orgs):
        assert is_404(scoping.for_member, AnonymousUser(), "acme")

    def test_the_slug_must_match_exactly(self, two_orgs):
        account = two_orgs["acme_admin"].account
        for slug in ("ACME", "acme ", "acm", "acme-2", ""):
            assert is_404(scoping.for_member, account, slug)


@pytest.mark.django_db
class TestForAdmin:
    def test_gives_an_admin_their_own_membership(self, two_orgs):
        membership = two_orgs["acme_admin"]
        found = scoping.for_admin(request_from(membership.account), "acme")
        assert found == membership and found.enterprise == two_orgs["acme"]

    def test_a_member_who_is_not_an_admin_is_not_found(self, two_orgs):
        assert is_404(scoping.for_admin, two_orgs["acme_member"].account, "acme")

    def test_another_organizations_admin_is_not_found(self, two_orgs):
        assert is_404(scoping.for_admin, two_orgs["globex_admin"].account, "acme")
        assert is_404(scoping.for_admin, two_orgs["globex_admin"].account, "nothing-here")

    def test_a_demoted_or_deactivated_admin_is_not_found(self, two_orgs):
        first = two_orgs["acme_admin"]
        second = new_member(two_orgs["acme"], "second@acme.example.com", role="admin")
        services.set_role(second, "member", by=first)
        assert is_404(scoping.for_admin, second.account, "acme")
        services.set_role(second, "admin", by=first)
        services.deactivate_membership(second, by=first)
        assert is_404(scoping.for_admin, second.account, "acme")

    def test_a_promoted_member_is_found(self, two_orgs):
        member = two_orgs["acme_member"]
        services.set_role(member, "admin", by=two_orgs["acme_admin"])
        assert scoping.for_admin(request_from(member.account), "acme") == member

    def test_someone_in_two_organizations_gets_the_one_in_the_address(self, two_orgs):
        both = two_orgs["acme_admin"].account
        in_globex = add_member(two_orgs["globex"], both)
        assert scoping.for_member(request_from(both), "globex") == in_globex
        assert scoping.for_admin(request_from(both), "acme") == two_orgs["acme_admin"]
        # An admin in one is still only a member in the other.
        assert is_404(scoping.for_admin, both, "globex")

    def test_a_visitor_who_is_not_logged_in_is_not_found(self, two_orgs):
        assert is_404(scoping.for_admin, AnonymousUser(), "acme")
