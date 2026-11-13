"""
Who may see which organization. Read this file slowly: it is the wall between
one organization's data and another's.

Every organization page starts by calling one of the two functions below with
the slug from the address. The slug is only a way of saying which organization
the person means. It is never trusted: what comes back is *this account's own*
membership, looked up by the account and the slug together, and the view then
uses `membership.enterprise` as the only organization in every query it makes.

So an attacker who edits the address to another organization's slug holds no
membership there, the lookup finds nothing, and the answer is "not found".
It is the same "not found" as for a slug that does not exist, so nobody can
discover which organizations exist by trying names. A member who is not an
admin gets the same answer for the admin pages, and so does a deactivated one.
"""

from django.http import Http404

from .models import Membership


def _membership(request, slug, **extra):
    if not request.user.is_authenticated:
        raise Http404
    membership = (
        Membership.objects.select_related("enterprise")
        .filter(
            account=request.user,
            enterprise__slug=slug,
            status=Membership.Status.ACTIVE,
            **extra,
        )
        .first()
    )
    if membership is None:
        raise Http404
    return membership


def for_member(request, slug):
    """The logged-in account's active membership of that organization, or 404."""
    return _membership(request, slug)


def for_admin(request, slug):
    """The logged-in account's active admin membership of that organization, or 404."""
    return _membership(request, slug, role=Membership.Role.ADMIN)
