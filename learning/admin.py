from django.contrib import admin

from .models import LearningCourse, LearningGoal, LearningSession, LearningTopic, Skill


@admin.register(LearningGoal)
class LearningGoalAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "priority", "target_date", "updated_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "description")
    filter_horizontal = ()
    date_hierarchy = "target_date"


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "current_proficiency", "target_proficiency", "status")
    list_filter = ("status", "category")
    search_fields = ("name", "description", "category")
    filter_horizontal = ("learning_goals",)


class LearningTopicInline(admin.TabularInline):
    model = LearningTopic
    extra = 0
    fields = ("position", "title", "status", "completion_date")


@admin.register(LearningCourse)
class LearningCourseAdmin(admin.ModelAdmin):
    list_display = ("title", "skill", "learning_goal", "status", "completed_topics", "total_topics", "target_completion_date")
    list_filter = ("status", "skill")
    search_fields = ("title", "description", "provider")
    inlines = (LearningTopicInline,)
    date_hierarchy = "start_date"


@admin.register(LearningTopic)
class LearningTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "position", "status", "completion_date")
    list_filter = ("status", "course")
    search_fields = ("title", "description")


@admin.register(LearningSession)
class LearningSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "session_date", "duration_minutes", "course", "skill", "learning_goal")
    list_filter = ("session_date", "course", "skill")
    search_fields = ("title", "topics_covered", "notes")
    date_hierarchy = "session_date"
