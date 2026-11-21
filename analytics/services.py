import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from gamification.models import DailyStreak, PlayerAchievement, PlayerProfile, XPTransaction
from gamification.services import (
    calculate_current_streak,
    calculate_level_progress,
    calculate_longest_streak,
    calculate_xp_to_next_level,
)
from tasks.models import Task, TaskCategory, TaskCompletion
from learning.models import LearningSession, LearningCourse, Skill


_XP_EARNING_TYPES = {XPTransaction.Type.EARNED, XPTransaction.Type.BONUS}
_XP_REVERSAL_TYPE = XPTransaction.Type.REVERSED
_XP_ADJUSTMENT_TYPE = XPTransaction.Type.ADJUSTMENT


@dataclass(slots=True)
class AnalyticsSnapshot:
    as_of: date
    tasks_created: int
    occurrences_by_date: dict
    categories: list
    category_counts: dict
    difficulty_counts: dict
    xp_by_date: dict
    category_xp: dict
    difficulty_xp: dict
    active_dates: set
    streak_record_dates: set
    earliest_date: date | None
    player_progress: dict


def _empty_counts():
    return {
        TaskCompletion.Status.COMPLETED: 0,
        TaskCompletion.Status.PENDING: 0,
        TaskCompletion.Status.SKIPPED: 0,
    }


def _empty_xp():
    return {"earned": 0, "reversed": 0, "adjustment": 0, "net": 0}


def _record_xp(target, transaction_type, amount):
    target["net"] += amount
    if transaction_type in _XP_EARNING_TYPES and amount > 0:
        target["earned"] += amount
    elif transaction_type == _XP_REVERSAL_TYPE and amount < 0:
        target["reversed"] += -amount
    elif transaction_type == _XP_ADJUSTMENT_TYPE:
        target["adjustment"] += amount


def _read_only_player_progress(completed_count):
    profile = PlayerProfile.objects.order_by("pk").first()
    if profile is None:
        return {
            "profile_available": False,
            "display_name": "Player One",
            "total_xp": 0,
            "current_level": 1,
            "current_rank": PlayerProfile.Rank.BEGINNER,
            "rank_display": PlayerProfile.Rank.BEGINNER.label,
            "level_start_xp": 0,
            "xp_into_level": 0,
            "xp_to_next_level": 100,
            "xp_remaining": 100,
            "progress_percentage": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "total_completed_missions": completed_count,
            "unlocked_achievement_count": 0,
        }

    level_start_xp = 50 * profile.current_level * (profile.current_level - 1)
    return {
        "profile_available": True,
        "display_name": profile.display_name,
        "total_xp": profile.total_xp,
        "current_level": profile.current_level,
        "current_rank": profile.current_rank,
        "rank_display": profile.get_current_rank_display(),
        "level_start_xp": level_start_xp,
        "xp_into_level": profile.total_xp - level_start_xp,
        "xp_to_next_level": calculate_xp_to_next_level(profile.current_level),
        "xp_remaining": (
            50 * (profile.current_level + 1) * profile.current_level - profile.total_xp
        ),
        "progress_percentage": calculate_level_progress(profile.total_xp),
        "current_streak": calculate_current_streak(profile),
        "longest_streak": max(
            profile.longest_streak,
            calculate_longest_streak(profile),
        ),
        "total_completed_missions": completed_count,
        "unlocked_achievement_count": PlayerAchievement.objects.filter(
            player=profile
        ).count(),
    }


def _snapshot(as_of=None):
    today = timezone.localdate()
    as_of = as_of or today
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise ValueError("Analytics dates must be date values.")
    if as_of > today:
        raise ValueError("Analytics cannot be calculated for a future date.")

    daily_counts = {}
    category_counts = {}
    difficulty_counts = {
        value: {"label": label, "counts": _empty_counts()}
        for value, label in Task.Difficulty.choices
    }
    occurrence_rows = (
        TaskCompletion.objects.filter(
            is_superseded=False,
            scheduled_date__lte=as_of,
        )
        .values(
            "scheduled_date",
            "status",
            "task__category_id",
            "task__category__name",
            "task__difficulty",
        )
        .annotate(count=Count("pk"))
    )
    for row in occurrence_rows:
        scheduled_date = row["scheduled_date"]
        status = row["status"]
        count = row["count"]
        daily_counts.setdefault(scheduled_date, _empty_counts())[status] += count

        category_id = row["task__category_id"]
        category = category_counts.setdefault(
            category_id,
            {
                "name": row["task__category__name"],
                "counts": _empty_counts(),
            },
        )
        category["counts"][status] += count

        difficulty = difficulty_counts.get(row["task__difficulty"])
        if difficulty is not None:
            difficulty["counts"][status] += count

    categories = list(
        TaskCategory.objects.order_by("name", "pk").values(
            "id", "name", "color", "is_active"
        )
    )
    category_ids = {category["id"] for category in categories}
    for category_id, counts in category_counts.items():
        if category_id not in category_ids:
            categories.append(
                {
                    "id": category_id,
                    "name": counts["name"],
                    "color": "#9b8cff",
                    "is_active": False,
                }
            )
            category_ids.add(category_id)

    xp_by_date = {}
    local_end = timezone.make_aware(
        datetime.combine(as_of + timedelta(days=1), time.min),
        timezone.get_current_timezone(),
    )
    xp_rows = (
        XPTransaction.objects.filter(created_at__lt=local_end)
        .annotate(local_date=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values("local_date", "transaction_type")
        .annotate(amount=Sum("amount"))
    )
    for row in xp_rows:
        _record_xp(
            xp_by_date.setdefault(row["local_date"], _empty_xp()),
            row["transaction_type"],
            row["amount"] or 0,
        )

    category_xp = {}
    difficulty_xp = {
        value: _empty_xp() for value, _label in Task.Difficulty.choices
    }
    task_xp_rows = (
        XPTransaction.objects.filter(
            task_completion__isnull=False,
            created_at__lt=local_end,
            transaction_type__in=[
                XPTransaction.Type.EARNED,
                XPTransaction.Type.REVERSED,
                XPTransaction.Type.ADJUSTMENT,
            ],
        )
        .values(
            "task_completion__task__category_id",
            "task_completion__task__difficulty",
            "transaction_type",
        )
        .annotate(amount=Sum("amount"))
    )
    for row in task_xp_rows:
        category_id = row["task_completion__task__category_id"]
        transaction_type = row["transaction_type"]
        amount = row["amount"] or 0
        _record_xp(
            category_xp.setdefault(category_id, _empty_xp()),
            transaction_type,
            amount,
        )
        difficulty = difficulty_xp.get(row["task_completion__task__difficulty"])
        if difficulty is not None:
            _record_xp(difficulty, transaction_type, amount)

    streak_rows = DailyStreak.objects.filter(
        activity_date__lte=as_of
    ).values_list("activity_date", "is_active_day")
    streak_record_dates = set()
    active_dates = set()
    for activity_date, is_active_day in streak_rows:
        streak_record_dates.add(activity_date)
        if is_active_day:
            active_dates.add(activity_date)

    completed_count = sum(
        counts[TaskCompletion.Status.COMPLETED]
        for counts in daily_counts.values()
    )
    player_progress = _read_only_player_progress(completed_count)
    recorded_dates = set(daily_counts) | set(xp_by_date) | streak_record_dates
    return AnalyticsSnapshot(
        as_of=as_of,
        tasks_created=Task.objects.count(),
        occurrences_by_date=daily_counts,
        categories=categories,
        category_counts=category_counts,
        difficulty_counts=difficulty_counts,
        xp_by_date=xp_by_date,
        category_xp=category_xp,
        difficulty_xp=difficulty_xp,
        active_dates=active_dates,
        streak_record_dates=streak_record_dates,
        earliest_date=min(recorded_dates) if recorded_dates else None,
        player_progress=player_progress,
    )


def _percent(numerator, denominator):
    if denominator == 0:
        return None
    return round(numerator * 100 / denominator, 1)


def _day_summary(snapshot, target_date):
    if target_date > snapshot.as_of:
        return {
            "date": target_date,
            "available": False,
            "scheduled_missions": None,
            "completed": None,
            "pending": None,
            "skipped": None,
            "missed": None,
            "completion_rate": None,
            "active_day": None,
            "active_streak": None,
            "streak_recorded": False,
            "xp_earned": None,
            "xp_reversed": None,
            "xp_adjustment": None,
            "xp_net": None,
        }

    counts = snapshot.occurrences_by_date.get(target_date, _empty_counts())
    completed = counts[TaskCompletion.Status.COMPLETED]
    pending = counts[TaskCompletion.Status.PENDING]
    skipped = counts[TaskCompletion.Status.SKIPPED]
    xp = snapshot.xp_by_date.get(target_date, _empty_xp())
    return {
        "date": target_date,
        "available": True,
        "scheduled_missions": completed + pending + skipped,
        "completed": completed,
        "pending": pending,
        "skipped": skipped,
        "missed": pending if target_date < snapshot.as_of else 0,
        "completion_rate": _percent(completed, completed + pending + skipped),
        "active_day": target_date in snapshot.active_dates,
        "active_streak": target_date in snapshot.active_dates,
        "xp_earned": xp["earned"],
        "xp_reversed": xp["reversed"],
        "xp_adjustment": xp["adjustment"],
        "xp_net": xp["net"],
        "streak_recorded": target_date in snapshot.streak_record_dates,
    }


def _period_summary(snapshot, start_date, end_date):
    effective_end = min(end_date, snapshot.as_of)
    elapsed_days = (
        max(0, (effective_end - start_date).days + 1)
        if start_date <= effective_end
        else 0
    )
    completed = pending = skipped = missed = 0
    xp_earned = xp_reversed = xp_adjustment = xp_net = 0
    scheduled_recorded = False
    for target_date in _date_range(start_date, effective_end):
        counts = snapshot.occurrences_by_date.get(target_date, _empty_counts())
        day_completed = counts[TaskCompletion.Status.COMPLETED]
        day_pending = counts[TaskCompletion.Status.PENDING]
        day_skipped = counts[TaskCompletion.Status.SKIPPED]
        completed += day_completed
        pending += day_pending
        skipped += day_skipped
        if target_date < snapshot.as_of:
            missed += day_pending
        scheduled_recorded = scheduled_recorded or (
            day_completed + day_pending + day_skipped > 0
        )

        xp = snapshot.xp_by_date.get(target_date, _empty_xp())
        xp_earned += xp["earned"]
        xp_reversed += xp["reversed"]
        xp_adjustment += xp["adjustment"]
        xp_net += xp["net"]

    total = completed + pending + skipped
    active_days = sum(
        1 for activity_date in snapshot.active_dates
        if start_date <= activity_date <= effective_end
    )
    streak_recorded = any(
        start_date <= activity_date <= effective_end
        for activity_date in snapshot.streak_record_dates
    )
    tracked = scheduled_recorded or streak_recorded
    return {
        "period_start": start_date,
        "period_end": end_date,
        "elapsed_days": elapsed_days,
        "available": elapsed_days > 0,
        "data_available": (
            scheduled_recorded
            or xp_earned > 0
            or xp_reversed > 0
            or xp_adjustment != 0
            or streak_recorded
        ),
        "scheduled_missions": total,
        "completed": completed,
        "pending": pending,
        "skipped": skipped,
        "missed": missed,
        "completion_rate": _percent(completed, total),
        "active_days": active_days,
        "inactive_days": max(0, elapsed_days - active_days) if tracked else None,
        "consistency_rate": _percent(active_days, elapsed_days) if tracked else None,
        "xp_earned": xp_earned,
        "xp_reversed": xp_reversed,
        "xp_adjustment": xp_adjustment,
        "xp_net": xp_net,
    }


def _date_range(start_date, end_date):
    if end_date < start_date:
        return ()
    return (
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    )


def _comparison(snapshot, period, current_start, current_end, previous_start, previous_end):
    current = _period_summary(snapshot, current_start, current_end)
    previous = _period_summary(snapshot, previous_start, previous_end)
    previous_available = previous["data_available"]
    comparison_available = current["data_available"] and previous_available
    rate_change = (
        round(current["completion_rate"] - previous["completion_rate"], 1)
        if comparison_available
        and current["completion_rate"] is not None
        and previous["completion_rate"] is not None
        else None
    )
    consistency_change = (
        round(current["consistency_rate"] - previous["consistency_rate"], 1)
        if comparison_available
        and current["consistency_rate"] is not None
        and previous["consistency_rate"] is not None
        else None
    )
    xp_change = (
        current["xp_net"] - previous["xp_net"] if comparison_available else None
    )
    xp_percentage = (
        round(xp_change * 100 / abs(previous["xp_net"]), 1)
        if xp_change is not None and previous["xp_net"] != 0
        else None
    )
    return {
        "period": period,
        "available": comparison_available,
        "previous_period_available": previous_available,
        "current": current,
        "previous": previous,
        "changes": {
            "completed_missions": (
                current["completed"] - previous["completed"]
                if comparison_available
                else None
            ),
            "completion_rate_points": rate_change,
            "xp_net": xp_change,
            "xp_net_percentage": xp_percentage,
            "consistency_points": consistency_change,
        },
        "completion_direction": (
            "unavailable"
            if rate_change is None
            else "up" if rate_change > 0
            else "down" if rate_change < 0
            else "unchanged"
        ),
    }


def _week_bounds(reference_date):
    start = reference_date - timedelta(days=reference_date.weekday())
    return start, start + timedelta(days=6)


def _month_bounds(reference_date):
    start = reference_date.replace(day=1)
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    return start, reference_date.replace(day=last_day)


def _comparison_for_period(snapshot, period, reference_date=None):
    reference_date = reference_date or snapshot.as_of
    if period == "week":
        current_start, current_end = _week_bounds(reference_date)
        if reference_date == snapshot.as_of:
            current_end = min(current_end, reference_date)
        previous_start = current_start - timedelta(days=7)
        previous_end = previous_start + (current_end - current_start)
    elif period == "month":
        current_start, full_current_end = _month_bounds(reference_date)
        is_current_month = (
            reference_date.year == snapshot.as_of.year
            and reference_date.month == snapshot.as_of.month
        )
        current_end = min(full_current_end, reference_date) if is_current_month else full_current_end
        if is_current_month:
            previous_month_last = current_start - timedelta(days=1)
            previous_start = previous_month_last.replace(day=1)
            previous_last_day = calendar.monthrange(
                previous_start.year, previous_start.month
            )[1]
            matching_days = min(current_end.day, previous_last_day)
            current_end = current_start + timedelta(days=matching_days - 1)
            previous_end = previous_start + timedelta(days=matching_days - 1)
        else:
            previous_month_last = current_start - timedelta(days=1)
            previous_start = previous_month_last.replace(day=1)
            previous_end = previous_month_last
    elif period in {"7d", "30d"}:
        days = int(period[:-1])
        current_end = reference_date
        current_start = current_end - timedelta(days=days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)
    else:
        raise ValueError("Comparison period must be week, month, 7d, or 30d.")

    return _comparison(
        snapshot,
        period,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )


def get_overview_analytics(as_of=None, *, snapshot=None):
    snapshot = snapshot or _snapshot(as_of)
    start = snapshot.earliest_date or snapshot.as_of
    totals = _period_summary(snapshot, start, snapshot.as_of)
    player = snapshot.player_progress
    all_xp = list(snapshot.xp_by_date.values())
    learning_sessions = LearningSession.objects.filter(session_date__lte=snapshot.as_of)
    learning_totals = learning_sessions.aggregate(
        total_minutes=Sum("duration_minutes"),
        session_count=Count("pk"),
    )
    learning_active_dates = learning_sessions.dates("session_date", "day")
    return {
        "as_of": snapshot.as_of,
        "data_available": totals["data_available"],
        "data_coverage": "Persisted mission occurrences and XP ledger transactions.",
        "missions_created": snapshot.tasks_created,
        "scheduled_missions": totals["scheduled_missions"],
        "completed_missions": totals["completed"],
        "pending_missions": totals["pending"],
        "skipped_missions": totals["skipped"],
        "missed_missions": totals["missed"],
        "completion_rate": totals["completion_rate"],
        "total_xp_balance": player["total_xp"],
        "lifetime_xp_earned": sum(item["earned"] for item in all_xp),
        "lifetime_xp_reversed": sum(item["reversed"] for item in all_xp),
        "lifetime_xp_adjustment": sum(item["adjustment"] for item in all_xp),
        "lifetime_xp_net": sum(item["net"] for item in all_xp),
        "active_days_recorded": len(snapshot.active_dates),
        "current_streak": player["current_streak"],
        "longest_streak": player["longest_streak"],
        "unlocked_achievements": player["unlocked_achievement_count"],
        "player_progress": player,
        "learning": {
            "total_minutes": learning_totals["total_minutes"] or 0,
            "session_count": learning_totals["session_count"] or 0,
            "active_days": learning_active_dates.count(),
            "active_courses": LearningCourse.objects.exclude(
                status__in=[
                    LearningCourse.Status.COMPLETED,
                    LearningCourse.Status.ARCHIVED,
                ]
            ).count(),
            "completed_courses": LearningCourse.objects.filter(
                status=LearningCourse.Status.COMPLETED
            ).count(),
            "active_skills": Skill.objects.exclude(status=Skill.Status.ARCHIVED).count(),
        },
    }


def get_daily_analytics(target_date=None, *, snapshot=None):
    target_date = target_date or timezone.localdate()
    today = timezone.localdate()
    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        raise ValueError("Date must use the YYYY-MM-DD format.")
    if target_date > today:
        return {
            "date": target_date,
            "available": False,
            "scheduled_missions": None,
            "completed": None,
            "pending": None,
            "skipped": None,
            "missed": None,
            "completion_rate": None,
            "active_day": None,
            "active_streak": None,
            "streak_recorded": False,
            "xp_earned": None,
            "xp_reversed": None,
            "xp_adjustment": None,
            "xp_net": None,
        }
    snapshot = snapshot or _snapshot()
    return _day_summary(snapshot, target_date)


def get_weekly_analytics(reference_date=None, *, snapshot=None):
    reference_date = reference_date or timezone.localdate()
    if reference_date > timezone.localdate():
        raise ValueError("Analytics cannot be calculated for a future date.")
    snapshot = snapshot or _snapshot()
    start, end = _week_bounds(reference_date)
    summary = _period_summary(snapshot, start, end)
    days = [_day_summary(snapshot, day) for day in _date_range(start, end)]
    recorded_days = [day for day in days if day["scheduled_missions"]]
    best_day = max(
        recorded_days,
        key=lambda day: (day["completion_rate"] or 0, day["completed"]),
        default=None,
    )
    weakest_day = min(
        recorded_days,
        key=lambda day: (day["completion_rate"] or 0, day["completed"]),
        default=None,
    )
    return {
        **summary,
        "days": days,
        "best_day": best_day,
        "weakest_day": weakest_day,
        "comparison": _comparison_for_period(snapshot, "week", reference_date),
    }


def get_monthly_analytics(reference_date=None, *, snapshot=None):
    reference_date = reference_date or timezone.localdate()
    snapshot = snapshot or _snapshot()
    month_start, month_end = _month_bounds(reference_date)
    summary = _period_summary(snapshot, month_start, month_end)

    weekly_breakdown = []
    cursor = month_start
    while cursor <= month_end:
        week_end = min(
            month_end,
            cursor + timedelta(days=6 - cursor.weekday()),
        )
        weekly_breakdown.append(
            _period_summary(snapshot, cursor, week_end)
        )
        cursor = week_end + timedelta(days=1)
    recorded_weeks = [
        week for week in weekly_breakdown if week["scheduled_missions"] > 0
    ]
    best_week = max(
        recorded_weeks,
        key=lambda week: (week["completion_rate"] or 0, week["completed"]),
        default=None,
    )
    weakest_week = min(
        recorded_weeks,
        key=lambda week: (week["completion_rate"] or 0, week["completed"]),
        default=None,
    )
    comparison = (
        _comparison_for_period(snapshot, "month", reference_date)
        if month_start <= snapshot.as_of
        else {
            "period": "month",
            "available": False,
            "previous_period_available": False,
            "current": _period_summary(snapshot, month_start, month_end),
            "previous": None,
            "changes": {
                "completed_missions": None,
                "completion_rate_points": None,
                "xp_net": None,
                "xp_net_percentage": None,
                "consistency_points": None,
            },
            "completion_direction": "unavailable",
        }
    )
    return {
        **summary,
        "weeks": weekly_breakdown,
        "best_week": best_week,
        "weakest_week": weakest_week,
        "comparison": comparison,
    }


def get_category_analytics(*, snapshot=None):
    snapshot = snapshot or _snapshot()
    results = []
    for category in snapshot.categories:
        counts = snapshot.category_counts.get(category["id"], {}).get(
            "counts", _empty_counts()
        )
        completed = counts[TaskCompletion.Status.COMPLETED]
        pending = counts[TaskCompletion.Status.PENDING]
        skipped = counts[TaskCompletion.Status.SKIPPED]
        total = completed + pending + skipped
        xp = snapshot.category_xp.get(category["id"], _empty_xp())
        results.append(
            {
                "category_id": category["id"],
                "category": category["name"],
                "color": category["color"],
                "is_active": category["is_active"],
                "scheduled_missions": total,
                "completed": completed,
                "pending": pending,
                "skipped": skipped,
                "completion_rate": _percent(completed, total),
                "contribution_rate": _percent(
                    completed,
                    sum(
                        item["counts"][TaskCompletion.Status.COMPLETED]
                        for item in snapshot.category_counts.values()
                    ),
                ),
                "xp_earned": xp["earned"],
                "xp_reversed": xp["reversed"],
                "xp_net": xp["net"],
                "data_available": total > 0 or xp["earned"] > 0 or xp["reversed"] > 0,
            }
        )
    active = [item for item in results if item["scheduled_missions"] > 0]
    strongest = max(
        active,
        key=lambda item: (item["completion_rate"] or 0, item["completed"]),
        default=None,
    )
    weakest = min(
        active,
        key=lambda item: (item["completion_rate"] or 0, item["completed"]),
        default=None,
    )
    return {
        "categories": results,
        "strongest_category": strongest,
        "weakest_category": weakest,
        "data_available": bool(active),
    }


def get_difficulty_analytics(*, snapshot=None):
    snapshot = snapshot or _snapshot()
    results = []
    for value, label in Task.Difficulty.choices:
        counts = snapshot.difficulty_counts[value]["counts"]
        completed = counts[TaskCompletion.Status.COMPLETED]
        pending = counts[TaskCompletion.Status.PENDING]
        skipped = counts[TaskCompletion.Status.SKIPPED]
        total = completed + pending + skipped
        xp = snapshot.difficulty_xp.get(value, _empty_xp())
        results.append(
            {
                "difficulty": value,
                "label": label,
                "scheduled_missions": total,
                "completed": completed,
                "pending": pending,
                "skipped": skipped,
                "completion_rate": _percent(completed, total),
                "xp_earned": xp["earned"],
                "xp_reversed": xp["reversed"],
                "xp_net": xp["net"],
                "data_available": total > 0 or xp["earned"] > 0 or xp["reversed"] > 0,
            }
        )
    return {
        "difficulties": results,
        "data_available": any(item["data_available"] for item in results),
    }


def get_consistency_analytics(start_date=None, end_date=None, *, snapshot=None):
    snapshot = snapshot or _snapshot()
    end_date = end_date or snapshot.as_of
    start_date = start_date or (end_date - timedelta(days=29))
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date.")
    summary = _period_summary(snapshot, start_date, end_date)
    return {
        "period_start": summary["period_start"],
        "period_end": summary["period_end"],
        "elapsed_days": summary["elapsed_days"],
        "active_days": summary["active_days"],
        "inactive_days": summary["inactive_days"],
        "consistency_rate": summary["consistency_rate"],
        "data_available": summary["inactive_days"] is not None,
        "current_streak": snapshot.player_progress["current_streak"],
        "longest_streak": snapshot.player_progress["longest_streak"],
        "active_dates": sorted(
            activity_date
            for activity_date in snapshot.active_dates
            if start_date <= activity_date <= min(end_date, snapshot.as_of)
        ),
        "daily": [
            {
                "date": day,
                "active": _day_summary(snapshot, day)["active_day"],
                "available": day <= snapshot.as_of,
            }
            for day in _date_range(start_date, end_date)
        ],
    }


def get_performance_trends(period="30d", *, snapshot=None):
    if period not in {"7d", "30d", "90d", "all"}:
        raise ValueError("Trend period must be 7d, 30d, 90d, or all.")
    snapshot = snapshot or _snapshot()
    if period == "all":
        start_date = snapshot.earliest_date
    else:
        days = int(period[:-1])
        start_date = snapshot.as_of - timedelta(days=days - 1)
    if start_date is None:
        return {
            "period": period,
            "period_start": None,
            "period_end": snapshot.as_of,
            "data_available": False,
            "points": [],
        }

    summary = _period_summary(snapshot, start_date, snapshot.as_of)
    if not summary["data_available"]:
        return {
            "period": period,
            "period_start": start_date,
            "period_end": snapshot.as_of,
            "data_available": False,
            "points": [],
        }

    points = []
    for target_date in _date_range(start_date, snapshot.as_of):
        day = _day_summary(snapshot, target_date)
        xp = snapshot.xp_by_date.get(target_date, _empty_xp())
        has_occurrence_data = target_date in snapshot.occurrences_by_date
        has_xp_data = target_date in snapshot.xp_by_date
        has_streak_data = target_date in snapshot.streak_record_dates
        points.append(
            {
                "date": target_date,
                "completed": day["completed"] if has_occurrence_data else None,
                "scheduled": day["scheduled_missions"] if has_occurrence_data else None,
                "completion_rate": day["completion_rate"] if has_occurrence_data else None,
                "xp_earned": xp["earned"] if has_xp_data else None,
                "xp_reversed": xp["reversed"] if has_xp_data else None,
                "xp_net": xp["net"] if has_xp_data else None,
                "active_day": day["active_day"] if has_streak_data else None,
            }
        )
    return {
        "period": period,
        "period_start": start_date,
        "period_end": snapshot.as_of,
        "data_available": summary["data_available"],
        "points": points,
    }


def get_period_comparison(period="week", *, snapshot=None):
    snapshot = snapshot or _snapshot()
    return _comparison_for_period(snapshot, period)


def get_learning_analytics(start_date=None, end_date=None, *, snapshot=None):
    snapshot = snapshot or _snapshot()
    end_date = end_date or snapshot.as_of
    start_date = start_date or (end_date - timedelta(days=29))
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date.")
    if end_date > snapshot.as_of:
        raise ValueError("Learning analytics cannot include future session dates.")

    sessions = LearningSession.objects.filter(
        session_date__gte=start_date,
        session_date__lte=end_date,
    ).select_related("course", "skill")
    totals = sessions.aggregate(
        total_minutes=Sum("duration_minutes"),
        session_count=Count("pk"),
        average_minutes=Sum("duration_minutes"),
    )
    total_minutes = totals["total_minutes"] or 0
    session_count = totals["session_count"] or 0
    active_dates = list(
        sessions.dates("session_date", "day")
    )
    daily = list(
        sessions.values("session_date")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("session_date")
    )
    skill_rows = list(
        sessions.exclude(skill_id=None)
        .values("skill__name")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("-minutes", "skill__name")
    )
    course_rows = list(
        sessions.exclude(course_id=None)
        .values("course__title")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("-minutes", "course__title")
    )
    elapsed_days = (end_date - start_date).days + 1
    return {
        "period_start": start_date,
        "period_end": end_date,
        "total_minutes": total_minutes,
        "session_count": session_count,
        "average_minutes": round(total_minutes / session_count, 1) if session_count else 0,
        "active_days": len(active_dates),
        "consistency_percentage": round(len(active_dates) * 100 / elapsed_days, 1),
        "most_studied_skill": skill_rows[0] if skill_rows else None,
        "most_studied_course": course_rows[0] if course_rows else None,
        "daily": [
            {
                "date": row["session_date"],
                "minutes": row["minutes"],
                "sessions": row["sessions"],
            }
            for row in daily
        ],
        "data_available": session_count > 0,
    }

def get_analytics_dashboard():
    snapshot = _snapshot()
    overview = get_overview_analytics(snapshot=snapshot)
    daily = get_daily_analytics(snapshot.as_of, snapshot=snapshot)
    weekly = get_weekly_analytics(snapshot=snapshot)
    monthly = get_monthly_analytics(snapshot=snapshot)
    categories = get_category_analytics(snapshot=snapshot)
    difficulty = get_difficulty_analytics(snapshot=snapshot)
    consistency = get_consistency_analytics(
        snapshot.as_of - timedelta(days=29),
        snapshot.as_of,
        snapshot=snapshot,
    )
    comparisons = {
        period: _comparison_for_period(snapshot, period)
        for period in ("7d", "30d")
    }
    from .insights import generate_insights

    result = {
        "overview": overview,
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "categories": categories,
        "difficulty": difficulty,
        "consistency": consistency,
        "trends": get_performance_trends(snapshot=snapshot),
        "learning": get_learning_analytics(snapshot=snapshot),
        "comparisons": {
            "week": weekly["comparison"],
            "month": monthly["comparison"],
            **comparisons,
        },
    }
    result["insights"] = generate_insights(result)
    return result
