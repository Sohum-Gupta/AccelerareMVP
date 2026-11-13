"""
The worker: the one process that does the background jobs.

    uv run python manage.py run_worker          # on a laptop, in a second terminal
    uv run python manage.py run_worker --once   # do what is due, then stop

On the server it runs in its own container beside the website
(deploy/docker-compose.yml). It reads the queue, does the oldest job that is
due, and sleeps for a second when there is nothing to do. When it is told to
stop (a deploy restarts it), it finishes the job in hand first.
"""

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from apps.jobs import services

logger = logging.getLogger(__name__)

IDLE_SECONDS = 1
# How often to look for jobs a dead worker left behind.
STUCK_CHECK_SECONDS = 60
# After losing the database, wait this long before trying again.
DATABASE_RETRY_SECONDS = 5


class Command(BaseCommand):
    help = "Do the background jobs in the queue, one at a time, until told to stop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Do every job that is due now, then stop. For a test, or a check after a deploy.",
        )

    def handle(self, *args, once=False, **options):
        self.stopping = False
        if not once:
            # Docker sends SIGTERM to stop a container; Ctrl-C sends SIGINT.
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        self.stdout.write(f"Worker started. It knows how to do: {', '.join(services.kinds())}.")
        # None means "not yet": the first pass always looks. (The clock used
        # here counts from when the machine started, which can be seconds ago.)
        last_stuck_check = None
        while not self.stopping:
            try:
                due = last_stuck_check is None or (
                    time.monotonic() - last_stuck_check >= STUCK_CHECK_SECONDS
                )
                if due:
                    services.requeue_stuck()
                    last_stuck_check = time.monotonic()
                ran = services.run_one()
            except DatabaseError as error:
                # The database went away (a restart, a network blip). Drop the
                # broken connection and try again shortly rather than dying.
                logger.error("The worker lost the database (%s); retrying", type(error).__name__)
                close_old_connections()
                if once:
                    raise
                self.pause(DATABASE_RETRY_SECONDS)
                continue
            if not ran:
                if once:
                    break
                # Give back a connection that has sat idle too long.
                close_old_connections()
                self.pause(IDLE_SECONDS)
        self.stdout.write("Worker stopped.")

    def stop(self, signum, frame):
        """Asked to stop: finish the job in hand (the loop checks this flag) and leave."""
        self.stopping = True

    def pause(self, seconds):
        """Sleep, but wake at once when asked to stop."""
        waited = 0.0
        while waited < seconds and not self.stopping:
            time.sleep(0.2)
            waited += 0.2
