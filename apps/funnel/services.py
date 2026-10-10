"""
Every write to the funnel goes through here. Other apps call record_event
inside the same transaction as the thing that happened, so a sign-up that rolls
back leaves no event. This app imports nothing from the apps that call it.
"""

from .models import FunnelEvent

Kind = FunnelEvent.Kind  # so callers write funnel.Kind.SIGNED_UP


def record_event(kind, *, country="", channel="direct", tier=None, source="", page=None):
    """Note that one step happened. Takes no account or person, on purpose."""
    return FunnelEvent.objects.create(
        kind=kind, country=country, channel=channel, tier=tier, source=source, page=page
    )
