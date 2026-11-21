from datetime import date, datetime, timedelta
from math import isqrt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from tasks.models import Task, TaskCompletion

from .models import Achievement, DailyStreak, PlayerAchievement, PlayerProfile, XPTransaction


class InvalidTaskXP(ValueError):
    """Raised when an XP operation does not match the task occurrence state."""


class InsufficientXP(ValueError):
    """Raised when an XP adjustment would make the player's balance negative."""


def get_player_profile():
    profile, _ = PlayerProfile.objects.get_or_create(
        singleton_key=1,
        defaults={
            "display_name": "Player One",
            "total_xp": 0,
            "current_level": 1,
            "current_rank": PlayerProfile.Rank.BEGINNER,
            "longest_streak": 0,
        },
    )
    return profile


def _resolve_player(player=None, *, lock=False):
    if player is None:
        profile = get_player_profile()
        if lock:
            return PlayerProfile.objects.select_for_update().get(pk=profile.pk)
        return profile
    player_id = player.pk if isinstance(player, PlayerProfile) else player
    if player_id is None:
        raise ValueError("A saved player profile is required.")
    queryset = PlayerProfile.objects.select_for_update() if lock else PlayerProfile.objects
    return queryset.get(pk=player_id)


def calculate_level(total_xp):
    if type(total_xp) is not int or total_xp < 0:
        raise ValueError("total_xp must be a non-negative integer.")
    return (5 + isqrt(25 + 2 * total_xp)) // 10


def calculate_xp_to_next_level(current_level):
    if type(current_level) is not int or current_level < 1:
        raise ValueError("current_level must be a positive integer.")
    return 100 * current_level


def calculate_level_progress(total_xp):
    level = calculate_level(total_xp)
    level_start_xp = 50 * level * (level - 1)
    return round(
        (total_xp - level_start_xp) * 100
        / calculate_xp_to_next_level(level),
        2,
    )


def get_xp_remaining(total_xp):
    level = calculate_level(total_xp)
    return 50 * (level + 1) * level - total_xp


def calculate_rank(current_level):
    if type(current_level) is not int or current_level < 1:
        raise ValueError("current_level must be a positive integer.")
    if current_level < 5:
        return PlayerProfile.Rank.BEGINNER
    if current_level < 10:
        return PlayerProfile.Rank.APPRENTICE
    if current_level < 20:
        return PlayerProfile.Rank.WARRIOR
    if current_level < 30:
        return PlayerProfile.Rank.ELITE
    if current_level < 50:
        return PlayerProfile.Rank.MASTER
    if current_level < 75:
        return PlayerProfile.Rank.LEGEND
    return PlayerProfile.Rank.MYTHIC


def calculate_current_streak(player=None):
    profile = _resolve_player(player)
    today = timezone.localdate()
    active_dates = list(
        DailyStreak.objects.filter(
            player=profile,
            is_active_day=True,
            activity_date__lte=today,
        )
        .order_by("-activity_date")
        .values_list("activity_date", flat=True)
    )
    if not active_dates or active_dates[0] < today - timedelta(days=1):
        return 0

    active_date_set = set(active_dates)
    current_date = active_dates[0]
    streak = 0
    while current_date in active_date_set:
        streak += 1
        current_date -= timedelta(days=1)
    return streak


def calculate_longest_streak(player=None):
    profile = _resolve_player(player)
    active_dates = DailyStreak.objects.filter(
        player=profile,
        is_active_day=True,
        activity_date__lte=timezone.localdate(),
    ).order_by("activity_date").values_list("activity_date", flat=True)

    longest = current = 0
    previous_date = None
    for activity_date in active_dates.iterator():
        if previous_date and activity_date == previous_date + timedelta(days=1):
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous_date = activity_date
    return longest


def recalculate_streaks(player):
    profile = _resolve_player(player, lock=True)
    today = timezone.localdate()
    active_counts = dict(
        TaskCompletion.objects.filter(
            status=TaskCompletion.Status.COMPLETED,
            is_superseded=False,
            scheduled_date__lte=today,
        )
        .values("scheduled_date")
        .annotate(activity_count=Count("pk"))
        .values_list("scheduled_date", "activity_count")
    )

    existing = list(
        DailyStreak.objects.filter(
            player=profile,
            activity_date__lte=today,
        ).order_by("activity_date")
    )
    existing_dates = {streak.activity_date for streak in existing}
    missing = [
        DailyStreak(
            player=profile,
            activity_date=activity_date,
            qualifying_activity_count=count,
            is_active_day=True,
        )
        for activity_date, count in active_counts.items()
        if activity_date not in existing_dates
    ]
    if missing:
        DailyStreak.objects.bulk_create(missing, ignore_conflicts=True)

    existing = list(
        DailyStreak.objects.filter(
            player=profile,
            activity_date__lte=today,
        ).order_by("activity_date")
    )
    now = timezone.now()
    changed = []
    for streak in existing:
        count = active_counts.get(streak.activity_date, 0)
        is_active_day = count > 0
        if (
            streak.qualifying_activity_count != count
            or streak.is_active_day != is_active_day
        ):
            streak.qualifying_activity_count = count
            streak.is_active_day = is_active_day
            streak.updated_at = now
            changed.append(streak)
    if changed:
        DailyStreak.objects.bulk_update(
            changed,
            ["qualifying_activity_count", "is_active_day", "updated_at"],
        )

    DailyStreak.objects.filter(
        player=profile,
        activity_date__gt=today,
        is_active_day=True,
    ).update(
        qualifying_activity_count=0,
        is_active_day=False,
        updated_at=now,
    )
    longest = calculate_longest_streak(profile)
    if longest > profile.longest_streak:
        profile.longest_streak = longest
        profile.save(update_fields=["longest_streak", "updated_at"])
    return profile


def record_daily_activity(player, activity_date):
    if not isinstance(activity_date, date) or isinstance(activity_date, datetime):
        raise TypeError("activity_date must be a datetime.date.")
    today = timezone.localdate()
    if activity_date > today:
        return None

    profile = _resolve_player(player)
    qualifying_count = TaskCompletion.objects.filter(
        scheduled_date=activity_date,
        status=TaskCompletion.Status.COMPLETED,
        is_superseded=False,
    ).count()
    with transaction.atomic():
        streak, _ = DailyStreak.objects.update_or_create(
            player=profile,
            activity_date=activity_date,
            defaults={
                "qualifying_activity_count": qualifying_count,
                "is_active_day": qualifying_count > 0,
            },
        )
        recalculate_streaks(profile)
    return streak


def _apply_xp_change(
    player,
    amount,
    transaction_type,
    description,
    *,
    task_completion=None,
    completion_cycle=0,
):
    if type(amount) is not int:
        raise TypeError("XP transaction amounts must be integers.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("An XP transaction description is required.")
    if transaction_type in {XPTransaction.Type.EARNED, XPTransaction.Type.BONUS} and amount < 0:
        raise ValueError("Earned and bonus XP amounts cannot be negative.")
    if transaction_type == XPTransaction.Type.REVERSED and amount > 0:
        raise ValueError("Reversed XP amounts must be non-positive.")

    profile = _resolve_player(player, lock=True)
    new_balance = profile.total_xp + amount
    if new_balance < 0:
        raise InsufficientXP("This XP change would make the player's balance negative.")

    profile.total_xp = new_balance
    profile.current_level = calculate_level(new_balance)
    profile.current_rank = calculate_rank(profile.current_level)
    profile.save(
        update_fields=["total_xp", "current_level", "current_rank", "updated_at"]
    )
    return XPTransaction.objects.create(
        player=profile,
        task_completion=task_completion,
        completion_cycle=completion_cycle,
        transaction_type=transaction_type,
        amount=amount,
        balance_after=new_balance,
        description=description.strip(),
    )


def award_task_xp(occurrence_id):
    with transaction.atomic():
        occurrence = (
            TaskCompletion.objects.select_for_update()
            .select_related("task")
            .get(pk=occurrence_id)
        )
        if occurrence.status != TaskCompletion.Status.COMPLETED:
            raise InvalidTaskXP("Only completed occurrences can earn XP.")
        if occurrence.is_superseded or not occurrence.task.is_active:
            raise InvalidTaskXP("An unscheduled occurrence cannot earn XP.")

        if occurrence.completion_cycle < 1:
            occurrence.completion_cycle = 1
            occurrence.save(update_fields=["completion_cycle", "updated_at"])
        existing = XPTransaction.objects.filter(
            task_completion=occurrence,
            completion_cycle=occurrence.completion_cycle,
            transaction_type=XPTransaction.Type.EARNED,
        ).first()
        if existing:
            if occurrence.xp_awarded != existing.amount:
                occurrence.xp_awarded = existing.amount
                occurrence.save(update_fields=["xp_awarded", "updated_at"])
            return existing

        profile = get_player_profile()
        reward = occurrence.task.xp_reward
        earned = _apply_xp_change(
            profile,
            reward,
            XPTransaction.Type.EARNED,
            f"Completed mission: {occurrence.task.title}",
            task_completion=occurrence,
            completion_cycle=occurrence.completion_cycle,
        )
        occurrence.xp_awarded = reward
        occurrence.save(update_fields=["xp_awarded", "updated_at"])
        record_daily_activity(profile, occurrence.scheduled_date)
        check_achievements(profile)
        return earned


def reverse_task_xp(occurrence_id):
    with transaction.atomic():
        occurrence = TaskCompletion.objects.select_for_update().get(pk=occurrence_id)
        if occurrence.status != TaskCompletion.Status.PENDING:
            raise InvalidTaskXP("Undo the mission before reversing its XP.")

        profile = get_player_profile()
        earned = XPTransaction.objects.filter(
            task_completion=occurrence,
            completion_cycle=occurrence.completion_cycle,
            transaction_type=XPTransaction.Type.EARNED,
        ).first()
        reversed_transaction = XPTransaction.objects.filter(
            task_completion=occurrence,
            completion_cycle=occurrence.completion_cycle,
            transaction_type=XPTransaction.Type.REVERSED,
        ).first()

        if earned and not reversed_transaction:
            reversed_transaction = _apply_xp_change(
                profile,
                -earned.amount,
                XPTransaction.Type.REVERSED,
                f"Undid mission: {occurrence.task.title}",
                task_completion=occurrence,
                completion_cycle=occurrence.completion_cycle,
            )
        if occurrence.xp_awarded:
            occurrence.xp_awarded = 0
            occurrence.save(update_fields=["xp_awarded", "updated_at"])
        recalculate_streaks(profile)
        return reversed_transaction


def award_bonus_xp(player, amount, description, *, evaluate_achievements=True):
    if type(amount) is not int or amount < 0:
        raise ValueError("Bonus XP must be a non-negative integer.")
    with transaction.atomic():
        bonus = _apply_xp_change(
            player,
            amount,
            XPTransaction.Type.BONUS,
            description,
        )
        if evaluate_achievements:
            check_achievements(bonus.player)
        return bonus


def _completed_mission_counts():
    return TaskCompletion.objects.filter(
        status=TaskCompletion.Status.COMPLETED,
        is_superseded=False,
    ).aggregate(
        total=Count("pk"),
        learning=Count(
            "pk",
            filter=Q(task__category__name__iexact="Learning"),
        ),
        hard=Count(
            "pk",
            filter=Q(task__difficulty__in=[Task.Difficulty.HARD, Task.Difficulty.EXTREME]),
        ),
    )


def _lifetime_xp_earned(player):
    return (
        XPTransaction.objects.filter(
            player=player,
            transaction_type__in=[XPTransaction.Type.EARNED, XPTransaction.Type.BONUS],
            amount__gt=0,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )


def unlock_achievement(player, achievement):
    with transaction.atomic():
        profile = _resolve_player(player, lock=True)
        unlocked, created = PlayerAchievement.objects.get_or_create(
            player=profile,
            achievement=achievement,
            defaults={"xp_awarded": achievement.xp_reward},
        )
        if not created:
            return unlocked

        award_bonus_xp(
            profile,
            achievement.xp_reward,
            f"Achievement unlocked: {achievement.name}",
            evaluate_achievements=False,
        )
        return unlocked


def check_achievements(player):
    profile = _resolve_player(player, lock=True)
    newly_unlocked = []
    while True:
        counts = _completed_mission_counts()
        candidates = Achievement.objects.filter(is_active=True).exclude(
            unlocks__player=profile
        )
        unlocked_this_pass = []
        for achievement in candidates.order_by("pk"):
            if achievement.condition_type == Achievement.ConditionType.TASK_COUNT:
                progress = counts["total"]
            elif achievement.condition_type == Achievement.ConditionType.LEARNING_COUNT:
                progress = counts["learning"]
            elif achievement.condition_type == Achievement.ConditionType.HARD_TASK_COUNT:
                progress = counts["hard"]
            elif achievement.condition_type == Achievement.ConditionType.STREAK:
                progress = profile.longest_streak
            elif achievement.condition_type == Achievement.ConditionType.LIFETIME_XP:
                progress = _lifetime_xp_earned(profile)
            else:
                continue
            if progress >= achievement.condition_value:
                unlocked_this_pass.append(
                    unlock_achievement(profile, achievement)
                )
        if not unlocked_this_pass:
            break
        newly_unlocked.extend(unlocked_this_pass)
    return newly_unlocked


def get_unlocked_achievements(player=None):
    profile = _resolve_player(player)
    return Achievement.objects.filter(
        unlocks__player=profile,
    ).distinct().order_by("category", "condition_value", "name")


def get_locked_achievements(player=None):
    profile = _resolve_player(player)
    unlocked_ids = PlayerAchievement.objects.filter(
        player=profile,
    ).values_list("achievement_id", flat=True)
    return Achievement.objects.filter(is_active=True).exclude(
        pk__in=unlocked_ids
    ).order_by("category", "condition_value", "name")


def get_xp_history(player=None, *, limit=50):
    profile = _resolve_player(player)
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer.")
    return XPTransaction.objects.filter(player=profile).select_related(
        "player",
        "task_completion__task",
    )[:limit]


def get_player_progress():
    profile = get_player_profile()
    level_start_xp = 50 * profile.current_level * (profile.current_level - 1)
    xp_to_next_level = calculate_xp_to_next_level(profile.current_level)
    xp_remaining = get_xp_remaining(profile.total_xp)
    completion_counts = TaskCompletion.objects.filter(
        status=TaskCompletion.Status.COMPLETED,
        is_superseded=False,
    ).aggregate(
        total=Count("pk"),
        learning=Count(
            "pk",
            filter=Q(task__category__name__iexact="Learning"),
        ),
    )
    achievements = list(
        Achievement.objects.filter(is_active=True)
        .order_by("pk")
        .values("id", "code", "name", "icon")[:5]
    )
    unlocked_ids = set(
        PlayerAchievement.objects.filter(
            player=profile,
            achievement_id__in=[achievement["id"] for achievement in achievements],
        ).values_list("achievement_id", flat=True)
    )
    for achievement in achievements:
        achievement["is_unlocked"] = achievement["id"] in unlocked_ids

    return {
        "player": profile,
        "display_name": profile.display_name,
        "total_xp": profile.total_xp,
        "current_level": profile.current_level,
        "current_rank": profile.current_rank,
        "rank_display": profile.get_current_rank_display(),
        "level_start_xp": level_start_xp,
        "xp_into_level": profile.total_xp - level_start_xp,
        "xp_to_next_level": xp_to_next_level,
        "next_level_total_xp": level_start_xp + xp_to_next_level,
        "xp_remaining": xp_remaining,
        "progress_percentage": calculate_level_progress(profile.total_xp),
        "current_streak": calculate_current_streak(profile),
        "longest_streak": max(
            profile.longest_streak,
            calculate_longest_streak(profile),
        ),
        "total_completed_missions": completion_counts["total"],
        "learning_completed_missions": completion_counts["learning"],
        "unlocked_achievement_count": PlayerAchievement.objects.filter(
            player=profile
        ).count(),
        "achievement_preview": achievements,
    }
