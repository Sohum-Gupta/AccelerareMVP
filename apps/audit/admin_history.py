"""
Copies every line of the Django admin's history into the audit log.

The Django admin already writes a history line (a LogEntry) each time staff
add, change or delete something, and this project's own admin pages write one
for each of their buttons. Copying those lines as they are written means every
staff action is in the audit log without any admin page having to remember to
put it there, including pages added later.

Two things are needed, because Django saves history lines in two ways:

- One line at a time, with an ordinary save. Django then sends its post_save
  signal, and the receiver below copies the line.
- Several lines at once (the "delete selected" action on more than one row),
  with a bulk insert. A bulk insert sends no signal. So the manager method
  that writes history, `log_actions`, is wrapped: after a bulk insert the
  wrapper copies each line itself.

The wrapper also runs Django's own writing inside one transaction, so a line
and its copy are saved together or not at all. tests/test_audit.py deletes two
rows at once through the admin and expects two copies: if a later version of
Django changes how history is written, that test says so.
"""

from django.contrib.admin.models import LogEntry, LogEntryManager
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from . import services


@receiver(post_save, sender=LogEntry, dispatch_uid="audit.copy_admin_history")
def copy_saved_line(sender, instance, created, **kwargs):
    if created:
        services.copy_admin_line(instance)


_django_log_actions = LogEntryManager.log_actions


def _log_actions_and_copy(self, *args, **kwargs):
    with transaction.atomic():
        written = _django_log_actions(self, *args, **kwargs)
        # A list of more than one line was a bulk insert: no signal was sent.
        if isinstance(written, list) and len(written) > 1:
            for entry in written:
                services.copy_admin_line(entry)
    return written


LogEntryManager.log_actions = _log_actions_and_copy
