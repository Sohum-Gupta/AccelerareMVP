"""
The background jobs the licences app knows how to do (see apps/jobs).

One so far: telling a member that their organization has given them a licence.
The job carries only the number of the licence. The address is looked up when
the job runs, so the queue never holds an email address, and if the person has
been erased or the licence taken back by then, nothing is sent.

A handler here must be safe to run twice, because the worker may. An email is
the one thing that cannot be: after a crash at exactly the wrong moment the
member may get the same email twice, which is accepted.
"""

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.urls import reverse

from apps.enterprises.shown import member_email
from apps.jobs import services as jobs

from .models import Entitlement
from .services import LICENCE_EMAIL


@jobs.job(LICENCE_EMAIL)
def send_licence_email(entitlement_id):
    """
    Email a member that they have a licence to take the survey for their
    organization. Sends nothing if it would no longer be true or useful: the
    licence is gone or was taken back, the survey on it has been started, the
    member has left, or the person has been erased.

    A refusal by the mail server is not caught: the job then fails and the
    worker tries again later.
    """
    licence = (
        Entitlement.objects.select_related(
            "membership__account", "membership__enterprise", "membership__joined_via_invite"
        )
        .filter(pk=entitlement_id, membership__isnull=False, revoked_at__isnull=True)
        .first()
    )
    if licence is None or not licence.membership.is_active:
        return
    if Entitlement.objects.filter(pk=licence.pk, response__isnull=False).exists():
        return
    # The address the organization knows them by; empty for an erased member.
    address = member_email(licence.membership)
    if not address:
        return
    enterprise = licence.membership.enterprise
    context = {
        "enterprise_name": enterprise.name,
        "start_url": settings.SITE_URL
        + reverse("responses:start_for_organization", args=[enterprise.slug]),
    }
    # allauth's adapter renders the mail, so the subject prefix and the From
    # address are the same as on every other email the site sends.
    get_adapter().render_mail("entitlements/email/licence_given", address, context).send()
