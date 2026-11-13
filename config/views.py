from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from apps.jobs import services as jobs


def health(request):
    """
    Liveness probe for Caddy, the deploy script and monitoring.
    Deliberately touches nothing (no DB, no auth) so it only fails when the
    app process itself is down.
    """
    return HttpResponse("ok", content_type="text/plain")


@never_cache
def worker_health(request):
    """
    Is the background worker keeping up? "ok", or "behind" (status 503) when a
    job has been due for more than ten minutes, which means the worker is
    stopped or stuck. For an uptime checker to watch. It is separate from
    /health on purpose: this one reads the database, and a slow queue must
    never make the site itself look down.
    """
    if jobs.waiting()["behind"]:
        return HttpResponse("behind", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


@never_cache
def home(request):
    """
    The site's front door, "/". There is no landing page yet, so it sends
    people on: someone logged in goes to "My surveys" (where a login lands
    too; an account with no verified email is sent on from there to its
    account page), anyone else to the login page. The "Accelerare" link in the header
    and logging out (LOGOUT_REDIRECT_URL) both come here.
    """
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    return redirect(settings.LOGIN_URL)
