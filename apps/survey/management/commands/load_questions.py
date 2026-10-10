"""
Load the real survey statements from a private JSON file.

The statements are never committed. On a laptop the file lives in the gitignored
private/ directory and this command loads it; on the live site a superuser
pastes or uploads the same file on the survey version's admin page, which runs
the same checks. Running it again with the same file changes nothing.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.survey import services


class Command(BaseCommand):
    help = "Set the current survey version's question text and metadata from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file: a list of {position, text, ...} objects")

    def handle(self, *args, **options):
        version = services.current_version()
        if version is None:
            raise CommandError("There is no survey version; run migrate first.")
        try:
            with open(options["path"], "rb") as f:
                raw = f.read(services.MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise CommandError(f"Cannot read {options['path']}: {exc.strerror}") from exc
        try:
            changes = services.load_questions(version, services.parse_questions(raw))
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Loaded {changes.total} questions into survey version {version.number} "
            f"({changes.changed} changed)."
        )
