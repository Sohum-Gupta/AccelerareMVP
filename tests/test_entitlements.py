"""
Milestone 2, PR 2: licences. Grant, revoke, upgrade in place, and the admin that
drives them. "Unused" is just "active" until Response exists (PR 3).
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.entitlements import services
from apps.entitlements.models import Entitlement

from .test_admin_and_guard import root  # noqa: F401  (fixture)
from .test_profile import verified_account


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


def grant(account, tier=1, source="manual", by=None):
    return services.grant_individual(account.person, tier, source, by)


@pytest.mark.django_db
class TestServices:
    def test_grant_gives_access_and_revoke_takes_it_away(self, bob):
        assert not services.has_survey_access(bob)
        licence = grant(bob, 2)
        assert services.has_survey_access(bob)
        assert licence.tier == 2 and licence.is_active
        services.revoke(licence)
        assert not services.has_survey_access(bob)
        assert services.unused_licence(bob) is None

    def test_revoking_twice_keeps_the_first_date(self, bob):
        licence = grant(bob)
        services.revoke(licence)
        first = licence.revoked_at
        services.revoke(licence)
        licence.refresh_from_db()
        assert licence.revoked_at == first

    def test_unused_licence_is_the_oldest_active_one(self, bob):
        oldest = grant(bob, 1)
        grant(bob, 3)
        assert services.unused_licence(bob) == oldest
        services.revoke(oldest)
        assert services.unused_licence(bob).tier == 3

    def test_licences_belong_to_the_person_not_to_someone_else(self, bob):
        carol = verified_account("carol@example.com")
        grant(bob)
        assert services.has_survey_access(bob)
        assert not services.has_survey_access(carol)

    @pytest.mark.parametrize("tier", [0, 4, -1, "2", 2.0, True, None])
    def test_bad_tiers_are_refused(self, bob, tier):
        with pytest.raises(ValidationError):
            grant(bob, tier)
        assert Entitlement.objects.count() == 0

    def test_bad_source_is_refused(self, bob):
        with pytest.raises(ValidationError):
            grant(bob, 1, source="seat")

    def test_database_refuses_a_bad_tier_even_without_the_service(self, bob):
        with pytest.raises(IntegrityError), transaction.atomic():
            Entitlement.objects.create(person=bob.person, tier=4, source="manual")

    def test_change_tier_upgrades_in_place(self, bob):
        licence = grant(bob, 1)
        granted_at = licence.granted_at
        services.change_tier(licence, 3)
        licence.refresh_from_db()
        assert licence.tier == 3 and licence.granted_at == granted_at
        assert Entitlement.objects.count() == 1

    def test_change_tier_refuses_a_bad_tier_and_a_revoked_licence(self, bob):
        licence = grant(bob, 1)
        with pytest.raises(ValidationError):
            services.change_tier(licence, 5)
        services.revoke(licence)
        with pytest.raises(ValidationError):
            services.change_tier(licence, 2)


@pytest.mark.django_db
class TestAdmin:
    def test_pages_load_and_search_finds_a_licence_by_email_and_phone(self, client, root, bob):  # noqa: F811
        grant(bob)
        assert client.get("/admin/entitlements/entitlement/").status_code == 200
        assert client.get("/admin/entitlements/entitlement/add/").status_code == 200
        for q in ("bob@example", "+919876543210"):
            page = client.get("/admin/entitlements/entitlement/", {"q": q}).content.decode()
            assert "bob@example.com" in page

    def test_add_form_grants_through_the_service_and_records_who(self, client, root, bob):  # noqa: F811
        response = client.post(
            "/admin/entitlements/entitlement/add/",
            {"account": bob.pk, "tier": 2, "source": "manual"},
        )
        assert response.status_code == 302
        licence = Entitlement.objects.get()
        assert licence.person == bob.person
        assert licence.tier == 2
        assert licence.granted_by == root

    def test_changing_the_tier_upgrades_but_nothing_else_is_editable(self, client, root, bob):  # noqa: F811
        licence = grant(bob, 1)
        url = f"/admin/entitlements/entitlement/{licence.pk}/change/"
        client.post(url, {"tier": 3, "source": "purchase", "person": 999})
        licence.refresh_from_db()
        assert licence.tier == 3
        assert licence.source == "manual" and licence.person == bob.person

    def test_revoke_action(self, client, root, bob):  # noqa: F811
        licence = grant(bob)
        client.post(
            "/admin/entitlements/entitlement/",
            {"action": "revoke_selected", "_selected_action": [licence.pk]},
        )
        licence.refresh_from_db()
        assert licence.revoked_at is not None

    def test_there_is_no_delete(self, client, root, bob):  # noqa: F811
        licence = grant(bob)
        url = f"/admin/entitlements/entitlement/{licence.pk}/delete/"
        assert client.post(url, {"post": "yes"}).status_code == 403
        assert Entitlement.objects.count() == 1

    def test_non_staff_cannot_reach_it(self, client, bob):
        client.force_login(bob)
        response = client.get("/admin/entitlements/entitlement/")
        assert response.status_code == 302
        assert reverse("admin:login") in response["Location"]
