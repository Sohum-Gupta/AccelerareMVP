"""
Load the real survey statements from a private JSON file.

The statements are never committed. On a laptop the file lives in the gitignored
private/ directory; on the server deploy.sh runs this on every deploy. Running it
again with the same file changes nothing.
"""

import json

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
            with open(options["path"], encoding="utf-8") as f:
                entries = json.load(f)
        except OSError as exc:
            raise CommandError(f"Cannot read {options['path']}: {exc.strerror}") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f"{options['path']} is not valid JSON: {exc}") from exc
        try:
            count = services.load_questions(version, entries)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(f"Loaded {count} questions into survey version {version.number}.")
