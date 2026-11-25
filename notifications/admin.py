from django.contrib import admin

from .models import EmailNotification


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "notification_type",
        "is_manual",
        "task",
        "report_date",
        "status",
        "attempts",
        "created_at",
        "sent_at",
    )
    list_filter = ("notification_type", "status", "is_manual", "created_at")
    search_fields = ("task__title", "error_message")
    readonly_fields = (
        "notification_type",
        "is_manual",
        "task",
        "report_date",
        "status",
        "attempts",
        "error_message",
        "created_at",
        "last_attempt_at",
        "next_attempt_at",
        "sent_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False
