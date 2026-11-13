"""
The organization pages, under /organizations/. Thin views: read the form, call
a service, show the result.

Who sees what (the founder's rules of 2026-11-12):

* A member sees the organization's name and their own surveys. Never other
  members.
* An admin also sees the members: name, email, role, status, joined date and
  licence tier. Never a phone number, and never anything about a survey someone
  took personally.

How that is kept true:

* Every page about one organization starts with scoping.for_member or
  scoping.for_admin. The slug in the address only says which organization is
  meant; what comes back is this account's own active membership, or a 404.
  From then on `membership.enterprise` is the only organization any query uses.
* A membership id in an address (to deactivate someone, say) is looked up
  inside that organization, so another organization's id is a 404 too.
* The templates are given plain values (a name, a date, a tier), never a
  database object, so no later template edit can print a phone number or an
  answer by accident. tests/test_tenant_isolation.py checks all of this.

Licences are read through `membership.entitlements`, the reverse relation:
this app never imports the entitlements or responses apps (see models.py).

The pages for joining an organization arrive in Milestone 3, PR 10. Until then
the invite link has an address, so the invite email can be written and tested,
but nothing behind it.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.accounts.decorators import verified_email_required

from . import scoping, services
from .forms import EnterpriseForm
from .models import Membership

ERASED = "Erased member"


def _organization(membership):
    """What a template may know about the organization itself."""
    return {"name": membership.enterprise.name, "slug": membership.enterprise.slug}


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
    erased), with the way to the members page.
    """
    membership = scoping.for_member(request, slug)
    context = {"organization": _organization(membership), "is_admin": membership.is_admin}
    if membership.is_admin:
        everyone = membership.enterprise.memberships
        context["current_members"] = everyone.filter(status=Membership.Status.ACTIVE).count()
        context["all_time_members"] = everyone.count()
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


# --- joining (Milestone 3, PR 10) ------------------------------------------------


def join_invite(request, token):
    raise Http404
