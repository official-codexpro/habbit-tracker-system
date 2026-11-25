from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from notifications.models import EmailNotification
from notifications.services import deliver_notification, queue_daily_report


class Command(BaseCommand):
    help = "Send a morning briefing or nightly report manually for a date."

    def add_arguments(self, parser):
        parser.add_argument("report", choices=["morning", "nightly"])
        parser.add_argument("--date", dest="report_date", help="Date in YYYY-MM-DD format.")
        parser.add_argument(
            "--retry", action="store_true", help="Retry a prior failed report now."
        )

    def handle(self, *args, **options):
        try:
            report_date = date.fromisoformat(options["report_date"]) if options["report_date"] else timezone.localdate()
        except ValueError as exc:
            raise CommandError("--date must use YYYY-MM-DD format.") from exc
        kind = (
            EmailNotification.Type.MORNING_REPORT
            if options["report"] == "morning"
            else EmailNotification.Type.NIGHTLY_REPORT
        )
        notification, created = queue_daily_report(kind, report_date, manual=True)
        if notification.status == EmailNotification.Status.SENT:
            self.stdout.write(self.style.WARNING("This report was already sent; skipped."))
            return
        if options["retry"] and notification.status == EmailNotification.Status.FAILED:
            EmailNotification.objects.filter(pk=notification.pk).update(
                status=EmailNotification.Status.PENDING,
                attempts=0,
                next_attempt_at=timezone.now(),
            )
        if not deliver_notification(notification.pk, force=options["retry"] or created):
            raise CommandError("Report was not sent. Check the notification log and server log.")
        self.stdout.write(self.style.SUCCESS("Report sent successfully."))
