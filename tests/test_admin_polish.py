"""
Milestone 6, PR 5: finding things in the Django admin.

Staff follow a thread: from a membership to the account, from the account to
its surveys, from a survey to its organization. This PR makes the columns of
the lists links, adds a "Related" line to the pages of an account, an
organization and a membership, and adds the searches and filters that were
missing.

The world: Acme, with its admin and a member, Bob, who joined by invite, holds
a licence from Acme's stock (which Acme bought) and has submitted a survey for
Acme. Ann took a survey personally. Ann and Bob are a possible duplicate.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import re
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.urls import reverse

from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.jobs.models import Job
from apps.matching.models import MatchCandidate
from apps.payments import services as buying
from apps.responses.models import Response
from apps.survey.services import current_version

from . import payments
from .orgs import add_member, org_with_admin
from .test_matching import give, take
from .test_staff_export import named
from .test_support_staff_admin import root, support  # noqa: F401
from .test_verification import fake_request

# The lists that both a superuser and Support staff may open.
SHARED_LISTS = [
    "accounts_account",
    "accounts_person",
    "accounts_contactpoint",
    "enterprises_enterprise",
    "enterprises_membership",
    "enterprises_invite",
    "enterprises_joincode",
    "entitlements_entitlement",
    "payments_purchase",
    "responses_response",
    "jobs_job",
]
# For superusers only.
SUPERUSER_LISTS = ["matching_matchcandidate", "audit_auditlog"]


def changelist(page):
    return reverse(f"admin:{page}_changelist")


def change(obj):
    return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])


@pytest.fixture
def world(db, monkeypatch, settings):
    stripe = payments.install(monkeypatch, settings)
    enterprise, admin_membership = org_with_admin("Acme")
    buying.start_stock(admin_membership, 2, 3, request=fake_request())
    purchase = buying.fulfil(stripe.pay())

    invite, _sent = orgs.invite_by_email(admin_membership, "bob@example.com")
    bob = named("bob@example.com", "Bob Example")
    membership = add_member(enterprise, bob, joined_via_invite=invite)
    seat = licences.assign_seat(admin_membership, membership, 2)
    survey = take(bob, membership)
    code = orgs.create_code(admin_membership, 5)

    ann = named("ann@example.com", "Ann Example")
    personal_licence = give(ann, 1)
    personal = take(ann)
    first, second = sorted([ann.pk, bob.pk])
    pair = MatchCandidate.objects.create(account_a_id=first, account_b_id=second, signals={})
    Job.objects.create(kind="test_job")
    return SimpleNamespace(
        stripe=stripe,
        enterprise=enterprise,
        admin=admin_membership,
        purchase=purchase,
        invite=invite,
        code=code,
        bob=bob,
        membership=membership,
        seat=seat,
        survey=survey,
        ann=ann,
        personal_licence=personal_licence,
        personal=personal,
        pair=pair,
    )


def links_in(text, inside):
    """Every admin address linked from one part of a page (the list's table, or one field)."""
    part = text.split(inside)[1].split("</table>" if "result_list" in inside else "</div>")[0]
    found = re.findall(r'href="(/admin/[^"]*)"', part)
    return [address.replace("&amp;", "&") for address in found]


def row_of(client, page, obj):
    """The list's row for one object, as text."""
    text = client.get(changelist(page)).content.decode()
    table = text.split('id="result_list"')[1].split("</table>")[0]
    return next(
        row
        for row in table.split("<tr")[1:]
        if f'value="{obj.pk}"' in row or f"/{obj.pk}/change/" in row
    )


@pytest.mark.django_db
class TestEveryLinkInEveryListCanBeFollowed:
    def follow_all(self, client, pages):
        followed = 0
        for page in pages:
            answer = client.get(changelist(page))
            assert answer.status_code == 200, page
            for address in set(links_in(answer.content.decode(), 'id="result_list"')):
                assert client.get(address).status_code == 200, f"{page} links to {address}"
                followed += 1
        return followed

    def test_by_a_superuser(self, client, world, root):
        assert self.follow_all(client, SHARED_LISTS + SUPERUSER_LISTS) > 30

    def test_by_support_staff(self, client, world, support):
        """No list shows Support staff a link that answers "forbidden"."""
        client.force_login(support)
        assert self.follow_all(client, SHARED_LISTS) > 25
        for page in SUPERUSER_LISTS:
            assert client.get(changelist(page)).status_code == 403


@pytest.mark.django_db
class TestColumnsAreLinks:
    def test_a_membership_links_to_its_account_and_its_organization(self, client, world, root):
        row = row_of(client, "enterprises_membership", world.membership)
        assert f'<a href="{change(world.bob)}">bob@example.com</a>' in row
        assert f'<a href="{change(world.enterprise)}">Acme</a>' in row

    def test_an_invite_and_a_join_code_link_to_their_organization(self, client, world, root):
        for page, obj in (
            ("enterprises_invite", world.invite),
            ("enterprises_joincode", world.code),
        ):
            assert f'<a href="{change(world.enterprise)}">Acme</a>' in row_of(client, page, obj)

    def test_a_contact_links_to_its_account(self, client, world, root):
        contact = world.bob.contact_points.first()
        row = row_of(client, "accounts_contactpoint", contact)
        assert f'<a href="{change(world.bob)}">bob@example.com</a>' in row

    def test_a_licence_links_to_who_can_use_it_and_to_its_organization(self, client, world, root):
        seat = row_of(client, "entitlements_entitlement", world.seat)
        assert f'<a href="{change(world.bob)}">bob@example.com</a>' in seat
        assert f'<a href="{change(world.enterprise)}">Acme</a>' in seat
        personal = row_of(client, "entitlements_entitlement", world.personal_licence)
        assert f'<a href="{change(world.ann)}">ann@example.com</a>' in personal
        assert "Personal" in personal

    def test_a_response_links_to_its_account_and_its_organization(self, client, world, root):
        row = row_of(client, "responses_response", world.survey)
        assert f'<a href="{change(world.bob)}">bob@example.com</a>' in row
        assert f'<a href="{change(world.enterprise)}">Acme</a>' in row
        assert "Personal" in row_of(client, "responses_response", world.personal)

    def test_a_payment_links_to_who_bought_it_and_for_which_organization(self, client, world, root):
        row = row_of(client, "payments_purchase", world.purchase)
        assert f'<a href="{change(world.admin.account)}">{world.admin.account.email}</a>' in row
        assert f'<a href="{change(world.enterprise)}">Acme</a>' in row

    def test_a_possible_duplicate_links_to_both_accounts_by_number_only(self, client, world, root):
        row = row_of(client, "matching_matchcandidate", world.pair)
        for account in (world.ann, world.bob):
            assert f'<a href="{change(account)}">Account #{account.pk}</a>' in row
        assert "@" not in row and "Example" not in row

    def test_a_name_that_is_markup_is_shown_as_text(self, client, world, root):
        """A person types their own email and an admin an organization's name."""
        type(world.enterprise).objects.filter(pk=world.enterprise.pk).update(name="<b>Acme</b>")
        row = row_of(client, "enterprises_membership", world.membership)
        assert "&lt;b&gt;Acme&lt;/b&gt;" in row and "<b>Acme</b>" not in row


@pytest.mark.django_db
class TestRelatedLines:
    def related(self, client, obj):
        """The "Related" line of an object's page: {words: address}."""
        text = client.get(change(obj)).content.decode()
        field = text.split("field-related")[1].split("</div>\n")[0]
        found = re.findall(r'<a href="([^"]*)">([^<]*)</a>', field)
        return {words: address.replace("&amp;", "&") for address, words in found}

    def rows(self, client, address):
        page = client.get(address)
        assert page.status_code == 200, address
        return page.context["cl"].result_count

    def test_an_account(self, client, world, root):
        lines = self.related(client, world.bob)
        assert list(lines) == [
            "Memberships (1)",
            "Personal licences (0)",
            "Surveys (1)",
            "Payments",
        ]
        assert self.rows(client, lines["Memberships (1)"]) == 1
        assert self.rows(client, lines["Personal licences (0)"]) == 0
        assert self.rows(client, lines["Surveys (1)"]) == 1
        assert self.rows(client, lines["Payments"]) == 0

    def test_an_account_with_personal_things_and_a_payment(self, client, world, root):
        ann = self.related(client, world.ann)
        assert list(ann)[:3] == ["Memberships (0)", "Personal licences (1)", "Surveys (1)"]
        assert self.rows(client, ann["Personal licences (1)"]) == 1
        buyer = self.related(client, world.admin.account)
        assert self.rows(client, buyer["Payments"]) == 1

    def test_an_organization(self, client, world, root):
        """With a second organization that has one of everything, to tell the lists apart."""
        _globex, globex_admin = org_with_admin("Globex")
        orgs.invite_by_email(globex_admin, "someone@example.com")
        orgs.create_code(globex_admin, 5)
        orgs.create_code(globex_admin, 5)
        lines = self.related(client, world.enterprise)
        assert list(lines) == ["Memberships (2)", "Invites (1)", "Join codes (1)", "Payments (1)"]
        for words, address in lines.items():
            assert self.rows(client, address) == int(words.split("(")[1].rstrip(")")), words
        pages = ["enterprises_membership", "enterprises_invite", "enterprises_joincode"]
        for address, page in zip(lines.values(), [*pages, "payments_purchase"], strict=True):
            assert address.startswith(changelist(page) + "?"), address

    def test_a_membership(self, client, world, root):
        lines = self.related(client, world.membership)
        assert list(lines) == ["Licences (1)", "Surveys (1)"]
        for address in lines.values():
            assert self.rows(client, address) == 1

    def test_the_lists_they_open_hold_only_that_ones_things(self, client, world, root):
        """Bob's surveys are Bob's: Ann's personal one is not in the list."""
        address = self.related(client, world.bob)["Surveys (1)"]
        shown = client.get(address).context["cl"].result_list
        assert [response.pk for response in shown] == [world.survey.pk]

    def test_support_staff_see_them_and_can_follow_them(self, client, world, support):
        client.force_login(support)
        for obj in (world.bob, world.enterprise, world.membership):
            for words, address in self.related(client, obj).items():
                assert client.get(address).status_code == 200, words

    def test_an_erased_account_still_has_its_line(self, client, world, root):
        from apps.accounts import erasure

        erasure.erase_account(world.bob, by=root)
        assert "Surveys (1)" in self.related(client, Account.objects.get(pk=world.bob.pk))


@pytest.mark.django_db
class TestALicencesPage:
    def test_it_says_which_survey_was_taken_on_it(self, client, world, root):
        text = client.get(change(world.seat)).content.decode()
        assert f'<a href="{change(world.survey)}">' in text

    def test_or_that_it_is_not_used_yet(self, client, world, root):
        unused = give(world.ann, 2)
        assert "Not used yet" in client.get(change(unused)).content.decode()

    def test_a_personal_one_says_which_login_it_was_granted_to(self, client, world, root):
        text = client.get(change(world.personal_licence)).content.decode()
        assert "field-granted_to" in text
        assert "field-granted_to" not in client.get(change(world.seat)).content.decode()


@pytest.mark.django_db
class TestSearch:
    def found(self, client, page, term):
        answer = client.get(changelist(page), {"q": term})
        assert answer.status_code == 200, f"{page} ?q={term}"
        return [obj.pk for obj in answer.context["cl"].result_list]

    def test_responses_by_who_took_it_or_for_whom(self, client, world, root):
        # A name that is not also in the email address.
        Account.objects.filter(pk=world.bob.pk).update(full_name="Robert Quill")
        for term in ("bob@example.com", "Quill", "Acme"):
            assert self.found(client, "responses_response", term) == [world.survey.pk], term
        # A number is looked for among account numbers and among response numbers.
        assert world.survey.pk in self.found(client, "responses_response", str(world.bob.pk))
        Response.objects.filter(pk=world.personal.pk).update(id=987654)
        assert self.found(client, "responses_response", "987654") == [987654]
        Response.objects.filter(pk=987654).update(id=world.personal.pk)
        assert self.found(client, "responses_response", "ann@example.com") == [world.personal.pk]
        assert self.found(client, "responses_response", "nobody at all") == []

    def test_responses_are_never_found_by_an_answer(self, client, world, root):
        Response.objects.filter(pk=world.survey.pk).update(
            answers={"1": 4}, took_before=True, took_before_via="company"
        )
        assert self.found(client, "responses_response", "company") == []

    def test_payments_by_who_bought(self, client, world, root):
        email = world.admin.account.email
        assert self.found(client, "payments_purchase", email) == [world.purchase.pk]
        assert self.found(client, "payments_purchase", "bob@example.com") == []

    def test_memberships_by_phone(self, client, world, root):
        phone = world.bob.contact_points.get(kind="phone").value_normalised
        assert world.membership.pk in self.found(client, "enterprises_membership", phone)

    def test_background_jobs_by_kind(self, client, world, root):
        assert len(self.found(client, "jobs_job", "test_job")) == 1
        assert self.found(client, "jobs_job", "no_such_kind") == []


@pytest.mark.django_db
class TestFilters:
    def count(self, client, page, **query):
        answer = client.get(changelist(page), query)
        assert answer.status_code == 200, query
        return answer.context["cl"].result_count

    def test_responses_by_who_they_were_taken_for(self, client, world, root):
        give(world.ann, 1)
        take(world.ann)  # a second personal survey, so the two answers differ
        assert self.count(client, "responses_response", taken_for="personal") == 2
        assert self.count(client, "responses_response", taken_for="organization") == 1
        assert self.count(client, "responses_response", taken_for="nonsense") == 3

    def test_people_by_whether_they_were_folded_into_another(self, client, world, root):
        everyone = self.count(client, "accounts_person")
        assert self.count(client, "accounts_person", merged_into__isempty=1) == everyone
        assert self.count(client, "accounts_person", merged_into__isempty=0) == 0

    @pytest.mark.parametrize(
        "page", ["enterprises_enterprise", "enterprises_invite", "enterprises_joincode"]
    )
    def test_organizations_invites_and_join_codes_by_date(self, client, world, root, page):
        text = client.get(changelist(page)).content.decode()
        assert "By created at" in text and "Past 7 days" in text


@pytest.mark.django_db
class TestTheLinkHelpers:
    def test_nothing_to_link_to_is_a_dash(self):
        from apps.accounts.admin_links import link

        assert link(None) == "-"

    def test_a_personal_payment_has_no_organization(self, client, world, root):
        buying.start_personal(world.ann, 2, request=fake_request())
        bought = buying.fulfil(world.stripe.pay())
        row = row_of(client, "payments_purchase", bought)
        assert f'<a href="{change(world.ann)}">ann@example.com</a>' in row
        assert "Acme" not in row


@pytest.mark.django_db
def test_the_wording_page_has_the_breadcrumbs_django_now_styles(client, root):
    version = current_version()
    address = reverse("admin:survey_surveyversion_load_wording", args=[version.pk])
    text = client.get(address).content.decode()
    assert '<ol class="breadcrumbs">' in text and '<div class="breadcrumbs">' not in text


@pytest.mark.django_db
def test_no_custom_admin_page_uses_the_breadcrumbs_django_no_longer_styles(settings):
    """Django 6.1 styles `<ol class="breadcrumbs">` only (NOTES.md, 2026-11-13)."""
    for template in (settings.BASE_DIR / "templates" / "admin").rglob("*.html"):
        assert '<div class="breadcrumbs">' not in template.read_text(), template.name


def test_every_model_has_an_admin_page_or_is_on_another_ones():
    """
    A new model with no admin page fails here, so somebody decides where staff
    will find it. An organization's stock is set on a page of the organization,
    and a refund is listed on the page of its payment.
    """
    from django.apps import apps

    missing = [
        model._meta.label
        for model in apps.get_models()
        if model.__module__.startswith("apps.") and not admin.site.is_registered(model)
    ]
    assert sorted(missing) == ["enterprises.SeatPool", "payments.Refund"]
