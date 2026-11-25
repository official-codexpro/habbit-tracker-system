from django.db import models
from django.db.models import Q
from django.utils import timezone


class EmailNotification(models.Model):
    class Type(models.TextChoices):
        TASK_CREATED = "TASK_CREATED", "New task created"
        MORNING_REPORT = "MORNING_REPORT", "Morning briefing"
        NIGHTLY_REPORT = "NIGHTLY_REPORT", "Nightly progress report"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    notification_type = models.CharField(max_length=20, choices=Type.choices)
    task = models.ForeignKey(
        "tasks.Task",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_notifications",
    )
    report_date = models.DateField(null=True, blank=True)
    is_manual = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["notification_type", "task"],
                condition=Q(notification_type="TASK_CREATED", task__isnull=False),
                name="notification_task_type_once",
            ),
            models.UniqueConstraint(
                fields=["notification_type", "report_date"],
                condition=Q(
                    notification_type__in=["MORNING_REPORT", "NIGHTLY_REPORT"],
                    report_date__isnull=False,
                    is_manual=False,
                ),
                name="notification_report_type_date_once",
            ),
            models.UniqueConstraint(
                fields=["notification_type", "report_date", "is_manual"],
                condition=Q(
                    notification_type__in=["MORNING_REPORT", "NIGHTLY_REPORT"],
                    report_date__isnull=False,
                    is_manual=True,
                ),
                name="notification_manual_report_once",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        notification_type="TASK_CREATED",
                        report_date__isnull=True,
                    )
                    | Q(
                        notification_type__in=["MORNING_REPORT", "NIGHTLY_REPORT"],
                        task__isnull=True,
                        report_date__isnull=False,
                    )
                ),
                name="notification_target_matches_type",
            ),
        ]

    def __str__(self):
        target = self.task or self.report_date
        return f"{self.get_notification_type_display()} — {target} ({self.status})"


class SchedulerLease(models.Model):
    """Database lease so only one scheduler process sends scheduled reports."""

    name = models.CharField(max_length=40, primary_key=True, default="email-scheduler")
    owner_token = models.CharField(max_length=36, blank=True)
    lease_until = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.name}: {self.owner_token or 'unclaimed'}"


class TaskCreationRequest(models.Model):
    """Idempotency key for retried task form/API submissions."""

    key = models.CharField(max_length=64, primary_key=True)
    task = models.ForeignKey(
        "tasks.Task",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="creation_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key
