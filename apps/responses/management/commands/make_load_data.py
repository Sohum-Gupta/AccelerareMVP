"""
Fill a scratch database with made-up people, organizations and surveys, to see
whether the pages stay quick (Milestone 7).

"It is fast with my five test rows" says nothing. This makes 500 accounts, ten
organizations and 1,000 submitted surveys the real way, through the same
services the site uses, so the data has the shape real data will have: verified
addresses, memberships, licences from an organization's stock, personal
licences, and every survey answered page by page.

    createdb accelerare_load   (once; see NOTES.md for the exact commands)
    DATABASE_URL=postgres://.../accelerare_load python manage.py migrate
    DATABASE_URL=postgres://.../accelerare_load python manage.py make_load_data

It is for a laptop only, and it is careful about where it writes:

* it refuses unless DEBUG is on, which it never is on the server;
* it refuses unless the database's name ends in "_load", so it cannot fill the
  database you develop against by mistake (`--any-database` overrides that, for
  the tests).

Everything it makes is made up: "Load Person 17" at an example.com address.
It sends no email itself and reaches nothing outside the database. Like the
site, it leaves work in the queue (results, the look for duplicates, the
"you have a licence" emails); `run_worker --once` then does it, and on a
laptop those emails are only printed.
"""

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.accounts import services as accounts
from apps.accounts.models import ContactPoint
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.responses import services as surveys
from apps.survey.models import Question

PASSWORD = "a made-up password for load data"


class Command(BaseCommand):
    help = "Fill a scratch database (name ending in _load) with made-up accounts and surveys."

    def add_arguments(self, parser):
        parser.add_argument("--accounts", type=int, default=500)
        parser.add_argument("--organizations", type=int, default=10)
        parser.add_argument("--responses", type=int, default=1000)
        parser.add_argument(
            "--any-database",
            action="store_true",
            help="Do not insist that the database's name ends in _load.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This only runs where DEBUG is on. It is never run on the server.")
        name = connection.settings_dict["NAME"]
        if not options["any_database"] and not str(name).endswith("_load"):
            raise CommandError(
                f'The database is "{name}". This fills a database with made-up data, so it '
                'only runs against one whose name ends in "_load".'
            )
        people, groups, wanted = options["accounts"], options["organizations"], options["responses"]
        if groups < 1 or people < groups * 2:
            raise CommandError("Ask for at least one organization and two accounts for each.")

        accounts_made = [self._account(number) for number in range(people)]
        self.stdout.write(f"{len(accounts_made)} accounts")

        # The first account of each slice is the organization's admin; four in
        # five of the people belong to one organization.
        members = []
        size = (people * 4 // 5) // groups
        for index in range(groups):
            crowd = accounts_made[index * size : (index + 1) * size]
            enterprise = orgs.create_enterprise(crowd[0], f"Load Organization {index + 1}")
            admin = enterprise.memberships.get()
            orgs.set_seat_pool(enterprise, 2, len(crowd) + 5)
            code = orgs.create_code(admin, len(crowd))
            members.append((admin, admin))
            for account in crowd[1:]:
                members.append((admin, orgs.redeem_code(code.code, account)))
        self.stdout.write(f"{groups} organizations, {len(members)} memberships")

        # Surveys: one for each membership, then personal ones round and round
        # the accounts until there are as many as were asked for.
        submitted = 0
        for admin, membership in members:
            if submitted >= wanted:
                break
            licences.assign_seat(admin, membership, 2)
            self._survey(membership.account, membership)
            submitted += 1
        turn = 0
        while submitted < wanted:
            account = accounts_made[turn % people]
            licences.grant_individual(account.person, 1 + turn % 3, "manual", granted_to=account)
            self._survey(account)
            submitted += 1
            turn += 1
        self.stdout.write(f"{submitted} submitted surveys")
        self.stdout.write(self.style.SUCCESS(f'Done, in the database "{name}".'))

    def _account(self, number):
        """A signed-up account with a verified address, as if the person had followed the link."""
        account = accounts.register(
            f"load.person.{number}@example.com",
            f"+9198765{number:05d}",
            None,
            PASSWORD,
            full_name=f"Load Person {number}",
        )
        ContactPoint.objects.filter(account=account, kind="email").update(
            verified_at=timezone.now()
        )
        EmailAddress.objects.filter(user=account).update(verified=True)
        return account

    def _survey(self, account, membership=None):
        """Take the whole survey the way the Next button does, and submit it."""
        response = surveys.start_response(account, membership)
        response = surveys.save_self_report(response, False)
        pages = {}
        for question in Question.objects.filter(survey_version=response.survey_version):
            answer = 1 + (question.position + account.pk) % 4
            pages.setdefault(surveys.page_of(question.position), {})[question.pk] = answer
        for page in sorted(pages):
            response = surveys.complete_page(response, page, pages[page])
        return surveys.submit(response)
