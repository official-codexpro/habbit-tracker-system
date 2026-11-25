import logging
import json
import re
import uuid
from datetime import date

from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from gamification.services import InsufficientXP, InvalidTaskXP

from .forms import TaskForm, WEEKDAY_CHOICES
from .models import Task, TaskCategory, TaskCompletion
from .services import (
    InvalidOccurrenceTransition,
    archive_task,
    complete_task_occurrence,
    get_task_completion_summary,
    get_task_history,
    generate_task_occurrences,
    get_tasks_for_date,
    skip_task_occurrence,
    synchronize_future_occurrences,
    undo_task_completion,
)
from notifications.models import TaskCreationRequest

logger = logging.getLogger(__name__)


def task_list(request):
    show_archived = request.GET.get("archived") == "1"
    if show_archived:
        tasks = Task.objects.filter(is_active=False).select_related("category")
        return render(
            request,
            "tasks/task_list.html",
            {
                "tasks": tasks,
                "show_archived": True,
                "active_section": "daily-tasks",
            },
        )

    target_date, date_error = _parse_date(request.GET.get("date"))
    filters, filter_error = _parse_task_filters(request.GET)
    if date_error or filter_error:
        return HttpResponseBadRequest(date_error or filter_error)

    occurrences = get_tasks_for_date(target_date)
    summary = get_task_completion_summary(target_date)
    occurrences = _apply_task_filters(occurrences, filters)
    return render(
        request,
        "tasks/task_list.html",
        {
            "occurrences": occurrences,
            "summary": summary,
            "target_date": target_date,
            "filters": filters,
            "categories": TaskCategory.objects.order_by("name"),
            "active_categories": TaskCategory.objects.filter(is_active=True).order_by("name"),
            "task_form": TaskForm(),
            "difficulty_choices": Task.Difficulty.choices,
            "mission_config": {
                "date": target_date.isoformat(),
                "today": timezone.localdate().isoformat(),
                "dailyUrl": reverse("tasks:api_daily"),
                "createUrl": reverse("tasks:api_create"),
                "editPageUrlTemplate": reverse(
                    "tasks:edit", kwargs={"task_id": 0}
                ),
                "updateUrlTemplate": reverse(
                    "tasks:api_update", kwargs={"task_id": 0}
                ),
                "archiveUrlTemplate": reverse(
                    "tasks:api_archive", kwargs={"task_id": 0}
                ),
                "completeUrlTemplate": reverse(
                    "tasks:api_complete", kwargs={"occurrence_id": 0}
                ),
                "undoUrlTemplate": reverse(
                    "tasks:api_undo", kwargs={"occurrence_id": 0}
                ),
                "skipUrlTemplate": reverse(
                    "tasks:api_skip", kwargs={"occurrence_id": 0}
                ),
                "createKey": uuid.uuid4().hex,
            },
            "has_active_tasks": Task.objects.filter(is_active=True).exists(),
            "show_archived": False,
            "active_section": "daily-tasks",
        },
    )


def task_create(request):
    if request.method == "POST":
        request_key = request.POST.get("idempotency_key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_key):
            request_key = uuid.uuid4().hex
        previous_request = TaskCreationRequest.objects.select_related("task").filter(
            pk=request_key
        ).first()
        if previous_request and previous_request.task_id:
            return redirect("tasks:detail", task_id=previous_request.task_id)
        if previous_request:
            request_key = uuid.uuid4().hex
        form = TaskForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    task = form.save()
                    TaskCreationRequest.objects.create(key=request_key, task=task)
            except IntegrityError:
                previous_request = TaskCreationRequest.objects.select_related("task").filter(
                    pk=request_key
                ).first()
                if previous_request and previous_request.task_id:
                    return redirect("tasks:detail", task_id=previous_request.task_id)
                raise
            return redirect("tasks:detail", task_id=task.pk)
    else:
        form = TaskForm()
    return render(
        request,
        "tasks/task_form.html",
        {
            "form": form,
            "is_create": True,
            "idempotency_key": uuid.uuid4().hex,
            "active_section": "daily-tasks",
        },
    )


def task_detail(request, task_id):
    task = get_object_or_404(Task.objects.select_related("category"), pk=task_id)
    occurrences = Paginator(get_task_history(task.pk), 30).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "tasks/task_detail.html",
        {
            "task": task,
            "occurrences": occurrences,
            "active_section": "daily-tasks",
            "recurrence_days_display": ", ".join(
                dict(WEEKDAY_CHOICES)[day] for day in task.recurrence_days
            ),
        },
    )


def task_update(request, task_id):
    task = get_object_or_404(Task.objects.select_related("category"), pk=task_id)
    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            with transaction.atomic():
                updated_task = form.save()
                synchronize_future_occurrences(updated_task)
            return redirect("tasks:detail", task_id=updated_task.pk)
    else:
        form = TaskForm(instance=task)
    return render(
        request,
        "tasks/task_form.html",
        {"form": form, "is_create": False, "active_section": "daily-tasks"},
    )


def task_archive(request, task_id):
    if request.method != "POST":
        return _api_method_not_allowed("POST")
    task = get_object_or_404(Task, pk=task_id)
    archive_task(task)
    return redirect("tasks:list")


def _api_method_not_allowed(method):
    response = JsonResponse({"error": "Method not allowed."}, status=405)
    response["Allow"] = method
    return response


def _database_error_response(action, *, conflict=False):
    logger.exception("Mission database operation failed: %s.", action)
    if conflict:
        return JsonResponse(
            {"error": "The mission conflicts with current database state."},
            status=409,
        )
    return JsonResponse(
        {"error": "A database error prevented the mission request."},
        status=500,
    )


def _parse_date(raw_date):
    if not raw_date:
        return timezone.localdate(), None
    try:
        parsed_date = date.fromisoformat(raw_date)
    except ValueError:
        return None, "Date must use the YYYY-MM-DD format."
    if parsed_date.isoformat() != raw_date:
        return None, "Date must use the YYYY-MM-DD format."
    return parsed_date, None


def _parse_task_filters(params):
    status_value = params.get("status", "").strip().lower()
    status_map = {value.lower(): value for value, _ in TaskCompletion.Status.choices}
    if status_value and status_value not in status_map:
        return None, "Status filter is invalid."

    category_value = params.get("category", "").strip()
    if category_value:
        try:
            category_id = int(category_value)
        except ValueError:
            return None, "Category filter must be a valid category ID."
        if not TaskCategory.objects.filter(pk=category_id).exists():
            return None, "Category filter does not exist."
    else:
        category_id = None

    difficulty_value = params.get("difficulty", "").strip().upper()
    valid_difficulties = {value for value, _ in Task.Difficulty.choices}
    if difficulty_value and difficulty_value not in valid_difficulties:
        return None, "Difficulty filter is invalid."

    search = params.get("search", "").strip()
    if len(search) > 200:
        return None, "Search text must be 200 characters or fewer."
    return {
        "status": status_map.get(status_value),
        "category": category_id,
        "difficulty": difficulty_value or None,
        "search": search,
    }, None


def _apply_task_filters(occurrences, filters):
    if filters["status"]:
        occurrences = occurrences.filter(status=filters["status"])
    if filters["category"]:
        occurrences = occurrences.filter(task__category_id=filters["category"])
    if filters["difficulty"]:
        occurrences = occurrences.filter(task__difficulty=filters["difficulty"])
    if filters["search"]:
        occurrences = occurrences.filter(
            Q(task__title__icontains=filters["search"])
            | Q(task__description__icontains=filters["search"])
        )
    return occurrences


def _api_target_date(request):
    target_date, error = _parse_date(request.GET.get("date"))
    if error:
        return None, JsonResponse(
            {"error": error},
            status=400,
        )
    return target_date, None


def _serialize_task(task):
    return {
        "id": task.pk,
        "title": task.title,
        "description": task.description,
        "category_id": task.category_id,
        "category": task.category.name,
        "category_color": task.category.color,
        "category_icon": task.category.icon,
        "difficulty": task.difficulty,
        "difficulty_label": task.get_difficulty_display(),
        "estimated_minutes": task.estimated_minutes,
        "xp_reward": task.xp_reward,
        "recurrence_type": task.recurrence_type,
        "recurrence_days": task.recurrence_days,
        "start_date": task.start_date.isoformat(),
        "end_date": task.end_date.isoformat() if task.end_date else None,
        "is_active": task.is_active,
    }


def _serialize_occurrence(occurrence):
    task = _serialize_task(occurrence.task)
    return {
        **task,
        "id": occurrence.pk,
        "task_id": task["id"],
        "scheduled_date": occurrence.scheduled_date.isoformat(),
        "status": occurrence.status,
        "status_label": occurrence.get_status_display(),
        "completed_at": (
            occurrence.completed_at.isoformat() if occurrence.completed_at else None
        ),
        "notes": occurrence.notes,
        "xp_reward": occurrence.task.xp_reward,
        "xp_awarded": occurrence.xp_awarded,
    }


def daily_tasks_api(request):
    if request.method != "GET":
        return _api_method_not_allowed("GET")
    target_date, error = _api_target_date(request)
    if error:
        return error

    try:
        filters, filter_error = _parse_task_filters(request.GET)
    except DatabaseError:
        return _database_error_response("validating mission filters for")
    if filter_error:
        return JsonResponse({"error": filter_error}, status=400)
    try:
        summary = get_task_completion_summary(target_date)
        occurrences = list(
            _apply_task_filters(get_tasks_for_date(target_date), filters)
        )
        has_active_tasks = Task.objects.filter(is_active=True).exists()
    except DatabaseError:
        return _database_error_response("loading")
    return JsonResponse(
        {
            "date": target_date.isoformat(),
            "tasks": [_serialize_occurrence(occurrence) for occurrence in occurrences],
            "summary": summary,
            "has_active_tasks": has_active_tasks,
        }
    )


def create_task_api(request):
    if request.method != "POST":
        return _api_method_not_allowed("POST")
    if request.content_type != "application/json":
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )
    target_date, error = _api_target_date(request)
    if error:
        return error
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must contain valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)

    request_key = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
    if request_key:
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_key):
            return JsonResponse({"error": "Idempotency key must be 1–64 letters, numbers, _ or -."}, status=400)
        previous_request = TaskCreationRequest.objects.select_related("task", "task__category").filter(
            pk=request_key
        ).first()
        if previous_request:
            if not previous_request.task_id:
                return JsonResponse({"error": "This idempotency key has already been used."}, status=409)
            task = previous_request.task
            return _task_creation_response(task, target_date, status=200)

    try:
        form = TaskForm(payload)
        if not form.is_valid():
            return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    except DatabaseError:
        return _database_error_response("validating")
    try:
        with transaction.atomic():
            task = form.save()
            if request_key:
                TaskCreationRequest.objects.create(key=request_key, task=task)
            generated_occurrences = generate_task_occurrences(target_date)
    except IntegrityError:
        if request_key:
            previous_request = TaskCreationRequest.objects.select_related(
                "task", "task__category"
            ).filter(pk=request_key).first()
            if previous_request and previous_request.task_id:
                return _task_creation_response(previous_request.task, target_date, status=200)
        return _database_error_response("creating", conflict=True)
    except DatabaseError:
        return _database_error_response("creating")
    scheduled_for_selected_date = any(
        occurrence.task_id == task.pk for occurrence in generated_occurrences
    )
    return _task_creation_response(task, target_date, status=201, scheduled=scheduled_for_selected_date)


def _task_creation_response(task, target_date, *, status, scheduled=None):
    if scheduled is None:
        scheduled = task.is_scheduled_for(target_date)
    return JsonResponse(
        {
            "id": task.pk,
            "title": task.title,
            "category": task.category.name,
            "difficulty": task.difficulty,
            "recurrence_type": task.recurrence_type,
            "start_date": task.start_date.isoformat(),
            "end_date": task.end_date.isoformat() if task.end_date else None,
            "task": _serialize_task(task),
            "scheduled_for_selected_date": scheduled,
        },
        status=status,
    )


def update_task_api(request, task_id):
    if request.method != "POST":
        return _api_method_not_allowed("POST")
    if request.content_type != "application/json":
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )
    try:
        task = Task.objects.select_related("category").filter(pk=task_id).first()
    except DatabaseError:
        return _database_error_response("loading")
    if task is None:
        return JsonResponse({"error": "Task not found."}, status=404)
    target_date, error = _api_target_date(request)
    if error:
        return error
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must contain valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)

    try:
        form = TaskForm(payload, instance=task)
        if not form.is_valid():
            return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    except DatabaseError:
        return _database_error_response("validating")
    try:
        with transaction.atomic():
            task = form.save()
            synchronize_future_occurrences(task)
            generate_task_occurrences(target_date)
    except IntegrityError:
        return _database_error_response("updating", conflict=True)
    except DatabaseError:
        return _database_error_response("updating")
    return JsonResponse({"task": _serialize_task(task)})


def archive_task_api(request, task_id):
    if request.method != "POST":
        return _api_method_not_allowed("POST")
    try:
        task = Task.objects.filter(pk=task_id).first()
    except DatabaseError:
        return _database_error_response("loading")
    if task is None:
        return JsonResponse({"error": "Task not found."}, status=404)
    try:
        archived_task = archive_task(task)
    except DatabaseError:
        return _database_error_response("archiving")
    return JsonResponse(
        {"task_id": archived_task.pk, "is_active": archived_task.is_active}
    )


def task_completion_api(request, occurrence_id, action):
    if request.method != "POST":
        return _api_method_not_allowed("POST")
    service_by_action = {
        "complete": complete_task_occurrence,
        "undo": undo_task_completion,
        "skip": skip_task_occurrence,
    }
    service = service_by_action.get(action)
    if service is None:
        return JsonResponse({"error": "Unknown task action."}, status=404)
    try:
        occurrence = service(occurrence_id)
    except TaskCompletion.DoesNotExist:
        return JsonResponse({"error": "Task occurrence not found."}, status=404)
    except (InvalidOccurrenceTransition, InvalidTaskXP, InsufficientXP) as error:
        return JsonResponse({"error": str(error)}, status=409)
    except DatabaseError:
        return _database_error_response("updating")
    return JsonResponse({"task": _serialize_occurrence(occurrence)})


def task_summary_api(request):
    if request.method != "GET":
        return _api_method_not_allowed("GET")
    target_date, error = _api_target_date(request)
    if error:
        return error
    try:
        summary = get_task_completion_summary(target_date)
    except DatabaseError:
        return _database_error_response("loading progress for")
    return JsonResponse({"date": target_date.isoformat(), "summary": summary})
