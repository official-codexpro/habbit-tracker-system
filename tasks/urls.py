from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="list"),
    path("create/", views.task_create, name="create"),
    path("<int:task_id>/", views.task_detail, name="detail"),
    path("<int:task_id>/edit/", views.task_update, name="edit"),
    path("<int:task_id>/archive/", views.task_archive, name="archive"),
    path("api/daily/", views.daily_tasks_api, name="api_daily"),
    path("api/create/", views.create_task_api, name="api_create"),
    path("api/<int:task_id>/update/", views.update_task_api, name="api_update"),
    path("api/<int:task_id>/archive/", views.archive_task_api, name="api_archive"),
    path(
        "api/<int:occurrence_id>/complete/",
        views.task_completion_api,
        {"action": "complete"},
        name="api_complete",
    ),
    path(
        "api/<int:occurrence_id>/undo/",
        views.task_completion_api,
        {"action": "undo"},
        name="api_undo",
    ),
    path(
        "api/<int:occurrence_id>/skip/",
        views.task_completion_api,
        {"action": "skip"},
        name="api_skip",
    ),
    path("api/summary/", views.task_summary_api, name="api_summary"),
]
