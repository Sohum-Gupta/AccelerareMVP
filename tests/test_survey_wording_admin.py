"""
Milestone 2, PR 9: a superuser loads the private survey wording from the admin.

Check, then preview (counts only), then Apply through survey.services.
Support staff never reach the page, and the wording never appears in the
preview, the messages, the admin history or the logs. Fixtures hold made-up
wording only.
"""

# ruff: noqa: F811  (tests take the imported fixtures as arguments)

import json
import logging

import pytest
from django.contrib.admin.models import LogEntry
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Account
from apps.survey import services
from apps.survey.models import Question

# root, bob and support are fixtures: pytest passes them in by name.
from .test_admin_and_guard import root  # noqa: F401
from .test_responses import bob, start, submit_row, support  # noqa: F401
from .test_survey import SAMPLE, sample_entries
from .test_verification import PASSWORD

SAMPLE_TEXTS = [entry["text"] for entry in sample_entries()]


def page_url():
    return reverse("admin:survey_surveyversion_load_wording", args=[services.current_version().pk])


def change_url():
    return reverse("admin:survey_surveyversion_change", args=[services.current_version().pk])


def texts():
    return list(services.current_version().questions.values_list("text", flat=True))


def check(client, wording="", upload=None):
    data = {"check": "Check", "wording": wording}
    if upload is not None:
        data["file"] = upload
    return client.post(page_url(), data)


def preview_fields(response):
    """The hidden fields the preview page sends back on Apply."""
    form = response.context["apply_form"]
    return {"wording": form["wording"].value(), "fingerprint": form["fingerprint"].value()}


def apply(client, fields, **extra):
    return client.post(page_url(), {"apply": "Apply", **fields, **extra}, follow=True)


def no_wording_in(text):
    return not any(sample in text for sample in SAMPLE_TEXTS)


@pytest.mark.django_db
class TestWhoCanReachIt:
    def test_the_button_shows_for_a_superuser_on_the_current_version(self, client, root):
        assert page_url() in client.get(change_url()).content.decode()

    def test_support_staff_see_no_button_and_are_refused(self, client, support):
        assert client.get(change_url()).status_code == 200  # they may view the version
        assert page_url() not in client.get(change_url()).content.decode()
        assert client.get(page_url()).status_code == 403
        assert check(client, SAMPLE.read_text()).status_code == 403
        assert texts() == [f"Question {n}" for n in range(1, 26)]

    def test_staff_without_the_group_are_refused(self, client, db):
        staff = Account.objects.create_user("staff@example.com", PASSWORD)
        staff.is_staff = True
        staff.save()
        client.force_login(staff)
        assert client.get(page_url()).status_code == 403

    def test_a_signed_in_non_staff_account_is_sent_to_the_admin_login(self, client, bob):
        client.force_login(bob)
        response = client.get(page_url())
        assert response.status_code == 302 and "/admin/login/" in response["Location"]

    def test_anonymous_is_sent_to_the_admin_login(self, client, db):
        response = client.get(page_url())
        assert response.status_code == 302 and "/admin/login/" in response["Location"]


@pytest.mark.django_db
class TestCheckAndApply:
    def test_paste_previews_counts_only_and_writes_nothing(self, client, root):
        response = check(client, SAMPLE.read_text())
        assert response.status_code == 200
        page = response.content.decode()
        flat = " ".join(page.split())
        assert (
            "Survey version 1 has 25 statements. This file changes the wording of 25, "
            "changes the extra fields of 3, and leaves 0 as they are." in flat
        )
        # The wording rides along only as the hidden field's value, never as text on the page.
        visible = page.replace(response.context["apply_form"]["wording"].as_widget(), "")
        assert no_wording_in(visible)
        assert texts() == [f"Question {n}" for n in range(1, 26)]

    def test_apply_loads_the_wording_and_logs_counts_without_the_wording(self, client, root):
        response = apply(client, preview_fields(check(client, SAMPLE.read_text())))
        assert response.redirect_chain[-1][0] == change_url()
        assert texts() == SAMPLE_TEXTS
        entry = LogEntry.objects.get()
        assert entry.user == root
        assert entry.object_repr == "Survey version 1"
        assert entry.change_message == (
            "Loaded the survey wording: 25 statements reworded, "
            "3 statements with changed extra fields, 0 statements unchanged."
        )
        assert no_wording_in(entry.object_repr + entry.change_message)
        shown = [str(m) for m in response.context["messages"]]
        assert shown == [entry.change_message]

    def test_upload_works_the_same(self, client, root):
        upload = SimpleUploadedFile("survey.json", SAMPLE.read_bytes(), "application/json")
        apply(client, preview_fields(check(client, upload=upload)))
        assert texts() == SAMPLE_TEXTS

    def test_the_pasted_field_is_marked_sensitive_for_error_reports(self, client, root):
        response = check(client, SAMPLE.read_text())
        assert response.wsgi_request.sensitive_post_parameters == ("wording",)

    def test_nothing_is_logged_that_contains_the_wording(self, client, root, caplog):
        caplog.set_level(logging.DEBUG)
        apply(client, preview_fields(check(client, SAMPLE.read_text())))
        assert no_wording_in(caplog.text)

    def test_applying_the_same_file_again_changes_nothing_and_logs_nothing(self, client, root):
        apply(client, preview_fields(check(client, SAMPLE.read_text())))
        response = check(client, SAMPLE.read_text())
        assert "Nothing would change" in response.content.decode()
        assert 'name="apply"' not in response.content.decode()
        assert LogEntry.objects.count() == 1

    def test_a_double_click_on_apply_is_harmless(self, client, root):
        fields = preview_fields(check(client, SAMPLE.read_text()))
        apply(client, fields)
        response = apply(client, fields)
        assert [str(m) for m in response.context["messages"]] == [
            "Nothing changed: the survey already has this wording."
        ]
        assert LogEntry.objects.count() == 1

    def test_a_change_by_someone_else_after_the_preview_is_refused(self, client, root):
        fields = preview_fields(check(client, SAMPLE.read_text()))
        other = sample_entries()
        other[0]["text"] = "Made-up wording from a second superuser"
        services.load_questions(services.current_version(), other)
        response = apply(client, fields)
        assert response.redirect_chain[-1][0] == page_url()
        assert "Check it again" in str(next(iter(response.context["messages"])))
        assert texts()[0] == "Made-up wording from a second superuser"
        assert LogEntry.objects.count() == 0

    def test_a_tampered_hidden_copy_is_rechecked(self, client, root):
        fields = preview_fields(check(client, SAMPLE.read_text()))
        fields["wording"] = json.dumps(sample_entries()[:24])
        response = apply(client, fields)
        assert "Positions must be exactly 1 to 25" in str(next(iter(response.context["messages"])))
        assert texts() == [f"Question {n}" for n in range(1, 26)]


@pytest.mark.django_db
class TestPeopleOnThisVersion:
    def test_preview_counts_unfinished_and_submitted_attempts(self, client, root, bob):
        start(bob)
        page = " ".join(check(client, SAMPLE.read_text()).content.decode().split())
        assert "1 unfinished attempt and 0 submitted surveys" in page
        assert 'name="understood"' not in page

    def test_a_submitted_survey_needs_the_box_ticked(self, client, root, bob):
        submit_row(start(bob))
        response = check(client, SAMPLE.read_text())
        page = " ".join(response.content.decode().split())
        assert "0 unfinished attempts and 1 submitted survey" in page
        fields = preview_fields(response)
        refused = client.post(page_url(), {"apply": "Apply", **fields})
        assert refused.status_code == 200
        assert "Tick the box to confirm." in refused.content.decode()
        assert texts() == [f"Question {n}" for n in range(1, 26)]
        apply(client, fields, understood="on")
        assert texts() == SAMPLE_TEXTS


@pytest.mark.django_db
class TestPlainEnglishErrors:
    @pytest.mark.parametrize(
        ("wording", "message"),
        [
            ("not json at all", "This is not valid JSON"),
            ('{"position": 1}', "The file must contain a list of questions."),
            (json.dumps(sample_entries()[:24]), "Positions must be exactly 1 to 25"),
            (
                json.dumps([*sample_entries()[:24], {"position": 24, "text": "Dup"}]),
                "Positions must be exactly 1 to 25",
            ),
            (
                json.dumps([*sample_entries()[:24], {"position": 25, "text": "  "}]),
                "Position 25 needs some text.",
            ),
        ],
    )
    def test_shows_the_message_and_writes_nothing(self, client, root, wording, message):
        response = check(client, wording)
        assert response.status_code == 200
        assert message in response.content.decode()
        assert response.context["changes"] is None
        assert texts() == [f"Question {n}" for n in range(1, 26)]

    def test_neither_or_both(self, client, root):
        assert "Paste the JSON or choose a file." in check(client).content.decode()
        upload = SimpleUploadedFile("survey.json", SAMPLE.read_bytes())
        both = check(client, SAMPLE.read_text(), upload).content.decode()
        assert "not both" in both

    def test_an_upload_over_the_limit_is_refused(self, client, root):
        upload = SimpleUploadedFile("big.json", b" " * (services.MAX_FILE_BYTES + 1))
        assert "larger than 200 KB" in check(client, upload=upload).content.decode()

    def test_an_error_never_quotes_the_wording(self, client, root):
        entries = sample_entries()
        entries[3]["text"] = "Sample statement 4 \x00"
        response = check(client, json.dumps(entries))
        errors = " ".join(response.context["form"].non_field_errors())
        assert "Position 4 contains something the database cannot store" in errors
        assert no_wording_in(errors)


@pytest.mark.django_db
def test_only_the_current_version_can_be_loaded(client, root):
    from django.utils import timezone

    from apps.survey.models import SurveyVersion

    old = services.current_version()
    SurveyVersion.objects.create(number=2, published_at=timezone.now(), question_count=1)
    url = reverse("admin:survey_surveyversion_load_wording", args=[old.pk])
    response = client.get(url, follow=True)
    assert "Only the current survey version can be loaded." in response.content.decode()
    assert (
        url
        not in client.get(
            reverse("admin:survey_surveyversion_change", args=[old.pk])
        ).content.decode()
    )
    assert Question.objects.filter(survey_version=old, text__startswith="Question ").count() == 25
