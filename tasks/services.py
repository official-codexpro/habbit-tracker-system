from datetime import date, datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Task, TaskCompletion


class InvalidOccurrenceTransition(ValueError):
    """Raised when an occurrence cannot be moved to the requested status."""


def _validate_target_date(target_date):
    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        raise TypeError("target_date must be a datetime.date.")


def generate_task_occurrences(target_date):
    _validate_target_date(target_date)
    tasks = (
        Task.objects.filter(is_active=True, start_date__lte=target_date)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=target_date))
        .only("id", "recurrence_type", "recurrence_days", "start_date", "end_date", "is_active")
    )
    occurrences = []

    with transaction.atomic():
        for task in tasks:
            if not task.is_scheduled_for(target_date):
                continue

            occurrence, created = TaskCompletion.objects.get_or_create(
                task=task,
                scheduled_date=target_date,
            )
            if not created and occurrence.is_superseded:
                TaskCompletion.objects.filter(
                    pk=occurrence.pk,
                    is_superseded=True,
                ).update(is_superseded=False, updated_at=timezone.now())
                occurrence.is_superseded = False
            occurrences.append(occurrence)

    return occurrences


def synchronize_future_occurrences(task, from_date=None):
    from_date = from_date or timezone.localdate()
    _validate_target_date(from_date)
    future = TaskCompletion.objects.filter(
        task=task,
        scheduled_date__gt=from_date,
        is_superseded=False,
    ).only("id", "scheduled_date")
    superseded_ids = [
        occurrence.pk
        for occurrence in future.iterator()
        if not task.is_scheduled_for(occurrence.scheduled_date)
    ]
    if superseded_ids:
        return TaskCompletion.objects.filter(pk__in=superseded_ids).update(
            is_superseded=True,
            updated_at=timezone.now(),
        )
    return 0


def archive_task(task):
    with transaction.atomic():
        archived_task = Task.objects.select_for_update().get(pk=task.pk)
        if archived_task.is_active:
            archived_task.is_active = False
            archived_task.save(update_fields=["is_active", "updated_at"])
        synchronize_future_occurrences(archived_task)
    return archived_task


def get_tasks_for_date(target_date):
    _validate_target_date(target_date)
    generated_occurrences = generate_task_occurrences(target_date)
    occurrences = TaskCompletion.objects.filter(
        scheduled_date=target_date,
        is_superseded=False,
    )
    if target_date >= timezone.localdate():
        occurrences = occurrences.filter(
            task__is_active=True,
            task_id__in=[occurrence.task_id for occurrence in generated_occurrences],
        )
    return occurrences.select_related("task", "task__category").order_by(
        "task__title", "pk"
    )


def get_pending_tasks(target_date):
    return get_tasks_for_date(target_date).filter(status=TaskCompletion.Status.PENDING)


def get_completed_tasks(target_date):
    return get_tasks_for_date(target_date).filter(status=TaskCompletion.Status.COMPLETED)


def get_task_completion_summary(target_date):
    counts = get_tasks_for_date(target_date).aggregate(
        total_scheduled=Count("pk"),
        completed=Count("pk", filter=Q(status=TaskCompletion.Status.COMPLETED)),
        pending=Count("pk", filter=Q(status=TaskCompletion.Status.PENDING)),
        skipped=Count("pk", filter=Q(status=TaskCompletion.Status.SKIPPED)),
    )
    total = counts["total_scheduled"]
    counts["completion_percentage"] = (
        counts["completed"] * 100 / total if total else 0
    )
    return counts


def get_task_history(task_id):
    return TaskCompletion.objects.filter(task_id=task_id).select_related(
        "task"
    ).order_by("-scheduled_date", "-pk")


def get_tasks_by_category(category_id, target_date):
    return get_tasks_for_date(target_date).filter(task__category_id=category_id)


def complete_task_occurrence(occurrence_id):
    with transaction.atomic():
        occurrence = (
            TaskCompletion.objects.select_for_update()
            .select_related("task")
            .get(pk=occurrence_id)
        )
        if occurrence.status == TaskCompletion.Status.COMPLETED:
            return occurrence
        if occurrence.is_superseded or not occurrence.task.is_active:
            raise InvalidOccurrenceTransition("This occurrence is no longer scheduled.")
        if occurrence.status != TaskCompletion.Status.PENDING:
            raise InvalidOccurrenceTransition("Only pending occurrences can be completed.")

        occurrence.status = TaskCompletion.Status.COMPLETED
        occurrence.completed_at = timezone.now()
        occurrence.completion_cycle += 1
        occurrence.save(
            update_fields=[
                "status",
                "completed_at",
                "completion_cycle",
                "updated_at",
            ]
        )
        from gamification.services import award_task_xp

        award_task_xp(occurrence.pk)
        occurrence.refresh_from_db()
        return occurrence


def undo_task_completion(occurrence_id):
    with transaction.atomic():
        occurrence = TaskCompletion.objects.select_for_update().get(pk=occurrence_id)
        if occurrence.status == TaskCompletion.Status.PENDING:
            return occurrence
        if occurrence.status != TaskCompletion.Status.COMPLETED:
            raise InvalidOccurrenceTransition("Only completed occurrences can be undone.")

        occurrence.status = TaskCompletion.Status.PENDING
        occurrence.completed_at = None
        occurrence.save(update_fields=["status", "completed_at", "updated_at"])
        from gamification.services import reverse_task_xp

        reverse_task_xp(occurrence.pk)
        occurrence.refresh_from_db()
        return occurrence


def skip_task_occurrence(occurrence_id):
    with transaction.atomic():
        occurrence = (
            TaskCompletion.objects.select_for_update()
            .select_related("task")
            .get(pk=occurrence_id)
        )
        if occurrence.status == TaskCompletion.Status.SKIPPED:
            return occurrence
        if occurrence.is_superseded or not occurrence.task.is_active:
            raise InvalidOccurrenceTransition("This occurrence is no longer scheduled.")
        if occurrence.status != TaskCompletion.Status.PENDING:
            raise InvalidOccurrenceTransition("Only pending occurrences can be skipped.")

        occurrence.status = TaskCompletion.Status.SKIPPED
        occurrence.save(update_fields=["status", "updated_at"])
        return occurrence
