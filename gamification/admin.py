from django.contrib import admin

from .models import Achievement, DailyStreak, PlayerAchievement, PlayerProfile, XPTransaction


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "current_level", "current_rank", "total_xp", "longest_streak")
    list_filter = ("current_rank",)
    search_fields = ("display_name",)
    readonly_fields = (
        "singleton_key",
        "total_xp",
        "current_level",
        "current_rank",
        "longest_streak",
        "created_at",
        "updated_at",
    )
    fields = (
        "display_name",
        "singleton_key",
        "total_xp",
        "current_level",
        "current_rank",
        "longest_streak",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not PlayerProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(XPTransaction)
class XPTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "transaction_type",
        "amount",
        "balance_after",
        "description",
        "created_at",
    )
    list_filter = ("transaction_type", "created_at")
    search_fields = ("description", "player__display_name")
    date_hierarchy = "created_at"
    readonly_fields = (
        "player",
        "task_completion",
        "completion_cycle",
        "transaction_type",
        "amount",
        "balance_after",
        "description",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "condition_type", "condition_value", "xp_reward", "is_active")
    list_filter = ("category", "is_active", "condition_type")
    search_fields = ("name", "code", "description")
    ordering = ("category", "condition_value", "name")


@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at", "xp_awarded")
    list_filter = ("achievement__category", "unlocked_at")
    search_fields = ("player__display_name", "achievement__name", "achievement__code")
    readonly_fields = ("player", "achievement", "unlocked_at", "xp_awarded")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DailyStreak)
class DailyStreakAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "activity_date",
        "qualifying_activity_count",
        "is_active_day",
        "updated_at",
    )
    list_filter = ("is_active_day", "activity_date")
    search_fields = ("player__display_name",)
    date_hierarchy = "activity_date"
    readonly_fields = (
        "player",
        "activity_date",
        "qualifying_activity_count",
        "is_active_day",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
