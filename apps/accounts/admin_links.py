"""
Links between pages of the Django admin (Milestone 6).

Staff follow a thread: from a membership to the account, from the account to
its surveys, from a survey to the organization. Django links a related thing
on a detail page by itself, but a column of a list is plain text, and nothing
points backwards (from an account to its memberships). These two helpers make
those links, the same way everywhere.

They live in the accounts app because every app whose admin pages use them may
import accounts (tests/test_app_dependencies.py). A page is named by its admin
address name ("enterprises_membership"), not by its model, so that an app can
link to a page of an app that depends on it without importing it.

Every page linked to this way can be opened by Support staff as well as by
superusers (a test follows every link as both). A staff login given a
hand-picked set of permissions could be shown a link it may not open; it would
get "forbidden", as it would from the links Django itself puts on these pages.
"""

from urllib.parse import urlencode

from django.urls import reverse
from django.utils.html import format_html, format_html_join


def link(obj, text=None):
    """A link to the object's own page in the admin, labelled `text` (or as the object names itself)."""
    if obj is None:
        return "-"
    name = f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change"
    return format_html(
        '<a href="{}">{}</a>', reverse(name, args=[obj.pk]), str(obj) if text is None else text
    )


def list_address(page, **filters):
    """The address of a list in the admin ("enterprises_membership"), with these filters on."""
    address = reverse(f"admin:{page}_changelist")
    return f"{address}?{urlencode(filters)}" if filters else address


def related(*lines):
    """
    The "Related" line of a detail page: each of `lines` is (words, page,
    filters), shown as a link to that list with those filters on.
    """
    return format_html_join(
        " · ",
        '<a href="{}">{}</a>',
        ((list_address(page, **filters), words) for words, page, filters in lines),
    )
