from django import forms
from django.db.models import Q

from .models import Task, TaskCategory


WEEKDAY_CHOICES = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)


class TaskForm(forms.ModelForm):
    recurrence_days = forms.MultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Required for weekly and custom recurrence.",
    )

    class Meta:
        model = Task
        fields = (
            "title",
            "description",
            "category",
            "difficulty",
            "estimated_minutes",
            "xp_reward",
            "recurrence_type",
            "recurrence_days",
            "start_date",
            "end_date",
        )
        widgets = {
            "title": forms.TextInput(attrs={"autocomplete": "off", "maxlength": 200}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "estimated_minutes": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "xp_reward": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = TaskCategory.objects.filter(is_active=True)
        if self.instance.pk and self.instance.category_id:
            categories = TaskCategory.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.category_id)
            )
        self.fields["category"].queryset = categories
        if self.instance.pk:
            self.initial["recurrence_days"] = [
                str(day) for day in self.instance.recurrence_days
            ]

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a task title.")
        return title

    def clean_recurrence_days(self):
        return sorted(int(day) for day in self.cleaned_data.get("recurrence_days", []))
