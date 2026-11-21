from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class LearningGoal(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    priority = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "target_date", "title"]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority__gte=1, priority__lte=4),
                name="learning_goal_priority_range",
            ),
        ]

    def clean(self):
        super().clean()
        self.title = self.title.strip() if self.title else ""
        if not self.title:
            raise ValidationError({"title": "Enter a learning goal title."})

    def __str__(self):
        return self.title


class Skill(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    learning_goals = models.ManyToManyField(
        LearningGoal,
        blank=True,
        related_name="skills",
    )
    current_proficiency = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    target_proficiency = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(current_proficiency__gte=1, current_proficiency__lte=5),
                name="skill_current_proficiency_range",
            ),
            models.CheckConstraint(
                condition=Q(target_proficiency__gte=1, target_proficiency__lte=5),
                name="skill_target_proficiency_range",
            ),
        ]

    def clean(self):
        super().clean()
        self.name = self.name.strip() if self.name else ""
        if not self.name:
            raise ValidationError({"name": "Enter a skill name."})

    def __str__(self):
        return self.name


class LearningCourse(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    skill = models.ForeignKey(
        Skill,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="courses",
    )
    learning_goal = models.ForeignKey(
        LearningGoal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="courses",
    )
    provider = models.CharField(max_length=200, blank=True)
    resource_url = models.URLField(blank=True)
    total_topics = models.PositiveIntegerField(null=True, blank=True)
    completed_topics = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )
    start_date = models.DateField(default=timezone.localdate)
    target_completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "pk"]
        indexes = [
            models.Index(fields=["status", "target_completion_date"], name="learn_course_status_target_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(completed_topics__gte=0),
                name="learning_course_completed_topics_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(total_topics__isnull=True) | Q(total_topics__gte=0),
                name="learning_course_total_topics_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        self.title = self.title.strip() if self.title else ""
        if not self.title:
            raise ValidationError({"title": "Enter a course title."})
        if self.target_completion_date and self.target_completion_date < self.start_date:
            raise ValidationError({"target_completion_date": "Target completion cannot be before the start date."})
        if self.total_topics is not None and self.completed_topics > self.total_topics:
            raise ValidationError({"completed_topics": "Completed topics cannot exceed total topics."})

    @property
    def has_topic_progress(self):
        if self.total_topics is None or self.total_topics == 0:
            return False
        if not self.topics.exists():
            return False
        return True

    @property
    def progress_percentage(self):
        if not self.has_topic_progress:
            return None
        return round(
            min(100, self.completed_topics * 100 / self.total_topics),
            1,
        )

    def sync_completed_topics(self):
        completed = self.topics.filter(status=LearningTopic.Status.COMPLETED).count()
        if self.completed_topics != completed:
            LearningCourse.objects.filter(pk=self.pk).update(completed_topics=completed)
            self.completed_topics = completed

    def __str__(self):
        return self.title


class LearningTopic(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"

    course = models.ForeignKey(
        LearningCourse,
        on_delete=models.CASCADE,
        related_name="topics",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )
    completion_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["course", "position", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "position"],
                name="learning_topic_unique_course_position",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1),
                name="learning_topic_position_positive",
            ),
        ]

    def clean(self):
        super().clean()
        self.title = self.title.strip() if self.title else ""
        if not self.title:
            raise ValidationError({"title": "Enter a topic title."})
        if self.status == self.Status.COMPLETED and self.completion_date is None:
            self.completion_date = timezone.localdate()
        if self.status != self.Status.COMPLETED:
            self.completion_date = None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.course.sync_completed_topics()

    def __str__(self):
        return f"{self.course.title}: {self.title}"


class LearningSession(models.Model):
    course = models.ForeignKey(
        LearningCourse,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    skill = models.ForeignKey(
        Skill,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    learning_goal = models.ForeignKey(
        LearningGoal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    title = models.CharField(max_length=200)
    topics_covered = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    session_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-session_date", "-created_at", "-pk"]
        indexes = [
            models.Index(fields=["session_date", "course"], name="learn_session_date_course_idx"),
            models.Index(fields=["session_date", "skill"], name="learn_session_date_skill_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_minutes__gte=1),
                name="learning_session_duration_positive",
            ),
        ]

    def clean(self):
        super().clean()
        self.title = self.title.strip() if self.title else ""
        if not self.title:
            raise ValidationError({"title": "Enter a learning session title."})
        if self.duration_minutes is None or self.duration_minutes < 1:
            raise ValidationError({"duration_minutes": "Duration must be greater than zero."})
        if self.session_date and self.session_date > timezone.localdate():
            raise ValidationError({"session_date": "Learning sessions cannot be dated in the future."})

    def __str__(self):
        return f"{self.title} ({self.duration_minutes} min)"
