"""
Creates the "Support staff" group and gives it its permissions.

Support staff are Django staff accounts that are not superusers: they can grant
and revoke licences, look things up for debugging, and read the funnel, and they
see which questions a response has answered but never the answers. A superuser makes
someone support staff by ticking "staff" and adding them to this group.

Done after migrate rather than in a migration because permissions are created
after migrations run, so a migration cannot find them on a fresh database. It
waits for this app, which is last in INSTALLED_APPS, so every other app's
permissions already exist. Safe to run every time: it only sets the list.
"""

from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver

GROUP_NAME = "Support staff"

# (app label, model, actions). Two jobs, named so they can become two groups
# later (debugging staff, insights staff); "Support staff" does both for now.
DEBUGGING = [
    ("entitlements", "entitlement", ("add", "change", "view")),
    ("responses", "response", ("view",)),
    ("accounts", "account", ("view",)),
    ("accounts", "person", ("view",)),
    ("accounts", "contactpoint", ("view",)),
    ("survey", "surveyversion", ("view",)),
    ("survey", "question", ("view",)),
]
INSIGHTS = [
    ("funnel", "funnelevent", ("view",)),
]
PERMISSIONS = DEBUGGING + INSIGHTS


@receiver(post_migrate, dispatch_uid="responses.support_staff_group")
def ensure_support_staff_group(sender, **kwargs):
    if sender.label != "responses":
        return
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    codenames = [
        (app, f"{action}_{model}") for app, model, actions in PERMISSIONS for action in actions
    ]
    permissions = [
        Permission.objects.get(content_type__app_label=app, codename=codename)
        for app, codename in codenames
    ]
    group.permissions.set(permissions)
