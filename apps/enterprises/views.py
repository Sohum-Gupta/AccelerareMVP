"""
The organization pages, under /organizations/, and the two pages for joining
one, under /join/. Thin views: read the form, call a service, show the result.

Who sees what (the founder's rules of 2026-11-12):

* A member sees the organization's name and their own surveys. Never other
  members.
* An admin also sees the members: name, email, role, status, joined date and
  licence tier. Never a phone number, and never anything about a survey someone
  took personally.
* An admin brings people in with join codes and email invites, and sees how
  many places the organization has left. An invite or a code can carry a tier:
  its licences are set aside out of the stock when it is made, and whoever
  joins with it is given one.

How that is kept true:

* Every page about one organization starts with scoping.for_member or
  scoping.for_admin. The slug in the address only says which organization is
  meant; what comes back is this account's own active membership, or a 404.
  From then on `membership.enterprise` is the only organization any query uses.
* An id in an address (a membership to deactivate, a code or an invite to
  revoke) is looked up inside that organization, so another organization's id
  is a 404 too.
* The templates are given plain values (a name, a date, a tier), never a
  database object, so no later template edit can print a phone number or an
  answer by accident. tests/test_tenant_isolation.py checks all of this.

Licences are read through `membership.entitlements`, the reverse relation:
this app never imports the entitlements or responses apps (see models.py).

The join pages are the exception to the scoping rule, because the person is
not a member yet: see the notes above them at the bottom of this file.
"""

from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts import arrival
from apps.accounts.decorators import verified_email_required

from . import scoping, services
from .forms import EnterpriseForm, InviteForm, JoinCodeForm, JoinForm
from .models import Invite, JoinCode, Membership
from .shown import member_email, member_name
from .shown import organization as _organization


def _tiers_left(enterprise):
    """{tier: how many licences of it can still be given or promised}, for the two forms."""
    return {line["tier"]: line["left"] for line in services.seat_summary(enterprise)}


def _stock_lines(enterprise):
    """The stock lines a page shows: only the tiers the organization has bought or holds."""
    return [
        line
        for line in services.seat_summary(enterprise)
        if line["bought"] or line["given"] or line["set_aside"]
    ]


def _places(enterprise):
    """How many more people the organization may bring in, out of its limit (admins only)."""
    return {"left": services.places_left(enterprise), "limit": services.people_limit(enterprise)}


# --- the account's organizations, and creating one -----------------------------


@never_cache
@verified_email_required
def organizations(request):
    """The organizations this account is an active member of, with a way to create one."""
    memberships = (
        Membership.objects.filter(account=request.user, status=Membership.Status.ACTIVE)
        .select_related("enterprise")
        .order_by("enterprise__name", "id")
    )
    rows = [{**_organization(m), "is_admin": m.is_admin} for m in memberships]
    return render(request, "enterprises/list.html", {"rows": rows})


@verified_email_required
def new(request):
    """Create an organization. Whoever creates it becomes its first admin."""
    form = EnterpriseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            enterprise = services.create_enterprise(request.user, form.cleaned_data["name"])
        except services.Refused as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"{enterprise.name} has been created. You are its admin.")
            return redirect("enterprises:dashboard", enterprise.slug)
    return render(request, "enterprises/new.html", {"form": form})


# --- one organization ------------------------------------------------------------


@never_cache
@verified_email_required
def dashboard(request, slug):
    """
    The organization's front page. A member gets its name and the way to their
    own surveys. An admin also gets two counts: the people who are members now,
    and everyone who has ever been one (including those since deactivated or
    erased), how many places are left, the stock of licences (only the tiers
    the organization has bought or holds), and the way to the admin pages.
    """
    membership = scoping.for_member(request, slug)
    context = {"organization": _organization(membership), "is_admin": membership.is_admin}
    if membership.is_admin:
        everyone = membership.enterprise.memberships
        context["current_members"] = everyone.filter(status=Membership.Status.ACTIVE).count()
        context["all_time_members"] = everyone.count()
        context["places"] = _places(membership.enterprise)
        context["stock"] = _stock_lines(membership.enterprise)
    return render(request, "enterprises/dashboard.html", context)


def _member_row(person, viewer, admin_count):
    """What an admin may see about one member. Plain values only; never the phone."""
    # Only licences for this organization hang off the membership; a personal
    # licence belongs to the person and is not reachable from here.
    tiers = [licence.tier for licence in person.entitlements.all() if licence.revoked_at is None]
    return {
        "id": person.pk,
        "name": member_name(person.account),
        "email": member_email(person),
        "erased": person.account.anonymised_at is not None,
        "is_admin": person.is_admin,
        "active": person.is_active,
        "joined_at": person.joined_at,
        "deactivated_at": person.deactivated_at,
        # The highest licence that still counts, or None.
        "tier": max(tiers, default=None),
        "is_you": person.pk == viewer.pk,
        # The last active admin can be neither demoted nor deactivated.
        "only_admin": person.is_active and person.is_admin and admin_count == 1,
    }


@never_cache
@verified_email_required
def members(request, slug):
    """Everyone who is or was a member of the admin's organization: active first."""
    membership = scoping.for_admin(request, slug)
    people = list(
        membership.enterprise.memberships.select_related(
            "account", "joined_via_invite"
        ).prefetch_related("entitlements")
    )
    admin_count = sum(1 for person in people if person.is_active and person.is_admin)
    people.sort(key=lambda person: (not person.is_active, person.joined_at, person.pk))
    context = {
        "organization": _organization(membership),
        "rows": [_member_row(person, membership, admin_count) for person in people],
        "current_members": sum(1 for person in people if person.is_active),
        "all_time_members": len(people),
    }
    return render(request, "enterprises/members.html", context)


# --- acting on a member ----------------------------------------------------------


def _their_member(membership, pk):
    """
    The membership an admin wants to act on, looked up inside the admin's own
    organization. An id from any other organization is "not found".
    """
    return get_object_or_404(
        Membership.objects.select_related("account"),
        pk=pk,
        enterprise_id=membership.enterprise_id,
    )


def _who(account):
    """How a message names the member: by name if there is one."""
    if account.anonymised_at is not None:
        return "The erased member"
    return account.full_name or "The member"


def _to_members(membership):
    return redirect("enterprises:members", membership.enterprise.slug)


@never_cache
@verified_email_required
def deactivate_member(request, slug, pk):
    """
    Switch a member off: first a page that says what will happen, then the POST
    that does it. Deactivating deletes the member's unfinished survey for the
    organization, which is why it is the one action that asks first.
    """
    membership = scoping.for_admin(request, slug)
    target = _their_member(membership, pk)
    organization = _organization(membership)
    yourself = target.pk == membership.pk
    if not target.is_active:
        messages.info(request, f"{_who(target.account)} is already deactivated.")
        return _to_members(membership)
    if request.method != "POST":
        context = {
            "organization": organization,
            "member": {"id": target.pk, "name": member_name(target.account)},
            "yourself": yourself,
        }
        return render(request, "enterprises/deactivate.html", context)
    try:
        done = services.deactivate_membership(target, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
        return _to_members(membership)
    if yourself:
        messages.success(request, f"You are no longer a member of {organization['name']}.")
        return redirect("enterprises:list")
    said = f"{_who(target.account)} has been deactivated."
    if done.draft_deleted:
        said += f" Their unfinished survey for {organization['name']} was deleted."
    messages.success(request, said)
    return _to_members(membership)


@verified_email_required
@require_POST
def reactivate_member(request, slug, pk):
    """Bring a deactivated member back, as an ordinary member."""
    membership = scoping.for_admin(request, slug)
    target = _their_member(membership, pk)
    try:
        services.reactivate_membership(target, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{_who(target.account)} is a member again.")
    return _to_members(membership)


@verified_email_required
@require_POST
def set_member_role(request, slug, pk):
    """Make a member an admin, or an admin a member again."""
    membership = scoping.for_admin(request, slug)
    target = _their_member(membership, pk)
    role = request.POST.get("role")
    try:
        services.set_role(target, role, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
        return _to_members(membership)
    if target.pk == membership.pk and role == Membership.Role.MEMBER:
        # The members page is no longer theirs to open.
        name = membership.enterprise.name
        messages.success(request, f"You are no longer an admin of {name}.")
        return redirect("enterprises:dashboard", membership.enterprise.slug)
    noun = "an admin" if role == Membership.Role.ADMIN else "a member, not an admin"
    messages.success(request, f"{_who(target.account)} is now {noun}.")
    return _to_members(membership)


# --- join codes --------------------------------------------------------------------


def _code_row(code, now):
    """What an admin sees of one join code. "active" means it would still let someone in."""
    state = services.code_state(code, now)
    return {
        "id": code.pk,
        "code": services.display_code(code.code),
        "uses": code.uses,
        "max_uses": code.max_uses,
        "tier": code.tier,
        "created_at": code.created_at,
        "expires_at": code.expires_at,
        "revoked_at": code.revoked_at,
        "state": state,
    }


@never_cache
@verified_email_required
def codes(request, slug):
    """
    The organization's join codes, working ones first, and the form that makes
    a new one: how many people it lets in, how many days it lasts, and the
    licence (if any) each person who joins with it is given. A code with a
    licence sets one aside for each person it allows, so the stock must cover it.
    """
    membership = scoping.for_admin(request, slug)
    form = JoinCodeForm(request.POST or None, left=_tiers_left(membership.enterprise))
    if request.method == "POST" and form.is_valid():
        expires_at = timezone.now() + timedelta(days=form.cleaned_data["days"])
        try:
            code = services.create_code(
                membership,
                form.cleaned_data["max_uses"],
                expires_at,
                tier=form.cleaned_data["tier"],
            )
        except services.Refused as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"Join code {services.display_code(code.code)} is ready.")
            return redirect("enterprises:codes", membership.enterprise.slug)
    now = timezone.now()
    rows = [_code_row(code, now) for code in membership.enterprise.join_codes.all()]
    rows.sort(key=lambda row: row["state"] != "active")  # newest first within each group
    context = {
        "organization": _organization(membership),
        "places": _places(membership.enterprise),
        "form": form,
        "rows": rows,
        "join_address": request.build_absolute_uri(reverse("join_code")),
    }
    return render(request, "enterprises/codes.html", context)


@verified_email_required
@require_POST
def revoke_code(request, slug, pk):
    """
    Switch a join code off. Nobody else can join with it; those who did stay.
    Licences it had set aside and nobody took are back in the stock.
    """
    membership = scoping.for_admin(request, slug)
    code = get_object_or_404(JoinCode, pk=pk, enterprise_id=membership.enterprise_id)
    try:
        services.revoke_code(code, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Join code {services.display_code(code.code)} is switched off.")
    return redirect("enterprises:codes", membership.enterprise.slug)


# --- invites -----------------------------------------------------------------------


def _invite_row(invite, now, request):
    """
    What an admin sees of one invite. Only one that can still be accepted
    ("pending") carries its link, for the admin to copy. An invite whose address
    is gone was sent to someone who has since been erased.
    """
    state = services.invite_state(invite, now)
    return {
        "id": invite.pk,
        "email": invite.email,
        "tier": invite.tier,
        "created_at": invite.created_at,
        "expires_at": invite.expires_at,
        "accepted_at": invite.accepted_at,
        "revoked_at": invite.revoked_at,
        "state": state,
        "link": services.invite_link(invite, request) if state == "pending" else "",
    }


@never_cache
@verified_email_required
def invites(request, slug):
    """
    The organization's invites, open ones first, and the form that sends one.
    If the email cannot be sent, the invite is kept and the page says so: the
    admin copies the link and passes it on some other way.
    """
    membership = scoping.for_admin(request, slug)
    form = InviteForm(request.POST or None, left=_tiers_left(membership.enterprise))
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        try:
            invite, sent = services.invite_by_email(
                membership, email, tier=form.cleaned_data["tier"], request=request
            )
        except services.Refused as error:
            form.add_error(None, str(error))
        else:
            if sent:
                messages.success(request, f"Invite sent to {invite.email}.")
            else:
                messages.warning(
                    request,
                    f"The invite for {invite.email} is saved, but we could not send the email. "
                    "Copy its link below and send it to them yourself.",
                )
            return redirect("enterprises:invites", membership.enterprise.slug)
    now = timezone.now()
    rows = [_invite_row(invite, now, request) for invite in membership.enterprise.invites.all()]
    rows.sort(key=lambda row: row["state"] != "pending")  # newest first within each group
    context = {
        "organization": _organization(membership),
        "places": _places(membership.enterprise),
        "form": form,
        "rows": rows,
        "days": services.INVITE_DAYS,
    }
    return render(request, "enterprises/invites.html", context)


@verified_email_required
@require_POST
def revoke_invite(request, slug, pk):
    """
    Withdraw an invite that has not been accepted. Its place is not given back;
    a licence that was set aside for it is.
    """
    membership = scoping.for_admin(request, slug)
    invite = get_object_or_404(Invite, pk=pk, enterprise_id=membership.enterprise_id)
    try:
        services.revoke_invite(invite, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The invite has been withdrawn.")
    return redirect("enterprises:invites", membership.enterprise.slug)


# --- joining ----------------------------------------------------------------------
#
# /join/code/ and /join/invite/<token>/. The person is not a member yet, so
# there is no membership to scope by. What stands in for it is the code or the
# link itself, and the services decide what it is good for.
#
# * Joining takes two steps. First a page that names the organization and says
#   what its admins will be able to see (services.check_code or check_invite:
#   every rule is checked and nothing is written). Then the button, a POST,
#   which is the only thing that joins (services.redeem_code or accept_invite,
#   which check everything again).
# * All these pages ever show of the organization is its name, and whether the
#   invite or the code comes with a licence for this person (never its tier).
#   Never a member or a count: the person does not belong to it yet.
# * Logged out, nothing is checked and nothing is revealed, not even whether
#   the code or the link is real. The person is asked to log in or sign up, and
#   a note in their session (apps/accounts/arrival.py) brings them back here
#   afterwards and tells the funnel how they arrived. If the note is lost (the
#   verification email was opened on another device), opening the link or
#   typing the code again works.

PENDING_CODE = "join_code"  # session key: a code typed while logged out


def _log_in_first(request, channel, back_to):
    """Logged out: remember where they were going, and ask them to log in or sign up."""
    arrival.remember(request, channel, back_to)
    return render(request, "enterprises/join_log_in.html", {"by_invite": channel == "invite"})


def _confirmation(request, enterprise, *, email, with_licence, code=""):
    """
    The page that tells the truth first. Plain values only. `email` is the
    address the organization's admins will see for this person (the invited
    address for an invite, the login address for a code; see shown.member_email).
    `with_licence` says whether the invite or the code carries a tier: a licence
    was then set aside for whoever joins, and the page promises it.
    """
    context = {
        "with_licence": with_licence,
        "organization_name": enterprise.name,
        "name": request.user.full_name,
        "email": email,
        "by_invite": not code,
        "code": code,
    }
    return render(request, "enterprises/join_confirm.html", context)


def _joined(request, membership):
    arrival.forget(request)
    enterprise = membership.enterprise
    said = f"You have joined {enterprise.name}."
    # The invite or code may have come with a licence (read through the reverse
    # name: this app does not import the licences app).
    if membership.entitlements.filter(revoked_at__isnull=True, response__isnull=True).exists():
        said += " You have a licence to take the survey for it."
    messages.success(request, said)
    return redirect("enterprises:dashboard", enterprise.slug)


def _already_a_member(request, error):
    arrival.forget(request)
    messages.info(request, str(error))
    return redirect("enterprises:dashboard", error.enterprise.slug)


@never_cache
@require_http_methods(["GET", "POST"])
def join_code(request):
    """
    Join an organization with a code: type it, read what joining means, confirm.
    A code typed while logged out is kept in the session and picked up again
    after the login.
    """
    confirmed = False
    if request.method == "POST":
        form = JoinForm(request.POST)
        confirmed = "confirm" in request.POST
    elif request.user.is_authenticated and PENDING_CODE in request.session:
        form = JoinForm({"code": request.session.pop(PENDING_CODE)})
    else:
        return render(request, "enterprises/join_code.html", {"form": JoinForm()})
    if not form.is_valid():
        return render(request, "enterprises/join_code.html", {"form": form})
    code = form.cleaned_data["code"]
    if not request.user.is_authenticated:
        request.session[PENDING_CODE] = code
        return _log_in_first(request, "code", reverse("join_code"))
    try:
        if confirmed:
            return _joined(request, services.redeem_code(code, request.user))
        found = services.check_code(code, request.user)
    except services.AlreadyMember as error:
        return _already_a_member(request, error)
    except services.Refused as error:
        form.add_error("code", str(error))
        return render(request, "enterprises/join_code.html", {"form": form})
    return _confirmation(
        request,
        found.enterprise,
        email=request.user.email,
        with_licence=found.tier is not None,
        code=services.display_code(found.code),
    )


@never_cache
@require_http_methods(["GET", "POST"])
def join_invite(request, token):
    """
    Accept an invite: the link opens the page that says what joining means, and
    its button joins. Only an account that has verified the invited address
    gets that far; anyone else is told why not.
    """
    if not request.user.is_authenticated:
        return _log_in_first(request, "invite", request.path)
    try:
        if request.method == "POST":
            return _joined(request, services.accept_invite(token, request.user))
        invite = services.check_invite(token, request.user)
    except services.AlreadyMember as error:
        return _already_a_member(request, error)
    except services.Refused as error:
        context = {
            "reason": str(error),
            # They can put this right themselves, on their profile.
            "wrong_address": isinstance(error, services.WrongAddress),
        }
        return render(request, "enterprises/join_refused.html", context)
    return _confirmation(
        request, invite.enterprise, email=invite.email, with_licence=invite.tier is not None
    )
