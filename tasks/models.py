from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone


def validate_recurrence_days(value):
    if not isinstance(value, list):
        raise ValidationError("Select weekdays as a list.")
    if any(type(day) is not int or day < 0 or day > 6 for day in value):
        raise ValidationError("Weekdays must be integers from 0 (Monday) to 6 (Sunday).")
    if len(value) != len(set(value)):
        raise ValidationError("A weekday can only be selected once.")


class TaskCategory(models.Model):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=7,
        default="#9b8cff",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Enter a six-digit hex color, such as #9b8cff.",
            )
        ],
    )
    icon = models.CharField(max_length=50, default="spark")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="task_category_name_ci_unique"),
        ]

    def clean(self):
        super().clean()
        self.name = self.name.strip() if self.name else self.name

    def __str__(self):
        return self.name


class Task(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "EASY", "Easy"
        NORMAL = "NORMAL", "Normal"
        HARD = "HARD", "Hard"
        EXTREME = "EXTREME", "Extreme"

    class RecurrenceType(models.TextChoices):
        ONCE = "ONCE", "Once"
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        CUSTOM = "CUSTOM", "Custom"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        TaskCategory,
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    difficulty = models.CharField(
        max_length=10,
        choices=Difficulty.choices,
        default=Difficulty.NORMAL,
    )
    estimated_minutes = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    xp_reward = models.PositiveIntegerField(
        default=25,
        validators=[MinValueValidator(0)],
    )
    recurrence_type = models.CharField(
        max_length=10,
        choices=RecurrenceType.choices,
        default=RecurrenceType.ONCE,
    )
    recurrence_days = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_recurrence_days],
    )
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(estimated_minutes__gte=0),
                name="task_estimated_minutes_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(xp_reward__gte=0),
                name="task_xp_reward_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="task_end_date_after_start_date",
            ),
            models.CheckConstraint(
                condition=Q(recurrence_type__in=["ONCE", "DAILY", "WEEKLY", "CUSTOM"]),
                name="task_recurrence_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(difficulty__in=["EASY", "NORMAL", "HARD", "EXTREME"]),
                name="task_difficulty_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active", "start_date"], name="task_active_start_idx"),
        ]

    def clean(self):
        super().clean()
        self.title = self.title.strip() if self.title else self.title

        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be before start date."})

        days = self.recurrence_days
        if not isinstance(days, list):
            return
        if self.recurrence_type in {
            self.RecurrenceType.WEEKLY,
            self.RecurrenceType.CUSTOM,
        } and not days:
            raise ValidationError(
                {"recurrence_days": "Select at least one weekday for this recurrence."}
            )
        if self.recurrence_type in {
            self.RecurrenceType.ONCE,
            self.RecurrenceType.DAILY,
        } and days:
            raise ValidationError(
                {"recurrence_days": "Weekdays only apply to weekly or custom recurrence."}
            )
        if all(type(day) is int and 0 <= day <= 6 for day in days):
            self.recurrence_days = sorted(days)

    def is_scheduled_for(self, target_date):
        if not self.is_active:
            return False
        if target_date < self.start_date:
            return False
        if self.end_date and target_date > self.end_date:
            return False
        if self.recurrence_type == self.RecurrenceType.ONCE:
            return target_date == self.start_date
        if self.recurrence_type == self.RecurrenceType.DAILY:
            return True
        if self.recurrence_type in {
            self.RecurrenceType.WEEKLY,
            self.RecurrenceType.CUSTOM,
        }:
            return target_date.weekday() in self.recurrence_days
        return False

    def __str__(self):
        return self.title


class TaskCompletion(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        SKIPPED = "SKIPPED", "Skipped"

    task = models.ForeignKey(
        Task,
        on_delete=models.PROTECT,
        related_name="occurrences",
    )
    scheduled_date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    xp_awarded = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    completion_cycle = models.PositiveIntegerField(default=0)
    is_superseded = models.BooleanField(
        default=False,
        help_text="Keeps an obsolete future schedule record without deleting its history.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_date", "task__title", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "scheduled_date"],
                name="task_completion_unique_task_date",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["PENDING", "COMPLETED", "SKIPPED"]),
                name="task_completion_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="COMPLETED", completed_at__isnull=False)
                    | (~Q(status="COMPLETED") & Q(completed_at__isnull=True))
                ),
                name="task_completion_timestamp_matches_status",
            ),
            models.CheckConstraint(
                condition=Q(xp_awarded__gte=0),
                name="task_completion_xp_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["scheduled_date", "status"],
                name="task_comp_date_status_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.status == self.Status.COMPLETED and self.completed_at is None:
            raise ValidationError({"completed_at": "Completed tasks need a completion timestamp."})
        if self.status != self.Status.COMPLETED and self.completed_at is not None:
            raise ValidationError(
                {"completed_at": "Only completed tasks can have a completion timestamp."}
            )

    def __str__(self):
        return f"{self.task} — {self.scheduled_date} ({self.get_status_display()})"
