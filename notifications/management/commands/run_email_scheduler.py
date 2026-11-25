import logging
import time
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import OperationalError
from django.db.models import Q
from django.utils import timezone

from notifications.models import SchedulerLease
from notifications.services import enqueue_due_reports, retry_due_notifications

logger = logging.getLogger("notifications.scheduler")
LEASE_NAME = "email-scheduler"
LEASE_SECONDS = 90
POLL_SECONDS = 20


class Command(BaseCommand):
    help = "Run the persistent LIFEGAME email report scheduler and retry worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="Run one scheduler pass and exit."
        )

    def handle(self, *args, **options):
        owner = str(uuid.uuid4())
        SchedulerLease.objects.get_or_create(name=LEASE_NAME)
        self.stdout.write("LIFEGAME email scheduler started (Asia/Kolkata).")
        try:
            while True:
                try:
                    now = timezone.now()
                    acquired = SchedulerLease.objects.filter(name=LEASE_NAME).filter(
                        Q(lease_until__lt=now) | Q(owner_token=owner)
                    ).update(
                        owner_token=owner,
                        lease_until=now + timedelta(seconds=LEASE_SECONDS),
                    ) == 1
                    if acquired:
                        enqueue_due_reports(now)
                        retry_due_notifications()
                    elif options["once"]:
                        self.stdout.write("Another scheduler owns the database lease.")
                        return
                except OperationalError:
                    logger.exception("Email scheduler database operation failed.")
                except Exception:
                    logger.exception("Email scheduler pass failed; it will retry.")
                if options["once"]:
                    return
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("\nLIFEGAME email scheduler stopping.")
        finally:
            SchedulerLease.objects.filter(
                name=LEASE_NAME, owner_token=owner
            ).update(owner_token="", lease_until=timezone.now())
