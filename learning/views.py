import json
import logging
from datetime import date

from django.db import DatabaseError, IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .forms import (
    LearningCourseForm,
    LearningGoalForm,
    LearningSessionForm,
    LearningTopicForm,
    SkillForm,
)
from .models import LearningCourse, LearningGoal, LearningSession, LearningTopic, Skill
from .services import (
    learning_dashboard as get_learning_dashboard,
    learning_history as get_learning_history,
    reorder_topic,
    set_course_status,
    set_goal_status,
    set_skill_proficiency,
    set_topic_status,
)

logger = logging.getLogger(__name__)


def _json_payload(request):
    if request.content_type != "application/json":
        raise ValueError("Content-Type must be application/json.")
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Request body must contain valid JSON.")
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def _method_error(allowed):
    response = JsonResponse({"error": "Method not allowed."}, status=405)
    response["Allow"] = allowed
    return response


def _form_errors(form):
    return JsonResponse({"errors": form.errors.get_json_data()}, status=400)


def _serialize_goal(goal):
    return {
        "id": goal.pk,
        "title": goal.title,
        "description": goal.description,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "status": goal.status,
        "status_label": goal.get_status_display(),
        "priority": goal.priority,
        "skills": [{"id": item.pk, "name": item.name} for item in goal.skills.all()],
        "courses": [{"id": item.pk, "title": item.title} for item in goal.courses.all()],
        "total_minutes": sum(session.duration_minutes for session in goal.sessions.all()),
    }


def _serialize_skill(skill):
    return {
        "id": skill.pk,
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "learning_goal_ids": list(skill.learning_goals.values_list("pk", flat=True)),
        "current_proficiency": skill.current_proficiency,
        "target_proficiency": skill.target_proficiency,
        "status": skill.status,
        "status_label": skill.get_status_display(),
    }


def _serialize_course(course):
    course.sync_completed_topics()
    course.refresh_from_db()
    return {
        "id": course.pk,
        "title": course.title,
        "description": course.description,
        "skill_id": course.skill_id,
        "skill": course.skill.name if course.skill_id else None,
        "learning_goal_id": course.learning_goal_id,
        "learning_goal": course.learning_goal.title if course.learning_goal_id else None,
        "provider": course.provider,
        "resource_url": course.resource_url,
        "total_topics": course.total_topics,
        "completed_topics": course.completed_topics,
        "progress_percentage": course.progress_percentage,
        "status": course.status,
        "status_label": course.get_status_display(),
        "start_date": course.start_date.isoformat(),
        "target_completion_date": course.target_completion_date.isoformat() if course.target_completion_date else None,
    }


def _serialize_topic(topic):
    return {
        "id": topic.pk,
        "course_id": topic.course_id,
        "title": topic.title,
        "description": topic.description,
        "position": topic.position,
        "status": topic.status,
        "status_label": topic.get_status_display(),
        "completion_date": topic.completion_date.isoformat() if topic.completion_date else None,
    }


def _serialize_session(session):
    return {
        "id": session.pk,
        "course_id": session.course_id,
        "course": session.course.title if session.course_id else None,
        "skill_id": session.skill_id,
        "skill": session.skill.name if session.skill_id else None,
        "learning_goal_id": session.learning_goal_id,
        "learning_goal": session.learning_goal.title if session.learning_goal_id else None,
        "title": session.title,
        "topics_covered": session.topics_covered,
        "notes": session.notes,
        "duration_minutes": session.duration_minutes,
        "session_date": session.session_date.isoformat(),
    }


def _parse_history_range(request):
    value = request.GET.get("range", "30")
    if value not in {"7", "30", "90", "all"}:
        raise ValueError("History range is invalid.")
    today = timezone.localdate()
    if value == "all":
        earliest = LearningSession.objects.order_by("session_date").values_list("session_date", flat=True).first()
        start = earliest or today
    else:
        start = today - __import__("datetime").timedelta(days=int(value) - 1)
    end = today
    return start, end


def _parse_history_filters(request):
    course_id = request.GET.get("course")
    skill_id = request.GET.get("skill")
    try:
        course_id = int(course_id) if course_id not in (None, "") else None
        skill_id = int(skill_id) if skill_id not in (None, "") else None
    except ValueError:
        raise ValueError("Course and skill filters must be valid IDs.")
    if course_id is not None and not LearningCourse.objects.filter(pk=course_id).exists():
        raise ValueError("Course filter does not exist.")
    if skill_id is not None and not Skill.objects.filter(pk=skill_id).exists():
        raise ValueError("Skill filter does not exist.")
    return course_id, skill_id


@require_GET
def learning_dashboard(request):
    context = learning_dashboard_data(request)
    context.update({
        "active_section": "learning",
        "current_date": timezone.localdate(),
    })
    return render(request, "learning/index.html", context)


def learning_dashboard_data(request):
    data = get_learning_dashboard()
    return {
        **data,
        "goals": LearningGoal.objects.exclude(status=LearningGoal.Status.ARCHIVED),
        "skills": Skill.objects.exclude(status=Skill.Status.ARCHIVED),
        "courses": LearningCourse.objects.exclude(status=LearningCourse.Status.ARCHIVED),
        "sessions": LearningSession.objects.select_related("course", "skill", "learning_goal")[:30],
        "goal_form": LearningGoalForm(),
        "skill_form": SkillForm(),
        "course_form": LearningCourseForm(),
        "session_form": LearningSessionForm(),
        "topic_form": LearningTopicForm(),
        "learning_config": {
            "today": timezone.localdate().isoformat(),
            "dashboardUrl": reverse("learning:dashboard_api"),
            "historyUrl": reverse("learning:history_api"),
            "goalsUrl": reverse("learning:goals_api"),
            "skillsUrl": reverse("learning:skills_api"),
            "coursesUrl": reverse("learning:courses_api"),
            "sessionsUrl": reverse("learning:sessions_api"),
        },
    }


@require_GET
def learning_history(request):
    try:
        start, end = _parse_history_range(request)
        course_id, skill_id = _parse_history_filters(request)
        report = get_learning_history(start, end, course_id=course_id, skill_id=skill_id)
    except ValueError as error:
        report = {"error": str(error)}
    return render(
        request,
        "learning/history.html",
        {
            "active_section": "learning",
            "current_date": timezone.localdate(),
            "report": report,
            "courses": LearningCourse.objects.exclude(status=LearningCourse.Status.ARCHIVED),
            "skills": Skill.objects.exclude(status=Skill.Status.ARCHIVED),
            "selected_range": request.GET.get("range", "30"),
            "selected_course": request.GET.get("course", ""),
            "selected_skill": request.GET.get("skill", ""),
            "learning_config": {
                "today": timezone.localdate().isoformat(),
                "historyUrl": reverse("learning:history_api"),
            },
        },
    )


def _api_error(operation):
    try:
        return operation()
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except LearningGoal.DoesNotExist:
        return JsonResponse({"error": "Learning goal not found."}, status=404)
    except LearningCourse.DoesNotExist:
        return JsonResponse({"error": "Learning course not found."}, status=404)
    except LearningTopic.DoesNotExist:
        return JsonResponse({"error": "Learning topic not found."}, status=404)
    except LearningSession.DoesNotExist:
        return JsonResponse({"error": "Learning session not found."}, status=404)
    except Skill.DoesNotExist:
        return JsonResponse({"error": "Skill not found."}, status=404)
    except (IntegrityError, DatabaseError):
        logger.exception("Learning database operation failed.")
        return JsonResponse({"error": "The learning operation could not be completed."}, status=409)


@require_GET
def dashboard_api(request):
    try:
        data = get_learning_dashboard()
    except DatabaseError:
        logger.exception("Learning dashboard database error.")
        return JsonResponse({"error": "Learning data could not be loaded."}, status=500)
    return JsonResponse({
        "active_goals_count": data["active_goals_count"],
        "skills_count": data["skills_count"],
        "courses_count": data["courses_count"],
        "completed_courses_count": data["completed_courses_count"],
        "total_minutes": data["total_minutes"],
        "session_count": data["session_count"],
        "active_learning_goals": [_serialize_goal(item) for item in data["active_goals"]],
        "skills": [_serialize_skill(item) for item in data["active_skills"]],
        "active_courses": [_serialize_course(item) for item in data["active_courses"]],
        "recent_sessions": [_serialize_session(item) for item in data["recent_sessions"]],
        "consistency_dates": [item.isoformat() for item in data["consistency_dates"]],
    })


@require_GET
def history_api(request):
    def operation():
        start, end = _parse_history_range(request)
        course_id, skill_id = _parse_history_filters(request)
        report = get_learning_history(start, end, course_id=course_id, skill_id=skill_id)
        sessions = [_serialize_session(item) for item in report["sessions"]]
        return JsonResponse({
            "period_start": report["period_start"].isoformat(),
            "period_end": report["period_end"].isoformat(),
            "elapsed_days": report["elapsed_days"],
            "total_minutes": report["total_minutes"],
            "session_count": report["session_count"],
            "average_minutes": report["average_minutes"],
            "most_studied_skill": report["most_studied_skill"],
            "most_studied_course": report["most_studied_course"],
            "skill_rows": report["skill_rows"],
            "course_rows": report["course_rows"],
            "daily": [
                {
                    "session_date": row["session_date"].isoformat(),
                    "minutes": row["minutes"],
                    "sessions": row["sessions"],
                }
                for row in report["daily"]
            ],
            "active_day_count": report["active_day_count"],
            "consistency_percentage": report["consistency_percentage"],
            "sessions": sessions,
        })

    return _api_error(operation)


def goals_api(request):
    if request.method == "GET":
        goals = LearningGoal.objects.exclude(status=LearningGoal.Status.ARCHIVED).prefetch_related("skills", "courses", "sessions")
        return JsonResponse({"goals": [_serialize_goal(item) for item in goals]})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningGoalForm(payload)
        if not form.is_valid():
            return _form_errors(form)
        goal = form.save()
        return JsonResponse({"goal": _serialize_goal(goal)}, status=201)

    return _api_error(operation)


def goal_detail_api(request, goal_id):
    goal = get_object_or_404(LearningGoal.objects.prefetch_related("skills", "courses", "sessions"), pk=goal_id)
    if request.method == "GET":
        return JsonResponse({"goal": _serialize_goal(goal)})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningGoalForm(payload, instance=goal)
        if not form.is_valid():
            return _form_errors(form)
        goal.save()
        form.save()
        goal.refresh_from_db()
        return JsonResponse({"goal": _serialize_goal(goal)})

    return _api_error(operation)


def goal_status_api(request, goal_id, action):
    if request.method != "POST":
        return _method_error("POST")
    action_status = {
        "pause": LearningGoal.Status.PAUSED,
        "resume": LearningGoal.Status.ACTIVE,
        "complete": LearningGoal.Status.COMPLETED,
        "archive": LearningGoal.Status.ARCHIVED,
    }.get(action)
    if action_status is None:
        return JsonResponse({"error": "Unknown learning goal action."}, status=404)
    return _api_error(
        lambda: JsonResponse(
            {"goal": _serialize_goal(set_goal_status(goal_id, action_status))}
        )
    )


def skills_api(request):
    if request.method == "GET":
        skills = Skill.objects.exclude(status=Skill.Status.ARCHIVED).prefetch_related("learning_goals")
        return JsonResponse({"skills": [_serialize_skill(item) for item in skills]})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = SkillForm(payload)
        if not form.is_valid():
            return _form_errors(form)
        skill = form.save()
        return JsonResponse({"skill": _serialize_skill(skill)}, status=201)

    return _api_error(operation)


def skill_detail_api(request, skill_id):
    skill = get_object_or_404(Skill.objects.prefetch_related("learning_goals"), pk=skill_id)
    if request.method == "GET":
        return JsonResponse({"skill": _serialize_skill(skill)})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = SkillForm(payload, instance=skill)
        if not form.is_valid():
            return _form_errors(form)
        skill.save()
        form.save()
        skill.refresh_from_db()
        return JsonResponse({"skill": _serialize_skill(skill)})

    return _api_error(operation)


def skill_proficiency_api(request, skill_id):
    if request.method != "POST":
        return _method_error("POST")

    def operation():
        payload = _json_payload(request)
        skill = set_skill_proficiency(
            skill_id,
            payload.get("current_proficiency"),
            payload.get("target_proficiency"),
        )
        return JsonResponse({"skill": _serialize_skill(skill)})

    return _api_error(operation)


def courses_api(request):
    if request.method == "GET":
        courses = LearningCourse.objects.exclude(
            status=LearningCourse.Status.ARCHIVED
        ).select_related("skill", "learning_goal")
        return JsonResponse({"courses": [_serialize_course(item) for item in courses]})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningCourseForm(payload)
        if not form.is_valid():
            return _form_errors(form)
        course = form.save()
        course.refresh_from_db()
        return JsonResponse({"course": _serialize_course(course)}, status=201)

    return _api_error(operation)


def course_detail_api(request, course_id):
    course = get_object_or_404(
        LearningCourse.objects.select_related("skill", "learning_goal"),
        pk=course_id,
    )
    if request.method == "GET":
        return JsonResponse({"course": _serialize_course(course)})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningCourseForm(payload, instance=course)
        if not form.is_valid():
            return _form_errors(form)
        form.save()
        course.refresh_from_db()
        course.sync_completed_topics()
        return JsonResponse({"course": _serialize_course(course)})

    return _api_error(operation)


def course_status_api(request, course_id, action):
    if request.method != "POST":
        return _method_error("POST")
    action_status = {
        "pause": LearningCourse.Status.PAUSED,
        "resume": LearningCourse.Status.IN_PROGRESS,
        "complete": LearningCourse.Status.COMPLETED,
        "archive": LearningCourse.Status.ARCHIVED,
    }.get(action)
    if action_status is None:
        return JsonResponse({"error": "Unknown learning course action."}, status=404)
    return _api_error(
        lambda: JsonResponse(
            {"course": _serialize_course(set_course_status(course_id, action_status))}
        )
    )


def topics_api(request, course_id):
    course = get_object_or_404(LearningCourse, pk=course_id)
    if request.method == "GET":
        topics = LearningTopic.objects.filter(course=course)
        return JsonResponse({"topics": [_serialize_topic(item) for item in topics]})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningTopicForm(payload)
        if not form.is_valid():
            return _form_errors(form)
        topic = form.save(commit=False)
        topic.course = course
        try:
            topic.full_clean()
            topic.save()
        except IntegrityError:
            raise
        course.sync_completed_topics()
        return JsonResponse({"topic": _serialize_topic(topic)}, status=201)

    return _api_error(operation)


def topic_detail_api(request, topic_id):
    topic = get_object_or_404(LearningTopic.objects.select_related("course"), pk=topic_id)
    if request.method == "GET":
        return JsonResponse({"topic": _serialize_topic(topic)})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningTopicForm(payload, instance=topic)
        if not form.is_valid():
            return _form_errors(form)
        try:
            form.save()
            topic.course.sync_completed_topics()
        except IntegrityError:
            raise
        topic.refresh_from_db()
        return JsonResponse({"topic": _serialize_topic(topic)})

    return _api_error(operation)


def topic_status_api(request, topic_id, action):
    if request.method != "POST":
        return _method_error("POST")
    action_status = {
        "complete": LearningTopic.Status.COMPLETED,
        "progress": LearningTopic.Status.IN_PROGRESS,
        "reopen": LearningTopic.Status.NOT_STARTED,
    }.get(action)
    if action_status is None:
        return JsonResponse({"error": "Unknown learning topic action."}, status=404)
    return _api_error(
        lambda: JsonResponse(
            {"topic": _serialize_topic(set_topic_status(topic_id, action_status))}
        )
    )


def topic_reorder_api(request, topic_id):
    if request.method != "POST":
        return _method_error("POST")

    def operation():
        payload = _json_payload(request)
        position = payload.get("position")
        topic = reorder_topic(topic_id, position)
        return JsonResponse({"topic": _serialize_topic(topic)})

    return _api_error(operation)


def sessions_api(request):
    sessions = LearningSession.objects.select_related("course", "skill", "learning_goal")
    if request.method == "GET":
        course_id = request.GET.get("course")
        skill_id = request.GET.get("skill")
        date_value = request.GET.get("date")
        if course_id:
            try:
                sessions = sessions.filter(course_id=int(course_id))
            except ValueError:
                return JsonResponse({"error": "Course filter must be a valid ID."}, status=400)
        if skill_id:
            try:
                sessions = sessions.filter(skill_id=int(skill_id))
            except ValueError:
                return JsonResponse({"error": "Skill filter must be a valid ID."}, status=400)
        if date_value:
            try:
                parsed_date = date.fromisoformat(date_value)
            except ValueError:
                return JsonResponse({"error": "Date must use the YYYY-MM-DD format."}, status=400)
            sessions = sessions.filter(session_date=parsed_date)
        return JsonResponse({"sessions": [_serialize_session(item) for item in sessions]})
    if request.method != "POST":
        return _method_error("GET, POST")

    def operation():
        payload = _json_payload(request)
        form = LearningSessionForm(payload)
        if not form.is_valid():
            return _form_errors(form)
        session = form.save()
        session.refresh_from_db()
        return JsonResponse({"session": _serialize_session(session)}, status=201)

    return _api_error(operation)


def session_detail_api(request, session_id):
    learning_session = get_object_or_404(
        LearningSession.objects.select_related("course", "skill", "learning_goal"),
        pk=session_id,
    )
    if request.method == "GET":
        return JsonResponse({"session": _serialize_session(learning_session)})
    if request.method == "POST":
        def operation():
            payload = _json_payload(request)
            form = LearningSessionForm(payload, instance=learning_session)
            if not form.is_valid():
                return _form_errors(form)
            form.save()
            learning_session.refresh_from_db()
            return JsonResponse({"session": _serialize_session(learning_session)})

        return _api_error(operation)
    if request.method == "DELETE":
        learning_session.delete()
        return JsonResponse({"deleted": True, "session_id": session_id})
    return _method_error("GET, POST, DELETE")
