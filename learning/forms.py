from django import forms
from django.utils import timezone

from .models import (
    LearningCourse,
    LearningGoal,
    LearningSession,
    LearningTopic,
    Skill,
)


class LearningGoalForm(forms.ModelForm):
    class Meta:
        model = LearningGoal
        fields = ("title", "description", "target_date", "status", "priority")
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 200, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "target_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a learning goal title.")
        return title


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = (
            "name",
            "description",
            "category",
            "learning_goals",
            "current_proficiency",
            "target_proficiency",
            "status",
        )
        widgets = {
            "name": forms.TextInput(attrs={"maxlength": 120, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "category": forms.TextInput(attrs={"maxlength": 80}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Enter a skill name.")
        return name


class LearningCourseForm(forms.ModelForm):
    class Meta:
        model = LearningCourse
        fields = (
            "title",
            "description",
            "skill",
            "learning_goal",
            "provider",
            "resource_url",
            "total_topics",
            "completed_topics",
            "status",
            "start_date",
            "target_completion_date",
        )
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 200, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "provider": forms.TextInput(attrs={"maxlength": 200}),
            "resource_url": forms.URLInput(),
            "total_topics": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "completed_topics": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "target_completion_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a course title.")
        return title


class LearningTopicForm(forms.ModelForm):
    class Meta:
        model = LearningTopic
        fields = ("title", "description", "position", "status", "completion_date")
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 200, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "position": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "completion_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a topic title.")
        return title


class LearningSessionForm(forms.ModelForm):
    class Meta:
        model = LearningSession
        fields = (
            "course",
            "skill",
            "learning_goal",
            "title",
            "topics_covered",
            "notes",
            "duration_minutes",
            "session_date",
        )
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 200, "autocomplete": "off"}),
            "topics_covered": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "duration_minutes": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "session_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a learning session title.")
        return title

    def clean_duration_minutes(self):
        duration = self.cleaned_data["duration_minutes"]
        if duration is None or duration < 1:
            raise forms.ValidationError("Duration must be greater than zero.")
        return duration

    def clean_session_date(self):
        session_date = self.cleaned_data["session_date"]
        if session_date and session_date > timezone.localdate():
            raise forms.ValidationError("Learning sessions cannot be dated in the future.")
        return session_date
