from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from tasks.models import Task, TaskCategory, TaskCompletion
from tasks.services import generate_task_occurrences
from tasks.services import complete_task_occurrence

from .models import EmailNotification, SchedulerLease
from .services import (
    build_report_context,
    deliver_notification,
    queue_daily_report,
    validate_email_configuration,
)


EMAIL_SETTINGS = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "DEFAULT_FROM_EMAIL": "lifegame@example.com",
    "EMAIL_NOTIFICATION_TO": ["player@example.com"],
}


@override_settings(**EMAIL_SETTINGS)
class NotificationTests(TestCase):
    def setUp(self):
        self.category = TaskCategory.objects.create(name="Learning")
        mail.outbox = []

    def create_task(self, title="Read a chapter", **overrides):
        values = {
            "title": title,
            "description": "Read and take notes.",
            "category": self.category,
            "difficulty": Task.Difficulty.HARD,
            "start_date": timezone.localdate(),
        }
        values.update(overrides)
        return Task.objects.create(**values)

    @patch("notifications.services.validate_email_configuration", return_value=["player@example.com"])
    def test_task_creation_sends_one_message_and_updates_send_none(self, _validate):
        with self.captureOnCommitCallbacks(execute=True):
            task = self.create_task()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Read a chapter", mail.outbox[0].subject)
        self.assertIn("Priority: Hard", mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].alternatives)
        delivery = EmailNotification.objects.get(task=task)
        self.assertEqual(delivery.status, EmailNotification.Status.SENT)

        task.title = "Updated chapter"
        task.save()
        occurrence = generate_task_occurrences(timezone.localdate())[0]
        complete_task_occurrence(occurrence.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailNotification.objects.filter(task=task).count(), 1)

    def test_repeated_api_create_request_with_same_key_creates_one_task(self):
        import json

        from django.urls import reverse

        payload = {
            "title": "Retry-safe task",
            "description": "Only one record should be created.",
            "category": self.category.pk,
            "difficulty": Task.Difficulty.NORMAL,
            "estimated_minutes": 15,
            "xp_reward": 10,
            "recurrence_type": Task.RecurrenceType.ONCE,
            "recurrence_days": [],
            "start_date": timezone.localdate().isoformat(),
            "end_date": "",
            "idempotency_key": "stable-create-attempt-001",
        }
        url = reverse("tasks:api_create")
        first = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        retry = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json()["id"], retry.json()["id"])
        self.assertEqual(Task.objects.filter(title="Retry-safe task").count(), 1)
        self.assertEqual(
            EmailNotification.objects.filter(
                notification_type=EmailNotification.Type.TASK_CREATED
            ).count(),
            1,
        )

    @patch("notifications.services.validate_email_configuration", return_value=["player@example.com"])
    def test_morning_report_uses_database_records_and_deduplicates(self, _validate):
        today = timezone.localdate()
        task = self.create_task()
        generate_task_occurrences(today)
        first, created = queue_daily_report(EmailNotification.Type.MORNING_REPORT, today)
        second, created_again = queue_daily_report(EmailNotification.Type.MORNING_REPORT, today)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(deliver_notification(first.pk, force=True))
        self.assertFalse(deliver_notification(second.pk, force=True))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(task.title, mail.outbox[0].body)
        self.assertIn("DUE TODAY", mail.outbox[0].body)

    def test_manual_report_does_not_consume_scheduled_report_slot(self):
        today = timezone.localdate()
        scheduled, _ = queue_daily_report(EmailNotification.Type.MORNING_REPORT, today)
        manual, _ = queue_daily_report(
            EmailNotification.Type.MORNING_REPORT, today, manual=True
        )
        self.assertNotEqual(scheduled.pk, manual.pk)
        self.assertFalse(scheduled.is_manual)
        self.assertTrue(manual.is_manual)

    @patch("notifications.services.validate_email_configuration", return_value=["player@example.com"])
    def test_nightly_report_counts_real_completion_and_task_creation(self, _validate):
        today = timezone.localdate()
        task = self.create_task("Finish the lesson")
        occurrence = generate_task_occurrences(today)[0]
        occurrence.status = TaskCompletion.Status.COMPLETED
        occurrence.completed_at = timezone.now()
        occurrence.save(update_fields=["status", "completed_at", "updated_at"])

        report, _ = queue_daily_report(EmailNotification.Type.NIGHTLY_REPORT, today)
        context = build_report_context(report)
        self.assertEqual(context["total_completed"], 1)
        self.assertEqual(context["completion_percentage"], 100)
        self.assertEqual(context["created_tasks"], [task])
        self.assertTrue(deliver_notification(report.pk, force=True))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("COMPLETED TODAY", mail.outbox[0].body)
        self.assertIn(task.title, mail.outbox[0].body)

    @patch("notifications.services.validate_email_configuration", return_value=["player@example.com"])
    def test_empty_morning_report_has_clear_empty_state(self, _validate):
        report, _ = queue_daily_report(
            EmailNotification.Type.MORNING_REPORT, timezone.localdate()
        )
        self.assertTrue(deliver_notification(report.pk, force=True))
        self.assertIn("There are no scheduled or overdue tasks", mail.outbox[0].body)

    @patch("notifications.services.validate_email_configuration", return_value=["player@example.com"])
    @patch("notifications.services.EmailMultiAlternatives.send", side_effect=OSError("SMTP unavailable"))
    def test_smtp_failure_is_recorded_and_not_marked_sent(self, _send, _validate):
        task = self.create_task()
        notification = EmailNotification.objects.get(task=task)
        with self.assertLogs("notifications.services", level="ERROR"):
            self.assertFalse(deliver_notification(notification.pk, force=True))
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.FAILED)
        self.assertEqual(notification.attempts, 1)
        self.assertIn("SMTP unavailable", notification.error_message)
        self.assertIsNone(notification.sent_at)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.gmail.com",
        EMAIL_PORT=587,
        EMAIL_USE_TLS=True,
        EMAIL_HOST_USER="",
        EMAIL_HOST_PASSWORD="",
        DEFAULT_FROM_EMAIL="",
        EMAIL_NOTIFICATION_TO=[],
    )
    def test_missing_smtp_credentials_produce_actionable_validation(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "EMAIL_HOST_USER"):
            validate_email_configuration()

    def test_scheduler_skips_when_another_instance_has_the_lease(self):
        SchedulerLease.objects.update_or_create(
            name="email-scheduler",
            defaults={
                "owner_token": "active-process",
                "lease_until": timezone.now() + timedelta(minutes=2),
            },
        )
        call_command("run_email_scheduler", once=True)
        self.assertEqual(
            SchedulerLease.objects.get(name="email-scheduler").owner_token,
            "active-process",
        )
