import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from tasks.models import Task, TaskCompletion
from tasks.services import get_tasks_for_date

from .models import EmailNotification

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 8
STALE_SEND_MINUTES = 15


def validate_email_configuration():
    """Fail early with actionable errors without ever logging the password."""
    problems = []
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        problems.append("EMAIL_BACKEND must use Django's SMTP backend.")
    if settings.EMAIL_HOST != "smtp.gmail.com":
        problems.append("EMAIL_HOST must be smtp.gmail.com for Gmail delivery.")
    if settings.EMAIL_PORT != 587:
        problems.append("EMAIL_PORT must be 587 for Gmail SMTP with TLS.")
    if not settings.EMAIL_USE_TLS:
        problems.append("EMAIL_USE_TLS must be enabled.")
    if not settings.EMAIL_HOST_USER:
        problems.append("Set EMAIL_HOST_USER to your Gmail address.")
    else:
        try:
            validate_email(settings.EMAIL_HOST_USER)
        except Exception:
            problems.append("EMAIL_HOST_USER must be a valid email address.")
    if len(settings.EMAIL_HOST_PASSWORD) != 16:
        problems.append("EMAIL_HOST_PASSWORD must be your 16-character Gmail App Password.")
    if not settings.DEFAULT_FROM_EMAIL:
        problems.append("Set DEFAULT_FROM_EMAIL (usually the same as EMAIL_HOST_USER).")
    else:
        try:
            validate_email(settings.DEFAULT_FROM_EMAIL)
        except Exception:
            problems.append("DEFAULT_FROM_EMAIL must be a valid email address.")
    recipients = getattr(settings, "EMAIL_NOTIFICATION_TO", [])
    if not recipients:
        problems.append("Set EMAIL_NOTIFICATION_TO or EMAIL_HOST_USER as the recipient.")
    for recipient in recipients:
        try:
            validate_email(recipient)
        except Exception:
            problems.append(f"Invalid notification recipient: {recipient!r}.")
    if problems:
        raise ImproperlyConfigured("Email configuration is incomplete: " + " ".join(problems))
    return recipients


def _day_bounds(target_date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    end = timezone.make_aware(datetime.combine(target_date + timedelta(days=1), time.min), tz)
    return start, end


def _outstanding_tasks(today):
    return TaskCompletion.objects.filter(
        status=TaskCompletion.Status.PENDING,
        is_superseded=False,
        task__is_active=True,
    ).select_related("task", "task__category").order_by(
        "scheduled_date", "task__title", "pk"
    )


def build_report_context(notification):
    report_date = notification.report_date or timezone.localdate()
    scheduled_today = list(get_tasks_for_date(report_date))
    outstanding = list(_outstanding_tasks(report_date))
    overdue = [row for row in outstanding if row.scheduled_date < report_date]
    pending_today = [row for row in scheduled_today if row.status == TaskCompletion.Status.PENDING]
    upcoming_deadlines = []
    for day_offset in range(1, 8):
        upcoming_deadlines.extend(
            row for row in get_tasks_for_date(report_date + timedelta(days=day_offset))
            if row.status == TaskCompletion.Status.PENDING
        )
    important = [
        row for row in [*overdue, *pending_today, *upcoming_deadlines]
        if row.task.difficulty in {Task.Difficulty.HARD, Task.Difficulty.EXTREME}
    ]

    if notification.notification_type == EmailNotification.Type.MORNING_REPORT:
        return {
            "report_date": report_date,
            "scheduled_today": scheduled_today,
            "pending_tasks": outstanding,
            "overdue_tasks": overdue,
            "high_priority_tasks": important,
            "due_today": pending_today,
            "upcoming_deadlines": upcoming_deadlines,
            "pending_count": len(outstanding),
            "empty": not scheduled_today and not overdue and not upcoming_deadlines,
            "opening": "A new day is a fresh chance to make meaningful progress.",
        }

    start, end = _day_bounds(report_date)
    completed_today = list(
        TaskCompletion.objects.filter(
            status=TaskCompletion.Status.COMPLETED,
            completed_at__gte=start,
            completed_at__lt=end,
        ).select_related("task", "task__category").order_by("completed_at", "pk")
    )
    created_today = list(
        Task.objects.filter(created_at__gte=start, created_at__lt=end)
        .select_related("category").order_by("created_at", "pk")
    )
    total_today = len(scheduled_today)
    completion_percentage = round(
        len([row for row in scheduled_today if row.status == TaskCompletion.Status.COMPLETED])
        * 100 / total_today
    ) if total_today else 0
    if total_today == 0:
        summary = "A quiet day with no tasks scheduled. Tomorrow is another opportunity to begin."
    elif completion_percentage == 100:
        summary = "Every scheduled task is complete. Excellent work today."
    elif completion_percentage >= 50:
        summary = "You made solid progress today. Carry that momentum into tomorrow."
    else:
        summary = "Today is complete. Review what matters most and start fresh tomorrow."
    return {
        "report_date": report_date,
        "completed_tasks": completed_today,
        "pending_tasks": outstanding,
        "overdue_tasks": overdue,
        "created_tasks": created_today,
        "important_unfinished": [*overdue, *pending_today],
        "total_completed": len(completed_today),
        "pending_count": len(outstanding),
        "completion_percentage": completion_percentage,
        "summary": summary,
        "empty": not scheduled_today and not overdue and not created_today,
    }


def _task_created_context(notification):
    task = notification.task
    if task is None:
        raise ValueError("The task for this new-task notification no longer exists.")
    return {
        "task": task,
        "created_at": timezone.localtime(task.created_at),
        "due_date": _next_scheduled_date(task),
        "priority": task.get_difficulty_display(),
    }


def _next_scheduled_date(task):
    today = timezone.localdate()
    first_candidate = max(today, task.start_date)
    search_days = 0 if task.recurrence_type == Task.RecurrenceType.ONCE else 6
    for offset in range(search_days + 1):
        candidate = first_candidate + timedelta(days=offset)
        if task.end_date and candidate > task.end_date:
            return None
        if task.is_scheduled_for(candidate):
            return candidate
    return None


def notification_subject(notification):
    if notification.notification_type == EmailNotification.Type.MORNING_REPORT:
        return "LIFEGAME — Your Daily Task Briefing"
    if notification.notification_type == EmailNotification.Type.NIGHTLY_REPORT:
        return "LIFEGAME — Your Daily Progress Report"
    return f"LIFEGAME — New task: {notification.task.title if notification.task else 'Task'}"


def _claim_notification(notification_id, *, force=False):
    now = timezone.now()
    stale_before = now - timedelta(minutes=STALE_SEND_MINUTES)
    EmailNotification.objects.filter(
        pk=notification_id,
        status=EmailNotification.Status.SENDING,
        last_attempt_at__lt=stale_before,
    ).update(
        status=EmailNotification.Status.FAILED,
        error_message="Previous send attempt expired; retrying after scheduler recovery.",
        next_attempt_at=now,
    )
    query = EmailNotification.objects.filter(
        pk=notification_id,
        attempts__lt=MAX_ATTEMPTS,
        status__in=[EmailNotification.Status.PENDING, EmailNotification.Status.FAILED],
    )
    if not force:
        query = query.filter(next_attempt_at__lte=now)
    return query.update(
        status=EmailNotification.Status.SENDING,
        attempts=F("attempts") + 1,
        last_attempt_at=now,
        error_message="",
    ) == 1

def deliver_notification(notification_id, *, force=False):
    """Claim and send once; failures stay recorded and are retried by the scheduler."""
    with transaction.atomic():
        if not _claim_notification(notification_id, force=force):
            return False
    notification = EmailNotification.objects.select_related(
        "task", "task__category"
    ).get(pk=notification_id)
    try:
        recipients = validate_email_configuration()
        context = (
            _task_created_context(notification)
            if notification.notification_type == EmailNotification.Type.TASK_CREATED
            else build_report_context(notification)
        )
        template_name = {
            EmailNotification.Type.TASK_CREATED: "emails/task_created",
            EmailNotification.Type.MORNING_REPORT: "emails/morning_report",
            EmailNotification.Type.NIGHTLY_REPORT: "emails/nightly_report",
        }[notification.notification_type]
        context["notification"] = notification
        message = EmailMultiAlternatives(
            subject=notification_subject(notification),
            body=render_to_string(f"{template_name}.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(
            render_to_string(f"{template_name}.html", context), "text/html"
        )
        sent_count = message.send(fail_silently=False)
        if sent_count != 1:
            raise RuntimeError("SMTP backend did not accept the email for delivery.")
    except Exception as exc:
        now = timezone.now()
        current = EmailNotification.objects.get(pk=notification_id)
        delay_minutes = min(60, 2 ** max(current.attempts - 1, 0))
        EmailNotification.objects.filter(pk=notification_id).update(
            status=EmailNotification.Status.FAILED,
            error_message=str(exc)[:4000],
            next_attempt_at=now + timedelta(minutes=delay_minutes),
        )
        logger.exception(
            "Email delivery failed for notification %s (%s), attempt %s.",
            notification_id,
            notification.notification_type,
            current.attempts,
        )
        return False

    EmailNotification.objects.filter(pk=notification_id).update(
        status=EmailNotification.Status.SENT,
        sent_at=timezone.now(),
        error_message="",
    )
    logger.info("Email notification %s sent successfully.", notification_id)
    return True


def queue_daily_report(notification_type, report_date, *, manual=False):
    notification, created = EmailNotification.objects.get_or_create(
        notification_type=notification_type,
        report_date=report_date,
        is_manual=manual,
        defaults={"status": EmailNotification.Status.PENDING},
    )
    return notification, created


def enqueue_due_reports(now=None):
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    queued = []
    if local_now.time() >= time(7, 0):
        queued.append(queue_daily_report(EmailNotification.Type.MORNING_REPORT, today)[0].pk)
    if local_now.time() >= time(22, 0):
        queued.append(queue_daily_report(EmailNotification.Type.NIGHTLY_REPORT, today)[0].pk)
    return queued


def retry_due_notifications(limit=25):
    now = timezone.now()
    ids = list(
        EmailNotification.objects.filter(
            status__in=[EmailNotification.Status.PENDING, EmailNotification.Status.FAILED],
            attempts__lt=MAX_ATTEMPTS,
            next_attempt_at__lte=now,
        ).order_by("created_at").values_list("pk", flat=True)[:limit]
    )
    return sum(deliver_notification(notification_id) for notification_id in ids)
