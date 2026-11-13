"""
The apps depend on each other in one direction only:

    accounts <- enterprises <- entitlements <- payments <- matching <- responses

(Nothing imports payments, and matching does not need it; they sit before
responses only because responses must stay last. Only responses imports
matching.)

An app may import the ones to its left, never the ones to its right; it reaches
those through reverse relations (`account.memberships`, `membership.responses`).
A circular import would be the first symptom of breaking this, usually at
deploy time. These tests read the source and fail at once instead.
"""

import ast
from pathlib import Path

import pytest
from django.conf import settings

APPS = Path(settings.BASE_DIR) / "apps"
ORDER = ["accounts", "enterprises", "entitlements", "payments", "matching", "responses"]


def imported_apps(app):
    """Names of the apps under apps/ that this app's code imports."""
    found = set()
    for path in (APPS / app).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
                if node.module == "apps":
                    names = [f"apps.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                parts = name.split(".")
                if parts[0] == "apps" and len(parts) > 1:
                    found.add(parts[1])
    return found - {app}


@pytest.mark.parametrize("position", range(len(ORDER)))
def test_an_app_never_imports_one_that_depends_on_it(position):
    app, later = ORDER[position], set(ORDER[position + 1 :])
    assert imported_apps(app) & later == set()


def test_the_funnel_imports_no_other_app():
    assert imported_apps("funnel") == set()


def test_the_job_queue_imports_no_other_app():
    """Apps hand it work by name; the function that does the work lives in their own app."""
    assert imported_apps("jobs") == set()


def test_the_audit_log_imports_no_other_app():
    """Every app may tell it what happened; it needs to know nothing about them."""
    assert imported_apps("audit") == set()


def test_matching_keeps_to_accounts_and_licences():
    """It reaches memberships and surveys through an account's reverse names, never by import."""
    assert imported_apps("matching") == {"accounts", "entitlements", "audit", "jobs"}


def test_the_apps_are_installed_in_dependency_order_with_responses_last():
    installed = [name for name in settings.INSTALLED_APPS if name.startswith("apps.")]
    positions = [installed.index(f"apps.{app}") for app in ORDER]
    assert positions == sorted(positions)
    # Its post_migrate hook needs every other app's permissions to exist.
    assert settings.INSTALLED_APPS[-1] == "apps.responses"
