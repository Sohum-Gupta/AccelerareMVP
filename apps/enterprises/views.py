"""
The pages for joining an organization. They arrive in Milestone 3, PR 10.

Until then the invite link has an address, so the invite email can be written
and tested, but nothing behind it: nobody can send an invite before the pages
that send them exist (PR 9).
"""

from django.http import Http404


def join_invite(request, token):
    raise Http404
