import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import TaskForm
from .models import Task, TaskCategory, TaskCompletion
from .services import (
    InvalidOccurrenceTransition,
    archive_task,
    complete_task_occurrence,
    generate_task_occurrences,
    get_task_completion_summary,
    get_task_history,
    get_tasks_by_category,
    get_tasks_for_date,
    skip_task_occurrence,
    synchronize_future_occurrences,
    undo_task_completion,
)


class TaskModelTests(TestCase):
    def setUp(self):
        self.category = TaskCategory.objects.create(name="Learning")

    def make_task(self, **overrides):
        values = {
            "title": "Read a chapter",
            "category": self.category,
            "start_date": timezone.localdate(),
        }
        values.update(overrides)
        return Task.objects.create(**values)

    def test_category_names_are_case_insensitively_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskCategory.objects.create(name="learning")

    def test_task_validation_rejects_invalid_recurrence_days(self):
        task = self.make_task(
            recurrence_type=Task.RecurrenceType.WEEKLY,
            recurrence_days=[0, 7],
        )

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertIn("recurrence_days", error.exception.message_dict)

    def test_task_validation_requires_weekdays_only_for_weekly_or_custom(self):
        task = self.make_task(
            recurrence_type=Task.RecurrenceType.WEEKLY,
            recurrence_days=[],
        )

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertIn("recurrence_days", error.exception.message_dict)

    def test_task_validation_rejects_end_date_before_start_date(self):
        today = timezone.localdate()
        task = Task(
            title="Read a chapter",
            category=self.category,
            start_date=today,
            end_date=today - timedelta(days=1),
        )

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertIn("end_date", error.exception.message_dict)

    def test_form_accepts_weekday_values_and_rejects_missing_weekdays(self):
        valid_form = TaskForm(
            {
                "title": "Practice",
                "category": self.category.pk,
                "difficulty": Task.Difficulty.NORMAL,
                "estimated_minutes": 20,
                "xp_reward": 15,
                "recurrence_type": Task.RecurrenceType.WEEKLY,
                "recurrence_days": ["0", "4"],
                "start_date": timezone.localdate().isoformat(),
                "end_date": "",
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertEqual(valid_form.cleaned_data["recurrence_days"], [0, 4])

        invalid_form = TaskForm(
            {
                "title": "Practice",
                "category": self.category.pk,
                "difficulty": Task.Difficulty.NORMAL,
                "estimated_minutes": 20,
                "xp_reward": 15,
                "recurrence_type": Task.RecurrenceType.WEEKLY,
                "recurrence_days": [],
                "start_date": timezone.localdate().isoformat(),
                "end_date": "",
            }
        )
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("recurrence_days", invalid_form.errors)


class TaskOccurrenceServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.category = TaskCategory.objects.create(name="Health")

    def make_task(self, **overrides):
        values = {
            "title": "Move for ten minutes",
            "category": self.category,
            "start_date": self.today,
            "recurrence_type": Task.RecurrenceType.DAILY,
        }
        values.update(overrides)
        return Task.objects.create(**values)

    def test_daily_occurrence_generation_is_idempotent(self):
        task = self.make_task()

        first = generate_task_occurrences(self.today)
        second = generate_task_occurrences(self.today)

        self.assertEqual([item.task_id for item in first], [task.pk])
        self.assertEqual([item.pk for item in second], [first[0].pk])
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 1)

    def test_recurrence_types_match_only_their_scheduled_dates(self):
        once = self.make_task(title="One time", recurrence_type=Task.RecurrenceType.ONCE)
        weekly = self.make_task(
            title="Weekly",
            recurrence_type=Task.RecurrenceType.WEEKLY,
            recurrence_days=[self.today.weekday()],
        )
        custom = self.make_task(
            title="Custom",
            recurrence_type=Task.RecurrenceType.CUSTOM,
            recurrence_days=[(self.today.weekday() + 1) % 7],
        )

        self.assertEqual(
            {item.task_id for item in generate_task_occurrences(self.today)},
            {once.pk, weekly.pk},
        )
        self.assertEqual(
            {item.task_id for item in generate_task_occurrences(self.today + timedelta(days=1))},
            {custom.pk},
        )

    def test_schedule_changes_preserve_and_reactivate_existing_occurrences(self):
        task = self.make_task()
        future_date = self.today + timedelta(days=2)
        occurrence = generate_task_occurrences(future_date)[0]

        task.recurrence_type = Task.RecurrenceType.ONCE
        task.save()
        self.assertEqual(synchronize_future_occurrences(task, self.today), 1)
        occurrence.refresh_from_db()
        self.assertTrue(occurrence.is_superseded)

        task.recurrence_type = Task.RecurrenceType.DAILY
        task.save()
        generate_task_occurrences(future_date)
        occurrence.refresh_from_db()
        self.assertFalse(occurrence.is_superseded)
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 1)

    def test_archiving_preserves_history_and_hides_future_occurrences(self):
        task = self.make_task()
        today_occurrence = generate_task_occurrences(self.today)[0]
        complete_task_occurrence(today_occurrence.pk)
        future_date = self.today + timedelta(days=1)
        future_occurrence = generate_task_occurrences(future_date)[0]

        archive_task(task)

        today_occurrence.refresh_from_db()
        future_occurrence.refresh_from_db()
        self.assertEqual(today_occurrence.status, TaskCompletion.Status.COMPLETED)
        self.assertTrue(future_occurrence.is_superseded)
        self.assertEqual(list(get_tasks_for_date(self.today)), [])
        self.assertEqual(list(get_tasks_for_date(future_date)), [])
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 2)
        self.assertEqual(list(get_task_history(task.pk)), [future_occurrence, today_occurrence])

    def test_archived_pending_occurrence_cannot_be_completed_or_skipped(self):
        task = self.make_task()
        occurrence = generate_task_occurrences(self.today)[0]
        archive_task(task)

        with self.assertRaises(InvalidOccurrenceTransition):
            complete_task_occurrence(occurrence.pk)
        with self.assertRaises(InvalidOccurrenceTransition):
            skip_task_occurrence(occurrence.pk)

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskCompletion.Status.PENDING)

    def test_daily_queries_filter_categories_and_summarize_real_occurrences(self):
        task = self.make_task()
        other_category = TaskCategory.objects.create(name="Learning")
        self.make_task(title="Study", category=other_category)
        occurrence = generate_task_occurrences(self.today)[0]
        complete_task_occurrence(occurrence.pk)

        self.assertEqual(
            list(get_tasks_by_category(self.category.pk, self.today).values_list("task_id", flat=True)),
            [task.pk],
        )
        self.assertEqual(
            get_task_completion_summary(self.today),
            {
                "total_scheduled": 2,
                "completed": 1,
                "pending": 1,
                "skipped": 0,
                "completion_percentage": 50.0,
            },
        )

    def test_empty_summary_has_zero_percentage(self):
        self.assertEqual(
            get_task_completion_summary(self.today),
            {
                "total_scheduled": 0,
                "completed": 0,
                "pending": 0,
                "skipped": 0,
                "completion_percentage": 0,
            },
        )

    def test_completion_transitions_are_idempotent_and_award_task_xp(self):
        self.make_task()
        occurrence = generate_task_occurrences(self.today)[0]

        completed = complete_task_occurrence(occurrence.pk)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(complete_task_occurrence(occurrence.pk).pk, occurrence.pk)
        self.assertEqual(completed.xp_awarded, 25)

        pending = undo_task_completion(occurrence.pk)
        self.assertEqual(pending.status, TaskCompletion.Status.PENDING)
        self.assertIsNone(pending.completed_at)
        self.assertEqual(undo_task_completion(occurrence.pk).status, TaskCompletion.Status.PENDING)

        skipped = skip_task_occurrence(occurrence.pk)
        self.assertEqual(skipped.status, TaskCompletion.Status.SKIPPED)
        self.assertEqual(skip_task_occurrence(occurrence.pk).status, TaskCompletion.Status.SKIPPED)
        with self.assertRaises(InvalidOccurrenceTransition):
            complete_task_occurrence(occurrence.pk)
        with self.assertRaises(InvalidOccurrenceTransition):
            undo_task_completion(occurrence.pk)


class TaskViewTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.category = TaskCategory.objects.create(name="Learning")

    def task_payload(self, **overrides):
        values = {
            "title": "Study Django",
            "category": self.category.pk,
            "difficulty": Task.Difficulty.NORMAL,
            "estimated_minutes": 30,
            "xp_reward": 25,
            "recurrence_type": Task.RecurrenceType.ONCE,
            "recurrence_days": [],
            "start_date": self.today.isoformat(),
            "end_date": "",
        }
        values.update(overrides)
        return values

    def test_task_list_create_detail_edit_and_archive_pages(self):
        list_response = self.client.get(reverse("tasks:list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Your journey begins with your first mission.")

        create_response = self.client.post(
            reverse("tasks:create"),
            self.task_payload(),
        )
        self.assertEqual(create_response.status_code, 302)
        task = Task.objects.get(title="Study Django")
        self.assertRedirects(
            create_response,
            reverse("tasks:detail", kwargs={"task_id": task.pk}),
        )

        detail_response = self.client.get(
            reverse("tasks:detail", kwargs={"task_id": task.pk})
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Occurrence history")

        edit_response = self.client.post(
            reverse("tasks:edit", kwargs={"task_id": task.pk}),
            self.task_payload(title="Study more"),
        )
        self.assertEqual(edit_response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.title, "Study more")

        archive_response = self.client.post(
            reverse("tasks:archive", kwargs={"task_id": task.pk})
        )
        self.assertRedirects(archive_response, reverse("tasks:list"))
        task.refresh_from_db()
        self.assertFalse(task.is_active)
        self.assertContains(
            self.client.get(reverse("tasks:list") + "?archived=1"),
            "Study more",
        )

    def test_daily_missions_page_renders_database_occurrences_and_dynamic_date(self):
        task = Task.objects.create(
            title="Practice Python",
            description="Solve a real coding exercise.",
            category=self.category,
            difficulty=Task.Difficulty.HARD,
            start_date=self.today,
        )

        response = self.client.get(
            reverse("tasks:list"),
            {"date": self.today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DAILY MISSIONS")
        self.assertContains(response, "Every mission completed makes you stronger.")
        self.assertContains(response, task.title)
        self.assertContains(response, task.description)
        self.assertContains(response, 'id="mission-total-count">1</span>')
        self.assertEqual(response.context["summary"]["total_scheduled"], 1)

    def test_task_create_rejects_weekly_schedule_without_selected_days(self):
        response = self.client.post(
            reverse("tasks:create"),
            self.task_payload(recurrence_type=Task.RecurrenceType.WEEKLY),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select at least one weekday")
        self.assertFalse(Task.objects.exists())

    def test_archive_rejects_get_requests(self):
        task = Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )

        response = self.client.get(reverse("tasks:archive", kwargs={"task_id": task.pk}))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
        self.assertTrue(Task.objects.get(pk=task.pk).is_active)

    def test_daily_and_summary_apis_return_real_occurrences(self):
        task = Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )

        daily_response = self.client.get(
            reverse("tasks:api_daily"),
            {"date": self.today.isoformat()},
        )
        summary_response = self.client.get(
            reverse("tasks:api_summary"),
            {"date": self.today.isoformat()},
        )

        self.assertEqual(daily_response.status_code, 200)
        self.assertEqual(daily_response.json()["tasks"][0]["task_id"], task.pk)
        self.assertEqual(daily_response.json()["summary"]["pending"], 1)
        self.assertEqual(summary_response.json()["summary"]["total_scheduled"], 1)

    def test_date_navigation_api_obeys_recurrence_and_leaves_future_pending(self):
        tomorrow = self.today + timedelta(days=1)
        task = Task.objects.create(
            title="Weekly study",
            category=self.category,
            recurrence_type=Task.RecurrenceType.WEEKLY,
            recurrence_days=[tomorrow.weekday()],
            start_date=self.today,
        )

        today_response = self.client.get(
            reverse("tasks:api_daily"),
            {"date": self.today.isoformat()},
        )
        tomorrow_response = self.client.get(
            reverse("tasks:api_daily"),
            {"date": tomorrow.isoformat()},
        )

        self.assertEqual(today_response.json()["tasks"], [])
        self.assertEqual(tomorrow_response.json()["date"], tomorrow.isoformat())
        self.assertEqual(tomorrow_response.json()["tasks"][0]["task_id"], task.pk)
        self.assertEqual(tomorrow_response.json()["tasks"][0]["status"], "PENDING")

    def test_search_category_difficulty_and_status_filters_use_real_data(self):
        Task.objects.create(
            title="Unscheduled reference",
            category=self.category,
            start_date=self.today + timedelta(days=10),
        )
        matching_task = Task.objects.create(
            title="Solve a logic puzzle",
            description="Practice analytical problem solving.",
            category=self.category,
            difficulty=Task.Difficulty.HARD,
            start_date=self.today,
        )
        other_category = TaskCategory.objects.create(name="Work")
        Task.objects.create(
            title="Sketch a project",
            category=other_category,
            difficulty=Task.Difficulty.EASY,
            start_date=self.today,
        )
        occurrence = next(
            item
            for item in generate_task_occurrences(self.today)
            if item.task_id == matching_task.pk
        )
        complete_task_occurrence(occurrence.pk)

        filtered = self.client.get(
            reverse("tasks:api_daily"),
            {
                "date": self.today.isoformat(),
                "search": "problem",
                "category": self.category.pk,
                "difficulty": "hard",
                "status": "completed",
            },
        )

        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered.json()["tasks"]), 1)
        self.assertEqual(filtered.json()["tasks"][0]["task_id"], matching_task.pk)
        self.assertEqual(filtered.json()["tasks"][0]["id"], occurrence.pk)
        self.assertEqual(filtered.json()["summary"]["total_scheduled"], 2)

        no_match = self.client.get(
            reverse("tasks:api_daily"),
            {"date": self.today.isoformat(), "search": "not found"},
        )
        self.assertEqual(no_match.json()["tasks"], [])

    def test_page_rejects_invalid_date_and_api_rejects_invalid_filter(self):
        invalid_page_date = self.client.get(reverse("tasks:list"), {"date": "2026-2-3"})
        invalid_filter = self.client.get(
            reverse("tasks:api_daily"),
            {"date": self.today.isoformat(), "difficulty": "IMPOSSIBLE"},
        )

        self.assertEqual(invalid_page_date.status_code, 400)
        self.assertEqual(invalid_filter.status_code, 400)

    def test_apis_validate_methods_dates_and_json(self):
        wrong_method = self.client.post(reverse("tasks:api_daily"))
        invalid_date = self.client.get(reverse("tasks:api_daily"), {"date": "2025-2-3"})
        invalid_json = self.client.post(
            reverse("tasks:api_create"),
            data="{broken",
            content_type="application/json",
        )
        wrong_content_type = self.client.post(
            reverse("tasks:api_create"),
            data="{}",
            content_type="text/plain",
        )

        self.assertEqual(wrong_method.status_code, 405)
        self.assertEqual(wrong_method["Allow"], "GET")
        self.assertEqual(invalid_date.status_code, 400)
        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(wrong_content_type.status_code, 415)

    def test_json_task_creation_and_completion_api(self):
        payload = self.task_payload(
            recurrence_type=Task.RecurrenceType.WEEKLY,
            recurrence_days=[self.today.weekday()],
        )
        create_response = self.client.post(
            reverse("tasks:api_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        task = Task.objects.get(title="Study Django")
        occurrence = generate_task_occurrences(self.today)[0]
        completion_response = self.client.post(
            reverse("tasks:api_complete", kwargs={"occurrence_id": occurrence.pk})
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["id"], task.pk)
        self.assertTrue(create_response.json()["scheduled_for_selected_date"])
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 1)
        self.assertEqual(completion_response.status_code, 200)
        self.assertEqual(completion_response.json()["task"]["status"], "COMPLETED")
        self.assertEqual(completion_response.json()["task"]["xp_awarded"], 25)
        undo_response = self.client.post(
            reverse("tasks:api_undo", kwargs={"occurrence_id": occurrence.pk})
        )
        self.assertEqual(undo_response.status_code, 200)
        self.assertEqual(undo_response.json()["task"]["status"], "PENDING")

    def test_edit_and_archive_apis_preserve_completed_history(self):
        task = Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )
        occurrence = generate_task_occurrences(self.today)[0]
        complete_task_occurrence(occurrence.pk)

        update_response = self.client.post(
            reverse("tasks:api_update", kwargs={"task_id": task.pk})
            + f"?date={self.today.isoformat()}",
            data=json.dumps(self.task_payload(title="Updated Django study")),
            content_type="application/json",
        )
        archive_response = self.client.post(
            reverse("tasks:api_archive", kwargs={"task_id": task.pk})
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["task"]["title"], "Updated Django study")
        self.assertEqual(archive_response.status_code, 200)
        self.assertFalse(archive_response.json()["is_active"])
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskCompletion.Status.COMPLETED)
        self.assertIsNotNone(occurrence.completed_at)
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(), 1)

    def test_duplicate_completion_api_requests_are_idempotent(self):
        Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )
        occurrence = generate_task_occurrences(self.today)[0]
        url = reverse("tasks:api_complete", kwargs={"occurrence_id": occurrence.pk})

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["task"]["completed_at"], second.json()["task"]["completed_at"])
        self.assertEqual(first.json()["task"]["xp_awarded"], 25)

    def test_skip_api_marks_only_the_requested_occurrence(self):
        Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )
        occurrence = generate_task_occurrences(self.today)[0]

        response = self.client.post(
            reverse("tasks:api_skip", kwargs={"occurrence_id": occurrence.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task"]["status"], "SKIPPED")

    def test_completion_api_reports_missing_and_invalid_transitions(self):
        missing = self.client.post(
            reverse("tasks:api_complete", kwargs={"occurrence_id": 9999})
        )
        task = Task.objects.create(
            title="Study Django",
            category=self.category,
            start_date=self.today,
        )
        occurrence = generate_task_occurrences(self.today)[0]
        complete_task_occurrence(occurrence.pk)
        skip_completed = self.client.post(
            reverse("tasks:api_skip", kwargs={"occurrence_id": occurrence.pk})
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(skip_completed.status_code, 409)

    def test_csrf_is_required_for_task_creation_api(self):
        csrf_client = Client(enforce_csrf_checks=True)
        url = reverse("tasks:api_create")
        payload = json.dumps(self.task_payload())

        rejected = csrf_client.post(url, data=payload, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)

        csrf_client.get(reverse("tasks:create"))
        token = csrf_client.cookies["csrftoken"].value
        accepted = csrf_client.post(
            url,
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 201)
