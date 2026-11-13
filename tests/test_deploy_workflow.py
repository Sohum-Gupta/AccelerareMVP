"""
A push to main that changes only documents is not deployed
(`paths-ignore` in .github/workflows/deploy.yml): rebuilding would produce the
image that is already running and restart the site for nothing.

That is only true while two things hold, and these tests hold them:

* everything on the skip list is kept out of the image by .dockerignore, so a
  change to it cannot change what runs on the server;
* the list is exactly the documents. `deploy/` and `tests/` are also kept out
  of the image, but they must never be skipped: the deploy job copies the files
  in `deploy/` to the server, and a change to the tests has to run on main.
"""

from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)
DOCUMENTS = {"docs", "NOTES.md", "README.md", "CLAUDE.md"}


def skipped_by_the_deploy():
    """The top-level names under `paths-ignore:` in deploy.yml ("docs/**" counts as "docs")."""
    lines = (ROOT / ".github" / "workflows" / "deploy.yml").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "paths-ignore:")
    names = []
    for line in lines[start + 1 :]:
        entry = line.strip()
        if not entry.startswith("- "):
            break
        names.append(entry[2:].strip("\"'").split("/")[0])
    return names


def kept_out_of_the_image():
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith(("#", "!"))}


def test_only_the_documents_skip_the_deploy():
    assert set(skipped_by_the_deploy()) == DOCUMENTS


def test_everything_that_skips_the_deploy_is_kept_out_of_the_image():
    for name in skipped_by_the_deploy():
        assert name in kept_out_of_the_image(), f"{name} is in the image, so it must deploy"


def test_the_skip_applies_to_pushes_only():
    """A pull request still runs its checks whatever it changes; only the deploy is skipped."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "paths-ignore" not in ci
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert deploy.count("paths-ignore:") == 1
    push = deploy.index("  push:")
    assert push < deploy.index("paths-ignore:") < deploy.index("  pull_request:")
