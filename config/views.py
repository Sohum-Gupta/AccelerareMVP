from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache


def health(request):
    """
    Liveness probe for Caddy, the deploy script and monitoring.
    Deliberately touches nothing (no DB, no auth) so it only fails when the
    app process itself is down.
    """
    return HttpResponse("ok", content_type="text/plain")


@never_cache
def home(request):
    """
    The site's front door, "/". There is no landing page yet, so it sends
    people on: someone logged in goes to their profile (where a login lands
    too), anyone else to the login page. The "Accelerare" link in the header
    and logging out (LOGOUT_REDIRECT_URL) both come here.
    """
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    return redirect(settings.LOGIN_URL)
