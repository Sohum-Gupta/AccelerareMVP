"""
Possible duplicates in the staff admin: for superusers only.

The list shows the pairs waiting for a decision first. Opening one shows the
two accounts side by side and what they have in common. Three buttons, each
leading to a page that says what will happen and asks first:

- "Same person…" links the two logins, so they share their personal licences.
- "Different people…" closes the pair; it is never raised again.
- "Undo the link…" on a linked pair puts the two apart again.

This is the one place in the admin that shows two people's details together,
which is why Support staff cannot open it. Neither person is told anything.
The history line of each decision holds account numbers only.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from apps.entitlements.models import Entitlement

from . import rules, services
from .models import MatchCandidate

Status = MatchCandidate.Status

# (the word in the address, the page's title, the button, who may press it when)
DECISIONS = {
    "same": ("Same person: link the two logins", "Yes, link them"),
    "different": ("Different people: close this", "Yes, they are different people"),
    "undo": ("Undo the link", "Yes, undo the link"),
}


def _available(candidate):
    """The decisions that make sense for this pair now."""
    if candidate.status == Status.FLAGGED:
        return ["same", "different"]
    if candidate.status == Status.CONFIRMED:
        return ["undo"]
    if candidate.status == Status.UNLINKED:
        return ["same"]
    return []


@admin.register(MatchCandidate)
class MatchCandidateAdmin(admin.ModelAdmin):
    change_form_template = "admin/matching/matchcandidate/change_form.html"
    list_display = ("__str__", "status", "in_common", "created_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("=account_a__id", "=account_b__id")
    search_help_text = "Search by an account's number."
    list_select_related = ("account_a", "account_b")
    fields = (
        "status",
        "in_common",
        "first_account",
        "second_account",
        "created_at",
        "resolved_by",
        "resolved_at",
    )

    def get_readonly_fields(self, request, obj=None):
        return self.fields

    # --- what the page shows --------------------------------------------------------

    @admin.display(description="What they have in common")
    def in_common(self, candidate):
        return " ".join(rules.WORDS.get(name, name) for name in candidate.signals) or "-"

    @admin.display(description="The older account")
    def first_account(self, candidate):
        return self._about(candidate.account_a)

    @admin.display(description="The newer account")
    def second_account(self, candidate):
        return self._about(candidate.account_b)

    def _about(self, account):
        """One account as the superuser needs it to compare: a short list of plain facts."""
        phones = ", ".join(
            account.contact_points.filter(kind="phone").values_list("value_display", flat=True)
        )
        organizations = ", ".join(
            f"{membership.enterprise.name} ({membership.get_status_display().lower()})"
            for membership in account.memberships.select_related("enterprise")
        )
        licences = Entitlement.objects.filter(person_id=account.person_id)
        facts = [
            ("Login", account.email),
            ("Full name", account.full_name or "(none given)"),
            ("Phone", phones or "(none)"),
            ("Signed up", f"{account.created_at:%d %b %Y}"),
            ("Organizations", organizations or "(none)"),
            ("Surveys submitted", account.responses.filter(status="submitted").count()),
            (
                "Personal licences not yet used",
                licences.filter(revoked_at__isnull=True, response__isnull=True).count(),
            ),
        ]
        link = reverse("admin:accounts_account_change", args=[account.pk])
        return format_html(
            '<a href="{}">Account #{}</a><ul style="margin: .25rem 0 0 0;">{}</ul>',
            link,
            account.pk,
            format_html_join("", "<li>{}: {}</li>", facts),
        )

    # --- superusers only, and nothing is edited by hand -----------------------------

    def _is_superuser(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return self._is_superuser(request)

    def has_view_permission(self, request, obj=None):
        return self._is_superuser(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # --- the three decisions --------------------------------------------------------

    def get_urls(self):
        custom = path(
            "<path:object_id>/decide/<slug:decision>/",
            self.admin_site.admin_view(self.decide_view),
            name="matching_matchcandidate_decide",
        )
        return [custom, *super().get_urls()]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        candidate = self.get_object(request, object_id)
        if candidate is not None and self._is_superuser(request):
            extra_context["decisions"] = [
                {
                    "label": DECISIONS[decision][0].split(":")[0] + "…",
                    "url": reverse(
                        "admin:matching_matchcandidate_decide", args=[object_id, decision]
                    ),
                }
                for decision in _available(candidate)
            ]
        return super().change_view(request, object_id, form_url, extra_context)

    def decide_view(self, request, object_id, decision):
        if not self._is_superuser(request):
            raise PermissionDenied
        candidate = get_object_or_404(
            MatchCandidate.objects.select_related("account_a", "account_b"), pk=object_id
        )
        back = reverse("admin:matching_matchcandidate_change", args=[candidate.pk])
        if decision not in DECISIONS or decision not in _available(candidate):
            self.message_user(request, services.NOT_WAITING, messages.ERROR)
            return redirect(back)
        preview = {"can": True}
        if decision == "same":
            preview = services.link_preview(candidate)
        elif decision == "undo":
            preview = services.unlink_preview(candidate)
        if request.method == "POST" and preview["can"]:
            older, newer = candidate.account_a_id, candidate.account_b_id
            try:
                if decision == "same":
                    services.confirm(candidate, request.user)
                    text = (
                        f"Linked: account {newer} now shares one set of personal "
                        f"licences with account {older}"
                    )
                elif decision == "different":
                    services.reject(candidate, request.user)
                    text = "Closed as different people"
                else:
                    services.unlink(candidate, request.user)
                    text = f"Link undone: accounts {older} and {newer} are separate again"
            except services.Refused as error:
                self.message_user(request, str(error), messages.ERROR)
                return redirect(back)
            # The pair's history says who decided and what; numbers only.
            self.log_change(request, candidate, text)
            self.message_user(request, text + ".", messages.SUCCESS)
            return redirect(back)
        title, button = DECISIONS[decision]
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.opts,
            "candidate": candidate,
            "decision": decision,
            "button": button,
            "preview": preview,
            "in_common": self.in_common(candidate),
        }
        return TemplateResponse(request, "admin/matching/matchcandidate/decide.html", context)
