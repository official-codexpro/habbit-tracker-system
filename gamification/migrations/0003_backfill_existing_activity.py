from django.db import migrations
from django.db.models import Count, Q
from django.utils import timezone


def backfill_existing_activity(apps, schema_editor):
    PlayerProfile = apps.get_model("gamification", "PlayerProfile")
    Achievement = apps.get_model("gamification", "Achievement")
    PlayerAchievement = apps.get_model("gamification", "PlayerAchievement")
    DailyStreak = apps.get_model("gamification", "DailyStreak")
    TaskCompletion = apps.get_model("tasks", "TaskCompletion")

    profile, _ = PlayerProfile.objects.get_or_create(
        singleton_key=1,
        defaults={
            "display_name": "Player One",
            "total_xp": 0,
            "current_level": 1,
            "current_rank": "BEGINNER",
            "longest_streak": 0,
        },
    )
    activity_counts = list(
        TaskCompletion.objects.filter(
            status="COMPLETED",
            is_superseded=False,
            scheduled_date__lte=timezone.localdate(),
        )
        .values("scheduled_date")
        .annotate(count=Count("pk"))
        .order_by("scheduled_date")
    )
    for activity in activity_counts:
        DailyStreak.objects.get_or_create(
            player_id=profile.pk,
            activity_date=activity["scheduled_date"],
            defaults={
                "qualifying_activity_count": activity["count"],
                "is_active_day": True,
            },
        )

    longest = current = 0
    previous_date = None
    for activity in activity_counts:
        activity_date = activity["scheduled_date"]
        if previous_date and (activity_date - previous_date).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous_date = activity_date
    if longest > profile.longest_streak:
        PlayerProfile.objects.filter(pk=profile.pk).update(longest_streak=longest)

    completed = TaskCompletion.objects.filter(
        status="COMPLETED",
        is_superseded=False,
    )
    metrics = {
        "TASK_COUNT": completed.count(),
        "LEARNING_COUNT": completed.filter(
            task__category__name__iexact="Learning"
        ).count(),
        "HARD_TASK_COUNT": completed.filter(
            task__difficulty__in=["HARD", "EXTREME"]
        ).count(),
        "STREAK": longest,
        "LIFETIME_XP": 0,
    }
    for achievement in Achievement.objects.filter(is_active=True):
        if metrics.get(achievement.condition_type, 0) >= achievement.condition_value:
            PlayerAchievement.objects.get_or_create(
                player_id=profile.pk,
                achievement_id=achievement.pk,
                defaults={"xp_awarded": 0},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("gamification", "0002_seed_initial_achievements"),
        ("tasks", "0002_taskcompletion_completion_cycle"),
    ]

    operations = [
        migrations.RunPython(backfill_existing_activity, migrations.RunPython.noop),
    ]
