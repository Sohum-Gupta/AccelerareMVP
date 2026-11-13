"""
The organization pages, under /organizations/. Thin views: read the form, call
a service, show the result.

Who sees what (the founder's rules of 2026-11-12):

* A member sees the organization's name and their own surveys. Never other
  members.
* An admin also sees the members: name, email, role, status, joined date and
  licence tier. Never a phone number, and never anything about a survey someone
  took personally.
* An admin brings people in with join codes and email invites, and sees how
  many places the organization has left.

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

The pages for joining an organization arrive in Milestone 3, PR 10. Until then
the invite link has an address, so the invite email can be written and tested,
but nothing behind it.
"""

from datetime import timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.accounts.decorators import verified_email_required

from . import scoping, services
from .forms import EnterpriseForm, InviteForm, JoinCodeForm
from .models import Invite, JoinCode, Membership

ERASED = "Erased member"


def _organization(membership):
    """What a template may know about the organization itself."""
    return {"name": membership.enterprise.name, "slug": membership.enterprise.slug}


def _places(enterprise):
    """How many more people the organization may bring in, out of its limit (admins only)."""
    return {"left": services.places_left(enterprise), "limit": enterprise.people_limit}


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
    erased), how many places are left, and the way to the admin pages.
    """
    membership = scoping.for_member(request, slug)
    context = {"organization": _organization(membership), "is_admin": membership.is_admin}
    if membership.is_admin:
        everyone = membership.enterprise.memberships
        context["current_members"] = everyone.filter(status=Membership.Status.ACTIVE).count()
        context["all_time_members"] = everyone.count()
        context["places"] = _places(membership.enterprise)
    return render(request, "enterprises/dashboard.html", context)


def _name(account):
    """A member's name as an admin sees it. Blank for an account made before names were asked for."""
    return ERASED if account.anonymised_at is not None else account.full_name


def _email_for_admins(person):
    """
    The address an organization's admins see for a member: the one the invite
    went to if they joined by invite (it is the address the organization knows
    them by), otherwise the address they log in with. An erased member has none.
    """
    if person.account.anonymised_at is not None:
        return ""
    invite = person.joined_via_invite
    if invite is not None and invite.email:
        return invite.email
    return person.account.email


def _member_row(person, viewer, admin_count):
    """What an admin may see about one member. Plain values only; never the phone."""
    # Only licences for this organization hang off the membership; a personal
    # licence belongs to the person and is not reachable from here.
    tiers = [licence.tier for licence in person.entitlements.all() if licence.revoked_at is None]
    return {
        "id": person.pk,
        "name": _name(person.account),
        "email": _email_for_admins(person),
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
            "member": {"id": target.pk, "name": _name(target.account)},
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
    if code.revoked_at is not None:
        state = "revoked"
    elif code.expires_at <= now:
        state = "expired"
    elif code.uses >= code.max_uses:
        state = "used_up"
    else:
        state = "active"
    return {
        "id": code.pk,
        "code": services.display_code(code.code),
        "uses": code.uses,
        "max_uses": code.max_uses,
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
    a new one: how many people it lets in and how many days it lasts.
    """
    membership = scoping.for_admin(request, slug)
    form = JoinCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        expires_at = timezone.now() + timedelta(days=form.cleaned_data["days"])
        try:
            code = services.create_code(membership, form.cleaned_data["max_uses"], expires_at)
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
    }
    return render(request, "enterprises/codes.html", context)


@verified_email_required
@require_POST
def revoke_code(request, slug, pk):
    """Switch a join code off. Nobody else can join with it; those who did stay."""
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
    if invite.accepted_at is not None:
        state = "accepted"
    elif invite.revoked_at is not None:
        state = "revoked"
    elif invite.expires_at <= now:
        state = "expired"
    elif not invite.email:
        state = "erased"
    else:
        state = "pending"
    return {
        "id": invite.pk,
        "email": invite.email,
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
    form = InviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        try:
            invite, sent = services.invite_by_email(membership, email, request=request)
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
    """Withdraw an invite that has not been accepted. Its place is not given back."""
    membership = scoping.for_admin(request, slug)
    invite = get_object_or_404(Invite, pk=pk, enterprise_id=membership.enterprise_id)
    try:
        services.revoke_invite(invite, by=membership)
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The invite has been withdrawn.")
    return redirect("enterprises:invites", membership.enterprise.slug)


# --- joining (Milestone 3, PR 10) ------------------------------------------------


def join_invite(request, token):
    raise Http404
