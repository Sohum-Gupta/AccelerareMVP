"""
The staff tools for organizations.

Staff never edit an organization's rows by hand. Each thing they can do calls
the same function in services.py that the organization's own pages call, so the
rules (an organization keeps at least one admin, an accepted invite cannot be
withdrawn, deactivating deletes the unfinished survey attempt) hold whoever is
acting. What staff can do:

* Organizations: find one, change its people limit, create one for a
  customer with a first admin, and set its stock of licences (how many of
  each tier it has bought), until payments set that by themselves.
* Memberships: deactivate, reactivate, make admin, make member.
* Invites: withdraw. Join codes: switch off.

Every action first shows a page that says what will happen and asks "are you
sure?", and afterwards writes a line in the row's history saying who did it.
History lines and labels never hold an email or a name ("Membership 12 in
Acme", "Invite 3", "Join code 4"), so nothing personal outlives an erasure.

Who may do what. Superusers: everything above. Support staff (the group set up
in apps/responses/signals.py): look at all four pages, deactivate a membership
and set an organization's stock of licences, nothing else. An invite's link secret is shown to nobody, and a
join code only to superusers, on its own page: both are ways in.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.widgets import AutocompleteSelect
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.accounts.models import Account

from . import services
from .models import Enterprise, Invite, JoinCode, Membership

CODE_STATES = {
    "active": "Working",
    "revoked": "Switched off",
    "expired": "Expired",
    "used_up": "Used up",
}
INVITE_STATES = {
    "pending": "Waiting",
    "accepted": "Accepted",
    "revoked": "Withdrawn",
    "expired": "Expired",
    "erased": "Address removed",
}


class ReadOnlyAdmin(admin.ModelAdmin):
    """
    A page where nothing is typed: every field is shown, none can be edited, and
    nothing is added or deleted. Changes happen through the actions, which call
    services.py.
    """

    # Fields that are never shown, to anyone or to some (see hidden_fields).
    hidden = ()

    def hidden_fields(self, request):
        return self.hidden

    def get_exclude(self, request, obj=None):
        return self.hidden_fields(request)

    def get_readonly_fields(self, request, obj=None):
        hidden = self.hidden_fields(request)
        return [field.name for field in self.model._meta.fields if field.name not in hidden]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_manage_permission(self, request):
        """
        Who may run the actions that change something. It is Django's ordinary
        "change" permission for the model, which superusers have and Support
        staff do not. It is asked here, under another name, because
        has_change_permission above says no to everyone to keep the form
        read-only.
        """
        opts = self.opts
        return request.user.has_perm(f"{opts.app_label}.{get_permission_codename('change', opts)}")

    # --- the "are you sure?" page, and doing it -----------------------------------

    def ask_first(self, request, queryset, *, action, title, question, rows, notes=(), button):
        """
        The confirmation page for an action, or None once the person has
        pressed its button. The page posts the same action and the same rows
        back to the list, with `confirm` added.
        """
        if request.POST.get("confirm") == "yes":
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.opts,
            "action": action,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "selected": [row.pk for row in queryset],
            "question": question,
            "rows": rows,
            "notes": notes,
            "button": button,
        }
        return TemplateResponse(request, "admin/enterprises/confirm_action.html", context)

    def for_each(self, request, queryset, act):
        """
        Run `act(row)` on every selected row and return how many it changed.
        `act` returns the line for the row's history, or None if there was
        nothing to do. A refusal from services.py is shown with the row's label
        (never a person's email) and the other rows carry on.
        """
        changed = 0
        for row in queryset:
            try:
                history = act(row)
            except services.Refused as error:
                self.message_user(request, f"{row}: {error}", messages.ERROR)
                continue
            if history:
                # The service bypasses the admin's own history, so record who did it.
                self.log_change(request, row, history)
                changed += 1
        return changed

    def report(self, request, changed, selected, done, nothing):
        """Say how many rows were changed; `nothing` explains a row left as it was."""
        if changed:
            self.message_user(request, done.format(count=changed), messages.SUCCESS)
        elif selected:
            self.message_user(request, nothing, messages.WARNING)


# --- organizations -------------------------------------------------------------------

FIRST_ADMIN_HELP = (
    "The customer's own account: it becomes the organization's first admin and can then "
    "invite people. Search by email, name or phone. They must have signed up first."
)


def first_admin_field(widget=None):
    return forms.ModelChoiceField(
        # An account that is switched off or erased cannot run an organization.
        Account.objects.filter(is_active=True, anonymised_at__isnull=True),
        label="First admin",
        help_text=FIRST_ADMIN_HELP,
        widget=widget,
        error_messages={
            "invalid_choice": "That account cannot have an organization: "
            "it is switched off or has been erased."
        },
    )


class CreateForCustomerForm(forms.ModelForm):
    """The "Add organization" page: its name and the account that will be its first admin."""

    account = first_admin_field()

    class Meta:
        model = Enterprise
        fields = ("name",)

    def clean_name(self):
        try:
            return services.clean_name(self.cleaned_data["name"])
        except services.Refused as error:
            raise forms.ValidationError(str(error)) from None


class StockForm(forms.Form):
    """
    The "Licence stock" page: one box per tier, holding how many licences of
    that tier the organization has bought in total (not how many to add).
    """

    def __init__(self, *args, summary, **kwargs):
        super().__init__(*args, **kwargs)
        for row in summary:
            self.fields[f"tier_{row['tier']}"] = forms.IntegerField(
                label=f"Tier {row['tier']} licences bought",
                min_value=0,
                max_value=services.MAX_SEATS,
                initial=row["bought"],
                help_text=f"The total bought so far. {row['given']} given to members, "
                f"{row['left']} left.",
            )


@admin.register(Enterprise)
class EnterpriseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "members_now", "people_limit", "created_at")
    search_fields = ("name", "slug")

    def get_queryset(self, request):
        active = Count("memberships", filter=Q(memberships__status=Membership.Status.ACTIVE))
        return super().get_queryset(request).annotate(active_members=active)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = CreateForCustomerForm
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            # A search box instead of a dropdown of every account. It searches
            # the way the Accounts page does; created_by is only the Account
            # relation the admin's search endpoint needs to find that page.
            form.base_fields["account"] = first_admin_field(
                AutocompleteSelect(Enterprise._meta.get_field("created_by"), self.admin_site)
            )
        return form

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("name", "account")
        return (
            "name",
            "slug",
            "people_limit",
            "places",
            "licences",
            "members_now",
            "members_ever",
            "created_by",
            "created_at",
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        # Everything but the people limit.
        return tuple(name for name in self.get_fields(request, obj) if name != "people_limit")

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Members now", ordering="active_members")
    def members_now(self, enterprise):
        return enterprise.active_members

    @admin.display(description="Members ever")
    def members_ever(self, enterprise):
        """Everyone who has belonged, including people who left or were erased."""
        return enterprise.memberships.count()

    @admin.display(description="Places")
    def places(self, enterprise):
        invites = enterprise.invites.count()
        joins = enterprise.join_codes.aggregate(total=Sum("uses"))["total"] or 0
        return (
            f"{services.places_left(enterprise)} of {services.people_limit(enterprise)} left "
            f"({invites} invite(s) sent, {joins} join(s) by code; "
            "withdrawn and expired invites still count)"
        )

    @admin.display(description="Licences bought")
    def licences(self, enterprise):
        """The stock, tier by tier. Changed on the "Licence stock" page, not here."""
        rows = [row for row in services.seat_summary(enterprise) if row["bought"] or row["given"]]
        if not rows:
            return "None yet"
        return "; ".join(
            f"Tier {row['tier']}: {row['bought']} bought, {row['given']} given, {row['left']} left"
            for row in rows
        )

    # --- the "Licence stock" page --------------------------------------------------

    def has_stock_permission(self, request):
        """Who may set an organization's stock: superusers and Support staff."""
        return request.user.has_perm("enterprises.change_seatpool")

    def get_urls(self):
        custom = path(
            "<path:object_id>/stock/",
            self.admin_site.admin_view(self.stock_view),
            name="enterprises_enterprise_stock",
        )
        return [custom, *super().get_urls()]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if self.has_stock_permission(request):
            extra_context["stock_url"] = reverse(
                "admin:enterprises_enterprise_stock", args=[object_id]
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def stock_view(self, request, object_id):
        if not self.has_stock_permission(request):
            raise PermissionDenied
        enterprise = get_object_or_404(Enterprise, pk=object_id)
        back = reverse("admin:enterprises_enterprise_change", args=[enterprise.pk])
        summary = services.seat_summary(enterprise)
        form = StockForm(request.POST or None, summary=summary)
        if request.method == "POST" and form.is_valid():
            changes = []
            for row in summary:
                new = form.cleaned_data[f"tier_{row['tier']}"]
                if new == row["bought"]:
                    continue
                services.set_seat_pool(enterprise, row["tier"], new)
                changes.append(f"Tier {row['tier']} from {row['bought']} to {new}")
                if new < row["given"]:
                    self.message_user(
                        request,
                        f"Tier {row['tier']}: {row['given']} are already given to members, more "
                        f"than the {new} now recorded as bought. Nobody loses a licence, and no "
                        "more can be given at that tier until fewer are given than bought.",
                        messages.WARNING,
                    )
            if changes:
                text = "Licence stock changed: " + "; ".join(changes)
                # The organization's history says who changed its stock and how.
                self.log_change(request, enterprise, text)
                self.message_user(request, text + ".", messages.SUCCESS)
            else:
                self.message_user(request, "Nothing was changed.", messages.WARNING)
            return redirect(back)
        context = {
            **self.admin_site.each_context(request),
            "title": "Licence stock",
            "opts": self.opts,
            "enterprise": enterprise,
            "form": form,
            "people_limit": services.people_limit(enterprise),
        }
        return TemplateResponse(request, "admin/enterprises/enterprise/stock.html", context)

    def add_view(self, request, form_url="", extra_context=None):
        try:
            return super().add_view(request, form_url, extra_context)
        except services.Refused as error:
            # The form has already checked the name and the account, so this is
            # the service refusing at the last moment (the account was erased a
            # second ago, say). Nothing was saved; say why and show the form again.
            self.message_user(request, str(error), messages.ERROR)
            return redirect(request.path)

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)  # only the people limit
            return
        created = services.create_enterprise(
            form.cleaned_data["account"], form.cleaned_data["name"], staff=request.user
        )
        # The admin goes on to write the history line and redirect using `obj`,
        # so make it the row the service saved.
        obj.pk = created.pk
        obj.refresh_from_db()


# --- memberships -----------------------------------------------------------------------


@admin.register(Membership)
class MembershipAdmin(ReadOnlyAdmin):
    list_display = ("id", "account", "enterprise", "role", "status", "joined_at", "deactivated_at")
    list_filter = ("role", "status")
    search_fields = ("account__email", "account__full_name", "enterprise__name")
    list_select_related = ("account", "enterprise")
    actions = ["deactivate_selected", "reactivate_selected", "make_admin", "make_member"]

    def has_deactivate_permission(self, request):
        return request.user.has_perm("enterprises.deactivate_membership")

    def _rows(self, queryset, extra=None):
        """Each membership as a line for the confirmation page (never stored anywhere)."""
        rows = []
        for membership in queryset:
            line = (
                f"{membership}: {membership.account.email}, "
                f"{membership.get_role_display().lower()}, "
                f"{membership.get_status_display().lower()}"
            )
            if extra is not None:
                line += extra(membership)
            rows.append(line)
        return rows

    @admin.action(description="Deactivate the selected memberships", permissions=["deactivate"])
    def deactivate_selected(self, request, queryset):
        queryset = queryset.select_related("account", "enterprise")

        def unfinished(membership):
            # Through the reverse name: this app never imports the responses app.
            if membership.is_active and membership.responses.filter(status="draft").exists():
                return ". Has an unfinished survey attempt for the organization: it will be deleted"
            return ""

        asking = self.ask_first(
            request,
            queryset,
            action="deactivate_selected",
            title="Deactivate memberships",
            question="Deactivate these memberships? Do this when the person has left "
            "the organization.",
            rows=self._rows(queryset, unfinished),
            notes=[
                (
                    "They can no longer take the survey for the organization, and an unfinished "
                    "attempt for it is deleted. Surveys they have submitted stay, and the "
                    "organization still sees that they were taken."
                ),
                (
                    "Their licence stays with the membership and works again if they are "
                    "reactivated. An admin who is deactivated becomes an ordinary member."
                ),
                (
                    "An organization's only admin cannot be deactivated: make someone else "
                    "an admin first."
                ),
            ],
            button="Yes, deactivate",
        )
        if asking:
            return asking
        drafts = 0

        def act(membership):
            nonlocal drafts
            if not membership.is_active:
                return None
            done = services.deactivate_membership(membership)
            if done.draft_deleted:
                drafts += 1
                return "Deactivated; the unfinished survey attempt for the organization was deleted"
            return "Deactivated"

        changed = self.for_each(request, queryset, act)
        self.report(
            request,
            changed,
            len(queryset),
            "Deactivated {count} membership(s).",
            "Nothing was deactivated.",
        )
        if drafts:
            self.message_user(
                request, f"Deleted {drafts} unfinished survey attempt(s).", messages.SUCCESS
            )

    @admin.action(description="Reactivate the selected memberships", permissions=["manage"])
    def reactivate_selected(self, request, queryset):
        queryset = queryset.select_related("account", "enterprise")
        asking = self.ask_first(
            request,
            queryset,
            action="reactivate_selected",
            title="Reactivate memberships",
            question="Reactivate these memberships?",
            rows=self._rows(queryset),
            notes=[
                (
                    "They come back as ordinary members, and a licence still on the membership "
                    "works again. A membership whose account was erased cannot be reactivated."
                ),
            ],
            button="Yes, reactivate",
        )
        if asking:
            return asking

        def act(membership):
            if membership.is_active:
                return None
            services.reactivate_membership(membership)
            return "Reactivated"

        changed = self.for_each(request, queryset, act)
        self.report(
            request,
            changed,
            len(queryset),
            "Reactivated {count} membership(s).",
            "Nothing was reactivated.",
        )

    def _set_role(self, request, queryset, *, action, role, title, question, notes, button, done):
        queryset = queryset.select_related("account", "enterprise")
        asking = self.ask_first(
            request,
            queryset,
            action=action,
            title=title,
            question=question,
            rows=self._rows(queryset),
            notes=notes,
            button=button,
        )
        if asking:
            return asking

        def act(membership):
            if membership.is_active and membership.role == role:
                return None
            services.set_role(membership, role)
            return done

        changed = self.for_each(request, queryset, act)
        self.report(
            request,
            changed,
            len(queryset),
            "Changed {count} membership(s).",
            "Nothing was changed.",
        )
        return None

    @admin.action(description="Make the selected members admins", permissions=["manage"])
    def make_admin(self, request, queryset):
        return self._set_role(
            request,
            queryset,
            action="make_admin",
            role=Membership.Role.ADMIN,
            title="Make admins",
            question="Make these members admins of their organization?",
            notes=[
                (
                    "An admin sees the organization's members (name, email, joined date, status "
                    "and licence) and who has taken the survey for it, never the answers. They "
                    "can invite people, make join codes, deactivate members and make other admins."
                ),
            ],
            button="Yes, make admin",
            done="Made an admin",
        )

    @admin.action(description="Make the selected admins ordinary members", permissions=["manage"])
    def make_member(self, request, queryset):
        return self._set_role(
            request,
            queryset,
            action="make_member",
            role=Membership.Role.MEMBER,
            title="Make ordinary members",
            question="Make these admins ordinary members again?",
            notes=[
                (
                    "They stay in the organization but can no longer see its members or manage it. "
                    "An organization's only admin cannot be changed: make someone else an "
                    "admin first."
                ),
            ],
            button="Yes, make member",
            done="Made an ordinary member",
        )


# --- invites ---------------------------------------------------------------------------


@admin.register(Invite)
class InviteAdmin(ReadOnlyAdmin):
    list_display = ("id", "enterprise", "email", "state", "created_at", "expires_at")
    search_fields = ("email", "enterprise__name")
    list_select_related = ("enterprise",)
    actions = ["withdraw_selected"]
    # The secret in the invite's link. Nobody is shown it here; the
    # organization's admin can copy the link from their own invites page.
    hidden = ("token",)

    @admin.display(description="State")
    def state(self, invite):
        return INVITE_STATES[services.invite_state(invite)]

    @admin.action(description="Withdraw the selected invites", permissions=["manage"])
    def withdraw_selected(self, request, queryset):
        queryset = queryset.select_related("enterprise")
        asking = self.ask_first(
            request,
            queryset,
            action="withdraw_selected",
            title="Withdraw invites",
            question="Withdraw these invites?",
            rows=[
                f"{invite} to {invite.enterprise.name}: {invite.email or 'address removed'}, "
                f"{self.state(invite).lower()}"
                for invite in queryset
            ],
            notes=[
                (
                    "The link in the email stops working. This cannot be undone: the organization's "
                    "admin sends a new invite instead. A withdrawn invite still counts towards the "
                    "organization's people limit, and an invite that was accepted cannot be withdrawn."
                ),
            ],
            button="Yes, withdraw",
        )
        if asking:
            return asking

        def act(invite):
            if invite.revoked_at is not None:
                return None
            services.revoke_invite(invite)
            return "Withdrawn"

        changed = self.for_each(request, queryset, act)
        self.report(
            request, changed, len(queryset), "Withdrew {count} invite(s).", "Nothing was withdrawn."
        )


# --- join codes ------------------------------------------------------------------------


@admin.register(JoinCode)
class JoinCodeAdmin(ReadOnlyAdmin):
    list_display = ("id", "enterprise", "state", "uses", "max_uses", "created_at", "expires_at")
    search_fields = ("enterprise__name",)
    list_select_related = ("enterprise",)
    actions = ["switch_off_selected"]

    def hidden_fields(self, request):
        # The code itself lets anyone into the organization. It is never on the
        # list; a superuser can read it on the code's own page, support cannot.
        return () if request.user.is_superuser else ("code",)

    @admin.display(description="State")
    def state(self, code):
        return CODE_STATES[services.code_state(code)]

    @admin.action(description="Switch off the selected join codes", permissions=["manage"])
    def switch_off_selected(self, request, queryset):
        queryset = queryset.select_related("enterprise")
        asking = self.ask_first(
            request,
            queryset,
            action="switch_off_selected",
            title="Switch off join codes",
            question="Switch off these join codes?",
            rows=[
                f"{code} for {code.enterprise.name}: used {code.uses} of {code.max_uses} "
                f"time(s), {self.state(code).lower()}"
                for code in queryset
            ],
            notes=[
                (
                    "Nobody else can join with them. This cannot be undone: the organization's "
                    "admin makes a new code instead. People who already joined stay members."
                ),
            ],
            button="Yes, switch off",
        )
        if asking:
            return asking

        def act(code):
            if code.revoked_at is not None:
                return None
            services.revoke_code(code)
            return "Switched off"

        changed = self.for_each(request, queryset, act)
        self.report(
            request,
            changed,
            len(queryset),
            "Switched off {count} join code(s).",
            "Nothing was switched off.",
        )
