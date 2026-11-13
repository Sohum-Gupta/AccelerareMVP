"""
T-19, point 4: a "Show password" button on every password box.

The founder asked for it on the live site (2026-10-18). The button is put in
the page by the one template every form field goes through, hidden, and the
page's script reveals it and does the switching. So these tests check that
each password box has its button and nothing else does; the switching itself
was checked in a real browser (see the pull request).
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse

from .test_profile import verified_account

BUTTON = re.compile(r'<button type="button"[^>]*data-show-password="([^"]+)"[^>]*>')


def buttons(html):
    """The ids of the boxes that have a Show password button, in page order."""
    return BUTTON.findall(html)


def password_boxes(html):
    return re.findall(r'<input type="password"[^>]*id="([^"]+)"', html) + re.findall(
        r'<input[^>]*id="([^"]+)"[^>]*type="password"', html
    )


@pytest.mark.django_db
class TestEveryPasswordBoxHasOne:
    def test_log_in_has_one(self, client):
        html = client.get(reverse("account_login")).content.decode()
        assert buttons(html) == ["id_password"]

    def test_sign_up_has_two(self, client):
        html = client.get(reverse("account_signup")).content.decode()
        assert buttons(html) == ["id_password1", "id_password2"]

    def test_choosing_a_new_password_has_two(self, client):
        verified_account("bob@example.com")
        client.post(reverse("account_reset_password"), {"email": "bob@example.com"})
        link = re.search(r"https?://\S+/accounts/password/reset/key/\S+/", mail.outbox[-1].body)
        html = client.get(link.group(0), follow=True).content.decode()
        assert "Choose a new password" in html
        assert buttons(html) == ["id_password1", "id_password2"]

    def test_each_button_belongs_to_a_password_box_on_the_same_page(self, client):
        for name in ("account_login", "account_signup"):
            html = client.get(reverse(name)).content.decode()
            assert sorted(buttons(html)) == sorted(set(password_boxes(html)))

    def test_no_other_box_gets_one(self, client):
        html = client.get(reverse("account_reset_password")).content.decode()
        assert buttons(html) == [] and 'name="email"' in html


@pytest.mark.django_db
def test_the_button_is_hidden_until_the_script_runs_and_cannot_submit_the_form(client):
    """Without JavaScript there must be no button that does nothing, and none that submits."""
    html = client.get(reverse("account_login")).content.decode()
    (tag,) = [match.group(0) for match in BUTTON.finditer(html)]
    assert " hidden" in tag and 'type="button"' in tag and 'aria-pressed="false"' in tag
    assert ">Show password</button>" in html


def test_the_script_reveals_it_switches_it_and_puts_the_dots_back_before_sending():
    script = (Path(settings.BASE_DIR) / "static" / "js" / "live-hints.js").read_text()
    assert "[data-show-password]" in script and "button.hidden = false" in script
    assert '"Hide password"' in script and '"Show password"' in script
    # Back to dots on submit, so the browser never stores it as ordinary text.
    assert 'addEventListener("submit"' in script and "show(false)" in script


def test_the_script_is_on_every_page():
    base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text()
    assert "js/live-hints.js" in base
