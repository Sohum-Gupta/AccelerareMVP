from django.http import HttpResponse


def health(request):
    """
    Liveness probe for Caddy, the deploy script and monitoring.
    Deliberately touches nothing (no DB, no auth) so it only fails when the
    app process itself is down.
    """
    return HttpResponse("ok", content_type="text/plain")
