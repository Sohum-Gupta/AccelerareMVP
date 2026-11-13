"""
Every write to the audit log goes through here.

Other apps call `record` inside the same transaction as the thing that
happened, so the two are saved together or not at all: there is never a record
of something that was undone, nor an action without its record. This app
imports no other app; the others import it.

The log must never hold a name, an email address or an answer. Callers pass
numbers and short plain words. As a second line of defence, anything shaped
like an email address is removed from every piece of text before it is stored.
"""

import json
import re

from .models import AuditLog

MESSAGE_MAX_LENGTH = 500
REMOVED = "[removed]"
_ADDRESS = re.compile(r"\S*@\S*")

# The Django admin's three kinds of history line (django.contrib.admin.models).
_ADMIN_ACTIONS = {1: "admin.added", 2: "admin.changed", 3: "admin.deleted"}


def record(actor, action, target=None, **detail):
    """
    Note that `actor` did `action` to `target`, and return the row.

    `actor` is an account, an account's number, or None when the site did it
    by itself. `target` is the saved object it was done to (only its kind and
    number are kept), or None. `detail` is a few plain facts: numbers, True or
    False, short words. Never pass a name, an email address or an answer.
    """
    return AuditLog.objects.create(
        actor_id=getattr(actor, "pk", actor),
        action=action,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        detail=_plain(detail),
    )


def copy_admin_line(entry):
    """
    Copy one line of the Django admin's history (a LogEntry) into the audit
    log, and return the row. Who, which kind of thing, its number and what was
    said about the change are copied. The line's label for the object is not:
    it can be a person's email address.
    """
    kind = entry.content_type
    return AuditLog.objects.create(
        actor_id=entry.user_id,
        action=_ADMIN_ACTIONS.get(entry.action_flag, "admin.changed"),
        target_type=f"{kind.app_label}.{kind.model}" if kind is not None else "",
        target_id=str(entry.object_id or "")[:40],
        detail=_plain({"history_line": entry.pk, "message": _admin_message(entry.change_message)}),
        at=entry.action_time,
    )


def _admin_message(text):
    """
    What an admin history line says, as plain words. Django's own lines are
    stored as a list such as [{"changed": {"fields": ["Role"]}}]; they are
    turned into "Changed: Role". Where such a line names an object ("added
    contact point <its label>") only the kind of object is kept, never its
    label. A line written by this project's own admin pages is plain text
    already and is copied as it is.
    """
    try:
        parts = json.loads(text)
    except ValueError:
        return str(text)[:MESSAGE_MAX_LENGTH]
    if not isinstance(parts, list):
        return str(text)[:MESSAGE_MAX_LENGTH]
    said = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        for verb, about in part.items():
            about = about if isinstance(about, dict) else {}
            line = str(verb).capitalize()
            if about.get("name"):
                line += f" {about['name']}"
            if about.get("fields"):
                line += ": " + ", ".join(str(field) for field in about["fields"])
            said.append(line)
    return ". ".join(said)[:MESSAGE_MAX_LENGTH]


def _plain(value):
    """The same value with anything shaped like an email address removed from its text."""
    if isinstance(value, str):
        return _ADDRESS.sub(REMOVED, value)
    if isinstance(value, dict):
        return {str(key): _plain(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(inner) for inner in value]
    return value
