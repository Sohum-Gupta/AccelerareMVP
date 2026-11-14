"""
Milestone 7, PR 5: the command that fills a scratch database for the load check.

It is for a laptop only. The tests hold it to the two things that keep it from
ever filling a database that matters, and run it small to see that what it
makes is what it says.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Account
from apps.enterprises.models import Enterprise, Membership
from apps.entitlements.models import Entitlement
from apps.responses.models import Response

SMALL = {"accounts": 12, "organizations": 2, "responses": 15}


@pytest.mark.django_db
class TestWhereItWillRun:
    def test_never_where_debug_is_off(self, settings):
        """That is the server, and CI."""
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG is on"):
            call_command("make_load_data", any_database=True, **SMALL)
        assert not Account.objects.exists()

    def test_never_in_a_database_that_is_not_named_for_it(self, settings):
        """The database you develop against is not called something_load."""
        settings.DEBUG = True
        with pytest.raises(CommandError, match='ends in "_load"'):
            call_command("make_load_data", **SMALL)
        assert not Account.objects.exists()

    def test_it_asks_for_sensible_numbers(self, settings):
        settings.DEBUG = True
        with pytest.raises(CommandError, match="at least one organization"):
            call_command("make_load_data", any_database=True, accounts=3, organizations=2)


@pytest.mark.django_db
class TestWhatItMakes:
    @pytest.fixture
    def made(self, settings):
        settings.DEBUG = True
        call_command("make_load_data", any_database=True, **SMALL)

    def test_the_numbers_asked_for(self, made):
        assert Account.objects.count() == 12
        assert Enterprise.objects.count() == 2
        assert Response.objects.filter(status="submitted").count() == 15
        assert not Response.objects.filter(status="draft").exists()

    def test_people_in_organizations_and_people_who_are_not(self, made):
        # Four in five of twelve is nine, so four in each of two organizations.
        assert Membership.objects.count() == 8
        assert Membership.objects.filter(role="admin").count() == 2
        assert Account.objects.filter(memberships__isnull=True).count() == 4

    def test_surveys_for_organizations_and_personal_ones(self, made):
        assert Response.objects.filter(membership__isnull=False).count() == 8
        assert Response.objects.filter(membership__isnull=True).count() == 7
        # Every survey used a licence, as on the site.
        assert Entitlement.objects.filter(response__isnull=False).count() == 15

    def test_every_survey_is_answered_in_full_with_answers_that_differ(self, made):
        answers = [response.answers for response in Response.objects.all()]
        count = Response.objects.first().survey_version.questions.count()
        assert all(len(given) == count for given in answers)
        assert len({tuple(sorted(given.items())) for given in answers}) > 1

    def test_everything_is_made_up_and_sends_no_email(self, made):
        from django.core import mail

        assert not Account.objects.exclude(email__endswith="@example.com").exists()
        assert not Account.objects.exclude(full_name__startswith="Load Person ").exists()
        assert mail.outbox == []
