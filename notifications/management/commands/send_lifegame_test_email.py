from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError

from notifications.services import validate_email_configuration


class Command(BaseCommand):
    help = "Validate Gmail SMTP settings and send a test message."

    def add_arguments(self, parser):
        parser.add_argument("recipient", nargs="?", help="Optional test recipient address.")

    def handle(self, *args, **options):
        try:
            recipients = [options["recipient"]] if options["recipient"] else validate_email_configuration()
            if options["recipient"]:
                validate_email_configuration()
            message = EmailMultiAlternatives(
                subject="LIFEGAME — SMTP test",
                body="Your LIFEGAME Gmail SMTP configuration is working.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
            )
            message.send(fail_silently=False)
        except Exception as exc:
            raise CommandError(f"SMTP test failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {', '.join(recipients)}."))
