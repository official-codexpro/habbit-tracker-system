from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q


class PlayerProfile(models.Model):
    class Rank(models.TextChoices):
        BEGINNER = "BEGINNER", "Beginner"
        APPRENTICE = "APPRENTICE", "Apprentice"
        WARRIOR = "WARRIOR", "Warrior"
        ELITE = "ELITE", "Elite"
        MASTER = "MASTER", "Master"
        LEGEND = "LEGEND", "Legend"
        MYTHIC = "MYTHIC", "Mythic"

    singleton_key = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
        validators=[MinValueValidator(1), MaxValueValidator(1)],
    )
    display_name = models.CharField(max_length=80, default="Player One")
    total_xp = models.PositiveBigIntegerField(default=0)
    current_level = models.PositiveIntegerField(default=1)
    current_rank = models.CharField(
        max_length=12,
        choices=Rank.choices,
        default=Rank.BEGINNER,
    )
    longest_streak = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(singleton_key=1),
                name="player_profile_singleton_key",
            ),
            models.CheckConstraint(
                condition=Q(current_level__gte=1),
                name="player_profile_level_positive",
            ),
        ]

    def __str__(self):
        return self.display_name


class XPTransaction(models.Model):
    class Type(models.TextChoices):
        EARNED = "EARNED", "Earned"
        REVERSED = "REVERSED", "Reversed"
        BONUS = "BONUS", "Bonus"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    player = models.ForeignKey(
        PlayerProfile,
        on_delete=models.PROTECT,
        related_name="xp_transactions",
    )
    task_completion = models.ForeignKey(
        "tasks.TaskCompletion",
        on_delete=models.PROTECT,
        related_name="xp_transactions",
        null=True,
        blank=True,
    )
    completion_cycle = models.PositiveIntegerField(default=0)
    transaction_type = models.CharField(max_length=12, choices=Type.choices)
    amount = models.BigIntegerField()
    balance_after = models.PositiveBigIntegerField()
    description = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["task_completion", "completion_cycle", "transaction_type"],
                condition=Q(task_completion__isnull=False),
                name="xp_tx_occ_cycle_type_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(transaction_type="EARNED", amount__gte=0)
                    | Q(transaction_type="REVERSED", amount__lte=0)
                    | Q(transaction_type="BONUS", amount__gte=0)
                    | Q(transaction_type="ADJUSTMENT")
                ),
                name="xp_tx_amount_matches_type",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        transaction_type__in=["EARNED", "REVERSED"],
                        task_completion__isnull=False,
                        completion_cycle__gt=0,
                    )
                    | Q(
                        transaction_type__in=["BONUS", "ADJUSTMENT"],
                        task_completion__isnull=True,
                        completion_cycle=0,
                    )
                ),
                name="xp_tx_task_link_matches_type",
            ),
        ]
        indexes = [
            models.Index(fields=["player", "-created_at"], name="xp_tx_player_created_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("XP transactions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("XP transactions are immutable.")

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount:+} XP — {self.description}"


class Achievement(models.Model):
    class Category(models.TextChoices):
        MISSIONS = "MISSIONS", "Missions"
        LEARNING = "LEARNING", "Learning"
        CONSISTENCY = "CONSISTENCY", "Consistency"
        PROGRESSION = "PROGRESSION", "Progression"

    class ConditionType(models.TextChoices):
        TASK_COUNT = "TASK_COUNT", "Completed mission count"
        LEARNING_COUNT = "LEARNING_COUNT", "Learning mission count"
        HARD_TASK_COUNT = "HARD_TASK_COUNT", "Hard or extreme mission count"
        STREAK = "STREAK", "Longest streak"
        LIFETIME_XP = "LIFETIME_XP", "Lifetime XP earned"

    code = models.CharField(
        max_length=40,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z][A-Z0-9_]*$",
                message="Use uppercase letters, numbers, and underscores.",
            )
        ],
    )
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, default="trophy")
    category = models.CharField(max_length=12, choices=Category.choices)
    condition_type = models.CharField(max_length=20, choices=ConditionType.choices)
    condition_value = models.PositiveIntegerField(default=1)
    xp_reward = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "condition_value", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(condition_value__gte=1),
                name="achievement_condition_positive",
            ),
            models.CheckConstraint(
                condition=Q(xp_reward__gte=0),
                name="achievement_xp_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
        if self.name:
            self.name = self.name.strip()

    def __str__(self):
        return self.name


class PlayerAchievement(models.Model):
    player = models.ForeignKey(
        PlayerProfile,
        on_delete=models.PROTECT,
        related_name="achievements",
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.PROTECT,
        related_name="unlocks",
    )
    unlocked_at = models.DateTimeField(auto_now_add=True)
    xp_awarded = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-unlocked_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "achievement"],
                name="player_achievement_uniq",
            ),
            models.CheckConstraint(
                condition=Q(xp_awarded__gte=0),
                name="player_achievement_xp_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.player}: {self.achievement}"


class DailyStreak(models.Model):
    player = models.ForeignKey(
        PlayerProfile,
        on_delete=models.PROTECT,
        related_name="daily_streaks",
    )
    activity_date = models.DateField()
    qualifying_activity_count = models.PositiveIntegerField(default=0)
    is_active_day = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["activity_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "activity_date"],
                name="player_streak_date_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active_day=True, qualifying_activity_count__gte=1)
                    | Q(is_active_day=False, qualifying_activity_count=0)
                ),
                name="daily_streak_count_matches_active",
            ),
        ]
        indexes = [
            models.Index(fields=["player", "is_active_day", "activity_date"], name="streak_player_active_date_idx"),
        ]

    def __str__(self):
        return f"{self.player} — {self.activity_date}"
