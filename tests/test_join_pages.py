"""
Milestone 3, PR 10: joining an organization, by code (/join/code/) and by
invite link (/join/invite/<token>/).

The rules these tests hold the pages to:

* Joining tells the truth first. The code or the link opens a page that names
  the organization and says what its admins will be able to see; only its
  button joins. Looking never joins.
* Logged out, the person is asked to log in or sign up, is told nothing about
  the code or the link, and is brought back afterwards. A sign-up that began
  on a join page is recorded in the funnel as "invite" or "code".
* All a join page shows of the organization is its name.

What a code or an invite is good for (the refusals, the people limit, the
locks) is tested with the services, in tests/test_enterprise_services.py and
tests/test_invite_services.py.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts import arrival
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.enterprises.models import Invite, JoinCode, Membership
from apps.funnel.models import FunnelEvent

from .orgs import add_member, locked_tables, new_member, org_with_admin
from .test_enterprise_services import expire, refusal, spend_places
from .test_profile import second_email, verified_account
from .test_signup_login import SIGNUP, signup_data
from .test_tenant_isolation import PHONE_DIGITS, database_objects_given_to
from .test_verification import PASSWORD, fake_request, last_link

CODE = "/join/code/"
LOGIN = "/accounts/login/"
PROFILE = "/accounts/profile/"
ACME = "/organizations/acme/"
CAROL = "carol@example.com"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def carol(client, db):
    """Someone with a verified address and a name, logged in, in no organization."""
    account = verified_account(CAROL)
    Account.objects.filter(pk=account.pk).update(full_name="Carol Example")
    client.force_login(account)
    return account


def code_for(admin, **extra):
    return orgs.create_code(admin, extra.pop("max_uses", 5), **extra)


def invite_for(admin, email=CAROL):
    return orgs.invite_by_email(admin, email)[0]


def link(invite):
    return f"/join/invite/{invite.token}/"


def text_of(page):
    assert page.status_code == 200, page.status_code
    return page.content.decode()


def landed(page):
    """Where a followed form post ended up, and what that page says."""
    assert page.redirect_chain, "the form did not redirect"
    return page.redirect_chain[-1][0], text_of(page)


def log_in(client, email, **extra):
    """Log in through the real page, keeping the session (so a pending join survives)."""
    return client.post(LOGIN + extra.pop("query", ""), {"login": email, "password": PASSWORD})


def members_of(enterprise):
    return set(enterprise.memberships.values_list("account__email", flat=True))


# --- by code -----------------------------------------------------------------------


@pytest.mark.django_db
class TestJoiningByCode:
    def test_the_page_asks_for_the_code(self, client, carol):
        page = text_of(client.get(CODE))
        assert "Join an organization" in page and 'name="code"' in page

    def test_a_code_opens_the_confirmation_and_joins_nobody(self, client, acme, carol):
        code = code_for(acme[1])
        page = text_of(client.post(CODE, {"code": code.code}))
        assert "Join Acme?" in page and "You have not joined yet" in page
        assert members_of(acme[0]) == {acme[1].account.email}
        assert JoinCode.objects.get(pk=code.pk).uses == 0

    @pytest.mark.parametrize("shape", ["{0}-{1}", "{0} {1}", " {0}{1} "])
    def test_the_code_can_be_typed_in_small_letters_with_or_without_the_hyphen(
        self, client, acme, carol, shape
    ):
        code = code_for(acme[1]).code
        typed = shape.format(code[:5], code[5:]).lower()
        assert "Join Acme?" in text_of(client.post(CODE, {"code": typed}))

    def test_the_button_joins_and_lands_on_the_organization(self, client, acme, carol):
        code = code_for(acme[1])
        confirmation = text_of(client.post(CODE, {"code": code.code}))
        assert 'name="confirm"' in confirmation
        shown = orgs.display_code(code.code)
        assert f'name="code" value="{shown}"' in confirmation

        where, page = landed(client.post(CODE, {"code": shown, "confirm": "yes"}, follow=True))

        assert where == ACME and "You have joined Acme." in page
        membership = Membership.objects.get(account=carol)
        assert membership.enterprise == acme[0] and membership.joined_via_code == code
        assert membership.is_active and not membership.is_admin
        assert JoinCode.objects.get(pk=code.pk).uses == 1

    def test_looking_at_the_page_never_joins(self, client, acme, carol):
        code = code_for(acme[1])
        client.get(CODE, {"code": code.code, "confirm": "yes"})
        assert not Membership.objects.filter(account=carol).exists()

    @pytest.mark.parametrize("typed", ["", "ABC", "ABCDE-FGH2", "ABCDE-FGH234", "ABCDE-FGH1O"])
    def test_something_that_cannot_be_a_code_is_asked_for_again(self, client, acme, carol, typed):
        with CaptureQueriesContext(connection) as queries:
            page = text_of(client.post(CODE, {"code": typed}))
        assert "Enter the join code." in page or "A join code is ten letters and digits" in page
        # Its shape alone says so: no code is looked up.
        assert not any("joincode" in query["sql"] for query in queries)

    def test_a_code_that_does_not_exist_is_refused(self, client, acme, carol):
        page = text_of(client.post(CODE, {"code": "ABCDE-FGH23"}))
        assert "That code is not valid. Check it and try again." in page
        assert "Join Acme?" not in page

    def test_each_refusal_is_shown_in_the_services_own_words(self, client, acme, carol):
        admin = acme[1]
        revoked = orgs.revoke_code(code_for(admin))
        expired = code_for(admin)
        expire(expired)
        used_up = code_for(admin, max_uses=1)
        orgs.redeem_code(used_up.code, verified_account("dave@example.com"))
        for code in (revoked, expired, used_up):
            expected = refusal(lambda code=code: orgs.check_code(code.code, carol))
            page = text_of(client.post(CODE, {"code": code.code}))
            assert expected in page and "Join Acme?" not in page
            # Pressing the button anyway (an old page) is refused the same way.
            page = text_of(client.post(CODE, {"code": code.code, "confirm": "yes"}))
            assert expected in page
        assert not Membership.objects.filter(account=carol).exists()

    def test_an_organization_with_no_places_left_is_refused_before_the_confirmation(
        self, client, acme, carol
    ):
        code = code_for(acme[1])
        spend_places(acme[0], acme[0].people_limit)
        page = text_of(client.post(CODE, {"code": code.code}))
        assert "Acme cannot take more people at the moment." in page and "Join Acme?" not in page

    def test_a_deactivated_member_cannot_come_back_with_a_code(self, client, acme, carol):
        add_member(acme[0], carol, active=False)
        page = text_of(client.post(CODE, {"code": code_for(acme[1]).code}))
        assert "Your membership of Acme was deactivated" in page

    def test_someone_who_already_belongs_is_taken_to_the_organization(self, client, acme, carol):
        add_member(acme[0], carol)
        code = code_for(acme[1])
        where, page = landed(client.post(CODE, {"code": code.code}, follow=True))
        assert where == ACME and "You are already a member of Acme." in page
        assert JoinCode.objects.get(pk=code.pk).uses == 0

    def test_a_code_switched_off_while_the_confirmation_is_open_does_not_join(
        self, client, acme, carol
    ):
        code = code_for(acme[1])
        text_of(client.post(CODE, {"code": code.code}))
        orgs.revoke_code(code)
        page = text_of(client.post(CODE, {"code": code.code, "confirm": "yes"}))
        assert "That code has been switched off." in page
        assert not Membership.objects.filter(account=carol).exists()

    def test_a_code_for_one_organization_never_joins_another(self, client, acme, carol):
        globex, globex_admin = org_with_admin("Globex")
        code = code_for(globex_admin)
        page = text_of(client.post(CODE, {"code": code.code}))
        assert "Join Globex?" in page and "Acme" not in page
        client.post(CODE, {"code": code.code, "confirm": "yes"})
        assert CAROL in members_of(globex) and CAROL not in members_of(acme[0])


# --- by invite ---------------------------------------------------------------------


@pytest.mark.django_db
class TestJoiningByInvite:
    def test_the_link_opens_the_confirmation_and_joins_nobody(self, client, acme, carol):
        invite = invite_for(acme[1])
        page = text_of(client.get(link(invite)))
        assert "Join Acme?" in page and "You have been invited to join" in page
        assert not Membership.objects.filter(account=carol).exists()
        assert Invite.objects.get(pk=invite.pk).accepted_at is None

    def test_the_button_joins_and_lands_on_the_organization(self, client, acme, carol):
        invite = invite_for(acme[1])
        where, page = landed(client.post(link(invite), follow=True))
        assert where == ACME and "You have joined Acme." in page
        membership = Membership.objects.get(account=carol)
        assert membership.enterprise == acme[0] and membership.joined_via_invite == invite
        assert Invite.objects.get(pk=invite.pk).accepted_at is not None

    def test_another_account_is_told_which_address_and_sent_to_its_profile(
        self, client, acme, carol
    ):
        invite = invite_for(acme[1], "carol@work.example.com")
        for page in (client.get(link(invite)), client.post(link(invite))):
            page = text_of(page)
            assert "This invite cannot be used" in page
            assert "This invite was sent to carol@work.example.com." in page
            assert f'href="{PROFILE}"' in page and "Join Acme?" not in page
        assert not Membership.objects.filter(account=carol).exists()

    def test_it_works_once_the_address_is_added_and_verified(self, client, acme, carol):
        invite = invite_for(acme[1], "carol@work.example.com")
        second_email(carol, "carol@work.example.com")
        assert "Join Acme?" in text_of(client.get(link(invite)))

    def test_each_refusal_is_shown_in_the_services_own_words(self, client, acme, carol):
        admin = acme[1]
        revoked = orgs.revoke_invite(invite_for(admin))
        expired = invite_for(admin)
        expire(expired)
        used = invite_for(admin, "dave@example.com")
        orgs.accept_invite(used.token, verified_account("dave@example.com"))
        for token in (revoked.token, expired.token, used.token, "no-such-invite"):
            expected = refusal(lambda token=token: orgs.check_invite(token, carol))
            for page in (
                client.get(f"/join/invite/{token}/"),
                client.post(f"/join/invite/{token}/"),
            ):
                page = text_of(page)
                assert "This invite cannot be used" in page and expected in page
                assert f'href="{PROFILE}"' not in page.split("<main")[1]
        assert not Membership.objects.filter(account=carol).exists()

    def test_someone_who_already_belongs_is_taken_to_the_organization(self, client, acme, carol):
        add_member(acme[0], carol)
        invite = invite_for(acme[1], "carol@work.example.com")
        where, page = landed(client.get(link(invite), follow=True))
        assert where == ACME and "You are already a member of Acme." in page
        assert Invite.objects.get(pk=invite.pk).accepted_at is None

    def test_it_brings_a_deactivated_member_back(self, client, acme, carol):
        add_member(acme[0], carol, active=False)
        invite = invite_for(acme[1])
        assert "Join Acme?" in text_of(client.get(link(invite)))
        where, _page = landed(client.post(link(invite), follow=True))
        assert where == ACME and Membership.objects.get(account=carol).is_active

    def test_an_invite_withdrawn_while_the_confirmation_is_open_does_not_join(
        self, client, acme, carol
    ):
        invite = invite_for(acme[1])
        text_of(client.get(link(invite)))
        orgs.revoke_invite(invite)
        assert "That invite has been withdrawn." in text_of(client.post(link(invite)))
        assert not Membership.objects.filter(account=carol).exists()


# --- the confirmation tells the truth ----------------------------------------------


def bullets(template, heading):
    """The list items under one heading of a template, as plain lines."""
    source = (Path(settings.BASE_DIR) / "templates" / template).read_text()
    section = source.split(heading, 1)[1].split("</ul>", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip().startswith("<li>")]


@pytest.mark.django_db
class TestTheConfirmation:
    def test_a_code_join_says_admins_will_see_the_login_address(self, client, acme, carol):
        second_email(carol, "carol@work.example.com")
        page = text_of(client.post(CODE, {"code": code_for(acme[1]).code}))
        assert f"{CAROL}</strong> (the address you log in with)" in page
        assert "carol@work.example.com" not in page

    def test_an_invite_join_says_admins_will_see_the_invited_address(self, client, acme, carol):
        second_email(carol, "carol@work.example.com")
        invite = invite_for(acme[1], "carol@work.example.com")
        page = text_of(client.get(link(invite))).split("<main")[1]
        assert "carol@work.example.com</strong> (the address the invite was sent to)" in page
        assert CAROL not in page

    def test_that_is_the_address_the_members_page_then_shows(self, client, acme, carol):
        second_email(carol, "carol@work.example.com")
        client.post(link(invite_for(acme[1], "carol@work.example.com")))
        client.force_login(acme[1].account)
        members = text_of(client.get(ACME + "members/")).split("<main")[1]
        assert "carol@work.example.com" in members and CAROL not in members

    def test_it_names_the_person_as_admins_will_see_them(self, client, acme, carol):
        page = text_of(client.get(link(invite_for(acme[1]))))
        assert "your name: <strong>Carol Example</strong>" in page
        Account.objects.filter(pk=carol.pk).update(full_name="")
        page = text_of(client.post(CODE, {"code": code_for(acme[1]).code}))
        assert "you have not added one yet" in page

    def test_it_says_what_admins_see_and_never_see(self, client, acme, carol):
        page = text_of(client.get(link(invite_for(acme[1]))))
        for said in (
            "the date you joined",
            "whether you have a licence to take the survey for Acme",
            "whether it is in progress or submitted",
            "the dates you started and submitted it",
            "a mark if it looks as though you have taken the survey before",
            "your results for that survey, once results are available",
            "your phone number",
            "your answers to the survey",
            "how far through a survey you are",
            "any survey you take personally, or for another organization",
            "Members who are not admins see nothing about you.",
            "does not by itself give you a licence",
        ):
            assert said in page, said

    def test_it_lists_what_the_survey_disclosure_lists(self):
        """Two pages make the same promise; a change to one must reach the other."""
        ours = bullets("enterprises/join_confirm.html", 'id="about-survey"')
        theirs = bullets("responses/disclosure.html", "can see:</p>")
        assert len(ours) == len(theirs) == 4
        assert ours[:3] == theirs[:3]
        # The last differs by one word: "this survey" there, "that survey" here.
        assert ours[3].replace("that survey", "this survey") == theirs[3]

    def test_it_shows_the_organizations_name_and_nothing_else_of_it(self, client, acme, carol):
        admin = acme[1]
        Account.objects.filter(pk=admin.account.pk).update(full_name="Alice Admin")
        member = new_member(acme[0], "dave@example.com")
        Account.objects.filter(pk=member.account.pk).update(full_name="Dave Member")
        pages = [
            client.get(link(invite_for(admin))),
            client.post(CODE, {"code": code_for(admin).code}),
        ]
        for page in pages:
            assert database_objects_given_to(page) == []
            assert page.context["organization_name"] == "Acme"
            body = text_of(page).split("<main")[1]
            for hidden in ("Alice Admin", admin.account.email, "Dave Member", "dave@example.com"):
                assert hidden not in body
            assert "places left" not in body and PHONE_DIGITS not in body

    def test_the_checks_write_nothing_and_lock_nothing(self, acme, carol):
        code, invite = code_for(acme[1]), invite_for(acme[1])
        with CaptureQueriesContext(connection) as queries:
            assert orgs.check_code(code.code, carol) == code
            assert orgs.check_invite(invite.token, carol) == invite
        assert locked_tables(queries) == set()
        assert all(query["sql"].startswith("SELECT") for query in queries)


# --- logged out --------------------------------------------------------------------


@pytest.mark.django_db
class TestLoggedOut:
    def test_an_invite_link_asks_them_to_log_in_or_sign_up(self, client, acme):
        page = text_of(client.get(link(invite_for(acme[1]))))
        assert "You have been invited to join an organization" in page
        assert 'href="/accounts/signup/"' in page and f'href="{LOGIN}"' in page

    def test_it_says_nothing_about_the_invite_not_even_that_it_is_real(self, client, acme):
        real = text_of(client.get(link(invite_for(acme[1])))).split("<main")[1]
        unreal = text_of(client.get("/join/invite/no-such-invite/")).split("<main")[1]
        assert real == unreal
        assert "Acme" not in real and CAROL not in real

    def test_a_code_is_kept_but_not_checked(self, client, acme):
        code = code_for(acme[1])
        with CaptureQueriesContext(connection) as queries:
            real = text_of(client.post(CODE, {"code": code.code}))
        assert not any("joincode" in query["sql"] for query in queries)
        assert "Log in to use your join code" in real and "Acme" not in real
        unreal = text_of(client.post(CODE, {"code": "ABCDE-FGH23"}))
        assert real.split("<main")[1] == unreal.split("<main")[1]

    def test_the_button_does_nothing_for_someone_logged_out(self, client, acme):
        code, invite = code_for(acme[1]), invite_for(acme[1])
        client.post(CODE, {"code": code.code, "confirm": "yes"})
        client.post(link(invite))
        assert members_of(acme[0]) == {acme[1].account.email}

    def test_logging_in_brings_them_back_to_the_invite_once(self, client, acme):
        verified_account(CAROL)
        invite = invite_for(acme[1])
        client.get(link(invite))

        response = log_in(client, CAROL)
        assert response.status_code == 302 and response.url == link(invite)
        assert "Join Acme?" in text_of(client.get(response.url))

        # The note is used up: the next login goes to the profile as usual.
        client.post("/accounts/logout/")
        assert log_in(client, CAROL).url == PROFILE

    def test_logging_in_brings_them_back_to_the_code_they_typed(self, client, acme):
        verified_account(CAROL)
        code = code_for(acme[1])
        client.post(CODE, {"code": code.code})

        response = log_in(client, CAROL)
        assert response.url == CODE
        page = text_of(client.get(CODE))
        assert "Join Acme?" in page and orgs.display_code(code.code) in page
        # Picked up once: the page is the empty form again afterwards.
        assert "Join Acme?" not in text_of(client.get(CODE))

    def test_a_kept_code_that_turns_out_wrong_is_shown_with_the_reason(self, client, acme):
        verified_account(CAROL)
        client.post(CODE, {"code": "ABCDE-FGH23"})
        log_in(client, CAROL)
        page = text_of(client.get(CODE))
        assert "That code is not valid." in page and 'value="ABCDEFGH23"' in page

    def test_an_address_the_login_page_was_given_still_wins(self, client, acme):
        verified_account(CAROL)
        client.get(link(invite_for(acme[1])))
        assert log_in(client, CAROL, query="?next=/survey/").url == "/survey/"

    def test_without_the_note_login_goes_to_the_profile_and_the_link_still_works(
        self, client, acme
    ):
        """The verification email was opened on another device: no session, no note."""
        verified_account(CAROL)
        invite = invite_for(acme[1])
        assert log_in(client, CAROL).url == PROFILE
        assert "Join Acme?" in text_of(client.get(link(invite)))

    def test_sign_up_verify_log_in_and_join_in_one_browser(self, client, acme):
        invite = invite_for(acme[1])
        client.get(link(invite))
        client.post(SIGNUP, signup_data(email=CAROL))
        client.post(last_link())

        response = log_in(client, CAROL)
        assert response.url == link(invite)
        assert "Join Acme?" in text_of(client.get(response.url))
        where, page = landed(client.post(response.url, follow=True))
        assert where == ACME and "You have joined Acme." in page
        assert CAROL in members_of(acme[0])


# --- the funnel --------------------------------------------------------------------


def signed_up_by():
    events = FunnelEvent.objects.filter(kind="signed_up").order_by("id")
    return list(events.values_list("channel", flat=True))


@pytest.mark.django_db
class TestTheSignUpChannel:
    def test_a_sign_up_that_began_at_an_invite_link_is_recorded_as_invite(self, client, acme):
        client.get(link(invite_for(acme[1])))
        before = signed_up_by()
        client.post(SIGNUP, signup_data(email=CAROL))
        assert signed_up_by() == [*before, "invite"]

    def test_a_sign_up_that_began_with_a_join_code_is_recorded_as_code(self, client, acme):
        client.post(CODE, {"code": code_for(acme[1]).code})
        before = signed_up_by()
        client.post(SIGNUP, signup_data(email=CAROL))
        assert signed_up_by() == [*before, "code"]

    def test_any_other_sign_up_is_direct(self, client, db):
        client.post(SIGNUP, signup_data(email=CAROL))
        assert signed_up_by() == ["direct"]

    def test_the_event_still_points_at_nobody(self, client, acme):
        client.get(link(invite_for(acme[1])))
        client.post(SIGNUP, signup_data(email=CAROL))
        event = FunnelEvent.objects.filter(kind="signed_up").latest("id")
        fields = {field.name for field in FunnelEvent._meta.get_fields()}
        assert fields == {
            "id",
            "kind",
            "occurred_at",
            "country",
            "channel",
            "tier",
            "source",
            "page",
        }
        assert event.channel == "invite" and event.source == ""


class TestTheArrivalNote:
    def test_no_note_means_direct_and_nowhere_to_go_back_to(self):
        request = fake_request()
        assert arrival.channel(request) == "direct" and arrival.take_next(request) is None

    def test_the_way_back_is_handed_out_once(self):
        request = fake_request()
        arrival.remember(request, "code", CODE)
        assert arrival.channel(request) == "code"
        assert arrival.take_next(request) == CODE
        assert arrival.take_next(request) is None and arrival.channel(request) == "direct"

    def test_only_the_two_channels_are_accepted(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            arrival.remember(fake_request(), "direct", CODE)

    @pytest.mark.parametrize("elsewhere", ["https://example.com/", "//example.com/", "join/code/"])
    def test_an_address_off_this_site_is_never_followed(self, elsewhere):
        request = fake_request()
        arrival.remember(request, "invite", elsewhere)
        assert arrival.take_next(request) is None

    def test_forgetting_drops_it(self):
        request = fake_request()
        arrival.remember(request, "invite", "/join/invite/abc/")
        arrival.forget(request)
        assert arrival.channel(request) == "direct"


# --- the ways in are signposted ----------------------------------------------------


@pytest.mark.django_db
class TestSignposts:
    def test_the_organizations_page_offers_the_join_code_page(self, client, carol):
        page = text_of(client.get("/organizations/"))
        assert "Have a join code?" in page and f'href="{CODE}"' in page

    def test_the_admins_codes_page_says_where_a_code_is_entered(self, client, acme):
        client.force_login(acme[1].account)
        page = text_of(client.get(ACME + "codes/"))
        assert "http://testserver/join/code/" in page

    def test_the_invite_email_links_to_a_page_that_exists(self, client, acme):
        orgs.invite_by_email(acme[1], CAROL, request=fake_request())
        address = "/join/invite/" + mail.outbox[-1].body.split("/join/invite/")[1].split()[0]
        assert "You have been invited to join an organization" in text_of(client.get(address))
