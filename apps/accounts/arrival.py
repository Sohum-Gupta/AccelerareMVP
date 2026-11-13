"""
How someone arrived, remembered while they sign up or log in.

A person who opens an invite link or types a join code while logged out has to
sign up or log in before they can join. Meanwhile their session keeps a note of
two things:

* the channel they came by ("invite" or "code"), which the sign-up page hands
  to the funnel, so the numbers can tell an invited sign-up from a direct one;
* the page to bring them back to once they are logged in.

The join pages (the enterprises app) write the note. It lives here because the
sign-up view and the login adapter read it, and this app imports nothing from
the apps that depend on it.

The note is in the session, so it belongs to one browser. Someone who opens
their verification email on another device arrives without it and lands on
their profile as usual; opening the invite link or typing the code again works.
Logging out empties the session, and the note with it.
"""

from django.utils.http import url_has_allowed_host_and_scheme

SESSION_KEY = "arrival"
CHANNELS = ("invite", "code")  # funnel.models.FunnelEvent.Channel, less "direct"


def remember(request, channel, next_url):
    """Note that this visitor came by `channel` and should come back to `next_url`."""
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel: {channel!r}")
    request.session[SESSION_KEY] = {"channel": channel, "next": next_url}


def channel(request):
    """The channel for the funnel's sign-up event: "invite", "code" or "direct"."""
    note = request.session.get(SESSION_KEY) or {}
    found = note.get("channel")
    return found if found in CHANNELS else "direct"


def take_next(request):
    """
    The page to go back to after logging in, or None. It is handed out once:
    the note is removed, so later logins go to the profile as usual.
    """
    note = request.session.pop(SESSION_KEY, None) or {}
    url = note.get("next") or ""
    # Only ever a page of this site: an address with a host in it is ignored.
    if url.startswith("/") and url_has_allowed_host_and_scheme(url, allowed_hosts=None):
        return url
    return None


def forget(request):
    """Drop the note: the join is done, or was refused."""
    request.session.pop(SESSION_KEY, None)
