from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import LearningCourse, LearningGoal, LearningSession, LearningTopic, Skill


def learning_dashboard():
    today = timezone.localdate()
    active_goals = LearningGoal.objects.filter(status=LearningGoal.Status.ACTIVE)
    active_skills = Skill.objects.filter(status=Skill.Status.ACTIVE)
    active_courses = LearningCourse.objects.exclude(status=LearningCourse.Status.ARCHIVED)
    sessions = LearningSession.objects.select_related("course", "skill", "learning_goal")
    recent_sessions = sessions[:8]
    active_dates = sessions.filter(session_date__lte=today).dates("session_date", "day")
    session_totals = sessions.aggregate(
        total_minutes=Sum("duration_minutes"),
        session_count=Count("pk"),
    )
    return {
        "active_goals": active_goals,
        "active_goals_count": active_goals.count(),
        "active_skills": active_skills,
        "skills_count": Skill.objects.exclude(status=Skill.Status.ARCHIVED).count(),
        "active_courses": active_courses.exclude(status=LearningCourse.Status.COMPLETED),
        "courses_count": LearningCourse.objects.exclude(status=LearningCourse.Status.ARCHIVED).count(),
        "completed_courses_count": LearningCourse.objects.filter(status=LearningCourse.Status.COMPLETED).count(),
        "total_minutes": session_totals["total_minutes"] or 0,
        "session_count": session_totals["session_count"] or 0,
        "recent_sessions": recent_sessions,
        "consistency_dates": list(active_dates),
    }


def learning_history(start_date=None, end_date=None, *, course_id=None, skill_id=None):
    today = timezone.localdate()
    end_date = end_date or today
    start_date = start_date or (end_date - timedelta(days=29))
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date.")
    if end_date > today:
        raise ValueError("Learning history cannot include future session dates.")

    sessions = LearningSession.objects.filter(
        session_date__gte=start_date,
        session_date__lte=end_date,
    ).select_related("course", "skill", "learning_goal")
    if course_id:
        sessions = sessions.filter(course_id=course_id)
    if skill_id:
        sessions = sessions.filter(skill_id=skill_id)

    totals = sessions.aggregate(
        total_minutes=Sum("duration_minutes"),
        session_count=Count("pk"),
        average_minutes=Avg("duration_minutes"),
    )
    total_minutes = totals["total_minutes"] or 0
    session_count = totals["session_count"] or 0

    skill_rows = list(
        sessions.exclude(skill_id=None)
        .values("skill_id", "skill__name")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("-minutes", "skill__name")
    )
    course_rows = list(
        sessions.exclude(course_id=None)
        .values("course_id", "course__title")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("-minutes", "course__title")
    )
    daily = list(
        sessions.values("session_date")
        .annotate(minutes=Sum("duration_minutes"), sessions=Count("pk"))
        .order_by("session_date")
    )

    elapsed_days = (end_date - start_date).days + 1
    active_dates = sessions.dates("session_date", "day")
    active_day_count = active_dates.count()
    return {
        "period_start": start_date,
        "period_end": end_date,
        "elapsed_days": elapsed_days,
        "total_minutes": total_minutes,
        "session_count": session_count,
        "average_minutes": round(totals["average_minutes"] or 0, 1),
        "most_studied_skill": skill_rows[0] if skill_rows else None,
        "most_studied_course": course_rows[0] if course_rows else None,
        "skill_rows": skill_rows,
        "course_rows": course_rows,
        "daily": daily,
        "active_day_count": active_day_count,
        "consistency_percentage": round(active_day_count * 100 / elapsed_days, 1) if elapsed_days else None,
        "sessions": sessions,
    }


@transaction.atomic
def set_goal_status(goal_id, status):
    goal = LearningGoal.objects.select_for_update().get(pk=goal_id)
    valid_statuses = {choice for choice, _label in LearningGoal.Status.choices}
    if status not in valid_statuses:
        raise ValueError("Invalid learning goal status.")
    goal.status = status
    goal.save(update_fields=["status", "updated_at"])
    return goal


@transaction.atomic
def set_skill_proficiency(skill_id, current=None, target=None):
    skill = Skill.objects.select_for_update().get(pk=skill_id)
    if current is not None:
        if type(current) is not int or not 1 <= current <= 5:
            raise ValueError("Current proficiency must be between 1 and 5.")
        skill.current_proficiency = current
    if target is not None:
        if type(target) is not int or not 1 <= target <= 5:
            raise ValueError("Target proficiency must be between 1 and 5.")
        skill.target_proficiency = target
    skill.full_clean()
    skill.save(update_fields=["current_proficiency", "target_proficiency", "updated_at"])
    return skill


@transaction.atomic
def set_course_status(course_id, status):
    course = LearningCourse.objects.select_for_update().get(pk=course_id)
    valid_statuses = {choice for choice, _label in LearningCourse.Status.choices}
    if status not in valid_statuses:
        raise ValueError("Invalid learning course status.")
    course.status = status
    course.save(update_fields=["status", "updated_at"])
    return course


@transaction.atomic
def set_topic_status(topic_id, status):
    topic = LearningTopic.objects.select_for_update().select_related("course").get(pk=topic_id)
    valid_statuses = {choice for choice, _label in LearningTopic.Status.choices}
    if status not in valid_statuses:
        raise ValueError("Invalid learning topic status.")
    topic.status = status
    topic.completion_date = timezone.localdate() if status == LearningTopic.Status.COMPLETED else None
    topic.full_clean()
    topic.save(update_fields=["status", "completion_date", "updated_at"])
    topic.course.sync_completed_topics()
    topic.course.refresh_from_db()
    return topic


@transaction.atomic
def reorder_topic(topic_id, position):
    topic = LearningTopic.objects.select_for_update().select_related("course").get(pk=topic_id)
    if type(position) is not int or position < 1:
        raise ValueError("Topic position must be a positive integer.")
    course_topics = list(
        LearningTopic.objects.select_for_update()
        .filter(course=topic.course)
        .exclude(pk=topic.pk)
        .order_by("position", "pk")
    )
    insert_at = min(position - 1, len(course_topics))
    course_topics.insert(insert_at, topic)
    for offset, course_topic in enumerate(course_topics, start=1):
        LearningTopic.objects.filter(pk=course_topic.pk).update(position=1000 + offset)
    for index, course_topic in enumerate(course_topics, start=1):
        LearningTopic.objects.filter(pk=course_topic.pk).update(position=index)
    topic.position = insert_at + 1
    return topic
