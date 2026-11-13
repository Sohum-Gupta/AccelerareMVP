"""
What an organization's admins are shown about a member, in one place.

The members page (this app) and the responses pages (the responses app) both
name a member. They take the name and the address from here, so the two can
never disagree about who is shown as "Erased member" or which address an admin
sees. Each function returns a plain value for a template, never a database
object.
"""

ERASED = "Erased member"


def organization(membership):
    """What a template may know about the organization itself."""
    return {"name": membership.enterprise.name, "slug": membership.enterprise.slug}


def member_name(account):
    """A member's name as an admin sees it. Blank for an account made before names were asked for."""
    return ERASED if account.anonymised_at is not None else account.full_name


def member_email(membership):
    """
    The address an organization's admins see for a member: the one the invite
    went to if they joined by invite (it is the address the organization knows
    them by), otherwise the address they log in with. An erased member has none.
    """
    if membership.account.anonymised_at is not None:
        return ""
    invite = membership.joined_via_invite
    if invite is not None and invite.email:
        return invite.email
    return membership.account.email
