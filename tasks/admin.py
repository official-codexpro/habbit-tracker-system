from django.contrib import admin

from .models import Task, TaskCategory, TaskCompletion
from .services import synchronize_future_occurrences


@admin.register(TaskCategory)
class TaskCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "difficulty",
        "recurrence_type",
        "start_date",
        "is_active",
    )
    list_filter = ("difficulty", "recurrence_type", "is_active")
    search_fields = ("title", "description", "category__name")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category",)

    def save_model(self, request, obj, form, change):
        previous = (
            Task.objects.filter(pk=obj.pk)
            .values("is_active", "recurrence_type", "recurrence_days", "start_date", "end_date")
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        schedule_fields = ("is_active", "recurrence_type", "recurrence_days", "start_date", "end_date")
        if previous and any(previous[field] != getattr(obj, field) for field in schedule_fields):
            synchronize_future_occurrences(obj)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaskCompletion)
class TaskCompletionAdmin(admin.ModelAdmin):
    list_display = ("task", "scheduled_date", "status", "completed_at", "xp_awarded")
    list_filter = ("status", "scheduled_date")
    search_fields = ("task__title",)
    date_hierarchy = "scheduled_date"
    list_select_related = ("task",)
    readonly_fields = (
        "task",
        "scheduled_date",
        "status",
        "completed_at",
        "notes",
        "xp_awarded",
        "is_superseded",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
