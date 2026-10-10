"""
Milestone 2, PR 3c: funnel events. What is recorded and when, that no event can
point at a person, and the admin summary and filters that read them.
"""

from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.db.models import ForeignKey
from django.utils import timezone

from apps.accounts import erasure, services
from apps.accounts.models import Account
from apps.entitlements import services as licences
from apps.funnel import services as funnel
from apps.funnel.admin import funnel_rows
from apps.funnel.models import FunnelEvent
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.survey.services import current_version

from .test_profile import second_email, verified_account
from .test_verification import PASSWORD

Kind = FunnelEvent.Kind


def kinds():
    return list(FunnelEvent.objects.order_by("id").values_list("kind", flat=True))


@pytest.mark.django_db
class TestRecording:
    def test_sign_up_records_the_phones_country_and_nothing_else(self):
        services.register("bob@example.com", "+919876543210", None, PASSWORD)
        event = FunnelEvent.objects.get()
        assert event.kind == Kind.SIGNED_UP
        assert event.country == "IN" and event.channel == "direct"
        assert event.tier is None and event.source == ""

    def test_us_and_uk_numbers_give_their_countries(self):
        services.register("a@example.com", "+14155552671", None, PASSWORD)
        services.register("b@example.com", "+442071838750", None, PASSWORD)
        assert set(FunnelEvent.objects.values_list("country", flat=True)) == {"US", "GB"}

    def test_a_refused_sign_up_records_nothing(self):
        services.register("bob@example.com", "+919876543210", None, PASSWORD)
        with pytest.raises(services.EmailInUse):
            services.register("BOB@example.com", "+919876543211", None, PASSWORD)
        assert kinds() == [Kind.SIGNED_UP]

    def test_the_first_verified_email_counts_once(self):
        account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
        FunnelEvent.objects.all().delete()
        from allauth.account.signals import email_confirmed

        row = EmailAddress.objects.get(user=account)
        email_confirmed.send(sender=None, request=None, email_address=row)
        email_confirmed.send(sender=None, request=None, email_address=row)  # clicked twice
        assert kinds() == [Kind.EMAIL_VERIFIED]

    def test_a_second_verified_email_is_not_a_funnel_step(self):
        account = verified_account("bob@example.com")
        FunnelEvent.objects.all().delete()
        second_email(account, "bob.two@example.com", verified=False)
        from allauth.account.signals import email_confirmed

        row = EmailAddress.objects.get(user=account, email="bob.two@example.com")
        email_confirmed.send(sender=None, request=None, email_address=row)
        assert kinds() == []

    def test_granting_records_tier_and_source(self):
        bob = verified_account("bob@example.com")
        FunnelEvent.objects.all().delete()
        licences.grant_individual(bob.person, 2, "manual", None)
        event = FunnelEvent.objects.get()
        assert (event.kind, event.tier, event.source) == (Kind.LICENCE_GRANTED, 2, "manual")

    def test_only_a_real_step_up_is_an_upgrade(self):
        bob = verified_account("bob@example.com")
        lic = licences.grant_individual(bob.person, 1, "purchase", None)
        FunnelEvent.objects.all().delete()
        licences.change_tier(lic, 1)  # saved again, nothing changed
        licences.change_tier(lic, 3)
        licences.change_tier(lic, 2)  # a correction downwards
        event = FunnelEvent.objects.get()
        assert (event.kind, event.tier, event.source) == (Kind.LICENCE_UPGRADED, 3, "purchase")

    def test_a_rolled_back_sign_up_leaves_no_event(self, monkeypatch):
        monkeypatch.setattr(
            EmailAddress.objects, "create", lambda **kw: (_ for _ in ()).throw(RuntimeError)
        )
        with pytest.raises(RuntimeError):
            services.register("bob@example.com", "+919876543210", None, PASSWORD)
        assert FunnelEvent.objects.count() == 0


@pytest.mark.django_db
class TestNoLinkToAPerson:
    def test_the_table_has_no_foreign_key_at_all(self):
        assert not [f for f in FunnelEvent._meta.get_fields() if isinstance(f, ForeignKey)]
        assert not [f for f in FunnelEvent._meta.get_fields() if f.is_relation]

    def test_erasing_an_account_leaves_the_counts_alone(self):
        bob = verified_account("bob@example.com")
        licences.grant_individual(bob.person, 1, "manual", None)
        before = kinds()
        assert before  # sign-up, verified is not recorded by the helper, licence
        erasure.erase_account(bob)
        assert kinds() == before


@pytest.mark.django_db
class TestSummary:
    def test_counts_and_percentages(self):
        for kind, n in [
            (Kind.SIGNED_UP, 100),
            (Kind.EMAIL_VERIFIED, 70),
            (Kind.LICENCE_GRANTED, 20),
            (Kind.SURVEY_STARTED, 10),
        ]:
            for _ in range(n):
                funnel.record_event(kind)
        rows, _ = funnel_rows(FunnelEvent.objects.all())
        by_label = {r["label"]: r for r in rows}
        assert by_label["Signed up"]["count"] == 100
        assert by_label["Signed up"]["of_previous"] is None
        assert by_label["Verified their email"]["of_previous"] == 70
        assert by_label["Got a licence"]["of_previous"] == 29  # 20 of 70
        assert by_label["Got a licence"]["of_signups"] == 20
        assert by_label["Submitted the survey"]["count"] == 0
        assert by_label["Submitted the survey"]["of_previous"] == 0

    def test_an_empty_funnel_has_no_percentages_not_a_crash(self):
        rows, _ = funnel_rows(FunnelEvent.objects.all())
        assert all(r["count"] == 0 for r in rows)
        assert all(r["of_signups"] is None for r in rows)
        assert rows[2]["of_previous"] is None


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def support(client, db):
    account = Account.objects.create_user("support@example.com", PASSWORD)
    account.is_staff = True
    account.save()
    account.groups.add(Group.objects.get(name=GROUP_NAME))
    client.force_login(account)
    return account


URL = "/admin/funnel/funnelevent/"


@pytest.mark.django_db
class TestAdmin:
    def test_the_summary_shows_on_the_page_and_follows_the_filters(self, client, root):
        funnel.record_event(Kind.SIGNED_UP, country="IN")
        funnel.record_event(Kind.SIGNED_UP, country="IN")
        funnel.record_event(Kind.SIGNED_UP, country="US")
        funnel.record_event(Kind.EMAIL_VERIFIED)
        page = client.get(URL).content.decode()
        assert "<strong>3</strong>" in page and "Verified their email" in page
        us = client.get(URL, {"country": "US"}).content.decode()
        assert "<strong>1</strong>" in us and "<strong>3</strong>" not in us

    def test_pages_finished_show_when_there_are_any(self, client, root):
        assert "Pages finished" not in client.get(URL).content.decode()
        funnel.record_event(Kind.PAGE_LOCKED, page=2)
        assert "Pages finished" in client.get(URL).content.decode()

    def test_support_staff_can_read_it_but_not_delete(self, client, support):
        funnel.record_event(Kind.SIGNED_UP)
        assert client.get(URL).status_code == 200
        event = FunnelEvent.objects.get()
        posted = client.post(
            URL, {"action": "delete_selected", "_selected_action": [event.pk], "post": "yes"}
        )
        assert posted.status_code in (200, 302, 403)
        assert FunnelEvent.objects.count() == 1

    def test_superusers_can_delete_events_to_clear_test_noise(self, client, root):
        event = funnel.record_event(Kind.SIGNED_UP)
        response = client.post(
            URL, {"action": "delete_selected", "_selected_action": [event.pk], "post": "yes"}
        )
        assert response.status_code == 302
        assert FunnelEvent.objects.count() == 0

    def test_nobody_can_add_or_edit_an_event(self, client, root):
        event = funnel.record_event(Kind.SIGNED_UP)
        assert client.get(URL + "add/").status_code == 403
        assert client.post(f"{URL}{event.pk}/change/", {"kind": "page_locked"}).status_code == 403
        event.refresh_from_db()
        assert event.kind == Kind.SIGNED_UP

    def test_staff_without_the_group_see_nothing(self, client, db):
        account = Account.objects.create_user("plain@example.com", PASSWORD)
        account.is_staff = True
        account.save()
        client.force_login(account)
        assert client.get(URL).status_code == 403


@pytest.mark.django_db
class TestUnusedLicenceFilter:
    URL = "/admin/entitlements/entitlement/"

    def ids(self, client, value):
        import re

        page = client.get(self.URL, {"unused": value}).content.decode()
        # Only the row checkboxes: the page also echoes the filter value back.
        return {int(n) for n in re.findall(r'name="_selected_action" value="(\d+)"', page)}

    def make(self, email, days_old=0, revoked=False, used=False):
        account = verified_account(email)
        lic = licences.grant_individual(account.person, 1, "manual", None)
        licences.Entitlement.objects.filter(pk=lic.pk).update(
            granted_at=timezone.now() - timedelta(days=days_old)
        )
        if revoked:
            licences.revoke(lic)
        if used:
            Response.objects.create(
                account=account, survey_version=current_version(), entitlement=lic
            )
        return lic

    def test_by_age_and_ignoring_revoked_and_used(self, client, root):
        fresh = self.make("a@example.com", days_old=1)
        week = self.make("b@example.com", days_old=10)
        month = self.make("c@example.com", days_old=40)
        self.make("d@example.com", days_old=40, revoked=True)
        self.make("e@example.com", days_old=40, used=True)
        assert self.ids(client, "any") == {fresh.pk, week.pk, month.pk}
        assert self.ids(client, "7") == {week.pk, month.pk}
        assert self.ids(client, "30") == {month.pk}
