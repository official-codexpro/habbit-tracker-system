from django.http import Http404
from django.shortcuts import render

from django.utils import timezone

from gamification.models import Achievement, PlayerAchievement
from gamification.services import (
    get_player_profile,
)
from learning.models import LearningSession
from tasks.models import TaskCompletion
from tasks.services import get_task_completion_summary, get_tasks_for_date


COMING_SOON_SECTIONS = {
    "daily-tasks": "Daily Tasks",
    "habits": "Habits",
    "learning": "Learning",
    "skills": "Skills",
    "analytics": "Analytics",
    "achievements": "Achievements",
    "rewards": "Rewards",
    "settings": "Settings",
}


def home(request):
    today = timezone.localdate()
    profile = get_player_profile()
    mission_summary = get_task_completion_summary(today)
    missions = get_tasks_for_date(today).select_related("task", "task__category")[:6]
    learning_count = LearningSession.objects.filter(session_date=today).count()
    learning_total = sum(
        session.duration_minutes
        for session in LearningSession.objects.filter(session_date=today)
    )
    unlocked_codes = set(
        PlayerAchievement.objects.filter(player=profile).values_list(
            "achievement__code", flat=True
        )
    )
    achievements = list(Achievement.objects.filter(is_active=True).order_by(
        "category", "condition_value", "name"
    )[:5])
    return render(
        request,
        "dashboard/index.html",
        {
            "active_section": "overview",
            "current_date": today,
            "mission_summary": mission_summary,
            "today_missions": missions,
            "learning_today_count": learning_count,
            "learning_today_minutes": learning_total,
            "dashboard_achievements": achievements,
            "unlocked_achievement_codes": unlocked_codes,
        },
    )


def coming_soon(request, section):
    section_name = COMING_SOON_SECTIONS.get(section)
    if section_name is None:
        raise Http404("This section does not exist.")

    return render(
        request,
        "dashboard/coming_soon.html",
        {
            "active_section": section,
            "section_name": section_name,
        },
    )
