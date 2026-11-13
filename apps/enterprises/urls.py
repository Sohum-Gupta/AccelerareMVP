from django.urls import path

from . import views

app_name = "enterprises"

# Mounted at /organizations/. "new" is a reserved slug (services.RESERVED_SLUGS),
# so no organization can ever sit behind the address of the create page.
#
# The slug in an address only says which organization is meant. Every view below
# it starts with scoping.for_member or scoping.for_admin, which answer with the
# account's own membership or "not found".
urlpatterns = [
    path("", views.organizations, name="list"),
    path("new/", views.new, name="new"),
    path("<slug:slug>/", views.dashboard, name="dashboard"),
    path("<slug:slug>/members/", views.members, name="members"),
    path(
        "<slug:slug>/members/<int:pk>/deactivate/",
        views.deactivate_member,
        name="member_deactivate",
    ),
    path(
        "<slug:slug>/members/<int:pk>/reactivate/",
        views.reactivate_member,
        name="member_reactivate",
    ),
    path("<slug:slug>/members/<int:pk>/role/", views.set_member_role, name="member_role"),
    path("<slug:slug>/codes/", views.codes, name="codes"),
    path("<slug:slug>/codes/<int:pk>/revoke/", views.revoke_code, name="code_revoke"),
    path("<slug:slug>/invites/", views.invites, name="invites"),
    path("<slug:slug>/invites/<int:pk>/revoke/", views.revoke_invite, name="invite_revoke"),
    path("<slug:slug>/invites/<int:pk>/resend/", views.resend_invite, name="invite_resend"),
    path("<slug:slug>/invites/<int:pk>/move/", views.move_invite, name="invite_move"),
]
